import type { MessageListFilters } from "@/types";

export interface ParsedQuery {
  /** Parte de la consulta lista para enviar al endpoint `/search?q=…`. */
  fts: string;
  /** Filtros estructurados extraídos del input. Sobrescriben a los del panel. */
  filters: MessageListFilters;
}

// Operadores que mapean al panel de filtros estructurados del backend.
const FILTER_OPS = new Set(["from", "after", "before", "account"]);

// Aliases user-friendly → columnas FTS5 reales. Pasamos `to:X` como
// `addresses_text:X` porque no tenemos una columna FTS5 separada por destinatario.
const FTS_COLUMN_ALIASES: Record<string, string> = {
  to: "addresses_text",
  cc: "addresses_text",
  bcc: "addresses_text",
};

function tokenize(input: string): string[] {
  const tokens: string[] = [];
  // Soporta `op:"frase entre comillas"`, `"frase"` suelta y tokens sin espacios.
  const re = /[a-z_]+:"[^"]*"|"[^"]*"|\S+/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(input)) !== null) tokens.push(m[0]);
  return tokens;
}

export function parseQuery(input: string): ParsedQuery {
  const filters: MessageListFilters = {};
  const ftsTokens: string[] = [];

  for (const raw of tokenize(input.trim())) {
    // Caso especial: `has:attachment` no es operador-con-valor estándar.
    if (raw.toLowerCase() === "has:attachment") {
      filters.has_attachment = true;
      continue;
    }

    const m = raw.match(/^([a-z_]+):(.*)$/i);
    if (m) {
      const op = m[1].toLowerCase();
      let value = m[2];
      const wasQuoted = value.startsWith('"') && value.endsWith('"') && value.length >= 2;
      if (wasQuoted) value = value.slice(1, -1);

      if (FILTER_OPS.has(op)) {
        if (!value) continue;
        if (op === "from") filters.from = value;
        else if (op === "after") filters.date_from = value;
        else if (op === "before") filters.date_to = value;
        else if (op === "account") filters.account = value;
        continue;
      }

      if (op in FTS_COLUMN_ALIASES) {
        if (!value) continue;
        const target = FTS_COLUMN_ALIASES[op];
        const needsQuotes = wasQuoted || /\s/.test(value);
        ftsTokens.push(needsQuotes ? `${target}:"${value}"` : `${target}:${value}`);
        continue;
      }
    }

    // Token desconocido → pasa tal cual al motor FTS5 (preserva la sintaxis
    // avanzada del usuario: `subject:foo*`, `body NEAR/5 algo`, etc.).
    ftsTokens.push(raw);
  }

  return { fts: ftsTokens.join(" "), filters };
}

export function mergeFilters(panel: MessageListFilters, parsed: MessageListFilters): MessageListFilters {
  // Los filtros del query (parsed) ganan al panel, pero solo en las keys
  // explícitamente definidas — no pisamos por accidente con `undefined`.
  const out: MessageListFilters = { ...panel };
  for (const [k, v] of Object.entries(parsed)) {
    if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}
