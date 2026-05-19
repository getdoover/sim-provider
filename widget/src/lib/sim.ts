import type { Aggregate } from "doover-js";
import type { DeviceMapEntry } from "doover-js/react";

/**
 * Shape every `sim-card` aggregate carries, regardless of which provider
 * integration wrote it. `details` is provider-specific, but `iccid`, `status`,
 * `usage`, and `provider` are part of the shared contract. The "checked at"
 * timestamp is the aggregate's own `last_updated`, not a field in the data.
 */
export interface SimAggregate {
  iccid: string;
  status: "in_account" | "not_in_account" | "error";
  details: Record<string, unknown> | null;
  usage: SimUsage | null;
  error: string | null;
  provider: string;
  configured_account_id: string;
}

export interface SimUsage {
  month_to_date_data_mb?: number | null;
  month_to_date_sms?: number | null;
  month_to_date_voice?: number | null;
  month_to_date_ussd?: number | null;
  overage_limit?: number | null;
  overage_limit_reached?: boolean | null;
}

export interface SimRow {
  agentId: string;
  deviceName: string;
  iccid: string | null;
  status: SimAggregate["status"] | "no_data";
  provider: string | null;
  dataMb: number | null;
  overage: boolean;
  checkedAtMs: number | null;
}

export function num(v: unknown): number | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return v;
}

export function deviceName(entry: DeviceMapEntry): string {
  if (typeof entry.display_name === "string" && entry.display_name) return entry.display_name;
  if (typeof entry.name === "string" && entry.name) return entry.name;
  return entry.id;
}

export function buildRow(entry: DeviceMapEntry, agg: Aggregate<SimAggregate> | undefined): SimRow {
  const data = agg?.data;
  if (!data) {
    return {
      agentId: entry.id,
      deviceName: deviceName(entry),
      iccid: null,
      status: "no_data",
      provider: null,
      dataMb: null,
      overage: false,
      checkedAtMs: null,
    };
  }
  return {
    agentId: entry.id,
    deviceName: deviceName(entry),
    iccid: data.iccid ?? null,
    status: data.status,
    provider: data.provider ?? null,
    dataMb: num(data.usage?.month_to_date_data_mb),
    overage: !!data.usage?.overage_limit_reached,
    checkedAtMs: typeof agg?.last_updated === "number" ? agg.last_updated : null,
  };
}

export function formatMb(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1024) return `${(v / 1024).toFixed(2)} GB`;
  if (v >= 10) return `${v.toFixed(1)} MB`;
  return `${v.toFixed(2)} MB`;
}

export function formatRelTime(ms: number | null): string {
  if (ms == null) return "—";
  // Small future skew (clocks drift, request latency) rounds to "just now"
  // rather than the alarming "in the future".
  const diff = Math.max(0, Date.now() - ms);
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const days = Math.floor(hr / 24);
  if (days < 30) return `${days} d ago`;
  const months = Math.floor(days / 30);
  return `${months} mo ago`;
}

export interface FleetTotals {
  /** Devices in scope (regardless of whether a sim-card aggregate exists). */
  totalDevices: number;
  /** Rows whose ICCID was matched to the configured provider account. */
  inAccount: number;
  /** Rows whose ICCID was not found in the provider account. */
  notInAccount: number;
  /** Rows where no `sim-card` aggregate has been written yet. */
  noData: number;
  /** Sum of month-to-date data across all rows with a usage figure (MB). */
  totalDataMb: number;
  /** Rows that contributed a usage figure to `totalDataMb`. */
  dataRowsCount: number;
  /** Rows whose month-to-date data is above `heavyThresholdMb`. */
  heavyUsers: number;
  /** Rows flagged by the provider as past their plan's overage limit. */
  overage: number;
}

export function computeTotals(rows: SimRow[], heavyThresholdMb: number): FleetTotals {
  let inAccount = 0;
  let notInAccount = 0;
  let noData = 0;
  let totalDataMb = 0;
  let dataRowsCount = 0;
  let heavyUsers = 0;
  let overage = 0;
  for (const r of rows) {
    if (r.status === "in_account") inAccount++;
    else if (r.status === "not_in_account") notInAccount++;
    else if (r.status === "no_data") noData++;
    if (r.dataMb != null) {
      totalDataMb += r.dataMb;
      dataRowsCount++;
      if (r.dataMb > heavyThresholdMb) heavyUsers++;
    }
    if (r.overage) overage++;
  }
  return {
    totalDevices: rows.length,
    inAccount,
    notInAccount,
    noData,
    totalDataMb,
    dataRowsCount,
    heavyUsers,
    overage,
  };
}

export type SortKey = "device" | "data" | "status" | "checked";
export type SortDir = "asc" | "desc";

export function sortRows(rows: SimRow[], key: SortKey, dir: SortDir): SimRow[] {
  const sign = dir === "asc" ? 1 : -1;
  // null/missing values always sort to the bottom regardless of direction,
  // so an empty cell never claims the "biggest user" slot at the top.
  const numKey = (r: SimRow): number | null => {
    if (key === "data") return r.dataMb;
    if (key === "checked") return r.checkedAtMs;
    return null;
  };
  const STATUS_RANK: Record<SimRow["status"], number> = {
    in_account: 0,
    not_in_account: 1,
    error: 2,
    no_data: 3,
  };
  return [...rows].sort((a, b) => {
    if (key === "device") return sign * a.deviceName.localeCompare(b.deviceName);
    if (key === "status") return sign * (STATUS_RANK[a.status] - STATUS_RANK[b.status]);
    const av = numKey(a);
    const bv = numKey(b);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return sign * (av - bv);
  });
}
