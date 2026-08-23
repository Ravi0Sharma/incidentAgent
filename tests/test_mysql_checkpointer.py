"""Integration coverage for database-direct checkpoint visibility."""

import unittest
import uuid

from graph.checkpointer import MySQLSaver
from langgraph.checkpoint.base import empty_checkpoint
from utils.mysql import connection as mysql_connection
from settings import MYSQL_TABLE


class MySQLCheckpointerTests(unittest.TestCase):
    def setUp(self):
        self.thread_id = "checkpoint-" + uuid.uuid4().hex

    def tearDown(self):
        with mysql_connection() as connection, connection.cursor() as cursor:
            for table in (MYSQL_TABLE, f"{MYSQL_TABLE}_writes", f"{MYSQL_TABLE}_blobs"):
                cursor.execute(f"DELETE FROM `{table}` WHERE thread_id=%s", (self.thread_id,))
            connection.commit()

    def test_second_process_reads_first_process_checkpoint(self):
        checkpoint = empty_checkpoint()
        version = "00000000000000000000000000000001.0000000000000000"
        checkpoint["channel_values"] = {"signal": {"value": 7}}
        checkpoint["channel_versions"] = {"signal": version}
        config = {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}}

        first_process = MySQLSaver()
        saved = first_process.put(config, checkpoint, {}, {"signal": version})

        second_process = MySQLSaver()
        loaded = second_process.get_tuple(saved)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.checkpoint["channel_values"]["signal"], {"value": 7})

    def test_duplicate_checkpoint_id_does_not_overwrite_original_payload(self):
        checkpoint = empty_checkpoint()
        version = "00000000000000000000000000000001.0000000000000000"
        checkpoint["channel_values"] = {"signal": "first"}
        checkpoint["channel_versions"] = {"signal": version}
        config = {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}}

        saved = MySQLSaver().put(config, checkpoint, {}, {"signal": version})
        stale = dict(checkpoint)
        stale["channel_values"] = {"signal": "stale-overwrite"}
        MySQLSaver().put(config, stale, {}, {"signal": version})

        loaded = MySQLSaver().get_tuple(saved)
        self.assertEqual(loaded.checkpoint["channel_values"]["signal"], "first")

    def test_list_and_latest_lookup_read_from_database(self):
        checkpoint = empty_checkpoint()
        version = "00000000000000000000000000000001.0000000000000000"
        checkpoint["channel_values"] = {"signal": "listed"}
        checkpoint["channel_versions"] = {"signal": version}
        config = {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}}
        MySQLSaver().put(config, checkpoint, {"source": "test"}, {"signal": version})

        saver = MySQLSaver()
        latest = saver.get_tuple(config)
        listed = list(saver.list(config, filter={"source": "test"}, limit=1))

        self.assertEqual(latest.checkpoint["channel_values"]["signal"], "listed")
        self.assertEqual(len(listed), 1)
