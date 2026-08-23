"""Bounded and fork-safe MySQL connection pool behavior."""

import unittest
from unittest.mock import patch

from utils import mysql


class _Connection:
    def __init__(self):
        self.closed = False
        self.rollbacks = 0

    def ping(self, reconnect=True):
        if self.closed:
            raise RuntimeError("closed")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class MySQLPoolTests(unittest.TestCase):
    def test_pool_exhaustion_is_bounded_and_connection_is_reusable(self):
        connection = _Connection()
        with (
            patch.object(mysql.settings, "MYSQL_POOL_SIZE", 1),
            patch.object(mysql.settings, "MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS", 0.01),
            patch.object(mysql, "_new_connection", return_value=connection),
        ):
            pool = mysql._Pool()
            first = pool.acquire()
            with self.assertRaisesRegex(mysql.MySQLPoolExhausted, "timed out"):
                pool.acquire()
            first.close()
            second = pool.acquire()
            second.close()

        self.assertGreaterEqual(connection.rollbacks, 2)

    def test_pool_discards_inherited_connections_after_fork_boundary(self):
        inherited = _Connection()
        replacement = _Connection()
        with (
            patch.object(mysql.settings, "MYSQL_POOL_SIZE", 1),
            patch.object(mysql, "_new_connection", side_effect=[inherited, replacement]),
        ):
            pool = mysql._Pool()
            borrowed = pool.acquire()
            borrowed.close()
            with patch.object(mysql.os, "getpid", return_value=pool._pid + 1):
                fresh = pool.acquire()
                self.assertTrue(inherited.closed)
                self.assertEqual(pool.stats()["created"], 1)
                fresh.close()
