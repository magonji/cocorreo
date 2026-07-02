import { useMemo, useState } from "react";
import { Eye, EyeOff, AlertTriangle } from "lucide-react";
import { prepareHtml } from "@/lib/htmlPrepare";
import type { MessageDetail } from "@/types";

interface Props {
  message: MessageDetail;
  html: string;
}

export function MessageHtml({ message, html }: Props) {
  const [loadRemote, setLoadRemote] = useState(false);

  const prepared = useMemo(
    () => prepareHtml(html, message, loadRemote),
    [html, message, loadRemote],
  );

  return (
    <div className="flex h-full flex-col">
      {(prepared.remoteImageCount > 0 || prepared.missingCidCount > 0) && (
        <div className="flex items-center gap-3 border-b border-border bg-secondary/40 px-4 py-2 text-xs text-muted-foreground">
          {prepared.remoteImageCount > 0 && (
            <button
              type="button"
              onClick={() => setLoadRemote((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 hover:bg-accent"
            >
              {loadRemote ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              {loadRemote
                ? `Ocultar imágenes remotas (${prepared.remoteImageCount})`
                : `Cargar ${prepared.remoteImageCount} imágen${prepared.remoteImageCount !== 1 ? "es" : ""} remota${prepared.remoteImageCount !== 1 ? "s" : ""}`}
            </button>
          )}
          {prepared.missingCidCount > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <AlertTriangle className="h-3 w-3 text-yellow-500" />
              {prepared.missingCidCount} referencias inline rotas
            </span>
          )}
        </div>
      )}
      <iframe
        title={`Mensaje #${message.id} (HTML)`}
        srcDoc={prepared.html}
        sandbox="allow-popups allow-popups-to-escape-sandbox"
        className="flex-1 w-full border-0 bg-white"
      />
    </div>
  );
}
