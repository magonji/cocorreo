"""cocorreo FastAPI API.

Synchronous endpoints (def, not async def) — FastAPI runs them in a threadpool
so the event loop isn't blocked. Each request opens a new SQLite connection
(cheap with WAL); the derived keys are kept in `app.state.keystore` for the
whole lifetime of the process.
"""

import base64
import json
import re
from contextlib import asynccontextmanager
from typing import Annotated, Iterator, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import crypto, db, export, importer
from .keystore import Keystore, insecure_dev_mode
from .models import (
    AccountStat,
    Address,
    AttachmentInfo,
    FolderInfo,
    FoldersResponse,
    HealthResponse,
    HourStat,
    ImageItem,
    ImageListResponse,
    MessageDetail,
    MessageListResponse,
    MessageSummary,
    MonthStat,
    SearchResponse,
    SenderStat,
    SourceInfo,
    StatsResponse,
    ThreadResponse,
    WeekdayStat,
    YearStat,
)
from .sanitise import sanitise_html

SNIPPET_LEN = 240


# ---------- pagination cursor ----------

def encode_cursor(date_utc: str, id_: int) -> str:
    raw = json.dumps([date_utc, id_], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, int]:
    pad = "=" * ((4 - len(cursor) % 4) % 4)
    raw = base64.urlsafe_b64decode(cursor + pad)
    date_utc, id_ = json.loads(raw)
    return str(date_utc), int(id_)


def _snippet(body_text: Optional[str]) -> Optional[str]:
    if not body_text:
        return None
    cleaned = " ".join(body_text.split())
    if len(cleaned) <= SNIPPET_LEN:
        return cleaned
    return cleaned[:SNIPPET_LEN] + "…"


def _row_to_summary(row) -> MessageSummary:
    (id_, message_id, subject, from_name, from_addr, date_utc,
     has_html, has_atts, size_bytes, body_text) = row
    return MessageSummary(
        id=id_,
        message_id=message_id,
        subject=subject or "",
        from_=Address(name=from_name or "", addr=from_addr) if from_addr else None,
        date_utc=date_utc,
        has_attachments=bool(has_atts),
        has_html=bool(has_html),
        size_bytes=size_bytes or 0,
        snippet=_snippet(body_text),
    )


_SUMMARY_COLS = (
    "m.id, m.message_id, m.subject, m.from_name, m.from_addr, "
    "m.date_utc, m.has_html, m.has_attachments, m.size_bytes, m.body_text"
)

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_date_from(s: Optional[str]) -> Optional[str]:
    """If the client passes 'YYYY-MM-DD', we expand it to the start of the UTC day."""
    if not s:
        return None
    if _DATE_ONLY_RE.match(s):
        return f"{s}T00:00:00+00:00"
    return s


def _normalize_date_to(s: Optional[str]) -> Optional[str]:
    """For `date_to`, we expand it to the end of the day (inclusive)."""
    if not s:
        return None
    if _DATE_ONLY_RE.match(s):
        return f"{s}T23:59:59+00:00"
    return s


def _build_filters(
    *,
    account: Optional[str],
    folder: Optional[str],
    from_addr: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    has_attachment: Optional[bool],
    cursor: Optional[str],
) -> tuple[list[str], list[str], list]:
    """Builds (joins, wheres, params) for the common listing/search filters."""
    wheres: list[str] = []
    params: list = []
    joins: list[str] = []

    if account or folder:
        joins.append("JOIN message_sources ms ON ms.message_id = m.id")
        if account:
            wheres.append("ms.account = ?")
            params.append(account)
        if folder:
            wheres.append("ms.folder_display = ?")
            params.append(folder)
    if from_addr:
        wheres.append("m.from_addr = ?")
        params.append(from_addr.lower())
    df = _normalize_date_from(date_from)
    dt = _normalize_date_to(date_to)
    if df:
        wheres.append("m.date_utc >= ?")
        params.append(df)
    if dt:
        wheres.append("m.date_utc <= ?")
        params.append(dt)
    if has_attachment is not None:
        wheres.append("m.has_attachments = ?")
        params.append(int(has_attachment))
    if cursor:
        try:
            cur_date, cur_id = decode_cursor(cursor)
        except Exception:
            raise HTTPException(400, "invalid cursor")
        wheres.append("(m.date_utc < ? OR (m.date_utc = ? AND m.id < ?))")
        params.extend([cur_date, cur_date, cur_id])
    return joins, wheres, params


