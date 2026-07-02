"""Modelos Pydantic v2 para las respuestas del API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Address(BaseModel):
    name: str = ""
    addr: str


class AttachmentInfo(BaseModel):
    id: int                       # id en la tabla `attachments`
    filename: Optional[str] = None
    mime_type: str
    size_bytes: int
    inline: bool = False
    content_id: Optional[str] = None


class SourceInfo(BaseModel):
    account: str
    section: str                  # 'IMAP' | 'Local'
    folder_display: str
    source_path: str


class MessageSummary(BaseModel):
    """Item de listado, con un snippet del cuerpo para preview."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    message_id: str
    subject: str = ""
    from_: Optional[Address] = Field(default=None, alias="from")
    date_utc: str
    has_attachments: bool = False
    has_html: bool = False
    size_bytes: int = 0
    snippet: Optional[str] = None


class MessageDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    message_id: str
    synthesized_id: bool = False
    subject: str = ""
    from_: Optional[Address] = Field(default=None, alias="from")
    to: list[Address] = Field(default_factory=list)
    cc: list[Address] = Field(default_factory=list)
    bcc: list[Address] = Field(default_factory=list)
    reply_to: list[Address] = Field(default_factory=list)
    date_utc: str
    date_original: Optional[str] = None
    in_reply_to: Optional[str] = None
    references_chain: Optional[str] = None
    body_text: str = ""
    body_html: Optional[str] = None       # ya sanitizado
    size_bytes: int = 0
    has_html: bool = False
    has_attachments: bool = False
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    sources: list[SourceInfo] = Field(default_factory=list)


class MessageListResponse(BaseModel):
    items: list[MessageSummary]
    next_cursor: Optional[str] = None


class ThreadResponse(BaseModel):
    """Conversación completa: mensajes alcanzables vía In-Reply-To desde el dado."""

    root_id: int                  # id del mensaje raíz (más antiguo del hilo)
    items: list[MessageSummary]   # ordenados por fecha asc


class ImageItem(BaseModel):
    """Una imagen adjunta única (deduplicada por SHA-256) con su mensaje contexto."""

    attachment_id: int            # id en la tabla `attachments`
    message_id: int               # mensaje más reciente donde aparece (para el clic)
    filename: Optional[str] = None
    mime_type: str
    size_bytes: int
    date_utc: str                 # fecha del mensaje más reciente que la contiene
    subject: str = ""
    from_addr: Optional[str] = None
    inline: bool = False
    appearances: int = 1          # nº de mensajes donde aparece esta misma imagen


class ImageListResponse(BaseModel):
    items: list[ImageItem]
    next_cursor: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    items: list[MessageSummary]
    next_cursor: Optional[str] = None


class FolderInfo(BaseModel):
    account: str
    section: str
    folder_display: str
    message_count: int


class FoldersResponse(BaseModel):
    folders: list[FolderInfo]


class YearStat(BaseModel):
    year: str
    count: int


class MonthStat(BaseModel):
    month: str       # 'YYYY-MM'
    count: int


class HourStat(BaseModel):
    hour: int        # 0-23 UTC
    count: int


class WeekdayStat(BaseModel):
    weekday: int     # 0=lunes ... 6=domingo (ISO)
    count: int


class AccountStat(BaseModel):
    account: str
    section: str     # 'IMAP' | 'Local'
    count: int       # mensajes únicos asociados a esta cuenta


class SenderStat(BaseModel):
    addr: str
    count: int


class StatsResponse(BaseModel):
    total_messages: int
    total_message_sources: int
    total_attachments: int
    total_unique_attachments: int
    attachments_bytes_total: int
    messages_with_attachments: int
    messages_with_html: int
    avg_message_size: int
    by_year: list[YearStat]
    by_month: list[MonthStat]
    by_hour: list[HourStat]
    by_weekday: list[WeekdayStat]
    by_account: list[AccountStat]
    top_senders: list[SenderStat]
    top_recipients: list[SenderStat]


class HealthResponse(BaseModel):
    ok: bool
    schema_version: int
    encrypted: bool
    total_messages: int
