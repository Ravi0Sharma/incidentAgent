import json
import os
import sqlite3
import zlib

from settings import (
    INCIDENT_STORE_PATH,
    MAX_COMPRESSED_LOG_BYTES,
    MAX_STORED_LOG_BYTES,
)
from utils.redaction import redact_data


def _encode_logs(logs):
    raw = json.dumps(
        redact_data(logs or []), default=str
    ).encode("utf-8")
    if len(raw) > MAX_STORED_LOG_BYTES:
        raise ValueError("incident log payload exceeds uncompressed byte limit")
    payload = zlib.compress(raw)
    if len(payload) > MAX_COMPRESSED_LOG_BYTES:
        raise ValueError("incident log payload exceeds compressed byte limit")
    return payload


def _decode_logs(payload):
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("incident log payload is not binary")
    payload = bytes(payload)
    if len(payload) > MAX_COMPRESSED_LOG_BYTES:
        raise ValueError("incident log payload exceeds compressed byte limit")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(payload, MAX_STORED_LOG_BYTES + 1)
        if (
            len(raw) > MAX_STORED_LOG_BYTES
            or decompressor.unconsumed_tail
        ):
            raise ValueError("incident log payload exceeds decompression limit")
        raw += decompressor.flush()
        if len(raw) > MAX_STORED_LOG_BYTES:
            raise ValueError("incident log payload exceeds decompression limit")
        if not decompressor.eof or decompressor.unused_data:
            raise ValueError("incident log payload has invalid compressed framing")
        decoded = json.loads(raw.decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("incident log payload is corrupt") from exc
    if not isinstance(decoded, list):
        raise ValueError("incident log payload must decode to a list")
    return decoded


def _connection():
    os.makedirs(
        os.path.dirname(INCIDENT_STORE_PATH) or ".",
        exist_ok=True,
    )
    conn = sqlite3.connect(INCIDENT_STORE_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS incident_logs "
        "(incident_id TEXT PRIMARY KEY, payload BLOB NOT NULL, updated_at TEXT NOT NULL)"
    )
    return conn


def put_logs(incident_id, logs):
    if not incident_id:
        return
    payload = _encode_logs(logs)
    with _connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO incident_logs "
            "VALUES (?, ?, datetime('now'))",
            (incident_id, payload),
        )


def get_logs(incident_id):
    if not incident_id:
        return []
    with _connection() as conn:
        row = conn.execute(
            "SELECT payload FROM incident_logs WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
    if not row:
        return []
    return _decode_logs(row[0])
