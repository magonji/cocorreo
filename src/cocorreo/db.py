"""Database connection and archive layout for the cocorreo archive.

Data directory layout:
    data/
    ├── cocorreo.db       # SQLite
    └── attachments/      # plain files, sharded by first hex byte
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import schema


@dataclass(frozen=True)
class Archive:
    """Locates the database and attachments of a cocorreo archive on disk."""

    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cocorreo.db"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"


def is_initialised(data_dir: Path) -> bool:
    return (data_dir / "cocorreo.db").is_file()


def initialise_archive(data_dir: Path) -> Archive:
    """Creates the data directory layout. Fails if it already exists."""
    data_dir = data_dir.expanduser().resolve()
    if is_initialised(data_dir):
        raise FileExistsError(f"{data_dir} is already initialised")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "attachments").mkdir(exist_ok=True)
    return Archive(data_dir=data_dir)


def open_archive(data_dir: Path) -> Archive:
    data_dir = data_dir.expanduser().resolve()
    if not is_initialised(data_dir):
        raise FileNotFoundError(f"{data_dir} is not initialised (missing cocorreo.db)")
    return Archive(data_dir=data_dir)


class Connection:
    """Thin wrapper over the underlying sqlite3 connection.

    Exposes the underlying connection via `.conn` for direct use
    (`.execute()`, `.executemany()`, `.commit()`, etc.) and adds utilities.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

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
        except sqlite3.DatabaseError:
            return None
        return int(row[0]) if row else None


def connect(db_path: Path) -> Connection:
    """Opens the database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return Connection(conn)


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
