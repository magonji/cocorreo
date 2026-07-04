"""Reconstruction of messages in `.eml` format (RFC 5322 + MIME).

From what's stored in the database we reconstruct a portable email that any
client (Thunderbird, Apple Mail, Outlook…) can open:

    multipart/mixed
    ├── multipart/related      (if there are inline images)
    │   ├── multipart/alternative
    │   │   ├── text/plain
    │   │   └── text/html
    │   └── image/png (inline, Content-ID: <…>)
    └── application/pdf (attachment, regular)

Notes:
- The HTML we return is the **sanitised** version served by the API
  (bleach stripped scripts/iframes). We don't reconstruct the original HTML.
- If the `Date:` header was synthesised because it was missing, we export the
  date in RFC 5322 format derived from `date_utc`.
- `Bcc:` is included if we had it stored — not common in received
  mail, but it is in mail sent by oneself.
"""

from __future__ import annotations

import re
from datetime import datetime
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import format_datetime
from typing import Optional

from . import db, importer
from .db import Archive

_BAD_FILENAME_CHARS = '/\\:*?"<>|\r\n\t\0'


def _fmt_addr(name: str, addr: str) -> str:
    name = (name or "").strip()
    if name:
        # email.utils.formataddr is the "correct" way, but its quoting is strict.
        # This is good enough for our export and keeps the header readable.
        return f'"{name}" <{addr}>'
    return addr


def _fmt_addrs(rows: list[tuple[str, str]]) -> str:
    return ", ".join(_fmt_addr(name, addr) for name, addr in rows)


def _safe_filename(subject: Optional[str], message_pk: int) -> str:
    base = (subject or "message").strip()
    base = "".join("_" if c in _BAD_FILENAME_CHARS else c for c in base)
    base = re.sub(r"\s+", " ", base).strip()
    base = base[:80] or "message"
    return f"{base} - #{message_pk}.eml"


def build_eml(conn: db.Connection, archive: Archive, message_pk: int) -> tuple[bytes, str]:
    """Reconstructs a full message as RFC 5322 bytes.

    Returns (eml_bytes, suggested_filename).
    """
    row = conn.execute(
        """
        SELECT message_id, subject, from_name, from_addr,
               date_utc, date_original, in_reply_to, references_chain,
               body_text, body_html
        FROM messages WHERE id = ?
        """,
        (message_pk,),
    ).fetchone()
    if not row:
        raise LookupError(f"message {message_pk} not found")

    (msg_id_str, subject, from_name, from_addr, date_utc, date_original,
     in_reply_to, references_chain, body_text, body_html) = row

    addr_rows = conn.execute(
        "SELECT kind, name, addr FROM addresses WHERE message_id = ?",
        (message_pk,),
    ).fetchall()
    to_, cc, bcc, reply_to = [], [], [], []
    for kind, name, addr in addr_rows:
        pair = (name or "", addr)
        if kind == "to":
            to_.append(pair)
        elif kind == "cc":
            cc.append(pair)
        elif kind == "bcc":
            bcc.append(pair)
        elif kind == "reply-to":
            reply_to.append(pair)

    # Attachments: inline ones first so `add_attachment(inline=…)` places them
    # inside the multipart/related alongside the HTML.
    att_rows = conn.execute(
        """
        SELECT a.sha256, a.mime_type, ma.filename, ma.content_id, ma.inline
        FROM message_attachments ma
        JOIN attachments a ON a.id = ma.attachment_id
        WHERE ma.message_id = ?
        ORDER BY ma.inline DESC, ma.id ASC
        """,
        (message_pk,),
    ).fetchall()

    msg = EmailMessage(policy=default_policy)
    if from_addr:
        msg["From"] = _fmt_addr(from_name or "", from_addr)
    if to_:
        msg["To"] = _fmt_addrs(to_)
    if cc:
        msg["Cc"] = _fmt_addrs(cc)
    if bcc:
        msg["Bcc"] = _fmt_addrs(bcc)
    if reply_to:
        msg["Reply-To"] = _fmt_addrs(reply_to)
    if subject:
        msg["Subject"] = subject
    # Date: prefer the original verbatim value; otherwise, RFC 5322 format from date_utc.
    if date_original:
        msg["Date"] = date_original
    elif date_utc and not date_utc.startswith("1970-"):
        try:
            dt = datetime.fromisoformat(date_utc)
            msg["Date"] = format_datetime(dt)
        except (TypeError, ValueError):
            pass
    if msg_id_str:
        msg["Message-ID"] = msg_id_str
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references_chain:
        msg["References"] = references_chain
    msg["X-Cocorreo-Exported"] = "1"

    text_body = body_text or ""
    html_body = body_html or ""

    # Body: alternative if there's HTML, plain text only otherwise.
    msg.set_content(text_body or "(message has no text body)")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    # Attachments
    for sha256, mime_type, filename, content_id, inline in att_rows:
        blob_path = importer.attachment_blob_path(archive.attachments_dir, sha256)
        if not blob_path.is_file():
            continue
        try:
            data = blob_path.read_bytes()
        except Exception:
            continue
        maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
        kwargs = {
            "maintype": maintype or "application",
            "subtype": subtype or "octet-stream",
            "filename": filename,
            "disposition": "inline" if inline else "attachment",
        }
        if inline and content_id:
            kwargs["cid"] = f"<{content_id}>"
        msg.add_attachment(data, **kwargs)

    return msg.as_bytes(), _safe_filename(subject, message_pk)
