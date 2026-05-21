import "./styles.css";

import { useMemo, useState } from "react";
import { Link } from "react-router";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import {
  useAgentChannel,
  useDeviceMap,
  useMultiAgentAggregates,
  type DeviceMapEntry,
} from "doover-js/react";

import { AlertTriangle, CheckCircle2, HelpCircle, Signal, SignalZero, TrendingUp, X } from "lucide-react";

import { cn } from "./components/ui/utils";
import { Badge } from "./components/ui/badge";
import { Card, CardContent } from "./components/ui/card";
import {
  buildRow,
  computeTotals,
  formatMb,
  formatRelTime,
  num,
  sortRows,
  type SimAggregate,
  type SimRow,
  type SortDir,
  type SortKey,
} from "./lib/sim";

const DEFAULT_HEAVY_USER_THRESHOLD_MB = 500;

interface UiRemoteComponentFleet {
  app_key: string;
}

interface DashboardDeploymentConfig {
  applications?: Record<
    string,
    {
      heavy_user_threshold_mb?: number | null;
    } & Record<string, unknown>
  >;
}

export default function FleetSimUsageWidget(props: { uiElement?: UiRemoteComponentFleet }) {
  return (
    <RemoteComponentWrapper>
      <FleetSimUsageWidgetInner uiElement={props.uiElement ?? { app_key: "" }} />
    </RemoteComponentWrapper>
  );
}

function FleetSimUsageWidgetInner({ uiElement }: { uiElement: UiRemoteComponentFleet }) {
  const params = useRemoteParams();
  const agentId = params?.agentId;
  const dashboardAppKey = uiElement?.app_key ?? "";

  const { devices, isLoading: cfgLoading, hasDeviceMap } = useDeviceMap(agentId, dashboardAppKey);
  const deviceIds = useMemo(() => devices.map((d) => d.id), [devices]);

  // The dashboard's own config (heavy-user threshold etc.) lives in the same
  // deployment_config channel as DEVICE_MAP — react-query dedupes the fetch.
  const { data: deploymentConfig } = useAgentChannel<DashboardDeploymentConfig>(
    agentId,
    "deployment_config",
  );
  const heavyThresholdMb = useMemo(() => {
    const t = num(deploymentConfig?.applications?.[dashboardAppKey]?.heavy_user_threshold_mb);
    return Math.max(1, t ?? DEFAULT_HEAVY_USER_THRESHOLD_MB);
  }, [deploymentConfig, dashboardAppKey]);

  const { aggregatesByAgent, query } = useMultiAgentAggregates<SimAggregate>(
    "sim-card",
    deviceIds,
  );

  const rows: SimRow[] = useMemo(() => {
    return devices.map((entry: DeviceMapEntry) =>
      buildRow(entry, aggregatesByAgent[entry.id]),
    );
  }, [devices, aggregatesByAgent]);

  const totals = useMemo(() => computeTotals(rows, heavyThresholdMb), [rows, heavyThresholdMb]);

  const [sortKey, setSortKey] = useState<SortKey>("data");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [search, setSearch] = useState("");

  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      // Numeric columns are most useful biggest-first; text columns A→Z.
      setSortDir(k === "device" || k === "status" ? "asc" : "desc");
    }
  };

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.deviceName.toLowerCase().includes(q) ||
        (r.iccid ?? "").toLowerCase().includes(q) ||
        (r.provider ?? "").toLowerCase().includes(q),
    );
  }, [rows, search]);

  const sortedRows = useMemo(
    () => sortRows(filteredRows, sortKey, sortDir),
    [filteredRows, sortKey, sortDir],
  );

  if (cfgLoading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading fleet…</div>;
  }
  if (!hasDeviceMap) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No devices in scope — add devices or groups under <em>Devices</em> in this dashboard's config.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <SummaryCards totals={totals} heavyThresholdMb={heavyThresholdMb} />
      <div className="flex items-center justify-between gap-2">
        <SearchInput value={search} onChange={setSearch} />
        <RefreshState query={query} />
      </div>
      <SimTable
        rows={sortedRows}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={onSort}
        heavyThresholdMb={heavyThresholdMb}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
