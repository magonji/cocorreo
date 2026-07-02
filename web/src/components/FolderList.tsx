import { useEffect, useState } from "react";
import { Inbox, Cloud, HardDrive } from "lucide-react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import type { FolderInfo } from "@/types";

export interface FolderSelection {
  account?: string;
  folder?: string;
  label: string;
}

interface Props {
  selected: FolderSelection | null;
  onSelect: (f: FolderSelection | null) => void;
}

interface GroupedAccount {
  section: "IMAP" | "Local";
  account: string;
  folders: FolderInfo[];
  total: number;
}

function groupByAccount(folders: FolderInfo[]): GroupedAccount[] {
  const map = new Map<string, GroupedAccount>();
  for (const f of folders) {
    const key = `${f.section}|${f.account}`;
    let g = map.get(key);
    if (!g) {
      g = { section: f.section, account: f.account, folders: [], total: 0 };
      map.set(key, g);
    }
    g.folders.push(f);
    g.total += f.message_count;
  }
  // Sort folders inside each account by count desc.
  for (const g of map.values()) g.folders.sort((a, b) => b.message_count - a.message_count);
  // Sort accounts by total desc.
  return [...map.values()].sort((a, b) => b.total - a.total);
}

export function FolderList({ selected, onSelect }: Props) {
  const [groups, setGroups] = useState<GroupedAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.folders()
      .then((r) => setGroups(groupByAccount(r.folders)))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="p-4 text-xs text-destructive">{error}</p>;
  if (!groups) return <p className="p-4 text-xs text-muted-foreground">cargando…</p>;

  return (
    <nav className="py-2">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent",
          selected === null && "bg-accent",
        )}
      >
        <Inbox className="h-4 w-4 text-muted-foreground" />
        <span className="flex-1">Todos los mensajes</span>
      </button>

      <div className="my-2 border-t border-border" />

      {groups.map((g) => (
        <div key={`${g.section}|${g.account}`} className="mb-3">
          <div className="flex items-center gap-2 px-3 py-1 text-xs uppercase tracking-wider text-muted-foreground">
            {g.section === "IMAP" ? <Cloud className="h-3 w-3" /> : <HardDrive className="h-3 w-3" />}
            <span className="flex-1 truncate" title={g.account}>{g.account}</span>
            <span>{g.total.toLocaleString("es-ES")}</span>
          </div>
          {g.folders.map((f) => {
            const isSelected = selected?.folder === f.folder_display;
            // Mostrar el último segmento de la carpeta como nombre legible.
            const shortName = f.folder_display.split("/").slice(-1)[0] || f.folder_display;
            return (
              <button
                key={f.folder_display}
                type="button"
                onClick={() => onSelect({
                  account: f.account,
                  folder: f.folder_display,
                  label: `${f.account} / ${shortName}`,
                })}
                title={f.folder_display}
                className={cn(
                  "flex w-full items-center gap-2 px-6 py-1 text-left text-xs hover:bg-accent",
                  isSelected && "bg-accent text-accent-foreground",
                )}
              >
                <span className="flex-1 truncate">{shortName}</span>
                <span className="text-muted-foreground tabular-nums">
                  {f.message_count.toLocaleString("es-ES")}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
