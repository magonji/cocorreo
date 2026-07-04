"""Importer mbox → encrypted database.

Orchestrates: for each mbox file under a Thunderbird profile, parses each
message, deduplicates by `Message-ID`, writes to the database, encrypts
attachments on the fly and keeps FTS5 up to date. Idempotent: re-running
doesn't duplicate.
"""

from __future__ import annotations

import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from . import crypto, db, discover, mbox, message
from .keystore import Keystore, insecure_dev_mode

COMMIT_EVERY_MESSAGES = 500
MAX_ERROR_LOG = 500


@dataclass(frozen=True)
class MboxCandidate:
    path: Path
    rel_path: str
    account: str
    section: str            # 'IMAP' | 'Local'
    display_folder: str     # relative path with modified UTF-7 decoded


@dataclass
class ImportStats:
    messages_imported: int = 0
    messages_duplicate_links: int = 0
    messages_errors: int = 0
    attachments_imported: int = 0
    attachments_dedup_hits: int = 0
    files_processed: int = 0


def attachment_blob_path(attachments_dir: Path, sha256_hex: str) -> Path:
    """`data/attachments/ab/abc1234….bin` (sharded by first 2 hex chars)."""
    return attachments_dir / sha256_hex[:2] / f"{sha256_hex}.bin"


def enumerate_candidates(profile_root: Path,
                         account_filter: Optional[set[str]] = None) -> list[MboxCandidate]:
    out: list[MboxCandidate] = []
    for path, account, section in discover.iter_mbox_candidates(profile_root):
        if account_filter and account not in account_filter:
            continue
        rel = path.relative_to(profile_root)
        display = "/".join(discover.decode_imap_utf7(p) for p in rel.parts)
        out.append(MboxCandidate(
            path=path,
            rel_path=str(rel),
            account=account,
            section=section,
            display_folder=display,
        ))
    return out


