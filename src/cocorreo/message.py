"""MIME parser: raw bytes → `ParsedMessage`.

Applies `email.policy.default` (modern, decodes RFC 2047) with a fallback to
`compat32` if default fails. Any individual error during extraction is
accumulated in `parse_errors` rather than aborting the parse.

Body extraction policy:
    - Prefers `text/plain` for `body_text` (what goes into FTS5).
    - If only `text/html` is present, converts it to text with `html2text`.
    - `body_html` always captures the original HTML if present.
"""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Optional

import html2text

# Reusable html2text configuration.
_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.body_width = 0   # don't wrap lines


@dataclass
class Address:
    name: str           # may be empty
    addr: str           # normalised lowercase

    @property
    def display(self) -> str:
        if self.name:
            return f"{self.name} <{self.addr}>"
        return self.addr


@dataclass
class Attachment:
    filename: Optional[str]
    mime_type: str
    content: bytes
    content_id: Optional[str] = None
    inline: bool = False

    @property
    def sha256_hex(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass
class ParsedMessage:
    message_id: str
    synthesised_id: bool
    subject: str
    from_: Optional[Address]
    to: list[Address]
    cc: list[Address]
    bcc: list[Address]
    reply_to: list[Address]
    date_utc: Optional[datetime]      # None if the date is invalid or missing
    date_original: Optional[str]
    in_reply_to: Optional[str]
    references_chain: Optional[str]
    body_text: str
    body_html: Optional[str]
    raw_headers_gz: bytes
    size_bytes: int
    attachments: list[Attachment] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_html(self) -> bool:
        return self.body_html is not None

    @property
    def has_attachments(self) -> bool:
        return any(not a.inline for a in self.attachments)


def _safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _normalize_msgid(value: str) -> str:
    v = _safe_str(value).strip()
    if not v:
        return ""
    if v.startswith("<") and v.endswith(">"):
        return v
    return f"<{v}>"


def _parse_addr_list(value: str) -> list[Address]:
    if not value:
        return []
    out: list[Address] = []
    try:
        for name, addr in getaddresses([value]):
            if addr:
                out.append(Address(name=name or "", addr=addr.lower()))
    except Exception:
        pass
    return out


def _addr_or_none(value: str) -> Optional[Address]:
    lst = _parse_addr_list(value)
    return lst[0] if lst else None


def _parse_date(value) -> tuple[Optional[datetime], Optional[str]]:
    original = _safe_str(value).strip() or None
    if not original:
        return None, None
    try:
        dt = parsedate_to_datetime(original)
    except (TypeError, ValueError):
        return None, original
    if dt is None:
        return None, original
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), original


def _synthesise_message_id(raw: bytes, msg: Message) -> str:
    h = hashlib.sha256()
    h.update(_safe_str(msg.get("Date")).encode("utf-8", errors="replace"))
    h.update(_safe_str(msg.get("From")).encode("utf-8", errors="replace"))
    h.update(_safe_str(msg.get("Subject")).encode("utf-8", errors="replace"))
    h.update(raw[:1024])
    return f"<synth-{h.hexdigest()[:32]}@cocorreo.local>"


def _gz_header_block(msg: Message) -> bytes:
    """Serialises just the headers (no body) and gzip-compresses them."""
    lines: list[str] = []
    for k, v in msg.items():
        lines.append(f"{k}: {_safe_str(v)}")
    return gzip.compress("\n".join(lines).encode("utf-8", errors="replace"))


def _get_text_payload(part: Message) -> str:
    """Reads the textual content of a part with charset fallbacks."""
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError, AssertionError, ValueError):
        pass
    try:
        b = part.get_payload(decode=True)
        if b is None:
            return ""
        return b.decode("latin-1", errors="replace")
    except Exception:
        return ""


def parse_message(raw: bytes) -> ParsedMessage:
    errors: list[str] = []
    try:
        msg = message_from_bytes(raw, policy=policy.default)
    except Exception as e:
        errors.append(f"policy.default failed ({e!r}); falling back to compat32")
        msg = message_from_bytes(raw, policy=policy.compat32)

    # ----- identifier -----
    raw_msgid = msg.get("Message-ID") or msg.get("Message-Id")
    if raw_msgid:
        message_id = _normalize_msgid(_safe_str(raw_msgid))
        synthesised = False
    else:
        message_id = _synthesise_message_id(raw, msg)
        synthesised = True

    # ----- basic headers -----
    subject = _safe_str(msg.get("Subject")).strip()
    from_ = _addr_or_none(_safe_str(msg.get("From")))
    to_ = _parse_addr_list(_safe_str(msg.get("To")))
    cc = _parse_addr_list(_safe_str(msg.get("Cc")))
    bcc = _parse_addr_list(_safe_str(msg.get("Bcc")))
    reply_to = _parse_addr_list(_safe_str(msg.get("Reply-To")))
    date_utc, date_original = _parse_date(msg.get("Date"))
    in_reply_to = _normalize_msgid(_safe_str(msg.get("In-Reply-To"))) or None

    refs_raw = _safe_str(msg.get("References"))
    if refs_raw:
        refs = [_normalize_msgid(r) for r in refs_raw.split() if r.strip()]
        references_chain = " ".join(refs) if refs else None
    else:
        references_chain = None

    # ----- body -----
    body_text = ""
    body_html: Optional[str] = None
    body_part = None
    try:
        body_part = msg.get_body(preferencelist=("plain", "html"))
    except Exception as e:
        errors.append(f"get_body: {e!r}")

    if body_part is not None:
        ct = body_part.get_content_type()
        if ct == "text/plain":
            body_text = _get_text_payload(body_part)
            # If there's also HTML, capture it too for rendering.
            try:
                html_part = msg.get_body(preferencelist=("html",))
                if html_part is not None and html_part is not body_part:
                    body_html = _get_text_payload(html_part)
            except Exception:
                pass
        elif ct == "text/html":
            body_html = _get_text_payload(body_part)
            try:
                body_text = _h2t.handle(body_html)
            except Exception as e:
                errors.append(f"html2text: {e!r}")

    # ----- attachments -----
    attachments: list[Attachment] = []
    try:
        for part in msg.iter_attachments():
            try:
                content = part.get_payload(decode=True)
            except Exception as e:
                errors.append(f"attachment decode: {e!r}")
                content = None
            if not content:
                continue
            disp = part.get_content_disposition()
            content_id = part.get("Content-ID")
            if content_id:
                content_id = _safe_str(content_id).strip().strip("<>")
            attachments.append(Attachment(
                filename=part.get_filename(),
                mime_type=part.get_content_type(),
                content=content,
                content_id=content_id,
                inline=(disp == "inline"),
            ))
    except Exception as e:
        errors.append(f"iter_attachments: {e!r}")

    return ParsedMessage(
        message_id=message_id,
        synthesised_id=synthesised,
        subject=subject,
        from_=from_,
        to=to_,
        cc=cc,
        bcc=bcc,
        reply_to=reply_to,
        date_utc=date_utc,
        date_original=date_original,
        in_reply_to=in_reply_to,
        references_chain=references_chain,
        body_text=body_text,
        body_html=body_html,
        raw_headers_gz=_gz_header_block(msg),
        size_bytes=len(raw),
        attachments=attachments,
        parse_errors=errors,
    )
