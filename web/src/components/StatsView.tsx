import { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  BarChart, Bar,
  LineChart, Line,
  AreaChart, Area,
  PieChart, Pie, Cell,
  XAxis, YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { api } from "@/api";
import type { StatsResponse } from "@/types";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Organic palette for categorical charts. Saturated hsl colours to
// stand out well against the dark theme.
const PALETTE = [
  "#60a5fa", "#a78bfa", "#f472b6", "#fb923c", "#facc15",
  "#34d399", "#22d3ee", "#94a3b8", "#fbbf24", "#f87171",
];

function fmt(n: number): string {
  return n.toLocaleString("en-GB");
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function StatsView() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStats(null);
    setError(null);
    api.stats()
      .then((s) => { if (!cancelled) setStats(s); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, []);

  if (error) return <div className="p-6 text-destructive">{error}</div>;
  if (!stats) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p>Computing aggregates…</p>
          <p className="mt-1 text-xs">Usually takes about 5-10 seconds across ~147k messages.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <h1 className="text-xl font-semibold">Archive statistics</h1>

        <KpiGrid stats={stats} />

        <Card title="Messages by year">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={stats.by_year} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", fontSize: 12 }}
                formatter={(v: number) => [fmt(v), "messages"]}
              />
              <Bar dataKey="count" fill={PALETTE[0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Messages by month (since 2010)">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={stats.by_month} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                interval={11}   // one label per year
              />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", fontSize: 12 }}
                formatter={(v: number) => [fmt(v), "messages"]}
              />
              <Line type="monotone" dataKey="count" stroke={PALETTE[1]} strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Hour of day (UTC)">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={stats.by_hour} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="hour"
                  tickFormatter={(h: number) => `${h}h`}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <Tooltip
                  contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", fontSize: 12 }}
                  labelFormatter={(h: number) => `${h}h UTC`}
                  formatter={(v: number) => [fmt(v), "messages"]}
                />
                <Area type="monotone" dataKey="count" stroke={PALETTE[2]} fill={PALETTE[2]} fillOpacity={0.25} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          <Card title="Day of week">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={stats.by_weekday.map((d) => ({ ...d, label: WEEKDAY_LABELS[d.weekday] ?? "?" }))}
                margin={{ left: 10, right: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <Tooltip
                  contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", fontSize: 12 }}
                  formatter={(v: number) => [fmt(v), "messages"]}
                />
                <Bar dataKey="count" fill={PALETTE[3]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>

        <Card title="Distribution by account">
          <AccountDonut accounts={stats.by_account} />
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Top 20 senders">
            <RankList items={stats.top_senders} />
          </Card>
          <Card title="Top 20 recipients">
            <RankList items={stats.top_recipients} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function KpiGrid({ stats }: { stats: StatsResponse }) {
  const withAttPct = stats.total_messages > 0
    ? Math.round(stats.messages_with_attachments * 100 / stats.total_messages)
    : 0;
  const withHtmlPct = stats.total_messages > 0
    ? Math.round(stats.messages_with_html * 100 / stats.total_messages)
    : 0;
  const dedupFactor = stats.total_messages > 0
    ? (stats.total_message_sources / stats.total_messages).toFixed(2)
    : "—";
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Kpi label="Unique messages" value={fmt(stats.total_messages)} hint={`${fmt(stats.total_message_sources)} occurrences (×${dedupFactor})`} />
      <Kpi label="Average size" value={fmtBytes(stats.avg_message_size)} hint={`with HTML: ${withHtmlPct}%`} />
      <Kpi label="With attachments" value={`${withAttPct}%`} hint={`${fmt(stats.messages_with_attachments)} messages`} />
      <Kpi label="Encrypted attachments" value={fmtBytes(stats.attachments_bytes_total)} hint={`${fmt(stats.total_unique_attachments)} unique · ${fmt(stats.total_attachments)} links`} />
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

function AccountDonut({ accounts }: { accounts: StatsResponse["by_account"] }) {
  const total = accounts.reduce((s, a) => s + a.count, 0);
  return (
    <div className="flex flex-col items-center gap-4 lg:flex-row lg:items-stretch">
      <div className="h-60 w-full max-w-xs">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={accounts}
              dataKey="count"
              nameKey="account"
              innerRadius="55%"
              outerRadius="90%"
              paddingAngle={1}
              stroke="hsl(var(--background))"
            >
              {accounts.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", fontSize: 12 }}
              formatter={(v: number, _: unknown, p: { payload?: { account?: string } }) =>
                [`${fmt(v)} (${Math.round(v * 100 / total)}%)`, p?.payload?.account ?? ""]
              }
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex-1 space-y-1 text-xs">
        {accounts.map((a, i) => (
          <li key={`${a.section}|${a.account}`} className="flex items-center gap-2">
            <span className="h-3 w-3 shrink-0 rounded" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="flex-1 truncate">
              <span className="text-muted-foreground">{a.section}</span> · {a.account}
            </span>
            <span className="tabular-nums text-muted-foreground">{fmt(a.count)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RankList({ items }: { items: { addr: string; count: number }[] }) {
  const max = useMemo(() => Math.max(1, ...items.map((i) => i.count)), [items]);
  return (
    <ul className="space-y-1">
      {items.map((s) => {
        const pct = (s.count * 100) / max;
        return (
          <li key={s.addr} className="space-y-0.5">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate font-mono" title={s.addr}>{s.addr}</span>
              <span className="tabular-nums text-muted-foreground">{fmt(s.count)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded bg-secondary/40">
              <div className="h-full rounded bg-primary/60" style={{ width: `${pct}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
