import json
import os
import sqlite3
from threading import Lock
from datetime import datetime

from langgraph.checkpoint.base import (
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.memory import MemorySaver, WRITES_IDX_MAP

from settings import (
    CHECKPOINTER,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_TABLE,
    RUNTIME_SCHEMA_DDL_ENABLED,
)
from utils.mysql import connection as mysql_connection


class SQLiteSaver(MemorySaver):
    """Durable local checkpointer without adding a database dependency.

    For multi-node production deploys, use the official Postgres saver. This
    implementation keeps LangGraph interrupts resumable across one process
    restart, which is a substantial improvement over MemorySaver/mysql-sim.
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self._lock = Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS graph_checkpoints (
              thread_id TEXT NOT NULL,
              checkpoint_ns TEXT NOT NULL,
              checkpoint_id TEXT NOT NULL,
              checkpoint_type TEXT NOT NULL,
              checkpoint_blob BLOB NOT NULL,
              metadata_type TEXT NOT NULL,
              metadata_blob BLOB NOT NULL,
              parent_checkpoint_id TEXT,
              PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE IF NOT EXISTS graph_checkpoint_writes (
              thread_id TEXT NOT NULL,
              checkpoint_ns TEXT NOT NULL,
              checkpoint_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              write_idx INTEGER NOT NULL,
              channel TEXT NOT NULL,
              value_type TEXT NOT NULL,
              value_blob BLOB NOT NULL,
              task_path TEXT NOT NULL,
              PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx)
            );
            CREATE TABLE IF NOT EXISTS graph_checkpoint_blobs (
              thread_id TEXT NOT NULL,
              checkpoint_ns TEXT NOT NULL,
              channel TEXT NOT NULL,
              version TEXT NOT NULL,
              value_type TEXT NOT NULL,
              value_blob BLOB NOT NULL,
              PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
            );
        """)
        self._load()

    def _load(self):
        for row in self._db.execute(
            "SELECT thread_id, checkpoint_ns, checkpoint_id, checkpoint_type, "
            "checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id "
            "FROM graph_checkpoints"
        ):
            thread, namespace, checkpoint_id, ctype, cblob, mtype, mblob, parent = row
            self.storage[thread][namespace][checkpoint_id] = (
                (ctype, bytes(cblob)),
                (mtype, bytes(mblob)),
                parent,
            )
        for row in self._db.execute(
            "SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, "
            "channel, value_type, value_blob, task_path FROM graph_checkpoint_writes"
        ):
            (
                thread,
                namespace,
                checkpoint_id,
                task_id,
                index,
                channel,
                kind,
                blob,
                path,
            ) = row
            self.writes[(thread, namespace, checkpoint_id)][(task_id, index)] = (
                task_id,
                channel,
                (kind, bytes(blob)),
                path,
            )
        for row in self._db.execute(
            "SELECT thread_id, checkpoint_ns, channel, version, value_type, value_blob "
            "FROM graph_checkpoint_blobs"
        ):
            thread, namespace, channel, version, kind, blob = row
            self.blobs[(thread, namespace, channel, version)] = (kind, bytes(blob))

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            result = super().put(config, checkpoint, metadata, new_versions)
            thread = config["configurable"]["thread_id"]
            namespace = config["configurable"]["checkpoint_ns"]
            checkpoint_id = checkpoint["id"]
            stored_checkpoint, stored_metadata, parent = self.storage[thread][
                namespace
            ][checkpoint_id]
            self._db.execute(
                "INSERT OR REPLACE INTO graph_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread,
                    namespace,
                    checkpoint_id,
                    stored_checkpoint[0],
                    stored_checkpoint[1],
                    stored_metadata[0],
                    stored_metadata[1],
                    parent,
                ),
            )
            for channel, version in new_versions.items():
                kind, blob = self.blobs[(thread, namespace, channel, version)]
                self._db.execute(
                    "INSERT OR REPLACE INTO graph_checkpoint_blobs VALUES (?, ?, ?, ?, ?, ?)",
                    (thread, namespace, channel, str(version), kind, blob),
                )
            self._db.commit()
            return result

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            result = super().put_writes(config, writes, task_id, task_path)
            thread = config["configurable"]["thread_id"]
            namespace = config["configurable"].get("checkpoint_ns", "")
            checkpoint_id = config["configurable"]["checkpoint_id"]
            for (saved_task, index), value in self.writes[
                (thread, namespace, checkpoint_id)
            ].items():
                saved_task, channel, serialized, saved_path = value
                self._db.execute(
                    "INSERT OR REPLACE INTO graph_checkpoint_writes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        thread,
                        namespace,
                        checkpoint_id,
                        saved_task,
                        index,
                        channel,
                        serialized[0],
                        serialized[1],
                        saved_path,
                    ),
                )
            self._db.commit()
            return result

    def delete_thread(self, thread_id):
        with self._lock:
            super().delete_thread(thread_id)
            for table in (
                "graph_checkpoints",
                "graph_checkpoint_writes",
                "graph_checkpoint_blobs",
            ):
                self._db.execute(
                    f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,)
                )
            self._db.commit()


