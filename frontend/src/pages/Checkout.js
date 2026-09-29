import React, { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { Copy, CheckCircle2, Clock } from "lucide-react";
import api, { apiErr } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { CoinIcon, fmtCrypto } from "@/components/common";
import { Button } from "@/components/ui/button";

export default function Checkout() {
  const { id } = useParams();
  const { t } = useLang();
  const [inv, setInv] = useState(null);
  const [meta, setMeta] = useState({ cur: {}, net: {} });
  const [pay, setPay] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/checkout/${id}`);
      setInv(data.data);
      setMeta({ cur: data.data.currency_meta, net: data.data.network_meta });
      if (data.data.pay_info) setPay(data.data.pay_info);
    } catch (e) { toast.error(apiErr(e)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (inv && inv.status === "Paid") return;
    const iv = setInterval(load, 6000);
    return () => clearInterval(iv);
  }, [inv, load]);

  const select = async (iso, network_id) => {
    try { const { data } = await api.post(`/checkout/${id}/select`, { iso, network_id }); setPay(data.data); }
    catch (e) { toast.error(apiErr(e)); }
  };

  if (!inv) return <div className="flex min-h-screen items-center justify-center text-slate-400">…</div>;
  const brand = inv.merchant?.brand_color || "#2563EB";
  const paid = inv.status === "Paid" || inv.status === "Completed";

  const curList = (inv.currencies || []).map((c) => ({
    iso: c.iso, network: c.network, name: meta.net[String(c.network)]?.name || "",
  }));

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 p-4">
      <div className="oki-fade-up w-full max-w-md rounded-3xl bg-white p-6 shadow-xl border border-slate-100">
        <div className="mb-4 flex items-center gap-3 border-b border-slate-100 pb-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl text-lg font-extrabold text-white" style={{ background: brand }}>
            {(inv.merchant?.name || "O").slice(0, 1)}
          </div>
          <div>
            <div className="font-bold text-slate-900">{inv.merchant?.name || "Merchant"}</div>
            <div className="text-xs text-slate-400">{t("invoice")} #{inv.id}</div>
          </div>
        </div>

        <div className="text-center">
          <div className="text-sm text-slate-500">{inv.description || t("invoice")}</div>
          <div className="mt-1 text-4xl font-extrabold text-slate-900">{inv.price} {inv.payment_currency_iso}</div>
        </div>

        {paid ? (
          <div data-testid="checkout-paid" className="mt-6 flex flex-col items-center gap-2 rounded-2xl bg-emerald-50 p-8 text-center">
            <CheckCircle2 className="h-14 w-14 text-emerald-500" />
            <div className="text-lg font-bold text-emerald-700">{t("paid")}</div>
          </div>
        ) : !pay ? (
          <div className="mt-6">
            <div className="mb-2 text-sm font-semibold text-slate-600">{t("select_currency")}</div>
            <div className="oki-scroll max-h-72 space-y-2 overflow-y-auto">
              {curList.map((c) => (
                <button key={`${c.iso}-${c.network}`} data-testid={`pick-${c.iso}-${c.network}`} onClick={() => select(c.iso, c.network)}
                  className="flex w-full items-center gap-3 rounded-xl border border-slate-100 p-3 text-left transition hover:border-blue-300 hover:bg-blue-50">
                  <CoinIcon iso={c.iso} />
                  <div><div className="font-semibold text-slate-800">{c.iso}</div><div className="text-xs text-slate-400">{c.name}</div></div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4 text-center">
              <img alt="qr" src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(pay.address)}`} className="mx-auto rounded-xl bg-white p-2" />
              <div className="mt-3 text-2xl font-extrabold text-slate-900">{fmtCrypto(pay.amount_to_pay)} {pay.currency}</div>
              <div className="text-xs text-slate-400">{pay.network}</div>
              {pay.merchant_fee > 0 && (
                <div data-testid="checkout-fee" className="mt-1 text-xs text-slate-400">
                  {fmtCrypto(pay.amount)} + {fmtCrypto(pay.merchant_fee)} ({t("fee_in")})
                </div>
              )}
              <div className="mt-3 flex items-center gap-2 rounded-xl bg-white p-2">
                <code data-testid="checkout-address" className="flex-1 break-all text-xs text-slate-700">{pay.address}</code>
                <Button size="icon" variant="ghost" onClick={() => { navigator.clipboard.writeText(pay.address); toast.success(t("copied")); }}><Copy className="h-4 w-4" /></Button>
              </div>
            </div>
            <div className="flex items-center justify-center gap-2 text-sm text-amber-600"><Clock className="h-4 w-4" />{t("waiting")}</div>
            <div className="rounded-xl bg-blue-50 border border-blue-100 p-3 text-xs text-blue-900 space-y-1">
              <div className="font-semibold">🔗 Реальний on-chain платіж</div>
              <div>Надішліть точну суму <b>{fmtCrypto(pay.amount_to_pay)} {pay.currency}</b> на вказану адресу в мережі <b>{pay.network}</b>. Транзакція автоматично підтвердиться після появи в блокчейні (Alchemy / TronGrid моніторять адресу).</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
