import type { MessageDetail } from "@/types";

/**
 * Resultado del pre-procesado de HTML para renderizar de forma segura
 * en un iframe sandbox.
 *
 * Transformaciones aplicadas:
 *  - `cid:X` en `<img src>` → URL del adjunto inline correspondiente.
 *  - `<img>` con src remoto se neutraliza cuando `loadRemoteImages` es false;
 *    el `src` original se preserva en `data-cocorreo-blocked` para reactivarlo.
 *  - Todos los `<a>` reciben `target="_blank" rel="noopener noreferrer"` para
 *    que el iframe sandboxed pueda abrirlos.
 *  - Se inyecta una hoja de estilos base de lectura.
 */
export interface PreparedHtml {
  html: string;
  remoteImageCount: number;
  missingCidCount: number;
}

const BASE_STYLE = `
  html, body { margin: 0; padding: 0; }
  body {
    font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #1a1a1a;
    background: #ffffff;
    padding: 1rem 1.25rem;
    word-wrap: break-word;
  }
  img { max-width: 100%; height: auto; }
  table { max-width: 100%; border-collapse: collapse; }
  pre, code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, Menlo, monospace; }
  pre { padding: 12px; overflow-x: auto; }
  blockquote { border-left: 3px solid #d1d5db; margin: 0.75rem 0; padding: 0.25rem 0.75rem; color: #4b5563; }
  a { color: #2563eb; }
  a:hover { text-decoration: underline; }
  .cocorreo-blocked-image {
    display: inline-block;
    border: 1px dashed #d1d5db;
    padding: 4px 8px;
    color: #6b7280;
    font-size: 12px;
    background: #f9fafb;
  }
`;

export function prepareHtml(
  html: string,
  message: MessageDetail,
  loadRemoteImages: boolean,
): PreparedHtml {
  const doc = new DOMParser().parseFromString(html, "text/html");

  // Mapa content_id → attachment_id para resolver `cid:`.
  const cidMap = new Map<string, number>();
  for (const a of message.attachments) {
    if (a.content_id) cidMap.set(a.content_id, a.id);
  }

  let remoteImageCount = 0;
  let missingCidCount = 0;

  doc.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") || "";
    if (src.toLowerCase().startsWith("cid:")) {
      const cid = src.slice(4).trim().replace(/^<|>$/g, "");
      const attId = cidMap.get(cid);
      if (attId != null) {
        img.setAttribute("src", `/api/messages/${message.id}/attachments/${attId}`);
      } else {
        missingCidCount++;
        img.removeAttribute("src");
        if (!img.getAttribute("alt")) {
          img.setAttribute("alt", `(imagen inline no resuelta: ${cid})`);
        }
        img.classList.add("cocorreo-blocked-image");
      }
    } else if (/^https?:\/\//i.test(src)) {
      remoteImageCount++;
      if (!loadRemoteImages) {
        img.setAttribute("data-cocorreo-blocked", src);
        img.removeAttribute("src");
        if (!img.getAttribute("alt")) {
          img.setAttribute("alt", "(imagen remota bloqueada)");
        }
        img.classList.add("cocorreo-blocked-image");
      }
    }
  });

  // Enlaces salen en nueva pestaña (necesario en iframe sandbox).
  doc.querySelectorAll("a[href]").forEach((a) => {
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener noreferrer");
  });

  // Inyectar nuestros estilos base sin pisar los del email.
  let head = doc.querySelector("head");
  if (!head) {
    head = doc.createElement("head");
    doc.documentElement.insertBefore(head, doc.documentElement.firstChild);
  }
  const style = doc.createElement("style");
  style.textContent = BASE_STYLE;
  head.insertBefore(style, head.firstChild);

  return {
    html: `<!doctype html>\n${doc.documentElement.outerHTML}`,
    remoteImageCount,
    missingCidCount,
  };
}
