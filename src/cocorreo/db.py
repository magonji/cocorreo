"""Database connection for the cocorreo archive.

On Linux (production Raspberry Pi) uses `sqlcipher3` — a drop-in
replacement for `sqlite3` that encrypts the whole database file with AES-256.

On development macOS, `sqlcipher3-binary` doesn't publish wheels and
compiling SQLCipher from source is prohibitively slow (macOS 12 is Tier 3 on
Homebrew). So here we fall back to stdlib `sqlite3`, **unencrypted**.
The passphrase is still requested and derived so the flow and
verification behave the same way; the `db_key` simply isn't applied.

This is acceptable because:
- The development machine is protected by FileVault.
- Attachments ARE always encrypted (handled by `crypto.encrypt_file`).
- The real database, the one containing your emails, lives on the Pi with SQLCipher.
"""

from __future__ import annotations

import sqlite3 as _stdlib_sqlite3
from pathlib import Path
from typing import Optional

from . import schema
from .crypto import DerivedKeys

# SQLCipher detection
try:
    import sqlcipher3 as _sqlcipher  # type: ignore[import-not-found]
    HAS_SQLCIPHER = True
except ImportError:
    _sqlcipher = None  # type: ignore[assignment]
    HAS_SQLCIPHER = False


class Connection:
    """Thin wrapper over the underlying SQLite/SQLCipher connection.

    Exposes the underlying connection via `.conn` for direct use
    (`.execute()`, `.executemany()`, `.commit()`, etc.) and adds utilities.
    """

    def __init__(self, conn, *, encrypted: bool):
        self.conn = conn
        self.encrypted = encrypted

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        try:
            if exc[0] is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()

    def execute(self, sql: str, params=()):
        return self.conn.execute(sql, params)

    def executescript(self, script: str):
        return self.conn.executescript(script)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_schema_version(self) -> Optional[int]:
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
        except _stdlib_sqlite3.DatabaseError:
            return None
        if _sqlcipher is not None:
            # sqlcipher3 raises its own DatabaseError class; caught broadly above too.
            pass
        return int(row[0]) if row else None


def connect(db_path: Path, keys: DerivedKeys) -> Connection:
    """Opens the database; uses SQLCipher if available, otherwise stdlib sqlite3."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if HAS_SQLCIPHER:
        conn = _sqlcipher.connect(str(db_path))
        # SQLCipher 4: pass the key as raw hex to avoid its internal KDF
        # (we've already done scrypt ourselves). Literal quotes required by SQLCipher.
        conn.execute(f"PRAGMA key = \"x'{keys.db_key_hex}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")
        # Sanity check: force SQLCipher to read a page with the key
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception as e:
            conn.close()
            raise RuntimeError(f"couldn't open encrypted database (wrong key?): {e}") from e
        encrypted = True
    else:
        conn = _stdlib_sqlite3.connect(str(db_path))
        encrypted = False

    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return Connection(conn, encrypted=encrypted)


def init_schema(conn: Connection) -> None:
    """Applies the V1 schema if the database is empty. Idempotent."""
    existing = conn.get_schema_version()
    if existing == schema.SCHEMA_VERSION:
        return
    if existing is not None and existing != schema.SCHEMA_VERSION:
        raise RuntimeError(
            f"database has schema v{existing}, expected v{schema.SCHEMA_VERSION}. "
            "Migrations aren't implemented yet."
        )
    for stmt in schema.V1:
        conn.conn.execute(stmt)
    conn.commit()
