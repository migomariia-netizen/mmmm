import React from "react";

export const COIN_COLORS = {
  USDT: "#26A17B", USDC: "#2775CA", BTC: "#F7931A", ETH: "#627EEA",
  BNB: "#F3BA2F", TRX: "#FF0013", SOL: "#14F195", LTC: "#345D9D",
};

export function CoinIcon({ iso, size = 36 }) {
  const c = COIN_COLORS[iso] || "#64748B";
  return (
    <div
      data-testid={`coin-icon-${iso}`}
      className="flex items-center justify-center rounded-full font-bold text-white shrink-0"
      style={{ width: size, height: size, background: c, fontSize: size * 0.34 }}
    >
      {iso.slice(0, 2)}
    </div>
  );
}

export function fmtUsd(v) {
  return "$" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtCrypto(v) {
  const n = Number(v || 0);
  return n.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

const STATUS_STYLES = {
  Done: "bg-emerald-100 text-emerald-700 border-emerald-200",
  Completed: "bg-emerald-100 text-emerald-700 border-emerald-200",
  Paid: "bg-emerald-100 text-emerald-700 border-emerald-200",
  Pending: "bg-amber-100 text-amber-700 border-amber-200",
  Created: "bg-amber-100 text-amber-700 border-amber-200",
  "In Process": "bg-sky-100 text-sky-700 border-sky-200",
  Partially: "bg-sky-100 text-sky-700 border-sky-200",
  Overpayment: "bg-violet-100 text-violet-700 border-violet-200",
  Cancelled: "bg-rose-100 text-rose-700 border-rose-200",
  Expired: "bg-slate-100 text-slate-600 border-slate-200",
  Failed: "bg-rose-100 text-rose-700 border-rose-200",
};

export function StatusBadge({ status }) {
  const cls = STATUS_STYLES[status] || "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span data-testid={`status-${status}`} className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${cls}`}>
      {status}
    </span>
  );
}
