"""Shared fixed-window webhook limiter backed by MySQL in runtime."""

import hashlib
import math
import time
from collections import defaultdict, deque

from utils.mysql import connection as mysql_connection
from settings import RUNTIME_SCHEMA_DDL_ENABLED


_TEST_WINDOWS: defaultdict[str, deque[float]] = defaultdict(deque)


def _connection():
    return mysql_connection()


def _test_allow(key, limit, window_seconds, current):
    bucket = _TEST_WINDOWS[str(key)]
    while bucket and current - bucket[0] >= window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False, max(1, int(window_seconds - (current - bucket[0])))
    bucket.append(current)
    return True, 0


def allow(key, limit, window_seconds, now=None):
    """Allow a key once per shared fixed window; ``now`` enables pure tests."""
    if now is not None:
        return _test_allow(key, limit, window_seconds, now)
    current = time.time()
    window_id = math.floor(current / window_seconds)
    key_hash = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    with _connection() as conn, conn.cursor() as cur:
        if RUNTIME_SCHEMA_DDL_ENABLED:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS webhook_rate_limits ("
                "key_hash CHAR(64) NOT NULL, window_id BIGINT NOT NULL, request_count INT NOT NULL, "
                "PRIMARY KEY (key_hash,window_id))"
            )
        cur.execute("DELETE FROM webhook_rate_limits WHERE window_id < %s", (window_id - 1,))
        cur.execute(
            "SELECT request_count FROM webhook_rate_limits WHERE key_hash=%s AND window_id=%s FOR UPDATE",
            (key_hash, window_id),
        )
        row = cur.fetchone()
        count = row[0] if row else 0
        if count >= limit:
            conn.commit()
            return False, max(1, int((window_id + 1) * window_seconds - current))
        if row:
            cur.execute(
                "UPDATE webhook_rate_limits SET request_count=request_count+1 WHERE key_hash=%s AND window_id=%s",
                (key_hash, window_id),
            )
        else:
            cur.execute(
                "INSERT INTO webhook_rate_limits (key_hash,window_id,request_count) VALUES (%s,%s,1)",
                (key_hash, window_id),
            )
        conn.commit()
    return True, 0


def reset_for_tests():
    _TEST_WINDOWS.clear()
