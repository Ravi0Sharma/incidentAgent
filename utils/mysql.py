"""Bounded process-local MySQL pool with role and TLS-aware connections."""

import os
import queue
import threading

import pymysql

import settings


class MySQLPoolExhausted(TimeoutError):
    """No database connection became available within the configured bound."""


def _credentials():
    role = settings.PROCESS_ROLE
    if role == "api" and settings.MYSQL_API_USER:
        return settings.MYSQL_API_USER, settings.MYSQL_API_PASSWORD
    if role == "worker" and settings.MYSQL_WORKER_USER:
        return settings.MYSQL_WORKER_USER, settings.MYSQL_WORKER_PASSWORD
    if role == "migrator" and settings.MYSQL_MIGRATOR_USER:
        return settings.MYSQL_MIGRATOR_USER, settings.MYSQL_MIGRATOR_PASSWORD
    return settings.MYSQL_USER, settings.MYSQL_PASSWORD


def _new_connection():
    user, password = _credentials()
    options = {
        "host": settings.MYSQL_HOST,
        "port": settings.MYSQL_PORT,
        "user": user,
        "password": password,
        "database": settings.MYSQL_DATABASE,
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": settings.MYSQL_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": settings.MYSQL_READ_TIMEOUT_SECONDS,
        "write_timeout": settings.MYSQL_WRITE_TIMEOUT_SECONDS,
    }
    if settings.MYSQL_SSL_ENABLED:
        options.update(
            {
                "ssl_ca": settings.MYSQL_SSL_CA or None,
                "ssl_verify_cert": True,
                "ssl_verify_identity": settings.MYSQL_SSL_VERIFY_IDENTITY,
            }
        )
    return pymysql.connect(**options)


class _Pool:
    def __init__(self):
        self._available = queue.LifoQueue(maxsize=settings.MYSQL_POOL_SIZE)
        self._created = 0
        self._lock = threading.Lock()
        self._pid = os.getpid()

    def _ensure_process(self):
        """Never reuse a parent process's sockets after fork."""
        current_pid = os.getpid()
        if current_pid == self._pid:
            return
        with self._lock:
            if current_pid == self._pid:
                return
            while True:
                try:
                    inherited = self._available.get_nowait()
                except queue.Empty:
                    break
                try:
                    inherited.close()
                except Exception:
                    pass
            self._available = queue.LifoQueue(maxsize=settings.MYSQL_POOL_SIZE)
            self._created = 0
            self._pid = current_pid

    def acquire(self):
        self._ensure_process()
        try:
            connection = self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < settings.MYSQL_POOL_SIZE:
                    connection = _new_connection()
                    self._created += 1
                else:
                    connection = None
            if connection is None:
                try:
                    connection = self._available.get(
                        timeout=settings.MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS
                    )
                except queue.Empty as exc:
                    raise MySQLPoolExhausted(
                        "timed out waiting for a pooled MySQL connection"
                    ) from exc
        try:
            connection.ping(reconnect=True)
        except Exception:
            self.discard(connection)
            raise
        return _PooledConnection(self, connection, self._pid)

    def release(self, connection, acquired_pid=None):
        self._ensure_process()
        if acquired_pid is not None and acquired_pid != os.getpid():
            try:
                connection.close()
            except Exception:
                pass
            return
        try:
            connection.rollback()
            self._available.put_nowait(connection)
        except Exception:
            self.discard(connection)

    def discard(self, connection):
        try:
            connection.close()
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)

    def stats(self):
        self._ensure_process()
        with self._lock:
            created = self._created
        return {
            "size": settings.MYSQL_POOL_SIZE,
            "created": created,
            "available": self._available.qsize(),
            "in_use": created - self._available.qsize(),
        }


class _PooledConnection:
    def __init__(self, pool, connection, acquired_pid):
        self._pool = pool
        self._connection = connection
        self._acquired_pid = acquired_pid
        self._released = False

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            try:
                self._connection.rollback()
            except Exception:
                pass
        self.close()
        return False

    def close(self):
        if not self._released:
            self._released = True
            self._pool.release(self._connection, self._acquired_pid)


_POOL = _Pool()


def connection():
    """Acquire a pooled connection; context exit returns it to the pool."""
    return _POOL.acquire()


def pool_stats():
    return _POOL.stats()
