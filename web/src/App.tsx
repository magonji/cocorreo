import { useEffect, useState } from "react";
import { BarChart3, Images, Mail, Moon, Sun } from "lucide-react";
import { FolderList, type FolderSelection } from "@/components/FolderList";
import { MessageList } from "@/components/MessageList";
import { MessageDetail } from "@/components/MessageDetail";
import { StatsView } from "@/components/StatsView";
import { GalleryView } from "@/components/GalleryView";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import type { HealthResponse } from "@/types";

type View = "messages" | "stats" | "gallery";
type Theme = "dark" | "light";

function App() {
  const [folder, setFolder] = useState<FolderSelection | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [view, setView] = useState<View>("messages");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  // The initial theme was applied by the inline script in `index.html` before mount,
  // so we mirror the class that's already present to avoid a mismatch.
  const [theme, setTheme] = useState<Theme>(() =>
    typeof document !== "undefined" && document.documentElement.classList.contains("dark")
      ? "dark"
      : "light"
  );
  const toggleTheme = () => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", next === "dark");
      try {
        localStorage.setItem("cocorreo-theme", next);
      } catch { /* ignore quota errors / private mode */ }
      return next;
    });
  };

  useEffect(() => {
    api.health()
      .then(setHealth)
      .catch((e: Error) => setHealthError(e.message));
  }, []);

  if (healthError) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-destructive">
        <div>
          <h1 className="text-lg font-medium">Can't reach the backend</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Is <code>cocorreo serve</code> running? We expect it at /api/.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{healthError}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full text-sm">
      <aside className="flex w-72 flex-col border-r border-border">
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h1 className="font-semibold tracking-tight">cocorreo</h1>
          <div className="flex items-center gap-3">
            {health && (
              <span className="text-xs text-muted-foreground">
                {health.total_messages.toLocaleString("en-GB")} msgs
              </span>
            )}
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              aria-label="Toggle theme"
            >
              {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        </header>

        <nav className="flex gap-1 border-b border-border px-2 py-2">
          <NavButton
            active={view === "messages"}
            onClick={() => setView("messages")}
            icon={<Mail className="h-3.5 w-3.5" />}
            label="Messages"
          />
          <NavButton
            active={view === "gallery"}
            onClick={() => setView("gallery")}
            icon={<Images className="h-3.5 w-3.5" />}
            label="Gallery"
          />
          <NavButton
            active={view === "stats"}
            onClick={() => setView("stats")}
            icon={<BarChart3 className="h-3.5 w-3.5" />}
            label="Statistics"
          />
        </nav>

        <div className="flex-1 overflow-y-auto scrollbar-thin">
          <FolderList
            selected={folder}
            onSelect={(f) => { setFolder(f); setSelectedId(null); setView("messages"); }}
          />
        </div>
      </aside>

      {view === "stats" ? (
        <section className="flex flex-1 flex-col overflow-hidden">
          <StatsView />
        </section>
      ) : view === "gallery" ? (
        <section className="flex flex-1 flex-col overflow-hidden">
          <GalleryView
            onOpenMessage={(id) => { setSelectedId(id); setFolder(null); setView("messages"); }}
          />
        </section>
      ) : (
        <>
          <section className="flex w-[420px] flex-col border-r border-border">
            <MessageList folder={folder} selectedId={selectedId} onSelect={setSelectedId} />
          </section>

          <section className="flex flex-1 flex-col overflow-hidden">
            {selectedId != null
              ? <MessageDetail messageId={selectedId} onSelectMessage={setSelectedId} />
              : (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  <p>Select a message</p>
                </div>
              )
            }
          </section>
        </>
      )}
    </div>
  );
}

function NavButton({
  active, onClick, icon, label,
}: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50",
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export default App;
