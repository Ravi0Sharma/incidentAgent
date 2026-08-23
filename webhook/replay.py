"""Durable replay guard for signed webhook requests."""

import hashlib
from datetime import datetime, timedelta, timezone

import pymysql

from utils.mysql import connection as mysql_connection
from settings import RUNTIME_SCHEMA_DDL_ENABLED


class ReplayError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _connection():
    return mysql_connection()


def _parse_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ReplayError("invalid_signature_timestamp", "signature timestamp must be ISO-8601")


def _nonce_hash(nonce):
    return hashlib.sha256(str(nonce).encode("utf-8")).hexdigest()


def _ensure_schema(conn):
    if not RUNTIME_SCHEMA_DDL_ENABLED:
        return
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS webhook_nonces ("
            "nonce_hash CHAR(64) PRIMARY KEY, expires_at DATETIME(6) NOT NULL, "
            "used_at DATETIME(6) NOT NULL)"
        )


def validate_and_record_nonce(timestamp, nonce, window_seconds, now=None):
    """Atomically consume a nonce after validating the signed timestamp."""
    if not nonce or len(str(nonce)) > 128:
        raise ReplayError("invalid_signature_nonce", "signature nonce is required and bounded")
    observed = _parse_timestamp(timestamp)
    if observed.tzinfo is None:
        raise ReplayError("invalid_signature_timestamp", "signature timestamp must include timezone")
    current = now or datetime.now(timezone.utc)
    if abs((current - observed).total_seconds()) > window_seconds:
        raise ReplayError("signature_timestamp_outside_window", "signature timestamp is outside replay window")

    with _connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM webhook_nonces WHERE expires_at < %s", (current,))
            try:
                cur.execute(
                    "INSERT INTO webhook_nonces (nonce_hash,expires_at,used_at) VALUES (%s,%s,%s)",
                    (_nonce_hash(nonce), current + timedelta(seconds=window_seconds), current),
                )
            except pymysql.err.IntegrityError:
                conn.rollback()
                raise ReplayError("replayed_signature_nonce", "signature nonce was already used")
        conn.commit()


def reset_for_tests():
    """Compatibility hook; durable replay records are intentionally not cleared."""
