import React, { useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Radar, ArrowRightLeft, ExternalLink } from "lucide-react";
import api, { apiErr } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { CoinIcon, fmtUsd, fmtCrypto } from "@/components/common";
import { Button } from "@/components/ui/button";

const NET_NAME = { ethereum: "Ethereum (ERC-20)", polygon: "Polygon", bsc: "BNB Chain (BEP-20)", arbitrum: "Arbitrum", tron: "TRON (TRC-20)", bitcoin: "Bitcoin" };
const EXPLORER = {
  ethereum: "https://etherscan.io/tx/", polygon: "https://polygonscan.com/tx/",
  bsc: "https://bscscan.com/tx/", arbitrum: "https://arbiscan.io/tx/",
};

export default function Recovery() {
  const { t } = useLang();
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [findings, setFindings] = useState([]);
  const [treasury, setTreasury] = useState("");
  const [busy, setBusy] = useState("");

  const scan = async () => {
    setScanning(true);
    try {
      const { data } = await api.get("/recovery/scan");
      setFindings(data.findings);
      setTreasury(data.treasury);
      setScanned(true);
      toast.success(`${t("scanning")} ✓ EVM:${data.scanned.evm} TRON:${data.scanned.tron} BTC:${data.scanned.btc}`);
    } catch (e) { toast.error(apiErr(e)); }
    finally { setScanning(false); }
  };

  const sweep = async (f) => {
    const key = `${f.address}-${f.chain}-${f.symbol}`;
    setBusy(key);
    try {
      const { data } = await api.post("/recovery/sweep", {
        address: f.address, chain: f.chain, kind: f.kind, contract: f.contract,
      });
      toast.success("Sweep відправлено: " + data.data.tx_hash.slice(0, 12) + "…");
      scan();
    } catch (e) { toast.error(apiErr(e)); }
    finally { setBusy(""); }
  };

  const total = findings.reduce((s, f) => s + (f.usd || 0), 0);

  return (
    <div className="space-y-6 oki-fade-up">
      <div className="rounded-3xl bg-gradient-to-br from-blue-600 to-indigo-700 p-6 text-white shadow-lg sm:p-8">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/15"><ShieldCheck className="h-6 w-6" /></div>
          <div className="flex-1">
            <h1 className="text-2xl font-bold">{t("recovery")}</h1>
            <p className="mt-1 max-w-2xl text-sm text-blue-100">{t("recovery_desc")}</p>
            {treasury && <div className="mt-3 text-xs text-blue-100">{t("treasury")}: <code className="rounded bg-white/10 px-2 py-0.5">{treasury}</code></div>}
          </div>
          <Button data-testid="scan-btn" onClick={scan} disabled={scanning} className="rounded-full bg-white text-blue-700 hover:bg-blue-50">
            <Radar className={`mr-2 h-4 w-4 ${scanning ? "animate-spin" : ""}`} />{scanning ? t("scanning") : t("scan_now")}
          </Button>
        </div>
      </div>

      {scanned && (
        <div className="rounded-3xl bg-white p-6 shadow-sm border border-slate-100">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-lg font-bold text-slate-900">{t("found_funds")}</div>
            {findings.length > 0 && <div className="text-sm font-semibold text-emerald-600">{fmtUsd(total)}</div>}
          </div>
          {findings.length === 0 ? (
            <div data-testid="no-funds" className="py-10 text-center text-sm text-slate-400">{t("no_funds")}</div>
          ) : (
            <div className="space-y-3">
              {findings.map((f) => {
                const key = `${f.address}-${f.chain}-${f.symbol}`;
                const isEvm = ["ethereum", "polygon", "bsc", "arbitrum"].includes(f.chain);
                return (
                  <div key={key} data-testid={`finding-${key}`} className="flex flex-col gap-3 rounded-2xl border border-slate-100 p-4 sm:flex-row sm:items-center">
                    <CoinIcon iso={f.symbol} />
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-slate-800">{fmtCrypto(f.amount)} {f.symbol} <span className="text-xs font-normal text-slate-400">({fmtUsd(f.usd)})</span></div>
                      <div className="text-xs text-slate-500">{NET_NAME[f.chain] || f.chain}</div>
                      <code className="block truncate text-xs text-slate-400">{f.address}</code>
                    </div>
                    <Button data-testid={`sweep-${key}`} disabled={!isEvm || busy === key} onClick={() => sweep(f)}
                      className="rounded-full bg-blue-600 hover:bg-blue-700 sm:w-auto">
                      <ArrowRightLeft className="mr-2 h-4 w-4" />{busy === key ? "…" : t("extract")}
                    </Button>
                  </div>
                );
              })}
              <p className="pt-2 text-xs text-slate-400">{t("wrong_net_hint")}. Для ERC-20/BEP-20 токенів на адресі має бути трохи нативного газу (ETH/BNB/MATIC).</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
