import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Paperclip } from "lucide-react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { parseQuery, mergeFilters } from "@/lib/parseQuery";
import { MessageListToolbar } from "@/components/MessageListToolbar";
import type { FolderSelection } from "@/components/FolderList";
import type { MessageListFilters, MessageSummary } from "@/types";

interface Props {
  folder: FolderSelection | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const PAGE_SIZE = 100;
const ROW_HEIGHT = 76;

function formatDate(iso: string): string {
  if (!iso || iso.startsWith("1970-")) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString("es-ES", sameYear
    ? { month: "short", day: "numeric" }
    : { year: "numeric", month: "short", day: "numeric" });
}

export function MessageList({ folder, selectedId, onSelect }: Props) {
  const [items, setItems] = useState<MessageSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<MessageListFilters>({});
  const debouncedQuery = useDebouncedValue(query.trim(), 300);

  // Parsea la sintaxis user-friendly (`from:`, `after:`, `has:attachment`,
  // alias `to:`/`cc:`/`bcc:` → FTS5 addresses_text, etc.) y separa la parte
  // FTS5 pura de los filtros estructurados.
  const parsed = useMemo(() => parseQuery(debouncedQuery), [debouncedQuery]);
  const effectiveFilters = useMemo(
    () => mergeFilters(filters, parsed.filters),
    [filters, parsed.filters],
  );

  const parentRef = useRef<HTMLDivElement>(null);

  // Al cambiar de folder, reseteamos también query+filtros — nuevo scope, nuevo contexto.
  useEffect(() => {
    setQuery("");
    setFilters({});
  }, [folder?.account, folder?.folder]);

  // Cargar primera página al cambiar cualquier parámetro relevante.
  useEffect(() => {
    let cancelled = false;
    setItems([]);
    setCursor(null);
    setHasMore(true);
    setError(null);
    setLoading(true);

    const params = {
      account: effectiveFilters.account ?? folder?.account,
      folder: folder?.folder,
      from: effectiveFilters.from,
      date_from: effectiveFilters.date_from,
      date_to: effectiveFilters.date_to,
      has_attachment: effectiveFilters.has_attachment,
      limit: PAGE_SIZE,
    };
    const fetcher = parsed.fts
      ? api.search(parsed.fts, params)
      : api.listMessages(params);

    fetcher
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setCursor(res.next_cursor);
        setHasMore(res.next_cursor != null);
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [
    folder?.account, folder?.folder,
    parsed.fts,
    effectiveFilters.account, effectiveFilters.from,
    effectiveFilters.date_from, effectiveFilters.date_to,
    effectiveFilters.has_attachment,
  ]);

  const loadMore = useCallback(() => {
    if (loading || !hasMore || !cursor) return;
    setLoading(true);
    const params = {
      account: effectiveFilters.account ?? folder?.account,
      folder: folder?.folder,
      from: effectiveFilters.from,
      date_from: effectiveFilters.date_from,
      date_to: effectiveFilters.date_to,
      has_attachment: effectiveFilters.has_attachment,
      limit: PAGE_SIZE,
      cursor,
    };
    const fetcher = parsed.fts
      ? api.search(parsed.fts, params)
      : api.listMessages(params);

    fetcher
      .then((res) => {
        setItems((prev) => [...prev, ...res.items]);
        setCursor(res.next_cursor);
        setHasMore(res.next_cursor != null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [
    cursor, folder?.account, folder?.folder, hasMore, loading,
    parsed.fts,
    effectiveFilters.account, effectiveFilters.from,
    effectiveFilters.date_from, effectiveFilters.date_to,
    effectiveFilters.has_attachment,
  ]);

  const virtualizer = useVirtualizer({
    count: items.length + (hasMore ? 1 : 0),
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  const virtualItems = virtualizer.getVirtualItems();

  useEffect(() => {
    const last = virtualItems[virtualItems.length - 1];
    if (!last) return;
    if (last.index >= items.length - 5 && hasMore && !loading) {
      loadMore();
    }
  }, [virtualItems, items.length, hasMore, loading, loadMore]);

  const title = debouncedQuery
    ? `Resultados para "${debouncedQuery}"`
    : (folder?.label ?? "Todos los mensajes");

  return (
    <>
      <MessageListToolbar
        title={title}
        count={items.length}
        hasMore={hasMore}
        query={query}
        onQueryChange={setQuery}
        filters={filters}
        onFiltersChange={setFilters}
      />
      {error ? (
        <p className="p-4 text-xs text-destructive">{error}</p>
      ) : (
        <div ref={parentRef} className="flex-1 overflow-y-auto scrollbar-thin">
          {items.length === 0 && !loading && (
            <p className="p-6 text-center text-xs text-muted-foreground">
              {debouncedQuery || Object.values(filters).some((v) => v !== undefined)
                ? "Sin resultados."
                : "Sin mensajes en esta vista."}
            </p>
          )}
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualItems.map((vi) => {
              const m = items[vi.index];
              const isLoader = !m;
              return (
                <div
                  key={vi.key}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    transform: `translateY(${vi.start}px)`,
                    height: vi.size,
                  }}
                >
                  {isLoader ? (
                    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                      {loading ? "cargando más…" : ""}
                    </div>
                  ) : (
                    <MessageRow message={m} selected={m.id === selectedId} onSelect={onSelect} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}

function MessageRow({
  message: m,
  selected,
  onSelect,
}: { message: MessageSummary; selected: boolean; onSelect: (id: number) => void }) {
  const fromLabel = m.from
    ? (m.from.name || m.from.addr)
    : "(sin remitente)";
  return (
    <button
      type="button"
      onClick={() => onSelect(m.id)}
      className={cn(
        "flex h-full w-full flex-col gap-1 border-b border-border px-4 py-2 text-left hover:bg-accent",
        selected && "bg-accent text-accent-foreground",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="flex-1 truncate text-sm font-medium" title={fromLabel}>{fromLabel}</span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatDate(m.date_utc)}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="flex-1 truncate text-xs" title={m.subject}>
          {m.subject || <span className="italic text-muted-foreground">(sin asunto)</span>}
        </span>
        {m.has_attachments && <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />}
      </div>
      {m.snippet && (
        <div className="line-clamp-1 text-xs text-muted-foreground">{m.snippet}</div>
      )}
    </button>
  );
}