def _short(value, limit=80):
    text = str(value)

    if len(text) <= limit:
        return text

    return text[:limit] + "..."


class SimulatedMySQLSaver(MemorySaver):
    """
    Behaves exactly like MemorySaver
    (so interrupts / resume work),
    but logs every write as the SQL
    it WOULD run against MySQL.

    No real MySQL server needed.
    """

    def __init__(self, log_file, table):
        super().__init__()
        self.log_file = log_file
        self.table = table

        self._log(
            f"-- SimulatedMySQLSaver started. Would ensure table `{self.table}` exists:"
        )
        self._log(
            "CREATE TABLE IF NOT "
            f"EXISTS `{self.table}` ("
            "thread_id VARCHAR(255), "
            "checkpoint_id "
            "VARCHAR(255), "
            "node VARCHAR(255), "
            "state JSON, "
            "created_at DATETIME, "
            "PRIMARY KEY "
            "(thread_id, "
            "checkpoint_id));"
        )

    def _log(self, line):
        stamp = datetime.now().isoformat()

        print(f"[mysql-sim] {line}")

        with open(self.log_file, "a") as f:
            f.write(f"{stamp} {line}\n")

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config.get("configurable", {}).get("thread_id", "?")

        checkpoint_id = checkpoint.get("id", "?")

        source = metadata.get("source", "?")

        step = metadata.get("step", "?")

        self._log(
            "INSERT INTO "
            f"`{self.table}` "
            "(thread_id, "
            "checkpoint_id, node, "
            "state, created_at) "
            "VALUES ("
            f"'{thread_id}', "
            f"'{checkpoint_id}', "
            f"'{source}:step{step}', "
            "'<json state ~"
            f"{len(json.dumps(checkpoint, default=str))}"
            " bytes>', "
            "NOW());"
        )

        return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        thread_id = config.get("configurable", {}).get("thread_id", "?")

        for channel, value in writes:
            self._log(
                "INSERT INTO "
                f"`{self.table}"
                "_writes` "
                "(thread_id, "
                "task_id, channel, "
                "value) VALUES ("
                f"'{thread_id}', "
                f"'{task_id}', "
                f"'{channel}', "
                f"'{_short(value)}');"
            )

        return super().put_writes(config, writes, task_id, task_path)


