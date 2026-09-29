import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Eye, EyeOff, RefreshCw, Check, Shield, ShieldCheck, Network as NetIcon, Coins, KeyRound, Users as UsersIcon, Flame, Trash2, Plus, Send } from "lucide-react";
import api, { apiErr } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useLang } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CoinIcon } from "@/components/common";

const FEE_COINS = ["USDT", "USDC", "BTC", "ETH", "BNB", "TRX", "SOL", "LTC"];

const COLORS = ["#94A3B8", "#1E3A5F", "#3B82F6", "#14B8A6", "#84CC16", "#2563EB",
  "#A855F7", "#EF4444", "#F87171", "#F59E0B", "#EAB308", "#92400E"];

export default function Settings() {
  const { t } = useLang();
  const { user, checkAuth } = useAuth();
  const [m, setM] = useState(null);
  const [showSecret, setShowSecret] = useState(false);
  const isAdmin = user?.role === "admin";

  useEffect(() => { api.get("/merchant").then((r) => setM(r.data.data)).catch(() => {}); }, []);
  if (!m) return <div className="text-slate-400">…</div>;

  const save = async () => {
    try {
      const { data } = await api.put("/merchant", {
        name: m.name, home_url: m.home_url, result_url: m.result_url,
        brand_color: m.brand_color, description: m.description,
        auto_swap: !!m.auto_swap, auto_swap_to: m.auto_swap_to || "USDT",
        fees: m.fees || {},
      });
      setM(data.data); toast.success(t("saved"));
    } catch (e) { toast.error(apiErr(e)); }
  };
  const regen = async () => {
    try { const { data } = await api.post("/merchant/regenerate"); setM(data.data); toast.success(t("regenerate")); }
    catch (e) { toast.error(apiErr(e)); }
  };
  const testWebhook = async () => {
    if (!m.result_url) { toast.error("Спочатку вкажіть URL сповіщень та збережіть"); return; }
    try {
      const { data } = await api.post("/merchant/test-webhook");
      const d = data.data || {};
      if (d.delivered) toast.success(`Вебхук доставлено ✓ HTTP ${d.http_status}`);
      else toast.error(`Не доставлено: ${d.error || ("HTTP " + d.http_status)}`);
    } catch (e) { toast.error(apiErr(e)); }
  };
  const copy = (v) => { navigator.clipboard.writeText(v); toast.success(t("copied")); };

  const setFee = (iso, key, val) => {
    const fees = { ...(m.fees || {}) };
    fees[iso] = { ...(fees[iso] || {}), [key]: val === "" ? "" : Number(val) };
    setM({ ...m, fees });
  };
  const feeVal = (iso, key) => {
    const v = m.fees?.[iso]?.[key];
    return v === undefined || v === null ? "" : v;
  };

  return (
    <div className="space-y-6 oki-fade-up">
      <h1 className="text-2xl font-bold text-slate-900">{t("settings")}</h1>
      <div className="rounded-3xl bg-white p-6 shadow-sm border border-slate-100">
        <Tabs defaultValue="profile">
          <TabsList className="rounded-xl flex-wrap h-auto">
            <TabsTrigger value="profile" data-testid="tab-profile">{t("profile")}</TabsTrigger>
            <TabsTrigger value="merchant" data-testid="tab-merchant">{t("merchant")}</TabsTrigger>
            {isAdmin && <TabsTrigger value="fees" data-testid="tab-fees">{t("fees")}</TabsTrigger>}
            <TabsTrigger value="security" data-testid="tab-security"><Shield className="mr-1 h-4 w-4" />Безпека</TabsTrigger>
            {isAdmin && <TabsTrigger value="platform" data-testid="tab-platform" className="bg-emerald-50 data-[state=active]:bg-emerald-100"><Coins className="mr-1 h-4 w-4" />Платформа</TabsTrigger>}
            {isAdmin && <TabsTrigger value="networks" data-testid="tab-networks" className="bg-emerald-50 data-[state=active]:bg-emerald-100"><NetIcon className="mr-1 h-4 w-4" />Мережі</TabsTrigger>}
            {isAdmin && <TabsTrigger value="users" data-testid="tab-users" className="bg-violet-50 data-[state=active]:bg-violet-100"><UsersIcon className="mr-1 h-4 w-4" />Користувачі</TabsTrigger>}
            {isAdmin && <TabsTrigger value="hotwallet" data-testid="tab-hotwallet" className="bg-fuchsia-50 data-[state=active]:bg-fuchsia-100"><Flame className="mr-1 h-4 w-4" />Гарячий гаманець</TabsTrigger>}
          </TabsList>

          <TabsContent value="profile" className="pt-6">
            <div className="max-w-md space-y-4">
              <div><Label>{t("name")}</Label><Input value={user?.name || ""} disabled className="rounded-xl mt-1 bg-slate-50" /></div>
              <div><Label>{t("email")}</Label><Input value={user?.email || ""} disabled className="rounded-xl mt-1 bg-slate-50" /></div>
              <div className="text-xs text-slate-400">Провайдер входу: {user?.auth_provider || "password"}</div>
            </div>
          </TabsContent>

          <TabsContent value="merchant" className="pt-6">
            <div className="grid gap-8 lg:grid-cols-2">
              <div className="space-y-6">
                <div>
                  <div className="mb-3 text-lg font-bold text-slate-900">{t("merchant_info")}</div>
                  <div className="space-y-3">
                    <div><Label>{t("title")} *</Label><Input data-testid="merchant-name" value={m.name || ""} onChange={(e) => setM({ ...m, name: e.target.value })} className="rounded-xl mt-1" /></div>
                    <div><Label>{t("home_url")}</Label><Input data-testid="merchant-home" value={m.home_url || ""} onChange={(e) => setM({ ...m, home_url: e.target.value })} className="rounded-xl mt-1" placeholder="https://www.example.io" /></div>
                  </div>
                </div>
                <div>
                  <div className="mb-3 text-lg font-bold text-slate-900">{t("api_settings")}</div>
                  <div className="mb-2 text-xs text-slate-400">{t("api_key_note")}</div>
                  <div className="space-y-3">
                    <div><Label>{t("result_url")}</Label>
                      <Input data-testid="merchant-result-url" value={m.result_url || ""} onChange={(e) => setM({ ...m, result_url: e.target.value })} className="rounded-xl mt-1" placeholder="https://site.com/webhook" />
                      <div className="mt-2">
                        <Button size="sm" variant="outline" data-testid="test-webhook-btn" onClick={testWebhook} className="rounded-full border-slate-300">Надіслати тестовий вебхук</Button>
                        <p className="text-[11px] text-slate-400 mt-1">Надішле підписаний тестовий POST (X-Auth-Token + X-Auth-Sign) на цей URL, щоб перевірити прийом сповіщень.</p>
                      </div>
                    </div>
                    <div><Label>{t("token")}</Label>
                      <div className="mt-1 flex items-center gap-2 rounded-xl border border-slate-200 p-2">
                        <code data-testid="merchant-token" className="flex-1 truncate text-xs">{m.token}</code>
                        <Button size="sm" variant="ghost" data-testid="copy-token" onClick={() => copy(m.token)}><Copy className="mr-1 h-3.5 w-3.5" />{t("copy")}</Button>
                      </div>
                    </div>
                    <div><Label>{t("secret")}</Label>
                      <div className="mt-1 flex items-center gap-2 rounded-xl border border-slate-200 p-2">
                        <code data-testid="merchant-secret" className="flex-1 truncate text-xs">{showSecret ? m.secret : "•".repeat(40)}</code>
                        <Button size="icon" variant="ghost" data-testid="toggle-secret" onClick={() => setShowSecret(!showSecret)}>{showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</Button>
                        <Button size="icon" variant="ghost" data-testid="copy-secret" onClick={() => copy(m.secret)}><Copy className="h-4 w-4" /></Button>
                      </div>
                    </div>
                    <Button data-testid="regen-btn" variant="outline" onClick={regen} className="rounded-full border-slate-300"><RefreshCw className="mr-2 h-4 w-4" />{t("regenerate")}</Button>
                  </div>
                </div>
              </div>

              <div>
                <div className="mb-3 text-lg font-bold text-slate-900">{t("branding")}</div>
                <Label>{t("color")}</Label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COLORS.map((c) => (
                    <button key={c} data-testid={`color-${c}`} onClick={() => setM({ ...m, brand_color: c })}
                      className="flex h-9 w-9 items-center justify-center rounded-full border-2 transition"
                      style={{ background: c, borderColor: m.brand_color === c ? "#0f172a" : "transparent" }}>
                      {m.brand_color === c && <Check className="h-4 w-4 text-white" />}
                    </button>
                  ))}
                </div>
                <div className="mt-6"><Label>{t("description")}</Label>
                  <Textarea data-testid="merchant-desc" value={m.description || ""} onChange={(e) => setM({ ...m, description: e.target.value })} className="rounded-xl mt-1" rows={4} placeholder="Зробіть назву вашого бізнесу зрозумілою для клієнтів" /></div>

                <div className="mt-8">
                  <div className="mb-3 text-lg font-bold text-slate-900">{t("auto_conv")}</div>
                  <div className="flex items-start justify-between rounded-2xl border border-slate-100 p-4">
                    <div className="pr-4">
                      <div className="font-semibold text-slate-800">{t("auto_swap")}</div>
                      <div className="text-xs text-slate-400">{t("auto_swap_desc")}</div>
                    </div>
                    <Switch data-testid="auto-swap-toggle" checked={!!m.auto_swap} onCheckedChange={(v) => setM({ ...m, auto_swap: v })} />
                  </div>
                  {m.auto_swap && (
                    <div className="mt-3 max-w-[220px]"><Label>{t("convert_to")}</Label>
                      <Select value={m.auto_swap_to || "USDT"} onValueChange={(v) => setM({ ...m, auto_swap_to: v })}>
                        <SelectTrigger data-testid="auto-swap-to" className="rounded-xl mt-1"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-white border border-slate-200">{["USDT", "USDC", "ETH", "BNB"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="mt-8 flex justify-end">
              <Button data-testid="save-merchant" onClick={save} className="rounded-full bg-blue-600 hover:bg-blue-700 px-8">{t("save")}</Button>
            </div>
          </TabsContent>

          {isAdmin && (
          <TabsContent value="fees" className="pt-6">
            <div className="mb-4 max-w-2xl text-sm text-slate-500">{t("fees_desc")}</div>
            <div className="oki-scroll overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-400">
                    <th className="py-2">{t("currency")}</th>
                    <th className="text-center" colSpan={2}>{t("fee_in")}</th>
                    <th className="text-center" colSpan={2}>{t("fee_out")}</th>
                  </tr>
                  <tr className="text-left text-[11px] text-slate-300">
                    <th></th><th className="font-normal">{t("fee_pct")}</th><th className="font-normal">{t("fee_fixed")}</th>
                    <th className="font-normal">{t("fee_pct")}</th><th className="font-normal">{t("fee_fixed")}</th>
                  </tr>
                </thead>
                <tbody>
                  {FEE_COINS.map((iso) => (
                    <tr key={iso} data-testid={`fee-row-${iso}`} className="border-t border-slate-100">
                      <td className="py-2.5"><div className="flex items-center gap-2"><CoinIcon iso={iso} size={28} /><span className="font-semibold text-slate-700">{iso}</span></div></td>
                      <td className="pr-2"><Input data-testid={`fee-${iso}-in-pct`} type="number" step="0.01" value={feeVal(iso, "in_percent")} onChange={(e) => setFee(iso, "in_percent", e.target.value)} className="h-9 w-20 rounded-lg" placeholder="0" /></td>
                      <td className="pr-2"><Input data-testid={`fee-${iso}-in-fix`} type="number" step="0.0001" value={feeVal(iso, "in_fixed")} onChange={(e) => setFee(iso, "in_fixed", e.target.value)} className="h-9 w-24 rounded-lg" placeholder="0" /></td>
                      <td className="pr-2"><Input data-testid={`fee-${iso}-out-pct`} type="number" step="0.01" value={feeVal(iso, "out_percent")} onChange={(e) => setFee(iso, "out_percent", e.target.value)} className="h-9 w-20 rounded-lg" placeholder="0" /></td>
                      <td><Input data-testid={`fee-${iso}-out-fix`} type="number" step="0.0001" value={feeVal(iso, "out_fixed")} onChange={(e) => setFee(iso, "out_fixed", e.target.value)} className="h-9 w-24 rounded-lg" placeholder="0" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-8 flex justify-end">
              <Button data-testid="save-fees" onClick={save} className="rounded-full bg-blue-600 hover:bg-blue-700 px-8">{t("save")}</Button>
            </div>
          </TabsContent>
          )}
          <TabsContent value="security" className="pt-6">
            <SecurityTab onChanged={checkAuth} />
          </TabsContent>

          {isAdmin && (
            <TabsContent value="platform" className="pt-6">
              <PlatformTab user={user} />
            </TabsContent>
          )}
          {isAdmin && (
            <TabsContent value="networks" className="pt-6">
              <NetworksTab user={user} />
            </TabsContent>
          )}
          {isAdmin && (
            <TabsContent value="users" className="pt-6">
              <UsersTab admin={user} />
            </TabsContent>
          )}
          {isAdmin && (
            <TabsContent value="hotwallet" className="pt-6">
              <HotWalletTab user={user} />
            </TabsContent>
          )}
        </Tabs>
      </div>
    </div>
  );
}

// ---------------------- Security (2FA) Tab ----------------------
function SecurityTab({ onChanged }) {
  const { user } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [setupData, setSetupData] = useState(null);
  const [otp, setOtp] = useState("");
  const [disableOtp, setDisableOtp] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.get("/security/2fa/status")
      .then((r) => setEnabled(!!r.data?.data?.enabled))
      .catch(() => {});
  }, []);

  const startSetup = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/security/2fa/setup");
      setSetupData(data.data);
    } catch (e) { toast.error(apiErr(e)); } finally { setLoading(false); }
  };
  const enable = async () => {
    try {
      await api.post("/security/2fa/enable", { otp });
      toast.success("2FA увімкнено!");
      setSetupData(null); setOtp(""); setEnabled(true);
      onChanged && onChanged();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const disable = async () => {
    try {
      await api.post("/security/2fa/disable", { otp: disableOtp });
      toast.success("2FA вимкнено");
      setDisableOtp(""); setEnabled(false);
      onChanged && onChanged();
    } catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="max-w-2xl space-y-4">
      <div className="rounded-2xl border border-slate-100 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className={"w-12 h-12 rounded-xl flex items-center justify-center " + (enabled ? "bg-emerald-100 text-emerald-600" : "bg-orange-100 text-orange-600")}>
            {enabled ? <ShieldCheck className="w-6 h-6" /> : <KeyRound className="w-6 h-6" />}
          </div>
          <div>
            <div className="text-lg font-bold text-slate-900">Google Authenticator (2FA)</div>
            <div className="text-sm text-slate-500">
              {enabled ? "Активна — вхід та критичні дії захищені кодом" : "Не увімкнена — рекомендуємо активувати"}
            </div>
          </div>
          {enabled ? <Badge className="ml-auto bg-emerald-600">УВІМКНЕНА</Badge> : <Badge variant="secondary" className="ml-auto">ВИМКНЕНА</Badge>}
        </div>
        <div className="text-sm text-slate-600 mb-4">
          Двофакторна автентифікація (TOTP) додає додатковий рівень безпеки: після пароля вам треба ввести 6-значний код з застосунку Google Authenticator (або Authy, 1Password).
        </div>

        {!enabled && !setupData && (
          <Button data-testid="2fa-start-btn" onClick={startSetup} disabled={loading}>{loading ? "Генерація…" : "Увімкнути 2FA"}</Button>
        )}

        {!enabled && setupData && (
          <div className="space-y-4">
            <div className="flex flex-col md:flex-row gap-6">
              <img src={setupData.qr_data_url} alt="QR" className="w-48 h-48 border rounded-lg bg-white" />
              <div className="flex-1 space-y-2 text-sm">
                <div className="font-semibold">Кроки:</div>
                <div>1. Відкрийте Google Authenticator</div>
                <div>2. Натисніть "+" → "Сканувати QR-код" → скануйте</div>
                <div>3. Або введіть секрет вручну:</div>
                <div className="font-mono text-xs bg-slate-100 p-2 rounded break-all select-all">{setupData.secret}</div>
                <div>4. Введіть 6-значний код з застосунку нижче:</div>
              </div>
            </div>
            <div className="flex gap-2">
              <Input data-testid="2fa-code" value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="123 456" inputMode="numeric" maxLength={6} className="max-w-xs rounded-xl tracking-widest text-center" />
              <Button data-testid="2fa-enable-btn" onClick={enable}>Підтвердити і увімкнути</Button>
            </div>
          </div>
        )}

        {enabled && (
          <div className="space-y-3">
            <Label>Введіть поточний код для вимкнення 2FA</Label>
            <div className="flex gap-2">
              <Input data-testid="2fa-disable-code" value={disableOtp} onChange={(e) => setDisableOtp(e.target.value)} placeholder="6 цифр" inputMode="numeric" maxLength={6} className="max-w-xs rounded-xl tracking-widest text-center" />
              <Button data-testid="2fa-disable-btn" variant="destructive" onClick={disable}>Вимкнути 2FA</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------- Platform Fees Tab (superadmin only) ----------------------
function PlatformTab({ user }) {
  const [pf, setPf] = useState(null);
  const [otp, setOtp] = useState("");
  const [treasury, setTreasury] = useState(null);
  const [labels, setLabels] = useState({});
  const [addrs, setAddrs] = useState({});
  const [pool, setPool] = useState([]);
  const [poolOtp, setPoolOtp] = useState("");

  const loadAll = () => {
    api.get("/admin/platform-fees").then((r) => setPf(r.data.data)).catch((e) => toast.error(apiErr(e)));
    api.get("/admin/treasury-addresses").then((r) => {
      setTreasury(r.data.data);
      setLabels(r.data.data.labels);
      setAddrs(r.data.data.addresses || {});
    }).catch(() => {});
    api.get("/admin/pool").then((r) => setPool(r.data.data)).catch(() => {});
  };
  useEffect(() => { loadAll(); }, []);
  if (!pf || !treasury) return <div className="text-slate-400">…</div>;

  const save = async () => {
    try {
      const { data } = await api.put("/admin/platform-fees", {
        deposit_fee: Number(pf.deposit_fee),
        deposit_fee_by_iso: Object.fromEntries(
          Object.entries(pf.deposit_fee_by_iso || {}).map(([k, v]) => [k, Number(v)])
        ),
        swap_fee_by_iso: Object.fromEntries(
          Object.entries(pf.swap_fee_by_iso || {}).map(([k, v]) => [k, Number(v)])
        ),
        withdrawal_fee_cabinet: Number(pf.withdrawal_fee_cabinet),
        withdrawal_fee_api: Number(pf.withdrawal_fee_api),
        withdrawal_fee_by_key: Object.fromEntries(
          (pf.withdrawal_fee_matrix || []).map((m) => [m.key, { cabinet: Number(m.cabinet) || 0, api: Number(m.api) || 0 }])
        ),
        otp: otp || undefined,
      });
      setPf(data.data); setOtp("");
      toast.success("Комісії платформи оновлено");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const saveTreasury = async () => {
    try {
      const { data } = await api.put("/admin/treasury-addresses", { addresses: addrs, otp: otp || undefined });
      setAddrs(data.data);
      toast.success("Treasury-адреси збережено");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const withdrawPool = async (key) => {
    try {
      const { data } = await api.post("/admin/pool/withdraw", { key, otp: poolOtp || undefined });
      toast.success(`Заявку створено: ${data.data.amount} ${data.data.iso} → ${data.data.chain}`);
      setPoolOtp("");
      loadAll();
    } catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50/60 to-transparent p-5">
        <div className="text-sm text-emerald-800 font-semibold mb-1">👑 Тільки для суперадміністратора FozPay</div>
        <div className="text-xs text-slate-600">Ці комісії застосовуються глобально до всіх мерчантів/користувачів платформи. Джерело доходу.</div>
      </div>

      {/* Fees */}
      <div className="rounded-2xl border border-slate-100 p-5 space-y-4">
        <div className="text-lg font-bold text-slate-900">Комісії</div>
        <div>
          <Label className="text-slate-700 font-semibold">Комісія на вхід (депозит) — окремо для кожної валюти</Label>
          <p className="text-xs text-slate-400 mt-1 mb-3">Комісія списується з вхідної суми в одиницях самої валюти. Приклад: якщо для USDT задано 0.5 і відправник надіслав 10 USDT, одержувачу зараховується 9.5 USDT, а 0.5 йде в пул платформи.</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.keys(pf.deposit_fee_by_iso || {}).map((iso) => (
              <div key={iso}>
                <Label className="text-xs font-semibold text-slate-600">{iso}</Label>
                <Input
                  data-testid={`pf-deposit-${iso}`}
                  type="number"
                  step="any"
                  min="0"
                  value={pf.deposit_fee_by_iso[iso]}
                  onChange={(e) => setPf({ ...pf, deposit_fee_by_iso: { ...pf.deposit_fee_by_iso, [iso]: e.target.value } })}
                  className="rounded-xl mt-1"
                />
              </div>
            ))}
          </div>
        </div>
        <div>
          <Label className="text-slate-700 font-semibold">Комісія при свопі (обміні) — окремо для кожної валюти, у %</Label>
          <p className="text-xs text-slate-400 mt-1 mb-3">Відсоток списується з валюти-джерела при обміні. Приклад: при 0.4% обмін 100 USDT → ETH утримає 0.4 USDT-еквіваленту комісії платформи.</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.keys(pf.swap_fee_by_iso || {}).map((iso) => (
              <div key={iso}>
                <Label className="text-xs font-semibold text-slate-600">{iso} (%)</Label>
                <Input
                  data-testid={`pf-swap-${iso}`}
                  type="number"
                  step="any"
                  min="0"
                  max="100"
                  value={pf.swap_fee_by_iso[iso]}
                  onChange={(e) => setPf({ ...pf, swap_fee_by_iso: { ...pf.swap_fee_by_iso, [iso]: e.target.value } })}
                  className="rounded-xl mt-1"
                />
              </div>
            ))}
          </div>
        </div>
        <div>
          <Label className="text-slate-700 font-semibold">Комісія на вивід (з особистого кабінету)</Label>
          <Input data-testid="pf-wd-cab" type="number" step="0.01" value={pf.withdrawal_fee_cabinet} onChange={(e) => setPf({ ...pf, withdrawal_fee_cabinet: e.target.value })} className="rounded-xl mt-1 max-w-xs" />
        </div>
        <div>
          <Label className="text-slate-700 font-semibold">Комісія на вивід через API</Label>
          <Input data-testid="pf-wd-api" type="number" step="0.01" value={pf.withdrawal_fee_api} onChange={(e) => setPf({ ...pf, withdrawal_fee_api: e.target.value })} className="rounded-xl mt-1 max-w-xs" />
        </div>
        <div>
          <Label className="text-slate-700 font-semibold">Комісія на вивід — окремо для кожної валюти та мережі</Label>
          <p className="text-xs text-slate-400 mt-1 mb-3">Індивідуальна комісія на вивід для кожної пари «валюта + мережа». «Кабінет» — вивід із особистого кабінету, «API» — вивід через merchant API. Значення успадковують глобальні поля вище, доки не зміните їх тут.</p>
          <div className="oki-scroll overflow-x-auto rounded-xl border border-slate-100">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400 bg-slate-50">
                <th className="py-2 px-3">Валюта</th><th>Мережа</th><th>Комісія (кабінет)</th><th>Комісія (API)</th>
              </tr></thead>
              <tbody>
                {(pf.withdrawal_fee_matrix || []).map((m, i) => (
                  <tr key={m.key} data-testid={`pf-wd-row-${m.key}`} className="border-t border-slate-100">
                    <td className="py-2 px-3 font-semibold text-slate-700">{m.iso}</td>
                    <td className="text-slate-500">{m.network_name} ({m.network_iso})</td>
                    <td className="pr-2">
                      <Input data-testid={`pf-wd-cab-${m.key}`} type="number" step="any" min="0" value={m.cabinet}
                        onChange={(e) => { const mx = [...pf.withdrawal_fee_matrix]; mx[i] = { ...mx[i], cabinet: e.target.value }; setPf({ ...pf, withdrawal_fee_matrix: mx }); }}
                        className="h-9 w-28 rounded-lg" />
                    </td>
                    <td className="pr-2">
                      <Input data-testid={`pf-wd-api-${m.key}`} type="number" step="any" min="0" value={m.api}
                        onChange={(e) => { const mx = [...pf.withdrawal_fee_matrix]; mx[i] = { ...mx[i], api: e.target.value }; setPf({ ...pf, withdrawal_fee_matrix: mx }); }}
                        className="h-9 w-28 rounded-lg" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {user?.two_fa?.enabled && (
          <div>
            <Label className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" /> Код 2FA</Label>
            <Input data-testid="pf-otp" value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="123 456" className="rounded-xl mt-1 max-w-xs" inputMode="numeric" maxLength={6} />
          </div>
        )}
        <div className="flex justify-end">
          <Button data-testid="pf-save" onClick={save} className="rounded-full bg-emerald-600 hover:bg-emerald-700 px-8">Зберегти комісії</Button>
        </div>
      </div>

      {/* Treasury addresses per chain */}
      <div className="rounded-2xl border border-slate-100 p-5 space-y-4">
        <div>
          <div className="text-lg font-bold text-slate-900">🏦 Гаманці для отримання комісій (по мережах)</div>
          <div className="text-sm text-slate-500 mt-1">Комісії платформи в кожній мережі накопичуються та виводяться на відповідну вашу адресу.</div>
        </div>
        <div className="grid md:grid-cols-2 gap-3">
          {Object.entries(labels).map(([chain, label]) => (
            <div key={chain} className="rounded-xl bg-slate-50 border border-slate-100 p-3">
              <Label className="text-xs text-slate-500">{label}</Label>
              <Input
                data-testid={`treasury-${chain}`}
                value={addrs[chain] || ""}
                onChange={(e) => setAddrs({ ...addrs, [chain]: e.target.value })}
                placeholder={chain === "tron" ? "T..." : chain === "bitcoin" ? "bc1... / 1... / 3..." : chain === "litecoin" ? "ltc1... / L... / M..." : chain === "solana" ? "Solana address" : "0x..."}
                className="rounded-lg mt-1 font-mono text-xs"
              />
            </div>
          ))}
        </div>
        <div className="flex justify-end">
          <Button data-testid="treasury-save" onClick={saveTreasury} className="rounded-full">Зберегти адреси</Button>
        </div>
      </div>

      {/* Pool */}
      <div className="rounded-2xl border border-emerald-100 p-5 space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-lg font-bold text-slate-900">💵 Пул платформи (доступно до виводу)</div>
            <div className="text-sm text-slate-500 mt-1">Комісії, накопичені по кожній валюті та мережі. Натисніть "Вивести" щоб надіслати на відповідну treasury-адресу.</div>
          </div>
          {user?.two_fa?.enabled && pool.length > 0 && (
            <div className="max-w-[160px]">
              <Label className="text-xs">2FA код</Label>
              <Input data-testid="pool-otp" value={poolOtp} onChange={(e) => setPoolOtp(e.target.value)} placeholder="123 456" className="rounded-lg mt-1" inputMode="numeric" maxLength={6} />
            </div>
          )}
        </div>
        {pool.length === 0 ? (
          <div className="text-sm text-slate-400 py-4">Ще нічого не накопичено. Комісії з'являться після перших транзакцій.</div>
        ) : (
          <div className="space-y-2">
            {pool.map((row) => (
              <div key={row.key} className="flex items-center justify-between rounded-xl border border-slate-100 p-3 hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <CoinIcon iso={row.iso} size={30} />
                  <div>
                    <div className="font-semibold text-slate-900">{row.amount.toFixed(6)} {row.iso}</div>
                    <div className="text-xs text-slate-500">{row.network_name} · {row.chain}</div>
                    {row.treasury_address ? (
                      <div className="text-[10px] text-slate-400 font-mono mt-1">→ {row.treasury_address}</div>
                    ) : (
                      <div className="text-[11px] text-orange-600 mt-1">⚠️ Не задано treasury для {row.chain}</div>
                    )}
                  </div>
                </div>
                <Button
                  data-testid={`pool-wd-${row.key}`}
                  onClick={() => withdrawPool(row.key)}
                  disabled={!row.withdrawable}
                  className="rounded-full bg-emerald-600 hover:bg-emerald-700"
                >
                  Вивести
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------- Networks Tab (superadmin only) ----------------------
function NetworksTab({ user }) {
  const [nets, setNets] = useState([]);
  const [otp, setOtp] = useState("");
  const load = () => api.get("/admin/networks").then((r) => setNets(r.data.data)).catch((e) => toast.error(apiErr(e)));
  useEffect(() => { load(); }, []);
  const toggle = async (n, val) => {
    try {
      await api.put("/admin/networks", { network_id: n.network_id, enabled: val, otp: otp || undefined });
      toast.success(`${n.name}: ${val ? "увімкнено" : "вимкнено"}`);
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  return (
    <div className="space-y-4 max-w-3xl">
      <div className="rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50/60 to-transparent p-5">
        <div className="text-sm text-emerald-800 font-semibold mb-1">👑 Керування платіжними мережами</div>
        <div className="text-xs text-slate-600">Вимкнення тумблера миттєво зупиняє прийом та вивід коштів у відповідній мережі на всій платформі.</div>
      </div>
      {user?.two_fa?.enabled && (
        <div className="rounded-2xl border border-slate-100 p-3">
          <Label className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" /> Код 2FA для змін</Label>
          <Input data-testid="net-otp" value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="123 456" className="rounded-xl mt-1 max-w-xs" inputMode="numeric" maxLength={6} />
        </div>
      )}
      <div className="space-y-2">
        {nets.map((n) => (
          <div key={n.network_id} data-testid={`net-row-${n.network_id}`} className="flex items-center justify-between rounded-2xl border border-slate-100 p-4 hover:bg-slate-50">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-slate-100 flex items-center justify-center text-xs font-bold text-slate-700">{n.iso}</div>
              <div>
                <div className="font-semibold text-slate-900">{n.name}</div>
                <div className="text-xs text-slate-500 capitalize">{n.chain}</div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant={n.enabled ? "default" : "secondary"} className={n.enabled ? "bg-emerald-600" : ""}>{n.enabled ? "Активна" : "Вимкнена"}</Badge>
              <Switch data-testid={`net-toggle-${n.network_id}`} checked={!!n.enabled} onCheckedChange={(v) => toggle(n, v)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------- Users management (admin only) ----------------------
function UsersTab({ admin }) {
  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [pwEdit, setPwEdit] = useState({});
  const load = () => api.get("/admin/users").then((r) => setUsers(r.data.data)).catch((e) => toast.error(apiErr(e)));
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api.post("/admin/users", { email, name, password });
      toast.success("Користувача створено");
      setEmail(""); setName(""); setPassword(""); load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const changePw = async (uid) => {
    const pw = pwEdit[uid];
    if (!pw) return;
    try {
      await api.put("/admin/users/password", { user_id: uid, password: pw });
      toast.success("Пароль оновлено");
      setPwEdit({ ...pwEdit, [uid]: "" });
    } catch (e) { toast.error(apiErr(e)); }
  };
  const del = async (uid) => {
    try { await api.delete(`/admin/users/${uid}`); toast.success("Видалено"); load(); }
    catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50/70 to-transparent p-5">
        <div className="text-sm text-violet-800 font-semibold mb-1">👥 Керування користувачами</div>
        <div className="text-xs text-slate-600">Реєстрація закрита для публіки. Тут ви створюєте акаунти користувачів та змінюєте їхні паролі.</div>
      </div>

      <div className="rounded-2xl border border-slate-100 p-5">
        <div className="text-lg font-bold text-slate-900 mb-3">Створити нового користувача</div>
        <div className="grid gap-3 sm:grid-cols-4">
          <div><Label>Ім'я</Label><Input data-testid="new-user-name" value={name} onChange={(e) => setName(e.target.value)} className="rounded-xl mt-1" placeholder="Ivan" /></div>
          <div><Label>Email</Label><Input data-testid="new-user-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="rounded-xl mt-1" placeholder="user@mail.com" /></div>
          <div><Label>Пароль</Label><Input data-testid="new-user-password" value={password} onChange={(e) => setPassword(e.target.value)} className="rounded-xl mt-1" placeholder="••••••" /></div>
          <div className="flex items-end"><Button data-testid="create-user-btn" onClick={create} disabled={!email || !password} className="w-full rounded-full bg-violet-600 hover:bg-violet-700"><Plus className="mr-1 h-4 w-4" />Створити</Button></div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-100 p-5">
        <div className="text-lg font-bold text-slate-900 mb-3">Усі користувачі ({users.length})</div>
        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.user_id} data-testid={`user-row-${u.user_id}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-100 p-3 hover:bg-white/50">
              <div className="flex-1 min-w-[180px]">
                <div className="font-semibold text-slate-900 flex items-center gap-2">
                  {u.name || u.email}
                  {u.role === "admin" && <Badge className="bg-violet-600">admin</Badge>}
                </div>
                <div className="text-xs text-slate-500">{u.email} · {u.auth_provider || "password"}</div>
                <div data-testid={`user-balance-${u.user_id}`} className="mt-1 text-xs font-semibold text-emerald-700">
                  Баланс: ${Number(u.balance_usdt ?? 0).toFixed(2)} <span className="text-emerald-500">(за курсом USDT)</span>
                  {u.balances && u.balances.length > 0 && (
                    <span className="ml-2 font-normal text-slate-400">{u.balances.map((b) => `${b.balance} ${b.iso}`).join(" · ")}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input data-testid={`pw-input-${u.user_id}`} value={pwEdit[u.user_id] || ""} onChange={(e) => setPwEdit({ ...pwEdit, [u.user_id]: e.target.value })} placeholder="Новий пароль" className="h-9 w-40 rounded-lg" />
                <Button data-testid={`pw-save-${u.user_id}`} size="sm" onClick={() => changePw(u.user_id)} disabled={!pwEdit[u.user_id]} className="rounded-full bg-violet-600 hover:bg-violet-700"><KeyRound className="mr-1 h-3.5 w-3.5" />Змінити</Button>
                {u.user_id !== admin?.user_id && (
                  <Button data-testid={`user-del-${u.user_id}`} size="icon" variant="ghost" onClick={() => del(u.user_id)} className="text-rose-500"><Trash2 className="h-4 w-4" /></Button>
                )}
              </div>
            </div>
          ))}
          {users.length === 0 && <div className="py-6 text-center text-sm text-slate-400">Ще немає користувачів</div>}
        </div>
      </div>
    </div>
  );
}

// ---------------------- Hot wallet (admin only) ----------------------
function HotWalletTab({ user }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ chain: "ethereum", iso: "USDT", to_address: "", amount: "", otp: "" });
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api.get("/admin/hot-wallet")
      .then((r) => setData(r.data.data))
      .catch((e) => toast.error(apiErr(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const withdraw = async () => {
    setBusy(true);
    try {
      const { data: res } = await api.post("/admin/hot-wallet/withdraw", {
        chain: form.chain, iso: form.iso, to_address: form.to_address,
        amount: Number(form.amount), otp: form.otp || undefined,
      });
      toast.success(`Відправлено! TX: ${res.data.tx_hash.slice(0, 14)}…`);
      setForm({ ...form, amount: "", to_address: "" });
      setTimeout(load, 3000);
    } catch (e) { toast.error(apiErr(e)); } finally { setBusy(false); }
  };

  const copy = (v) => { navigator.clipboard.writeText(v); toast.success("Скопійовано"); };

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="rounded-2xl border border-fuchsia-100 bg-gradient-to-br from-fuchsia-50/70 via-violet-50/50 to-transparent p-5">
        <div className="flex items-center gap-2 text-sm text-fuchsia-800 font-semibold mb-1"><Flame className="h-4 w-4" /> Гарячий гаманець платформи</div>
        <div className="text-xs text-slate-600">Усі депозити автоматично зводяться сюди. Звідси проводяться виводи та своп. Комісії сервісу теж лишаються тут — ви можете вивести будь-яку валюту на потрібну адресу.</div>
      </div>

      {loading ? <div className="text-slate-400">Читаємо баланси on-chain…</div> : data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-100 p-4">
              <div className="text-xs text-slate-500">EVM адреса (ETH/BSC/Polygon/Arbitrum)</div>
              <div className="mt-1 flex items-center gap-2"><code className="flex-1 truncate text-xs">{data.evm_address}</code>
                <Button size="icon" variant="ghost" onClick={() => copy(data.evm_address)}><Copy className="h-4 w-4" /></Button></div>
            </div>
            <div className="rounded-2xl border border-slate-100 p-4">
              <div className="text-xs text-slate-500">TRON адреса</div>
              <div className="mt-1 flex items-center gap-2"><code className="flex-1 truncate text-xs">{data.tron_address}</code>
                <Button size="icon" variant="ghost" onClick={() => copy(data.tron_address)}><Copy className="h-4 w-4" /></Button></div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-100 p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-lg font-bold text-slate-900">Баланси on-chain <span className="text-sm text-slate-400 font-normal">≈ ${data.total_usd}</span></div>
              <Button size="sm" variant="outline" onClick={load} className="rounded-full"><RefreshCw className="mr-1 h-3.5 w-3.5" />Оновити</Button>
            </div>
            <div className="space-y-2">
              {(data.balances || []).map((b, i) => (
                <div key={i} data-testid={`hot-bal-${b.symbol}-${b.chain}`} className="flex items-center justify-between rounded-xl border border-slate-100 p-3">
                  <div className="flex items-center gap-3">
                    <CoinIcon iso={b.symbol} size={30} />
                    <div>
                      <div className="font-semibold text-slate-900">{Number(b.amount).toLocaleString("en-US", { maximumFractionDigits: 8 })} {b.symbol}</div>
                      <div className="text-xs text-slate-500 capitalize">{b.chain} · {b.kind}</div>
                    </div>
                  </div>
                  <div className="text-sm text-slate-500">${b.usd}</div>
                </div>
              ))}
              {(data.balances || []).length === 0 && <div className="py-6 text-center text-sm text-slate-400">Гаманець порожній (кошти з'являться після депозитів).</div>}
            </div>
          </div>

          <div className="rounded-2xl border border-fuchsia-100 p-5 space-y-3">
            <div className="text-lg font-bold text-slate-900 flex items-center gap-2"><Send className="h-4 w-4 text-fuchsia-600" />Вивести з гарячого гаманця</div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label>Мережа</Label>
                <Select value={form.chain} onValueChange={(v) => setForm({ ...form, chain: v })}>
                  <SelectTrigger data-testid="hot-chain" className="rounded-xl mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-white border border-slate-200">
                    {["ethereum", "bsc", "polygon", "arbitrum"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Валюта</Label>
                <Select value={form.iso} onValueChange={(v) => setForm({ ...form, iso: v })}>
                  <SelectTrigger data-testid="hot-iso" className="rounded-xl mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-white border border-slate-200">
                    {["USDT", "USDC", "ETH", "BNB", "MATIC"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>Адреса отримувача</Label><Input data-testid="hot-to" value={form.to_address} onChange={(e) => setForm({ ...form, to_address: e.target.value })} className="rounded-xl mt-1 font-mono text-xs" placeholder="0x…" /></div>
            <div><Label>Сума</Label><Input data-testid="hot-amount" type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="rounded-xl mt-1" placeholder="0.00" /></div>
            {user?.two_fa?.enabled && (
              <div><Label className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" />Код 2FA</Label>
                <Input data-testid="hot-otp" value={form.otp} onChange={(e) => setForm({ ...form, otp: e.target.value })} className="rounded-xl mt-1 max-w-xs" placeholder="123 456" inputMode="numeric" maxLength={6} /></div>
            )}
            <div className="flex justify-end">
              <Button data-testid="hot-withdraw-btn" onClick={withdraw} disabled={busy || !form.to_address || !form.amount} className="rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-600 px-8 hover:opacity-95">
                {busy ? "Відправка…" : "Вивести кошти"}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
