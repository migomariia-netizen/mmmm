import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { Download, Upload, RefreshCw, Eye, EyeOff, Plus, ArrowUpRight, ArrowDownLeft } from "lucide-react";
import api from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { CoinIcon, StatusBadge, fmtUsd, fmtCrypto } from "@/components/common";
import { Button } from "@/components/ui/button";

const RANGES = ["1Д", "1Т", "1М", "1Р"];

export default function Dashboard() {
  const { t } = useLang();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [prices, setPrices] = useState([]);
  const [range, setRange] = useState("1Т");
  const [hideBalance, setHideBalance] = useState(false);

  useEffect(() => {
    api.get("/me/summary").then((r) => setData(r.data)).catch(() => {});
    api.get("/prices").then((r) => setPrices(r.data.data)).catch(() => {});
  }, []);

  if (!data) return <div className="text-slate-400">…</div>;
  const ticker = prices.filter((p) => ["SOL", "TRX", "LTC", "BTC"].includes(p.iso));

  return (
    <div className="space-y-6 oki-fade-up">
      {/* Balance card */}
      <div className="rounded-3xl bg-white p-6 shadow-sm border border-slate-100 sm:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-slate-500">
              {t("total_balance")}
              <button
                type="button"
                data-testid="toggle-balance"
                onClick={() => setHideBalance((v) => !v)}
                aria-label={hideBalance ? "Показати баланс" : "Приховати баланс"}
                className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              >
                {hideBalance ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <div data-testid="total-balance" className="mt-1 text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
              {hideBalance ? "••••••" : fmtUsd(data.total_usd)}
            </div>
            <div className="mt-1 text-sm text-slate-500">{t("available")} • {hideBalance ? "••••••" : fmtUsd(data.available_usd)}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button data-testid="action-receive" onClick={() => navigate("/wallet")} className="rounded-full bg-white text-slate-800 border border-slate-200 shadow-sm hover:bg-slate-50">
              <Download className="mr-2 h-4 w-4" /> {t("receive")}
            </Button>
            <Button data-testid="action-send" onClick={() => navigate("/wallet")} className="rounded-full bg-white text-slate-800 border border-slate-200 shadow-sm hover:bg-slate-50">
              <Upload className="mr-2 h-4 w-4" /> {t("send")}
            </Button>
            <Button data-testid="action-exchange" onClick={() => navigate("/wallet")} className="rounded-full bg-blue-600 hover:bg-blue-700">
              <RefreshCw className="mr-2 h-4 w-4" /> {t("exchange")}
            </Button>
          </div>
        </div>
        <div className="mt-6 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          {ticker.map((p) => (
            <div key={p.iso} data-testid={`ticker-${p.iso}`} className="flex items-center gap-2 rounded-full bg-slate-50 px-3 py-1.5">
              <CoinIcon iso={p.iso} size={22} />
              <span className="text-sm font-semibold text-slate-700">{p.iso}</span>
              <span className="text-sm text-slate-500">{fmtUsd(p.price)}</span>
              <span className={`text-xs font-semibold ${p.change >= 0 ? "text-emerald-600" : "text-rose-500"}`}>
                {p.change >= 0 ? "+" : ""}{p.change}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Chart */}
        <div className="rounded-3xl bg-white p-6 shadow-sm border border-slate-100 lg:col-span-3 min-w-0 overflow-hidden">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-lg font-bold text-slate-900">{t("balance_chart")}</div>
              <div className="text-sm text-slate-500">{t("available")} • {fmtUsd(data.available_usd)}</div>
            </div>
            <div className="flex gap-1 rounded-full bg-slate-100 p-1">
              {RANGES.map((r) => (
                <button key={r} data-testid={`range-${r}`} onClick={() => setRange(r)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold transition ${range === r ? "bg-white text-slate-900 shadow" : "text-slate-500"}`}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.chart}>
              <defs>
                <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#7c3aed" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#7c3aed" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} minTickGap={30} />
              <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => "$" + v} />
              <Tooltip formatter={(v) => fmtUsd(v)} />
              <Area type="monotone" dataKey="value" stroke="#7c3aed" strokeWidth={2.5} fill="url(#g)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Recent transactions */}
        <div className="rounded-3xl bg-white p-6 shadow-sm border border-slate-100 lg:col-span-2 min-w-0">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-lg font-bold text-slate-900">{t("recent_tx")}</div>
            <div className="flex gap-2">
              <Button size="sm" data-testid="dash-create-invoice" onClick={() => navigate("/requests")} className="rounded-full bg-blue-600 hover:bg-blue-700 text-xs h-8">
                <Plus className="mr-1 h-3.5 w-3.5" /> {t("create_invoice")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => navigate("/wallet")} className="rounded-full text-xs h-8 border-slate-200">{t("all_tx")}</Button>
            </div>
          </div>
          <div className="space-y-1">
            {data.recent.length === 0 && <div className="py-8 text-center text-sm text-slate-400">{t("empty_tx")}</div>}
            {data.recent.map((tx) => {
              const neg = tx.type === "withdraw";
              return (
                <div key={tx.tx_id} data-testid={`tx-row-${tx.tx_id}`} className="flex items-center gap-3 rounded-xl px-2 py-2.5 hover:bg-slate-50">
                  <div className="relative">
                    <CoinIcon iso={tx.iso} size={38} />
                    <div className={`absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full text-white ${neg ? "bg-rose-500" : "bg-emerald-500"}`}>
                      {neg ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownLeft className="h-2.5 w-2.5" />}
                    </div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold capitalize text-slate-800">{tx.type}</div>
                    <div className="truncate text-xs text-slate-400">{tx.description}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-semibold ${neg ? "text-rose-500" : "text-emerald-600"}`}>
                      {neg ? "-" : "+"}{fmtCrypto(tx.amount)} {tx.iso}
                    </div>
                    <div className="text-xs text-slate-400">{fmtUsd(tx.usd_value)}</div>
                  </div>
                  <StatusBadge status={tx.status} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
