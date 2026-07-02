import { useEffect, useState } from "react";
import { Paperclip, Folder, Calendar, User, FileText, Code2, MessagesSquare, Download } from "lucide-react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import { MessageHtml } from "@/components/MessageHtml";
import type { MessageDetail as MessageDetailType, Address, MessageSummary } from "@/types";

type ViewMode = "html" | "text";

function fmtAddr(a: Address): string {
  if (a.name) return `${a.name} <${a.addr}>`;
  return a.addr;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function fmtDate(iso: string): string {
  if (!iso || iso.startsWith("1970-")) return "fecha desconocida";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-ES", {
    year: "numeric", month: "long", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

interface Props {
  messageId: number;
  onSelectMessage: (id: number) => void;
}

export function MessageDetail({ messageId, onSelectMessage }: Props) {
  const [msg, setMsg] = useState<MessageDetailType | null>(null);
  const [thread, setThread] = useState<MessageSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<ViewMode>("html");

  useEffect(() => {
    let cancelled = false;
    setMsg(null);
    setThread([]);
    setError(null);
    setLoading(true);
    api.message(messageId)
      .then((d) => {
        if (cancelled) return;
        setMsg(d);
        setView(d.has_html ? "html" : "text");
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    // El hilo se carga aparte y de forma independiente para no bloquear el render
    // del mensaje principal si la query del hilo tarda más.
    api.thread(messageId)
      .then((t) => { if (!cancelled) setThread(t.items); })
      .catch(() => { /* hilo es opcional; ignoramos errores */ });
    return () => { cancelled = true; };
  }, [messageId]);

  if (loading) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">cargando…</div>;
  }
  if (error) {
    return <div className="p-6 text-destructive">{error}</div>;
  }
  if (!msg) return null;

  const visibleAttachments = msg.attachments.filter((a) => !a.inline);
  const effectiveView: ViewMode = view === "html" && msg.body_html ? "html" : "text";

  return (
    <div className="flex h-full flex-col">
      <header className="space-y-2 border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold leading-snug">
          {msg.subject || <span className="italic text-muted-foreground">(sin asunto)</span>}
        </h1>
        <div className="space-y-0.5 text-xs text-muted-foreground">
          {msg.from && (
            <div className="flex items-center gap-2">
              <User className="h-3 w-3" />
              <span className="text-foreground">{fmtAddr(msg.from)}</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Calendar className="h-3 w-3" />
            <span>{fmtDate(msg.date_utc)}</span>
            {msg.synthesized_id && (
              <span className="ml-2 rounded bg-secondary px-1.5 py-0.5 text-[10px]">
                ID sintético
              </span>
            )}
          </div>
          {msg.to.length > 0 && (
            <div><span className="uppercase tracking-wide">para:</span> {msg.to.map(fmtAddr).join(", ")}</div>
          )}
          {msg.cc.length > 0 && (
            <div><span className="uppercase tracking-wide">cc:</span> {msg.cc.map(fmtAddr).join(", ")}</div>
          )}
          {msg.bcc.length > 0 && (
            <div><span className="uppercase tracking-wide">bcc:</span> {msg.bcc.map(fmtAddr).join(", ")}</div>
          )}
        </div>

        {visibleAttachments.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {visibleAttachments.map((a) => (
              <a
                key={a.id}
                href={api.attachmentUrl(msg.id, a.id)}
                download={a.filename || undefined}
                className="inline-flex items-center gap-1.5 rounded border border-border bg-secondary px-2 py-1 text-xs hover:bg-accent"
              >
                <Paperclip className="h-3 w-3" />
                <span className="max-w-xs truncate">{a.filename || "(sin nombre)"}</span>
                <span className="text-muted-foreground">· {fmtBytes(a.size_bytes)}</span>
              </a>
            ))}
          </div>
        )}

        {msg.sources.length > 0 && (
          <details className="pt-2">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              <Folder className="mr-1 inline h-3 w-3" />
              aparece en {msg.sources.length} ubicación{msg.sources.length !== 1 && "es"}
            </summary>
            <ul className="ml-5 mt-1 list-disc space-y-0.5 text-xs text-muted-foreground">
              {msg.sources.map((s, i) => (
                <li key={i}>
                  <span className="font-mono">{s.account}</span> / {s.folder_display}
                </li>
              ))}
            </ul>
          </details>
        )}

        {thread.length > 1 && (
          <details className="pt-2" open={thread.length <= 8}>
            <summary className="cursor-pointer text-xs text-muted-foreground">
              <MessagesSquare className="mr-1 inline h-3 w-3" />
              hilo de {thread.length} mensajes
            </summary>
            <ul className="ml-1 mt-1.5 space-y-0.5">
              {thread.map((t) => {
                const isCurrent = t.id === msg.id;
                const who = t.from?.name || t.from?.addr || "(sin remitente)";
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => !isCurrent && onSelectMessage(t.id)}
                      disabled={isCurrent}
                      className={cn(
                        "flex w-full items-baseline gap-2 rounded px-1.5 py-0.5 text-left text-xs",
                        isCurrent
                          ? "bg-accent text-accent-foreground"
                          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground cursor-pointer",
                      )}
                    >
                      <span className="w-24 shrink-0 tabular-nums">
                        {t.date_utc?.startsWith("1970-") ? "—" : t.date_utc?.slice(0, 10)}
                      </span>
                      <span className="w-40 shrink-0 truncate" title={who}>{who}</span>
                      <span className="flex-1 truncate">
                        {t.subject || <span className="italic">(sin asunto)</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </details>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          {/* Toggle vista solo si hay ambos formatos. */}
          {msg.body_html && msg.body_text && (
            <div className="inline-flex items-center gap-0 rounded border border-border">
              <button
                type="button"
                onClick={() => setView("html")}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 text-xs",
                  effectiveView === "html" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50",
                )}
              >
                <Code2 className="h-3 w-3" /> HTML
              </button>
              <button
                type="button"
                onClick={() => setView("text")}
                className={cn(
                  "inline-flex items-center gap-1.5 border-l border-border px-2.5 py-1 text-xs",
                  effectiveView === "text" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50",
                )}
              >
                <FileText className="h-3 w-3" /> Texto
              </button>
            </div>
          )}
          <a
            href={api.exportEmlUrl(msg.id)}
            download
            className="inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            title="Descargar el mensaje reconstruido en formato .eml (RFC 5322) con adjuntos descifrados"
          >
            <Download className="h-3 w-3" /> .eml
          </a>
        </div>
      </header>

      {effectiveView === "html" && msg.body_html ? (
        <MessageHtml message={msg} html={msg.body_html} />
      ) : (
        <div className="flex-1 overflow-y-auto scrollbar-thin">
          <pre className="m-0 whitespace-pre-wrap break-words p-6 font-sans text-sm leading-relaxed">
            {msg.body_text || (
              <span className="italic text-muted-foreground">(sin cuerpo)</span>
            )}
          </pre>
        </div>
      )}
    </div>
  );
}