class MySQLSaver(MemorySaver):
    """MySQL-backed checkpoints with database-direct multi-process visibility."""

    def __init__(self):
        super().__init__()
        self._lock = Lock()
        prefix = MYSQL_TABLE
        if RUNTIME_SCHEMA_DDL_ENABLED:
            with mysql_connection() as db, db.cursor() as cursor:
                self._create_schema(cursor, prefix)
                db.commit()
        # MemorySaver supplies the LangGraph serialization contract, but MySQL
        # is the source of truth. Do not preload a process-local snapshot: a
        # different API or worker process may write after this process starts.

    @staticmethod
    def _create_schema(cursor, prefix):
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS `{prefix}` ("
            "thread_id VARCHAR(255) NOT NULL, checkpoint_ns VARCHAR(255) NOT NULL, "
            "checkpoint_id VARCHAR(255) NOT NULL, checkpoint_type VARCHAR(64) NOT NULL, "
            "checkpoint_blob LONGBLOB NOT NULL, metadata_type VARCHAR(64) NOT NULL, "
            "metadata_blob LONGBLOB NOT NULL, parent_checkpoint_id VARCHAR(255), "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS `{prefix}_writes` ("
            "thread_id VARCHAR(128) NOT NULL, checkpoint_ns VARCHAR(128) NOT NULL, "
            "checkpoint_id VARCHAR(128) NOT NULL, task_id VARCHAR(128) NOT NULL, "
            "write_idx INT NOT NULL, channel VARCHAR(128) NOT NULL, value_type VARCHAR(64) NOT NULL, "
            "value_blob LONGBLOB NOT NULL, task_path TEXT NOT NULL, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx))"
        )
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS `{prefix}_blobs` ("
            "thread_id VARCHAR(128) NOT NULL, checkpoint_ns VARCHAR(128) NOT NULL, "
            "channel VARCHAR(128) NOT NULL, version VARCHAR(128) NOT NULL, value_type VARCHAR(64) NOT NULL, "
            "value_blob LONGBLOB NOT NULL, PRIMARY KEY (thread_id, checkpoint_ns, channel, version))"
        )

    def _load_values(self, cursor, thread_id, namespace, versions):
        values = {}
        for channel, version in versions.items():
            cursor.execute(
                f"SELECT value_type,value_blob FROM `{MYSQL_TABLE}_blobs` "
                "WHERE thread_id=%s AND checkpoint_ns=%s AND channel=%s AND version=%s",
                (thread_id, namespace, channel, str(version)),
            )
            row = cursor.fetchone()
            if not row or row[0] == "empty":
                continue
            values[channel] = self.serde.loads_typed((row[0], bytes(row[1])))
        return values

    def _tuple_from_row(self, cursor, row):
        thread_id, namespace, checkpoint_id, ctype, cblob, mtype, mblob, parent = row
        checkpoint = self.serde.loads_typed((ctype, bytes(cblob)))
        cursor.execute(
            f"SELECT task_id,channel,value_type,value_blob FROM `{MYSQL_TABLE}_writes` "
            "WHERE thread_id=%s AND checkpoint_ns=%s AND checkpoint_id=%s "
            "ORDER BY task_id,write_idx",
            (thread_id, namespace, checkpoint_id),
        )
        pending = [
            (task_id, channel, self.serde.loads_typed((kind, bytes(blob))))
            for task_id, channel, kind, blob in cursor.fetchall()
        ]
        return CheckpointTuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": checkpoint_id}},
            checkpoint={
                **checkpoint,
                "channel_values": self._load_values(
                    cursor, thread_id, namespace, checkpoint["channel_versions"]
                ),
            },
            metadata=self.serde.loads_typed((mtype, bytes(mblob))),
            parent_config=(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": parent}}
                if parent else None
            ),
            pending_writes=pending,
        )

    def get_tuple(self, config):
        thread_id = config["configurable"]["thread_id"]
        namespace = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with mysql_connection() as db, db.cursor() as cursor:
            if checkpoint_id:
                cursor.execute(
                    f"SELECT thread_id,checkpoint_ns,checkpoint_id,checkpoint_type,checkpoint_blob,metadata_type,metadata_blob,parent_checkpoint_id FROM `{MYSQL_TABLE}` "
                    "WHERE thread_id=%s AND checkpoint_ns=%s AND checkpoint_id=%s",
                    (thread_id, namespace, checkpoint_id),
                )
            else:
                cursor.execute(
                    f"SELECT thread_id,checkpoint_ns,checkpoint_id,checkpoint_type,checkpoint_blob,metadata_type,metadata_blob,parent_checkpoint_id FROM `{MYSQL_TABLE}` "
                    "WHERE thread_id=%s AND checkpoint_ns=%s ORDER BY checkpoint_id DESC LIMIT 1",
                    (thread_id, namespace),
                )
            row = cursor.fetchone()
            return self._tuple_from_row(cursor, row) if row else None

    def list(self, config, *, filter=None, before=None, limit=None):
        clauses, parameters = [], []
        if config:
            configurable = config["configurable"]
            clauses.append("thread_id=%s")
            parameters.append(configurable["thread_id"])
            if "checkpoint_ns" in configurable:
                clauses.append("checkpoint_ns=%s")
                parameters.append(configurable["checkpoint_ns"])
            if checkpoint_id := get_checkpoint_id(config):
                clauses.append("checkpoint_id=%s")
                parameters.append(checkpoint_id)
        if before and (before_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id<%s")
            parameters.append(before_id)
        query = (
            f"SELECT thread_id,checkpoint_ns,checkpoint_id,checkpoint_type,checkpoint_blob,metadata_type,metadata_blob,parent_checkpoint_id FROM `{MYSQL_TABLE}`"
            + (" WHERE " + " AND ".join(clauses) if clauses else "")
            + " ORDER BY checkpoint_id DESC"
        )
        yielded = 0
        with mysql_connection() as db, db.cursor() as cursor:
            cursor.execute(query, tuple(parameters))
            for row in cursor.fetchall():
                value = self._tuple_from_row(cursor, row)
                if filter and not all(value.metadata.get(key) == expected for key, expected in filter.items()):
                    continue
                yield value
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            thread = config["configurable"]["thread_id"]
            namespace = config["configurable"]["checkpoint_ns"]
            checkpoint_id = checkpoint["id"]
            stored_checkpoint = checkpoint.copy()
            values = stored_checkpoint.pop("channel_values")
            checkpoint_value = self.serde.dumps_typed(stored_checkpoint)
            metadata_value = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
            parent = config["configurable"].get("checkpoint_id")
            with mysql_connection() as db, db.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO `{MYSQL_TABLE}` VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE checkpoint_id=checkpoint_id",
                    (
                        thread,
                        namespace,
                        checkpoint_id,
                        checkpoint_value[0],
                        checkpoint_value[1],
                        metadata_value[0],
                        metadata_value[1],
                        parent,
                    ),
                )
                for channel, version in new_versions.items():
                    kind, blob = self.serde.dumps_typed(values[channel]) if channel in values else ("empty", b"")
                    cursor.execute(
                        f"INSERT INTO `{MYSQL_TABLE}_blobs` VALUES (%s,%s,%s,%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE version=version",
                        (thread, namespace, channel, str(version), kind, blob),
                    )
                db.commit()
            return {"configurable": {"thread_id": thread, "checkpoint_ns": namespace, "checkpoint_id": checkpoint_id}}

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            thread = config["configurable"]["thread_id"]
            namespace = config["configurable"].get("checkpoint_ns", "")
            checkpoint_id = config["configurable"]["checkpoint_id"]
            with mysql_connection() as db, db.cursor() as cursor:
                for index, (channel, value) in enumerate(writes):
                    write_index = WRITES_IDX_MAP.get(channel, index)
                    if write_index < 0:
                        write_index = index
                    serialized = self.serde.dumps_typed(value)
                    cursor.execute(
                        f"INSERT INTO `{MYSQL_TABLE}_writes` VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE write_idx=write_idx",
                        (
                            thread,
                            namespace,
                            checkpoint_id,
                            task_id,
                            write_index,
                            channel,
                            serialized[0],
                            serialized[1],
                            task_path,
                        ),
                    )
                db.commit()

    def delete_thread(self, thread_id):
        with self._lock:
            with mysql_connection() as db, db.cursor() as cursor:
                for table in (
                    MYSQL_TABLE,
                    f"{MYSQL_TABLE}_writes",
                    f"{MYSQL_TABLE}_blobs",
                ):
                    cursor.execute(
                        f"DELETE FROM `{table}` WHERE thread_id = %s", (thread_id,)
                    )
                db.commit()


def build_checkpointer():
    if CHECKPOINTER == "mysql":
        print(
            f"[checkpointer] using MySQLSaver -> {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
        )
        return MySQLSaver()

    raise ValueError("CHECKPOINTER must be mysql")
