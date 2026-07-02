"""Conexión a la base de datos del archivo cocorreo.

En Linux (Raspberry Pi de producción) usa `sqlcipher3` — un drop-in
replacement de `sqlite3` que cifra todo el archivo de BD con AES-256.

En macOS de desarrollo, `sqlcipher3-binary` no publica wheels y compilar
SQLCipher desde fuente es prohibitivamente lento (macOS 12 es Tier 3 en
Homebrew). Por eso aquí caemos a la `sqlite3` de stdlib, **sin cifrar**.
La passphrase se sigue pidiendo y derivando para que el flujo y la
verificación funcionen igual; simplemente la `db_key` no se aplica.

Esto es aceptable porque:
- La máquina de desarrollo está protegida por FileVault.
- Los adjuntos VAN cifrados siempre (los maneja `crypto.encrypt_file`).
- La BD real, la que contiene tus correos, vive en la Pi con SQLCipher.
"""

from __future__ import annotations

import sqlite3 as _stdlib_sqlite3
from pathlib import Path
from typing import Optional

from . import schema
from .crypto import DerivedKeys

# Detección de SQLCipher
try:
    import sqlcipher3 as _sqlcipher  # type: ignore[import-not-found]
    HAS_SQLCIPHER = True
except ImportError:
    _sqlcipher = None  # type: ignore[assignment]
    HAS_SQLCIPHER = False


class Connection:
    """Wrapper fino sobre la conexión SQLite/SQLCipher.

    Expone el connection subyacente vía `.conn` para uso directo
    (`.execute()`, `.executemany()`, `.commit()`, etc.) y añade utilidades.
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
            # sqlcipher3 raises its own DatabaseError class; capture broadly above too.
            pass
        return int(row[0]) if row else None


def connect(db_path: Path, keys: DerivedKeys) -> Connection:
    """Abre la BD; usa SQLCipher si está disponible, si no stdlib sqlite3."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if HAS_SQLCIPHER:
        conn = _sqlcipher.connect(str(db_path))
        # SQLCipher 4: pasamos la clave como hex raw para evitar su KDF interno
        # (ya hicimos scrypt nosotros). Comilla literal exigida por SQLCipher.
        conn.execute(f"PRAGMA key = \"x'{keys.db_key_hex}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")
        # Verificación: forzar a SQLCipher a leer un page con la clave
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception as e:
            conn.close()
            raise RuntimeError(f"no se pudo abrir BD cifrada (clave incorrecta?): {e}") from e
        encrypted = True
    else:
        conn = _stdlib_sqlite3.connect(str(db_path))
        encrypted = False

    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return Connection(conn, encrypted=encrypted)


def init_schema(conn: Connection) -> None:
    """Aplica el esquema V1 si la BD está vacía. Idempotente."""
    existing = conn.get_schema_version()
    if existing == schema.SCHEMA_VERSION:
        return
    if existing is not None and existing != schema.SCHEMA_VERSION:
        raise RuntimeError(
            f"BD con esquema v{existing}, esperado v{schema.SCHEMA_VERSION}. "
            "Migraciones aún no implementadas."
        )
    for stmt in schema.V1:
        conn.conn.execute(stmt)
    conn.commit()