class Importer:
    def __init__(
        self,
        ks: Keystore,
        conn: db.Connection,
        profile_root: Path,
        console: Optional[Console] = None,
    ):
        self.ks = ks
        self.conn = conn
        self.profile_root = profile_root
        self.console = console or Console()
        self.stats = ImportStats()
        self.run_id: Optional[int] = None
        self._errors: list[dict] = []

    # ---------- lifecycle ----------

    def _begin_run(self) -> None:
        cur = self.conn.execute(
            "INSERT INTO import_runs (started_at, profile_root) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             str(self.profile_root)),
        )
        self.run_id = cur.lastrowid
        self.conn.commit()

    def _finalize_run(self) -> None:
        if self.run_id is None:
            return
        self.conn.execute(
            """UPDATE import_runs SET
                finished_at = ?,
                messages_imported = ?,
                messages_duplicate_links = ?,
                messages_errors = ?,
                attachments_imported = ?,
                attachments_dedup_hits = ?,
                notes = ?
               WHERE id = ?""",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                self.stats.messages_imported,
                self.stats.messages_duplicate_links,
                self.stats.messages_errors,
                self.stats.attachments_imported,
                self.stats.attachments_dedup_hits,
                json.dumps(self._errors[:MAX_ERROR_LOG], ensure_ascii=False) if self._errors else None,
                self.run_id,
            ),
        )
        self.conn.commit()

    def _log_error(self, source: str, offset: Optional[int], err: BaseException | str) -> None:
        self.stats.messages_errors += 1
        if len(self._errors) < MAX_ERROR_LOG:
            self._errors.append({
                "source": source,
                "offset": offset,
                "error": err if isinstance(err, str) else f"{type(err).__name__}: {err}",
            })

    # ---------- inserts ----------

    def _ensure_attachment(self, att: message.Attachment) -> int:
        sha = att.sha256_hex
        row = self.conn.execute(
            "SELECT id FROM attachments WHERE sha256 = ?", (sha,)
        ).fetchone()
        if row:
            self.stats.attachments_dedup_hits += 1
            return row[0]

        blob_path = attachment_blob_path(self.ks.attachments_dir, sha)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        if insecure_dev_mode():
            blob_path.write_bytes(att.content)
        else:
            with io.BytesIO(att.content) as src, blob_path.open("wb") as dst:
                crypto.encrypt_file(src, dst, self.ks.keys.attach_key)

        cur = self.conn.execute(
            "INSERT INTO attachments (sha256, size_bytes, mime_type) VALUES (?, ?, ?)",
            (sha, len(att.content), att.mime_type),
        )
        self.stats.attachments_imported += 1
        return cur.lastrowid

    def _link_source(self, message_pk: int, cand: MboxCandidate, byte_offset: int) -> bool:
        """True if we added a new source, False if it already existed."""
        try:
            self.conn.execute(
                """INSERT INTO message_sources
                       (message_id, source_path, folder_display, account, section, byte_offset)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_pk, cand.rel_path, cand.display_folder,
                 cand.account, cand.section, byte_offset),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def _insert_new_message(self, parsed: message.ParsedMessage) -> int:
        cur = self.conn.execute(
            """INSERT INTO messages (
                message_id, synthesized_id, in_reply_to, references_chain,
                subject, from_name, from_addr,
                date_utc, date_original,
                size_bytes, has_html, has_attachments,
                body_text, body_html, raw_headers,
                imported_at
            ) VALUES (?,?,?,?, ?,?,?, ?,?, ?,?,?, ?,?,?, ?)""",
            (
                parsed.message_id,
                int(parsed.synthesised_id),
                parsed.in_reply_to,
                parsed.references_chain,
                parsed.subject,
                parsed.from_.name if parsed.from_ else None,
                parsed.from_.addr if parsed.from_ else None,
                parsed.date_utc.isoformat() if parsed.date_utc else "1970-01-01T00:00:00+00:00",
                parsed.date_original,
                parsed.size_bytes,
                int(parsed.has_html),
                int(parsed.has_attachments),
                parsed.body_text,
                parsed.body_html,
                parsed.raw_headers_gz,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        msg_pk: int = cur.lastrowid

        # Addresses
        addr_rows = []
        if parsed.from_:
            addr_rows.append((msg_pk, "from", parsed.from_.name, parsed.from_.addr))
        for a in parsed.to:
            addr_rows.append((msg_pk, "to", a.name, a.addr))
        for a in parsed.cc:
            addr_rows.append((msg_pk, "cc", a.name, a.addr))
        for a in parsed.bcc:
            addr_rows.append((msg_pk, "bcc", a.name, a.addr))
        for a in parsed.reply_to:
            addr_rows.append((msg_pk, "reply-to", a.name, a.addr))
        if addr_rows:
            self.conn.conn.executemany(
                "INSERT INTO addresses (message_id, kind, name, addr) VALUES (?,?,?,?)",
                addr_rows,
            )

        # Attachments
        for att in parsed.attachments:
            att_id = self._ensure_attachment(att)
            self.conn.execute(
                """INSERT INTO message_attachments
                       (message_id, attachment_id, filename, content_id, inline)
                   VALUES (?, ?, ?, ?, ?)""",
                (msg_pk, att_id, att.filename, att.content_id, int(att.inline)),
            )

        # FTS5
        from_text = parsed.from_.display if parsed.from_ else ""
        addr_text = " ".join(
            (a.name + " " + a.addr).strip()
            for a in (parsed.to + parsed.cc + parsed.bcc)
        )
        self.conn.execute(
            """INSERT INTO messages_fts (rowid, subject, from_text, addresses_text, body)
               VALUES (?, ?, ?, ?, ?)""",
            (msg_pk, parsed.subject, from_text, addr_text, parsed.body_text),
        )

        return msg_pk

    # ---------- per-message processing ----------

    def _process_one(self, cand: MboxCandidate, byte_offset: int, raw: bytes) -> None:
        try:
            parsed = message.parse_message(raw)
        except Exception as e:
            self._log_error(cand.rel_path, byte_offset, e)
            return

        # Does it already exist?
        row = self.conn.execute(
            "SELECT id FROM messages WHERE message_id = ?", (parsed.message_id,)
        ).fetchone()
        if row:
            if self._link_source(row[0], cand, byte_offset):
                self.stats.messages_duplicate_links += 1
            return

        try:
            msg_pk = self._insert_new_message(parsed)
            self._link_source(msg_pk, cand, byte_offset)
            self.stats.messages_imported += 1
        except sqlite3.IntegrityError as e:
            # Race with a duplicate within the same batch.
            row = self.conn.execute(
                "SELECT id FROM messages WHERE message_id = ?", (parsed.message_id,)
            ).fetchone()
            if row:
                self._link_source(row[0], cand, byte_offset)
                self.stats.messages_duplicate_links += 1
            else:
                self._log_error(cand.rel_path, byte_offset, e)
        except Exception as e:
            self._log_error(cand.rel_path, byte_offset, e)

    # ---------- entry point ----------

    def run(
        self,
        candidates: Iterable[MboxCandidate],
        limit: Optional[int] = None,
    ) -> ImportStats:
        candidates = sorted(candidates, key=lambda c: c.path.stat().st_size)
        self._begin_run()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[cyan]{task.fields[name]}"),
            TextColumn("• [green]{task.fields[stats]}"),
            TimeRemainingColumn(),
            console=self.console,
        ) as progress:
            outer = progress.add_task(
                "Importing", total=len(candidates), name="", stats="",
            )

            commit_counter = 0
            total_done = 0
            stopped_early = False
            for cand in candidates:
                progress.update(
                    outer,
                    name=cand.display_folder[:60],
                    stats=f"{self.stats.messages_imported:,} new / "
                          f"{self.stats.messages_duplicate_links:,} dup / "
                          f"{self.stats.messages_errors:,} err",
                )
                try:
                    for byte_offset, raw in mbox.iter_messages(cand.path):
                        self._process_one(cand, byte_offset, raw)
                        commit_counter += 1
                        total_done += 1
                        if commit_counter >= COMMIT_EVERY_MESSAGES:
                            self.conn.commit()
                            commit_counter = 0
                            progress.update(
                                outer,
                                stats=f"{self.stats.messages_imported:,} new / "
                                      f"{self.stats.messages_duplicate_links:,} dup / "
                                      f"{self.stats.messages_errors:,} err",
                            )
                        if limit is not None and total_done >= limit:
                            stopped_early = True
                            break
                except Exception as e:
                    self._log_error(cand.rel_path, None, f"file-level: {e!r}")

                self.stats.files_processed += 1
                progress.advance(outer)
                if stopped_early:
                    break

            self.conn.commit()

        self._finalize_run()
        return self.stats
