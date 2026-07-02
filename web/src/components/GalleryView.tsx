import { useCallback, useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import type { ImageItem } from "@/types";

interface Props {
  onOpenMessage: (id: number) => void;
}

const PAGE_SIZE = 60;
const SIZE_PRESETS_KB = [50, 100, 250, 500, 1024];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  if (!iso || iso.startsWith("1970-")) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("es-ES", { year: "numeric", month: "short", day: "numeric" });
}

export function GalleryView({ onOpenMessage }: Props) {
  const [minSizeKB, setMinSizeKB] = useState(100);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [items, setItems] = useState<ImageItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // (Re)fetch al cambiar filtros.
  useEffect(() => {
    let cancelled = false;
    setItems([]);
    setCursor(null);
    setHasMore(true);
    setError(null);
    setLoading(true);
    api.images({
      min_size: minSizeKB * 1024,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: PAGE_SIZE,
    })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setCursor(res.next_cursor);
        setHasMore(res.next_cursor != null);
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [minSizeKB, dateFrom, dateTo]);

  const loadMore = useCallback(() => {
    if (loading || !hasMore || !cursor) return;
    setLoading(true);
    api.images({
      min_size: minSizeKB * 1024,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: PAGE_SIZE,
      cursor,
    })
      .then((res) => {
        setItems((prev) => [...prev, ...res.items]);
        setCursor(res.next_cursor);
        setHasMore(res.next_cursor != null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [cursor, dateFrom, dateTo, hasMore, loading, minSizeKB]);

  // Trigger load-more cuando el sentinel entra en viewport.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const obs = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) loadMore();
    }, { rootMargin: "200px" });
    obs.observe(node);
    return () => obs.disconnect();
  }, [loadMore]);

  return (
    <div className="flex h-full flex-col">
      <header className="space-y-3 border-b border-border px-6 py-4">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">Galería de imágenes</h1>
          <span className="text-xs text-muted-foreground tabular-nums">
            {items.length.toLocaleString("es-ES")}{hasMore ? "+" : ""} imágenes
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted-foreground">
              Tamaño mínimo
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                step={50}
                value={minSizeKB}
                onChange={(e) => setMinSizeKB(Math.max(0, Number(e.target.value) || 0))}
                className="h-8 w-20 rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
              />
              <span className="text-xs text-muted-foreground">KB</span>
              <div className="flex gap-1">
                {SIZE_PRESETS_KB.map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setMinSizeKB(k)}
                    className={cn(
                      "rounded border border-border px-1.5 py-0.5 text-[10px]",
                      minSizeKB === k ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50",
                    )}
                  >
                    {k < 1024 ? `${k} KB` : `${k / 1024} MB`}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted-foreground">
              Desde
            </label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="h-8 rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted-foreground">
              Hasta
            </label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="h-8 rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
            />
          </div>

          {(dateFrom || dateTo || minSizeKB !== 100) && (
            <button
              type="button"
              onClick={() => { setDateFrom(""); setDateTo(""); setMinSizeKB(100); }}
              className="h-8 self-end rounded border border-border px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Reset
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="p-6 text-destructive">{error}</div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
        {items.length === 0 && !loading && !error && (
          <div className="flex h-32 items-center justify-center gap-2 text-muted-foreground">
            <ImageOff className="h-4 w-4" />
            <span className="text-sm">Sin imágenes con esos filtros.</span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
          {items.map((img) => (
            <ImageCard key={img.attachment_id} img={img} onOpen={() => onOpenMessage(img.message_id)} />
          ))}
        </div>

        <div ref={sentinelRef} className="flex h-16 items-center justify-center">
          {loading && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              cargando…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ImageCard({ img, onOpen }: { img: ImageItem; onOpen: () => void }) {
  const [failed, setFailed] = useState(false);
  const url = api.attachmentUrl(img.message_id, img.attachment_id);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative flex flex-col gap-1.5 overflow-hidden rounded-lg border border-border bg-card text-left hover:border-ring focus:outline-none focus:ring-2 focus:ring-ring"
      title={img.filename || "(sin nombre)"}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-muted/40">
        {failed ? (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <ImageOff className="h-5 w-5" />
          </div>
        ) : (
          <img
            src={url}
            alt={img.filename || ""}
            loading="lazy"
            onError={() => setFailed(true)}
            className="h-full w-full object-cover transition-transform group-hover:scale-[1.02]"
          />
        )}
        {img.appearances > 1 && (
          <span
            className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur"
            title={`Aparece en ${img.appearances} mensajes`}
          >
            ×{img.appearances}
          </span>
        )}
      </div>
      <div className="space-y-0.5 px-2 pb-2">
        <div className="truncate text-xs font-medium">
          {img.filename || <span className="italic text-muted-foreground">(sin nombre)</span>}
        </div>
        <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
          <span className="truncate">{img.from_addr || "?"}</span>
          <span className="shrink-0 tabular-nums">{fmtBytes(img.size_bytes)}</span>
        </div>
        <div className="text-[10px] text-muted-foreground">{fmtDate(img.date_utc)}</div>
      </div>
    </button>
  );
}
