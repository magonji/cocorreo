"""Heurística para rellenar `date_utc` en mensajes sin fecha válida.

Cuando el header `Date:` falta o no parsea, el importer marca el mensaje con
epoch (`1970-01-01T00:00:00+00:00`). Esos mensajes existen en la BD pero
no se ordenan correctamente. Este módulo intenta recuperarlos extrayendo
la fecha del **primer header `Received:`** (la entrega más reciente en la
cadena MTA), que es el delivery time real del correo.
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
    """Devuelve (UTC datetime, fecha-string verbatim) del primer Received: válido."""
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
    """Recorre los mensajes con date_utc=epoch y los repara si es posible.

    Devuelve (revisados, arreglados).
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
