"""Schema for the cocorreo archive (version 1).

The schema is applied as a linear list of SQL statements. We don't use
any ORM or Alembic — `db.init_schema()` runs this in order if the
database is empty. For future migrations we'll add `MIGRATIONS = [V1, V2, ...]`
and a comparator against `meta.schema_version`.
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

    # ---------- messages ----------
    """
    CREATE TABLE messages (
        id                INTEGER PRIMARY KEY,
        message_id        TEXT NOT NULL UNIQUE,
        synthesized_id    INTEGER NOT NULL DEFAULT 0,  -- 1 if message_id is synthetic (no header present)
        in_reply_to       TEXT,
        references_chain  TEXT,                         -- full 'References:', space-separated
        subject           TEXT,
        from_name         TEXT,
        from_addr         TEXT,                         -- normalised lowercase
        date_utc          TEXT NOT NULL,                -- ISO 8601 in UTC, sortable
        date_original     TEXT,                         -- verbatim from the 'Date:' header
        size_bytes        INTEGER NOT NULL,
        has_html          INTEGER NOT NULL DEFAULT 0,
        has_attachments   INTEGER NOT NULL DEFAULT 0,
        body_text         TEXT,                         -- plain text (extracted or converted from HTML)
        body_html         TEXT,                         -- original HTML, sanitised on render
        raw_headers       BLOB,                         -- gzipped header block
        imported_at       TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_messages_date ON messages(date_utc)",
    "CREATE INDEX idx_messages_from ON messages(from_addr)",

    # ---------- addresses (from/to/cc/bcc/reply-to) ----------
    """
    CREATE TABLE addresses (
        id          INTEGER PRIMARY KEY,
        message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL CHECK (kind IN ('from','to','cc','bcc','reply-to')),
        name        TEXT,
        addr        TEXT NOT NULL                       -- normalised lowercase
    )
    """,
    "CREATE INDEX idx_addresses_msg  ON addresses(message_id)",
    "CREATE INDEX idx_addresses_addr ON addresses(addr)",

    # ---------- provenance (M:N message ↔ original location) ----------
    # A Gmail message appears in [Gmail]/All Mail, in INBOX, in Important, etc.
    # Each occurrence is a row here; there's only ONE row in `messages`.
    """
    CREATE TABLE message_sources (
        id              INTEGER PRIMARY KEY,
        message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        source_path     TEXT NOT NULL,                  -- path relative to the Thunderbird profile
        folder_display  TEXT NOT NULL,                  -- decoded folder name (modified UTF-7)
        account         TEXT NOT NULL,                  -- 'imap.gmail-3.com', 'Local Folders', ...
        section         TEXT NOT NULL CHECK (section IN ('IMAP','Local')),
        byte_offset     INTEGER,                        -- position of the 'From ' line in the mbox (debug)
        UNIQUE (message_id, source_path, byte_offset)
    )
    """,
    "CREATE INDEX idx_msources_msg     ON message_sources(message_id)",
    "CREATE INDEX idx_msources_folder  ON message_sources(folder_display)",
    "CREATE INDEX idx_msources_account ON message_sources(account)",

    # ---------- attachments (deduplicated by SHA-256 of the plaintext) ----------
    """
    CREATE TABLE attachments (
        id          INTEGER PRIMARY KEY,
        sha256      TEXT NOT NULL UNIQUE,              -- hex; also used as the encrypted blob's filename
        size_bytes  INTEGER NOT NULL,
        mime_type   TEXT
    )
    """,
    """
    CREATE TABLE message_attachments (
        id              INTEGER PRIMARY KEY,
        message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        attachment_id   INTEGER NOT NULL REFERENCES attachments(id),
        filename        TEXT,                          -- name as it appears in this message
        content_id      TEXT,                          -- Content-ID if inline
        inline          INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX idx_msgatt_msg ON message_attachments(message_id)",
    "CREATE INDEX idx_msgatt_att ON message_attachments(attachment_id)",

    # ---------- FTS5 ----------
    # Contentless: we insert into messages_fts ourselves whenever we insert into messages.
    # `remove_diacritics 2` lets us search 'gonzalez' and find 'González'.
    """
    CREATE VIRTUAL TABLE messages_fts USING fts5(
        subject,
        from_text,         -- 'Name <email@x.com>'
        addresses_text,    -- denormalised: names+emails of To/Cc/Bcc
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
        messages_duplicate_links INTEGER NOT NULL DEFAULT 0,  -- messages that already existed, only a new source
        messages_errors          INTEGER NOT NULL DEFAULT 0,
        attachments_imported     INTEGER NOT NULL DEFAULT 0,
        attachments_dedup_hits   INTEGER NOT NULL DEFAULT 0,
        notes                    TEXT
    )
    """,
]
