import type {
  FoldersResponse,
  HealthResponse,
  ImageFilters,
  ImageListResponse,
  MessageDetail,
  MessageListFilters,
  MessageListResponse,
  StatsResponse,
  ThreadResponse,
} from "@/types";

const BASE = "/api";

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.append(k, String(v));
    }
  }
  const url = `${BASE}${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(`${res.status} ${detail}`, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => get<HealthResponse>("/health"),
  folders: () => get<FoldersResponse>("/folders"),
  listMessages: (filters: MessageListFilters & { limit?: number; cursor?: string } = {}) =>
    get<MessageListResponse>("/messages", filters as Record<string, string | number | boolean | undefined>),
  search: (
    q: string,
    opts: MessageListFilters & { limit?: number; cursor?: string } = {},
  ) =>
    get<MessageListResponse & { query: string }>("/search", { q, ...opts } as Record<string, string | number | boolean | undefined>),
  message: (id: number) => get<MessageDetail>(`/messages/${id}`),
  thread: (id: number) => get<ThreadResponse>(`/messages/${id}/thread`),
  stats: () => get<StatsResponse>("/stats"),
  images: (filters: ImageFilters & { limit?: number; cursor?: string } = {}) =>
    get<ImageListResponse>("/images", filters as Record<string, string | number | boolean | undefined>),
  attachmentUrl: (messageId: number, attachmentId: number) =>
    `${BASE}/messages/${messageId}/attachments/${attachmentId}`,
  exportEmlUrl: (messageId: number) =>
    `${BASE}/messages/${messageId}/export.eml`,
};
