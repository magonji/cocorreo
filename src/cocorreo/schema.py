"""Esquema del archivo cocorreo (versión 1).

El esquema se aplica como una lista lineal de sentencias SQL. No usamos
ningún ORM ni Alembic — `db.init_schema()` ejecuta esto en orden si la
BD está vacía. Para migraciones futuras añadiremos `MIGRATIONS = [V1, V2, ...]`
y un comparador con `meta.schema_version`.
"""

from __future__ import annotations

SCHEMA_VERSION = 1


V1: list[str] = [
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    INSERT INTO meta(key, value) VALUES ('schema_version', '1')
    """,

    # ---------- mensajes ----------
    """
    CREATE TABLE messages (
        id                INTEGER PRIMARY KEY,
        message_id        TEXT NOT NULL UNIQUE,
        synthesized_id    INTEGER NOT NULL DEFAULT 0,  -- 1 si message_id es sintético (no había header)
        in_reply_to       TEXT,
        references_chain  TEXT,                         -- 'References:' completo, space-separated
        subject           TEXT,
        from_name         TEXT,
        from_addr         TEXT,                         -- normalizado lowercase
        date_utc          TEXT NOT NULL,                -- ISO 8601 en UTC, ordenable
        date_original     TEXT,                         -- verbatim del header 'Date:'
        size_bytes        INTEGER NOT NULL,
        has_html          INTEGER NOT NULL DEFAULT 0,
        has_attachments   INTEGER NOT NULL DEFAULT 0,
        body_text         TEXT,                         -- texto plano (extraído o convertido desde HTML)
        body_html         TEXT,                         -- HTML original sanitizable en render
        raw_headers       BLOB,                         -- block de headers gzipped
        imported_at       TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_messages_date ON messages(date_utc)",
    "CREATE INDEX idx_messages_from ON messages(from_addr)",

    # ---------- direcciones (from/to/cc/bcc/reply-to) ----------
    """
    CREATE TABLE addresses (
        id          INTEGER PRIMARY KEY,
        message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL CHECK (kind IN ('from','to','cc','bcc','reply-to')),
        name        TEXT,
        addr        TEXT NOT NULL                       -- normalizado lowercase
    )
    """,
    "CREATE INDEX idx_addresses_msg  ON addresses(message_id)",
    "CREATE INDEX idx_addresses_addr ON addresses(addr)",

    # ---------- procedencia (M:N mensaje ↔ ubicación original) ----------
    # Un correo de Gmail aparece en [Gmail]/Todos, en INBOX, en Important, etc.
    # Cada aparición es una fila aquí; en `messages` solo hay UNA.
    """
    CREATE TABLE message_sources (
        id              INTEGER PRIMARY KEY,
        message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        source_path     TEXT NOT NULL,                  -- ruta relativa al perfil Thunderbird
        folder_display  TEXT NOT NULL,                  -- nombre de carpeta decodificado (UTF-7 mod)
        account         TEXT NOT NULL,                  -- 'imap.gmail-3.com', 'Local Folders', ...
        section         TEXT NOT NULL CHECK (section IN ('IMAP','Local')),
        byte_offset     INTEGER,                        -- posición del 'From ' en el mbox (debug)
        UNIQUE (message_id, source_path, byte_offset)
    )
    """,
    "CREATE INDEX idx_msources_msg     ON message_sources(message_id)",
    "CREATE INDEX idx_msources_folder  ON message_sources(folder_display)",
    "CREATE INDEX idx_msources_account ON message_sources(account)",

    # ---------- adjuntos (deduplicado por SHA-256 del plaintext) ----------
    """
    CREATE TABLE attachments (
        id          INTEGER PRIMARY KEY,
        sha256      TEXT NOT NULL UNIQUE,              -- hex; usado también como nombre del blob cifrado
        size_bytes  INTEGER NOT NULL,
        mime_type   TEXT
    )
    """,
    """
    CREATE TABLE message_attachments (
        id              INTEGER PRIMARY KEY,
        message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        attachment_id   INTEGER NOT NULL REFERENCES attachments(id),
        filename        TEXT,                          -- nombre tal como aparece en este mensaje
        content_id      TEXT,                          -- Content-ID si es inline
        inline          INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX idx_msgatt_msg ON message_attachments(message_id)",
    "CREATE INDEX idx_msgatt_att ON message_attachments(attachment_id)",

    # ---------- FTS5 ----------
    # Contentless: nosotros insertamos en messages_fts cuando insertamos en messages.
    # `remove_diacritics 2` permite buscar 'gonzalez' y encontrar 'González'.
    """
    CREATE VIRTUAL TABLE messages_fts USING fts5(
        subject,
        from_text,         -- 'Nombre <correo@x.com>'
        addresses_text,    -- denormalizado: nombres+emails de To/Cc/Bcc
        body,              -- body_text
        content='',
        tokenize="unicode61 remove_diacritics 2"
    )
    """,

    # ---------- provenance ----------
    """
    CREATE TABLE import_runs (
        id                       INTEGER PRIMARY KEY,
        started_at               TEXT NOT NULL,
        finished_at              TEXT,
        profile_root             TEXT NOT NULL,
        messages_imported        INTEGER NOT NULL DEFAULT 0,
        messages_duplicate_links INTEGER NOT NULL DEFAULT 0,  -- mensajes ya existentes, solo nuevo source
        messages_errors          INTEGER NOT NULL DEFAULT 0,
        attachments_imported     INTEGER NOT NULL DEFAULT 0,
        attachments_dedup_hits   INTEGER NOT NULL DEFAULT 0,
        notes                    TEXT
    )
    """,
]
