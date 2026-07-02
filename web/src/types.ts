// Tipos espejo de los modelos Pydantic del backend.

export interface Address {
  name: string;
  addr: string;
}

export interface AttachmentInfo {
  id: number;
  filename: string | null;
  mime_type: string;
  size_bytes: number;
  inline: boolean;
  content_id: string | null;
}

export interface SourceInfo {
  account: string;
  section: "IMAP" | "Local";
  folder_display: string;
  source_path: string;
}

export interface MessageSummary {
  id: number;
  message_id: string;
  subject: string;
  from: Address | null;
  date_utc: string;
  has_attachments: boolean;
  has_html: boolean;
  size_bytes: number;
  snippet: string | null;
}

export interface MessageDetail {
  id: number;
  message_id: string;
  synthesized_id: boolean;
  subject: string;
  from: Address | null;
  to: Address[];
  cc: Address[];
  bcc: Address[];
  reply_to: Address[];
  date_utc: string;
  date_original: string | null;
  in_reply_to: string | null;
  references_chain: string | null;
  body_text: string;
  body_html: string | null;
  size_bytes: number;
  has_html: boolean;
  has_attachments: boolean;
  attachments: AttachmentInfo[];
  sources: SourceInfo[];
}

export interface MessageListResponse {
  items: MessageSummary[];
  next_cursor: string | null;
}

export interface ThreadResponse {
  root_id: number;
  items: MessageSummary[];
}

export interface ImageItem {
  attachment_id: number;
  message_id: number;
  filename: string | null;
  mime_type: string;
  size_bytes: number;
  date_utc: string;
  subject: string;
  from_addr: string | null;
  inline: boolean;
  appearances: number;
}

export interface ImageListResponse {
  items: ImageItem[];
  next_cursor: string | null;
}

export interface ImageFilters {
  min_size?: number;       // bytes
  date_from?: string;
  date_to?: string;
}

export interface FolderInfo {
  account: string;
  section: "IMAP" | "Local";
  folder_display: string;
  message_count: number;
}

export interface FoldersResponse {
  folders: FolderInfo[];
}

export interface HealthResponse {
  ok: boolean;
  schema_version: number;
  encrypted: boolean;
  total_messages: number;
}

export interface YearStat { year: string; count: number; }
export interface MonthStat { month: string; count: number; }
export interface HourStat { hour: number; count: number; }
export interface WeekdayStat { weekday: number; count: number; }
export interface AccountStat { account: string; section: "IMAP" | "Local"; count: number; }
export interface SenderStat { addr: string; count: number; }

export interface StatsResponse {
  total_messages: number;
  total_message_sources: number;
  total_attachments: number;
  total_unique_attachments: number;
  attachments_bytes_total: number;
  messages_with_attachments: number;
  messages_with_html: number;
  avg_message_size: number;
  by_year: YearStat[];
  by_month: MonthStat[];
  by_hour: HourStat[];
  by_weekday: WeekdayStat[];
  by_account: AccountStat[];
  top_senders: SenderStat[];
  top_recipients: SenderStat[];
}

export interface MessageListFilters {
  account?: string;
  folder?: string;
  from?: string;
  date_from?: string;
  date_to?: string;
  has_attachment?: boolean;
}
