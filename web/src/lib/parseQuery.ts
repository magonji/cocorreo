import type { MessageListFilters } from "@/types";

export interface ParsedQuery {
  /** Part of the query ready to send to the `/search?q=…` endpoint. */
  fts: string;
  /** Structured filters extracted from the input. Override the panel's own. */
  filters: MessageListFilters;
}

// Operators that map to the backend's structured filter panel.
const FILTER_OPS = new Set(["from", "after", "before", "account"]);

// User-friendly aliases → actual FTS5 columns. We pass `to:X` as
// `addresses_text:X` because we don't have a separate FTS5 column per recipient.
const FTS_COLUMN_ALIASES: Record<string, string> = {
  to: "addresses_text",
  cc: "addresses_text",
  bcc: "addresses_text",
};

function tokenize(input: string): string[] {
  const tokens: string[] = [];
  // Supports `op:"quoted phrase"`, a standalone `"phrase"` and tokens without spaces.
  const re = /[a-z_]+:"[^"]*"|"[^"]*"|\S+/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(input)) !== null) tokens.push(m[0]);
  return tokens;
}

export function parseQuery(input: string): ParsedQuery {
  const filters: MessageListFilters = {};
  const ftsTokens: string[] = [];

  for (const raw of tokenize(input.trim())) {
    // Special case: `has:attachment` isn't a standard operator-with-value.
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

    // Unknown token → passed through as-is to the FTS5 engine (preserves the
    // user's advanced syntax: `subject:foo*`, `body NEAR/5 something`, etc.).
    ftsTokens.push(raw);
  }

  return { fts: ftsTokens.join(" "), filters };
}

export function mergeFilters(panel: MessageListFilters, parsed: MessageListFilters): MessageListFilters {
  // Filters from the query (parsed) win over the panel, but only for keys
  // explicitly defined — we don't accidentally overwrite with `undefined`.
  const out: MessageListFilters = { ...panel };
  for (const [k, v] of Object.entries(parsed)) {
    if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}