function SummaryCards({
  totals,
  heavyThresholdMb,
}: {
  totals: ReturnType<typeof computeTotals>;
  heavyThresholdMb: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <StatCard
        label="Active SIMs"
        value={totals.inAccount.toLocaleString()}
        sub={`of ${totals.totalDevices.toLocaleString()} device${totals.totalDevices === 1 ? "" : "s"}`}
        icon={<Signal className="size-4 text-muted-foreground" />}
      />
      <StatCard
        label="Avg MTD data"
        value={formatMb(totals.dataRowsCount > 0 ? totals.totalDataMb / totals.dataRowsCount : null)}
        sub={`total ${formatMb(totals.totalDataMb)} across ${totals.dataRowsCount} SIM${totals.dataRowsCount === 1 ? "" : "s"}`}
        icon={<TrendingUp className="size-4 text-muted-foreground" />}
      />
      <StatCard
        label="Heavy users"
        value={totals.heavyUsers.toLocaleString()}
        sub={`> ${heavyThresholdMb} MB this month`}
        tone={totals.heavyUsers > 0 ? "warning" : "muted"}
        icon={<AlertTriangle className="size-4 text-amber-600 dark:text-amber-400" />}
      />
      <StatCard
        label="Overage"
        value={totals.overage.toLocaleString()}
        sub="SIMs past their plan limit"
        tone={totals.overage > 0 ? "destructive" : "muted"}
        icon={<SignalZero className="size-4 text-destructive" />}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "muted" | "warning" | "destructive";
  icon?: React.ReactNode;
}) {
  const valueClass =
    tone === "destructive"
      ? "text-destructive"
      : tone === "warning"
      ? "text-amber-700 dark:text-amber-400"
      : "";
  return (
    <Card>
      <CardContent>
        <div className="flex items-start justify-between gap-2">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
          {icon}
        </div>
        <div className={cn("text-2xl font-semibold tabular-nums", valueClass)}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative flex items-center">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Filter device, ICCID, provider…"
        className="w-72 max-w-full rounded-md border border-border bg-background px-2 py-1 pr-7 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-1 inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
          aria-label="Clear filter"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

function RefreshState({ query }: { query: { isFetching: boolean; isError: boolean } }) {
  if (query.isError) return <span className="text-xs text-destructive">Failed to load SIM data</span>;
  if (query.isFetching) return <span className="text-xs text-muted-foreground">Refreshing…</span>;
  return null;
}

// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: SimRow["status"] }) {
  switch (status) {
    case "in_account":
      return (
        <Badge variant="success">
          <CheckCircle2 /> Matched
        </Badge>
      );
    case "not_in_account":
      return (
        <Badge variant="warning">
          <HelpCircle /> Unknown
        </Badge>
      );
    case "error":
      return (
        <Badge variant="destructive">
          <AlertTriangle /> Error
        </Badge>
      );
    default:
      return (
        <Badge variant="muted">
          <HelpCircle /> No data
        </Badge>
      );
  }
}

function SortHeader({
  label,
  k,
  sortKey,
  sortDir,
  onSort,
  align = "left",
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right" | "center";
}) {
  const active = k === sortKey;
  const arrow = active ? (sortDir === "asc" ? "▲" : "▼") : "";
  return (
    <th
      scope="col"
      className={cn(
        "px-2 py-1.5 text-xs font-medium text-muted-foreground select-none",
        align === "right" && "text-right",
        align === "center" && "text-center",
        align === "left" && "text-left",
      )}
    >
      <button
        type="button"
        onClick={() => onSort(k)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-foreground",
          active && "text-foreground",
        )}
      >
        {label}
        {arrow && <span className="text-[0.625rem]">{arrow}</span>}
      </button>
    </th>
  );
}

function SimTable({
  rows,
  sortKey,
  sortDir,
  onSort,
  heavyThresholdMb,
}: {
  rows: SimRow[];
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  heavyThresholdMb: number;
}) {
  if (rows.length === 0) {
    return (
      <Card>
        <CardContent>
          <div className="py-6 text-center text-sm text-muted-foreground">No matching SIMs.</div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-muted/40">
              <tr className="border-b border-border">
                <SortHeader label="Device" k="device" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <th className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">ICCID</th>
                <SortHeader label="Status" k="status" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <SortHeader label="Data (MTD)" k="data" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right" />
                <SortHeader label="Checked" k="checked" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <SimRowView key={r.agentId} row={r} heavyThresholdMb={heavyThresholdMb} />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function SimRowView({ row, heavyThresholdMb }: { row: SimRow; heavyThresholdMb: number }) {
  const heavy = row.dataMb != null && row.dataMb > heavyThresholdMb;
  return (
    <tr className="border-b border-border/60 last:border-b-0 hover:bg-muted/30">
      <td className="px-2 py-1.5">
        <Link
          to={`/agent/${row.agentId}`}
          className="font-medium text-foreground hover:underline"
          title={`Open ${row.deviceName}`}
        >
          {row.deviceName}
        </Link>
      </td>
      <td className="px-2 py-1.5 font-mono text-[0.6875rem] text-muted-foreground">
        {row.iccid ?? "—"}
      </td>
      <td className="px-2 py-1.5">
        <StatusBadge status={row.status} />
        {row.overage && (
          <span className="ml-1 align-middle">
            <Badge variant="destructive">overage</Badge>
          </span>
        )}
      </td>
      <td className={cn("px-2 py-1.5 text-right tabular-nums", heavy && "font-semibold text-amber-700 dark:text-amber-400")}>
        {formatMb(row.dataMb)}
      </td>
      <td
        className="px-2 py-1.5 text-right text-xs text-muted-foreground"
        title={row.checkedAtMs ? new Date(row.checkedAtMs).toLocaleString() : ""}
      >
        {formatRelTime(row.checkedAtMs)}
      </td>
    </tr>
  );
}