# ---------- factory ----------

def create_app(keystore: Keystore) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Sanity check on startup (correct key, schema applied).
        with db.connect(keystore.db_path, keystore.keys) as conn:
            ver = conn.get_schema_version()
            if ver is None:
                raise RuntimeError(
                    f"no schema found in database {keystore.db_path}. Run `cocorreo init` first."
                )
        yield

    app = FastAPI(
        title="cocorreo",
        description="Personal email archive — local API.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.keystore = keystore

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],         # local dev; in prod the frontend is served by the same FastAPI
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- dependency: DB ----------

    def get_db(request: Request):
        ks: Keystore = request.app.state.keystore
        conn = db.connect(ks.db_path, ks.keys)
        try:
            yield conn
        finally:
            conn.close()

    DbDep = Annotated[db.Connection, Depends(get_db)]

    # ---------- /health ----------

    @app.get("/health", response_model=HealthResponse)
    def health(conn: DbDep) -> HealthResponse:
        ver = conn.get_schema_version() or 0
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return HealthResponse(
            ok=True,
            schema_version=ver,
            encrypted=conn.encrypted,
            total_messages=total,
        )

    # ---------- /messages ----------

    @app.get("/messages", response_model=MessageListResponse)
    def list_messages(
        conn: DbDep,
        account: Annotated[Optional[str], Query(description="Filters by account.")] = None,
        folder: Annotated[Optional[str], Query(description="Filters by folder (folder_display).")] = None,
        from_addr: Annotated[Optional[str], Query(alias="from", description="Filters by exact sender.")] = None,
        date_from: Annotated[Optional[str], Query(description="ISO 8601, inclusive.")] = None,
        date_to: Annotated[Optional[str], Query(description="ISO 8601, inclusive.")] = None,
        has_attachment: Annotated[Optional[bool], Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[Optional[str], Query()] = None,
    ) -> MessageListResponse:
        joins, wheres, params = _build_filters(
            account=account, folder=folder, from_addr=from_addr,
            date_from=date_from, date_to=date_to,
            has_attachment=has_attachment, cursor=cursor,
        )

        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        join_clause = " ".join(joins)
        distinct = "DISTINCT" if joins else ""
        sql = (
            f"SELECT {distinct} {_SUMMARY_COLS} "
            f"FROM messages m {join_clause} {where_clause} "
            f"ORDER BY m.date_utc DESC, m.id DESC LIMIT ?"
        )
        params.append(limit + 1)

        rows = conn.execute(sql, params).fetchall()
        has_more = len(rows) > limit
        items = [_row_to_summary(r) for r in rows[:limit]]
        next_cursor = encode_cursor(items[-1].date_utc, items[-1].id) if (has_more and items) else None
        return MessageListResponse(items=items, next_cursor=next_cursor)

    # ---------- /search ----------

    @app.get("/search", response_model=SearchResponse)
    def search(
        conn: DbDep,
        q: Annotated[str, Query(min_length=1, description="FTS5 syntax.")],
        account: Annotated[Optional[str], Query()] = None,
        folder: Annotated[Optional[str], Query()] = None,
        from_addr: Annotated[Optional[str], Query(alias="from")] = None,
        date_from: Annotated[Optional[str], Query()] = None,
        date_to: Annotated[Optional[str], Query()] = None,
        has_attachment: Annotated[Optional[bool], Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[Optional[str], Query()] = None,
    ) -> SearchResponse:
        joins, wheres, params = _build_filters(
            account=account, folder=folder, from_addr=from_addr,
            date_from=date_from, date_to=date_to,
            has_attachment=has_attachment, cursor=cursor,
        )

        # MATCH goes in the base WHERE; the other filters are concatenated with AND.
        extra_where = ("AND " + " AND ".join(wheres)) if wheres else ""
        join_clause = " ".join(joins)
        distinct = "DISTINCT" if joins else ""
        sql = (
            f"SELECT {distinct} {_SUMMARY_COLS} "
            "FROM messages_fts fts "
            f"JOIN messages m ON m.id = fts.rowid {join_clause} "
            "WHERE messages_fts MATCH ? "
            f"{extra_where} "
            "ORDER BY m.date_utc DESC, m.id DESC LIMIT ?"
        )
        # MATCH goes FIRST in params; _build_filters already returns its own in order.
        match_params = [q] + params + [limit + 1]
        try:
            rows = conn.execute(sql, match_params).fetchall()
        except Exception as e:
            raise HTTPException(400, f"invalid FTS5 query: {e}")

        has_more = len(rows) > limit
        items = [_row_to_summary(r) for r in rows[:limit]]
        next_cursor = encode_cursor(items[-1].date_utc, items[-1].id) if (has_more and items) else None
        return SearchResponse(query=q, items=items, next_cursor=next_cursor)

    # ---------- /messages/{id} ----------

    @app.get("/messages/{message_id}", response_model=MessageDetail)
    def message_detail(message_id: int, conn: DbDep) -> MessageDetail:
        row = conn.execute(
            """
            SELECT id, message_id, synthesized_id, subject, from_name, from_addr,
                   date_utc, date_original, in_reply_to, references_chain,
                   size_bytes, has_html, has_attachments, body_text, body_html
            FROM messages WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "message not found")

        (id_, msg_id_str, synth, subject, from_name, from_addr, date_utc,
         date_original, in_reply_to, refs, size, has_html, has_atts,
         body_text, body_html) = row

        addr_rows = conn.execute(
            "SELECT kind, name, addr FROM addresses WHERE message_id = ?",
            (message_id,),
        ).fetchall()
        to_, cc, bcc, reply_to = [], [], [], []
        for kind, name, addr in addr_rows:
            a = Address(name=name or "", addr=addr)
            if kind == "to":
                to_.append(a)
            elif kind == "cc":
                cc.append(a)
            elif kind == "bcc":
                bcc.append(a)
            elif kind == "reply-to":
                reply_to.append(a)

        att_rows = conn.execute(
            """
            SELECT a.id, ma.filename, a.mime_type, a.size_bytes, ma.inline, ma.content_id
            FROM message_attachments ma
            JOIN attachments a ON a.id = ma.attachment_id
            WHERE ma.message_id = ?
            ORDER BY ma.inline ASC, ma.id ASC
            """,
            (message_id,),
        ).fetchall()
        attachments = [
            AttachmentInfo(
                id=r[0],
                filename=r[1],
                mime_type=r[2] or "application/octet-stream",
                size_bytes=r[3] or 0,
                inline=bool(r[4]),
                content_id=r[5],
            )
            for r in att_rows
        ]

        src_rows = conn.execute(
            """
            SELECT account, section, folder_display, source_path
            FROM message_sources WHERE message_id = ?
            ORDER BY id ASC
            """,
            (message_id,),
        ).fetchall()
        sources = [
            SourceInfo(account=r[0], section=r[1], folder_display=r[2], source_path=r[3])
            for r in src_rows
        ]

        return MessageDetail(
            id=id_,
            message_id=msg_id_str,
            synthesised_id=bool(synth),
            subject=subject or "",
            from_=Address(name=from_name or "", addr=from_addr) if from_addr else None,
            to=to_,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            date_utc=date_utc,
            date_original=date_original,
            in_reply_to=in_reply_to,
            references_chain=refs,
            body_text=body_text or "",
            body_html=sanitise_html(body_html) if body_html else None,
            size_bytes=size or 0,
            has_html=bool(has_html),
            has_attachments=bool(has_atts),
            attachments=attachments,
            sources=sources,
        )

    # ---------- /messages/{id}/thread ----------

    @app.get("/messages/{message_id}/thread", response_model=ThreadResponse)
    def message_thread(message_id: int, conn: DbDep) -> ThreadResponse:
        # Recursive CTE: starts from the given message and expands towards parents
        # (following `in_reply_to`) and towards children (other messages that point
        # to this one). SQLite limits recursion to 1000 iterations by default,
        # more than enough for typical threads.
        sql = f"""
            WITH RECURSIVE thread_msgids(msgid) AS (
                SELECT message_id FROM messages WHERE id = ?
                UNION
                SELECT m.in_reply_to
                FROM messages m, thread_msgids t
                WHERE m.message_id = t.msgid AND m.in_reply_to IS NOT NULL AND m.in_reply_to != ''
                UNION
                SELECT m.message_id
                FROM messages m, thread_msgids t
                WHERE m.in_reply_to = t.msgid
            )
            SELECT {_SUMMARY_COLS}
            FROM messages m
            WHERE m.message_id IN (SELECT msgid FROM thread_msgids)
            ORDER BY m.date_utc ASC, m.id ASC
        """
        rows = conn.execute(sql, (message_id,)).fetchall()
        if not rows:
            raise HTTPException(404, "message not found")
        items = [_row_to_summary(r) for r in rows]
        # The root is the oldest in the thread (first item in ASC order).
        return ThreadResponse(root_id=items[0].id, items=items)

    # ---------- /messages/{id}/export.eml ----------

    @app.get("/messages/{message_id}/export.eml")
    def export_eml(message_id: int, request: Request):
        ks: Keystore = request.app.state.keystore
        with db.connect(ks.db_path, ks.keys) as conn:
            try:
                data, filename = export.build_eml(conn, ks, message_id)
            except LookupError:
                raise HTTPException(404, "message not found")
        headers = {
            "Content-Disposition": (
                f"attachment; filename=\"{filename}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
        }
        return Response(content=data, media_type="message/rfc822", headers=headers)

    # ---------- /messages/{id}/attachments/{att_id} ----------

    @app.get("/messages/{message_id}/attachments/{att_id}")
    def attachment_download(message_id: int, att_id: int, request: Request):
        ks: Keystore = request.app.state.keystore
        with db.connect(ks.db_path, ks.keys) as conn:
            row = conn.execute(
                """
                SELECT a.sha256, a.mime_type, a.size_bytes, ma.filename, ma.inline
                FROM message_attachments ma
                JOIN attachments a ON a.id = ma.attachment_id
                WHERE ma.message_id = ? AND a.id = ?
                LIMIT 1
                """,
                (message_id, att_id),
            ).fetchone()
        if not row:
            raise HTTPException(404, "attachment not found")
        sha256, mime_type, size_bytes, filename, inline = row
        blob_path = importer.attachment_blob_path(ks.attachments_dir, sha256)
        if not blob_path.is_file():
            raise HTTPException(500, f"blob doesn't exist on disk: {sha256[:16]}…")

        attach_key = ks.keys.attach_key

        def stream() -> Iterator[bytes]:
            if insecure_dev_mode():
                with blob_path.open("rb") as f:
                    yield from iter(lambda: f.read(1024 * 1024), b"")
            else:
                yield from crypto.iter_decrypt(blob_path, attach_key)

        headers: dict[str, str] = {}
        if size_bytes:
            headers["Content-Length"] = str(size_bytes)
        if filename:
            disp = "inline" if inline else "attachment"
            # RFC 5987 for non-ASCII filenames (accents, etc.)
            headers["Content-Disposition"] = (
                f"{disp}; filename=\"{filename}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        return StreamingResponse(
            stream(),
            media_type=mime_type or "application/octet-stream",
            headers=headers,
        )

    # ---------- /images ----------

    @app.get("/images", response_model=ImageListResponse)
    def list_images(
        conn: DbDep,
        min_size: Annotated[int, Query(ge=0, description="Minimum blob size in bytes.")] = 102_400,
        date_from: Annotated[Optional[str], Query()] = None,
        date_to: Annotated[Optional[str], Query()] = None,
        account: Annotated[Optional[str], Query()] = None,
        folder: Annotated[Optional[str], Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 60,
        cursor: Annotated[Optional[str], Query()] = None,
    ) -> ImageListResponse:
        # Pre-aggregation: filters over rows (account, dates, type, size).
        wheres: list[str] = ["a.mime_type LIKE 'image/%'", "a.size_bytes >= ?"]
        params: list = [min_size]
        joins: list[str] = []

        df = _normalize_date_from(date_from)
        dt = _normalize_date_to(date_to)
        if df:
            wheres.append("m.date_utc >= ?")
            params.append(df)
        if dt:
            wheres.append("m.date_utc <= ?")
            params.append(dt)
        if account or folder:
            joins.append("JOIN message_sources ms ON ms.message_id = m.id")
            if account:
                wheres.append("ms.account = ?")
                params.append(account)
            if folder:
                wheres.append("ms.folder_display = ?")
                params.append(folder)

        # SQLite: GROUP BY with bare columns returns the row associated with the MAX.
        # We wrap it in a subquery to apply the cursor over the aggregated result
        # (not over the pre-aggregation rows).
        inner_sql = f"""
            SELECT a.id AS att_id, m.id AS message_id, ma.filename, a.mime_type, a.size_bytes,
                   MAX(m.date_utc) AS latest_date, m.subject, m.from_addr, ma.inline,
                   (SELECT COUNT(*) FROM message_attachments WHERE attachment_id = a.id) AS apps
            FROM attachments a
            JOIN message_attachments ma ON ma.attachment_id = a.id
            JOIN messages m ON m.id = ma.message_id
            {" ".join(joins)}
            WHERE {" AND ".join(wheres)}
            GROUP BY a.id
        """

        cursor_clause = ""
        if cursor:
            try:
                cur_date, cur_id = decode_cursor(cursor)
            except Exception:
                raise HTTPException(400, "invalid cursor")
            cursor_clause = "WHERE (g.latest_date < ? OR (g.latest_date = ? AND g.att_id < ?))"
            params.extend([cur_date, cur_date, cur_id])
        params.append(limit + 1)

        sql = f"""
            SELECT * FROM ({inner_sql}) AS g
            {cursor_clause}
            ORDER BY g.latest_date DESC, g.att_id DESC
            LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            ImageItem(
                attachment_id=r[0],
                message_id=r[1],
                filename=r[2],
                mime_type=r[3] or "image/*",
                size_bytes=r[4] or 0,
                date_utc=r[5],
                subject=r[6] or "",
                from_addr=r[7],
                inline=bool(r[8]),
                appearances=r[9] or 1,
            )
            for r in rows
        ]
        next_cursor = (
            encode_cursor(items[-1].date_utc, items[-1].attachment_id)
            if has_more and items else None
        )
        return ImageListResponse(items=items, next_cursor=next_cursor)

    # ---------- /folders ----------

    @app.get("/folders", response_model=FoldersResponse)
    def folders(conn: DbDep) -> FoldersResponse:
        rows = conn.execute(
            """
            SELECT account, section, folder_display, COUNT(DISTINCT message_id) AS cnt
            FROM message_sources
            GROUP BY account, section, folder_display
            ORDER BY section, account, folder_display
            """
        ).fetchall()
        return FoldersResponse(
            folders=[
                FolderInfo(account=r[0], section=r[1], folder_display=r[2], message_count=r[3])
                for r in rows
            ]
        )

    # ---------- /stats ----------

    @app.get("/stats", response_model=StatsResponse)
    def stats(conn: DbDep) -> StatsResponse:
        # Simple KPIs
        total_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_sources = conn.execute("SELECT COUNT(*) FROM message_sources").fetchone()[0]
        total_att_unique = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        total_att = conn.execute("SELECT COUNT(*) FROM message_attachments").fetchone()[0]
        att_bytes = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM attachments"
        ).fetchone()[0]
        msgs_with_att = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE has_attachments = 1"
        ).fetchone()[0]
        msgs_with_html = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE has_html = 1"
        ).fetchone()[0]
        avg_size = conn.execute(
            "SELECT COALESCE(CAST(AVG(size_bytes) AS INTEGER), 0) FROM messages"
        ).fetchone()[0]

        by_year = conn.execute(
            """
            SELECT substr(date_utc, 1, 4) AS year, COUNT(*)
            FROM messages WHERE date_utc >= '1995'
            GROUP BY year ORDER BY year
            """
        ).fetchall()

        # We limit to >= 2010 to keep the list of months bounded (~15 years x 12)
        by_month = conn.execute(
            """
            SELECT substr(date_utc, 1, 7) AS month, COUNT(*)
            FROM messages WHERE date_utc >= '2010'
            GROUP BY month ORDER BY month
            """
        ).fetchall()

        # UTC hour (chars 12-13 of the ISO 'YYYY-MM-DDTHH:MM:SS+TZ').
        by_hour = conn.execute(
            """
            SELECT CAST(substr(date_utc, 12, 2) AS INTEGER) AS hour, COUNT(*)
            FROM messages
            WHERE length(date_utc) >= 13 AND date_utc >= '1995'
            GROUP BY hour ORDER BY hour
            """
        ).fetchall()

        # Day of the week: SQLite strftime('%w') is 0=Sunday … 6=Saturday.
        # We convert to ISO: 0=Monday … 6=Sunday.
        by_weekday = conn.execute(
            """
            SELECT (CAST(strftime('%w', date_utc) AS INTEGER) + 6) % 7 AS wd, COUNT(*)
            FROM messages WHERE date_utc >= '1995'
            GROUP BY wd ORDER BY wd
            """
        ).fetchall()

        by_account = conn.execute(
            """
            SELECT account, section, COUNT(DISTINCT message_id) AS cnt
            FROM message_sources
            GROUP BY account, section
            ORDER BY cnt DESC
            """
        ).fetchall()

        top_senders = conn.execute(
            """
            SELECT from_addr, COUNT(*) AS cnt
            FROM messages WHERE from_addr IS NOT NULL
            GROUP BY from_addr ORDER BY cnt DESC LIMIT 20
            """
        ).fetchall()

        top_recipients = conn.execute(
            """
            SELECT addr, COUNT(DISTINCT message_id) AS cnt
            FROM addresses WHERE kind = 'to'
            GROUP BY addr ORDER BY cnt DESC LIMIT 20
            """
        ).fetchall()

        return StatsResponse(
            total_messages=total_msgs,
            total_message_sources=total_sources,
            total_attachments=total_att,
            total_unique_attachments=total_att_unique,
            attachments_bytes_total=att_bytes or 0,
            messages_with_attachments=msgs_with_att,
            messages_with_html=msgs_with_html,
            avg_message_size=avg_size or 0,
            by_year=[YearStat(year=r[0], count=r[1]) for r in by_year],
            by_month=[MonthStat(month=r[0], count=r[1]) for r in by_month],
            by_hour=[HourStat(hour=r[0], count=r[1]) for r in by_hour],
            by_weekday=[WeekdayStat(weekday=r[0], count=r[1]) for r in by_weekday],
            by_account=[AccountStat(account=r[0], section=r[1], count=r[2]) for r in by_account],
            top_senders=[SenderStat(addr=r[0], count=r[1]) for r in top_senders],
            top_recipients=[SenderStat(addr=r[0], count=r[1]) for r in top_recipients],
        )

    return app
