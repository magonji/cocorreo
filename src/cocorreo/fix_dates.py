"""Heuristic to fill in `date_utc` for messages without a valid date.

When the `Date:` header is missing or fails to parse, the importer marks the message
with epoch (`1970-01-01T00:00:00+00:00`). Those messages exist in the database but
don't sort correctly. This module tries to recover them by extracting
the date from the **first `Received:` header** (the most recent hop in the
MTA chain), which is the actual delivery time of the email.
"""

from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from . import db

EPOCH = "1970-01-01T00:00:00+00:00"
RECEIVED_DATE_RE = re.compile(r";\s*(.+?)\s*$")


def _decode_headers(blob: Optional[bytes]) -> Optional[str]:
    if not blob:
        return None
    try:
        return gzip.decompress(blob).decode("utf-8", errors="replace")
    except Exception:
        return None


def _parse_received_date(headers: str) -> tuple[Optional[datetime], Optional[str]]:
    """Returns (UTC datetime, verbatim date string) of the first valid Received:."""
    for line in headers.split("\n"):
        if not line.lower().startswith("received:"):
            continue
        m = RECEIVED_DATE_RE.search(line)
        if not m:
            continue
        raw = m.group(1)
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), raw
    return None, None


def fix_epoch_dates(conn: db.Connection) -> tuple[int, int]:
    """Walks through messages with date_utc=epoch and repairs them where possible.

    Returns (reviewed, fixed).
    """
    rows = conn.execute(
        "SELECT id, raw_headers FROM messages WHERE date_utc = ? AND raw_headers IS NOT NULL",
        (EPOCH,),
    ).fetchall()
    reviewed = len(rows)
    fixed = 0
    for msg_id, headers_gz in rows:
        headers = _decode_headers(headers_gz)
        if not headers:
            continue
        dt, original = _parse_received_date(headers)
        if dt is None:
            continue
        conn.execute(
            "UPDATE messages SET date_utc = ?, date_original = ? WHERE id = ?",
            (dt.isoformat(), original, msg_id),
        )
        fixed += 1
    conn.commit()
    return reviewed, fixed
