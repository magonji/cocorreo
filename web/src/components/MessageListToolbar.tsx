import { Search, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { MessageListFilters } from "@/types";

interface Props {
  title: string;
  count: number;
  hasMore: boolean;
  query: string;
  onQueryChange: (q: string) => void;
  filters: MessageListFilters;
  onFiltersChange: (f: MessageListFilters) => void;
}

function activeFilterCount(f: MessageListFilters): number {
  let n = 0;
  if (f.from) n++;
  if (f.date_from) n++;
  if (f.date_to) n++;
  if (f.has_attachment !== undefined) n++;
  return n;
}

export function MessageListToolbar({
  title,
  count,
  hasMore,
  query,
  onQueryChange,
  filters,
  onFiltersChange,
}: Props) {
  const active = activeFilterCount(filters);
  const [open, setOpen] = useState(active > 0);

  return (
    <div className="border-b border-border">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Buscar — texto, from:, after:, has:attachment, subject:, …"
            className={cn(
              "h-8 w-full rounded border border-border bg-secondary/30 pl-8 pr-7 text-xs",
              "outline-none placeholder:text-muted-foreground/70",
              "focus:border-ring focus:bg-secondary/60",
            )}
          />
          {query && (
            <button
              type="button"
              onClick={() => onQueryChange("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-accent"
              title="Limpiar búsqueda"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded border border-border px-2 text-xs",
            (open || active > 0) && "bg-accent",
          )}
          title="Filtros"
        >
          <SlidersHorizontal className="h-3 w-3" />
          {active > 0 && <span className="rounded bg-primary/80 px-1 text-[10px] text-primary-foreground">{active}</span>}
        </button>
      </div>

      {open && (
        <div className="space-y-2 border-t border-border bg-background/60 px-4 py-2.5">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                Desde
              </label>
              <input
                type="date"
                value={filters.date_from ?? ""}
                onChange={(e) => onFiltersChange({ ...filters, date_from: e.target.value || undefined })}
                className="h-7 w-full rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
              />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                Hasta
              </label>
              <input
                type="date"
                value={filters.date_to ?? ""}
                onChange={(e) => onFiltersChange({ ...filters, date_to: e.target.value || undefined })}
                className="h-7 w-full rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
              />
            </div>
          </div>
          <div>
            <label className="mb-0.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
              Remitente exacto
            </label>
            <input
              type="email"
              value={filters.from ?? ""}
              placeholder="ejemplo@dominio.com"
              onChange={(e) => onFiltersChange({ ...filters, from: e.target.value || undefined })}
              className="h-7 w-full rounded border border-border bg-secondary/30 px-2 text-xs outline-none focus:border-ring"
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <label className="inline-flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={filters.has_attachment === true}
                onChange={(e) => onFiltersChange({
                  ...filters,
                  has_attachment: e.target.checked ? true : undefined,
                })}
                className="h-3.5 w-3.5 accent-primary"
              />
              <span>Solo con adjuntos</span>
            </label>
            {active > 0 && (
              <button
                type="button"
                onClick={() => onFiltersChange({})}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Limpiar filtros
              </button>
            )}
          </div>

          <details className="pt-1">
            <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-muted-foreground">
              Sintaxis del buscador
            </summary>
            <div className="mt-1.5 space-y-1 text-xs text-muted-foreground">
              <div><code className="rounded bg-secondary/60 px-1">from:foo@x.com</code> filtra remitente exacto</div>
              <div><code className="rounded bg-secondary/60 px-1">after:2020-01-01</code> · <code className="rounded bg-secondary/60 px-1">before:2023-12-31</code></div>
              <div><code className="rounded bg-secondary/60 px-1">has:attachment</code> · <code className="rounded bg-secondary/60 px-1">account:imap.gmail-3.com</code></div>
              <div><code className="rounded bg-secondary/60 px-1">subject:reunión</code> · <code className="rounded bg-secondary/60 px-1">body:contrato</code> · <code className="rounded bg-secondary/60 px-1">to:klaas</code></div>
              <div><code className="rounded bg-secondary/60 px-1">"frase exacta"</code> · combina todos: <code className="rounded bg-secondary/60 px-1">from:klaas after:2020 has:attachment ftir</code></div>
            </div>
          </details>
        </div>
      )}

      <div className="flex items-center justify-between border-t border-border px-4 py-1.5">
        <h2 className="truncate text-sm font-medium">{title}</h2>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {count.toLocaleString("es-ES")}{hasMore ? "+" : ""}
        </span>
      </div>
    </div>
  );
}
