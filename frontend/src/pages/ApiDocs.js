import React, { useEffect, useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { API } from "@/lib/api";

function Code({ children, lang = "bash" }) {
  return (
    <div className="group relative my-3 rounded-xl bg-slate-900 p-4">
      <button onClick={() => { navigator.clipboard.writeText(children); toast.success("Скопійовано"); }}
        className="absolute right-3 top-3 text-slate-400 opacity-0 transition group-hover:opacity-100">
        <Copy className="h-4 w-4" />
      </button>
      <pre className="oki-scroll overflow-x-auto text-xs leading-relaxed text-slate-100"><code className={`language-${lang}`}>{children}</code></pre>
    </div>
  );
}

function Endpoint({ method, path, desc, children }) {
  const color = { GET: "bg-emerald-500", POST: "bg-blue-500" }[method] || "bg-slate-500";
  return (
    <div className="mb-8 scroll-mt-20">
      <div className="mb-2 flex items-center gap-3">
        <span className={`rounded-md px-2 py-0.5 text-xs font-bold text-white ${color}`}>{method}</span>
        <code className="text-sm font-semibold text-slate-800">{path}</code>
      </div>
      <p className="mb-2 text-sm text-slate-500">{desc}</p>
      {children}
    </div>
  );
}

export default function ApiDocs() {
  const [token, setToken] = useState("YOUR_TOKEN");
  const [secret, setSecret] = useState("YOUR_SECRET");
  const base = API;

  useEffect(() => {
    api.get("/merchant").then((r) => { setToken(r.data.data.token); setSecret(r.data.data.secret); }).catch(() => {});
  }, []);

  return (
    <div className="oki-fade-up mx-auto max-w-4xl space-y-6">
      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-100">
        <h1 className="text-3xl font-extrabold text-slate-900">FozPay API</h1>
        <p className="mt-1 text-slate-500">v0.1.1 · Прийом та обмін криптовалют через REST API. Нижче — приклади з вашими реальними ключами.</p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-slate-50 p-3"><div className="text-xs text-slate-400">Base URL</div><code className="text-xs">{base}</code></div>
          <div className="rounded-xl bg-slate-50 p-3"><div className="text-xs text-slate-400">X-Auth-Token</div><code className="text-xs break-all">{token}</code></div>
        </div>

        <h2 className="mt-8 text-xl font-bold text-slate-900">Підпис запиту (X-Auth-Sign)</h2>
        <p className="mt-1 text-sm text-slate-500">Відсортуйте ключі тіла запиту за абеткою (рекурсивно), об'єднайте всі значення в один рядок (булеве → <code>true/false</code>, ціле число з плаваючою крапкою без дробової частини → без <code>.0</code>, <code>null</code> → порожньо), додайте <code>secret</code> у кінець та захешуйте через <code>sha256</code>.</p>
        <Code lang="python">{`import hashlib, time, requests

TOKEN = "${token}"
SECRET = "${secret}"

def _scalar(o):
    if isinstance(o, bool): return "true" if o else "false"
    if o is None: return ""
    if isinstance(o, float):
        return str(int(o)) if o == int(o) else repr(o)
    return str(o)

def make_sign(body):
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k in sorted(o): walk(o[k])
        elif isinstance(o, (list, tuple)):
            for i in o: walk(i)
        else: out.append(_scalar(o))
    walk(body)
    return hashlib.sha256(("".join(out) + SECRET).encode()).hexdigest()

body = {"request_id": int(time.time()), "currency": "USDT", "network": 1}
r = requests.post("${base}/v1/private/get-address", json=body,
    headers={"X-Auth-Token": TOKEN, "X-Auth-Sign": make_sign(body)})
print(r.json())`}</Code>
      </div>

      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-100">
        <h2 className="mb-6 text-xl font-bold text-slate-900">Public API</h2>
        <Endpoint method="GET" path="/api/v1/public/currency-list" desc="Список фіатних валют для інвойсів.">
          <Code>{`curl ${base}/v1/public/currency-list`}</Code>
        </Endpoint>
        <Endpoint method="GET" path="/api/v1/public/currency-network-list" desc="Список криптовалют та їх мереж.">
          <Code>{`curl ${base}/v1/public/currency-network-list`}</Code>
        </Endpoint>
      </div>

      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-100">
        <h2 className="mb-6 text-xl font-bold text-slate-900">Private API (потрібен підпис)</h2>

        <Endpoint method="GET" path="/api/v1/private/coins" desc="Доступні монети, мережі та комісії.">
          <Code>{`curl ${base}/v1/private/coins -H "X-Auth-Token: ${token}"`}</Code>
        </Endpoint>

        <Endpoint method="POST" path="/api/v1/private/get-address" desc="Отримати крипто-адресу для поповнення балансу.">
          <Code lang="json">{`{ "request_id": 1610097140, "currency": "BTC", "network": "Main" }`}</Code>
        </Endpoint>

        <Endpoint method="POST" path="/api/v1/order/create" desc="Створити інвойс (замовлення). Повертає посилання checkout.">
          <Code lang="json">{`{
  "request_id": 1610097140116,
  "order_id": 123,
  "payment_currency_iso": "USD",
  "price": 15,
  "include_commission": 1,
  "description": "Order #123",
  "currencies": [{ "iso": "USDT", "network": 1 }, { "iso": "BTC", "network": 0 }],
  "redirect_url": "https://my-site.com"
}`}</Code>
        </Endpoint>

        <Endpoint method="POST" path="/api/v1/order/get" desc="Отримати інформацію про інвойс за order_id.">
          <Code lang="json">{`{ "request_id": 1610097141, "order_id": 123 }`}</Code>
        </Endpoint>

        <Endpoint method="POST" path="/api/v1/merchant/pay-in" desc="Create Pay-in v2 — інвойс із готовою адресою та pay_info.">
          <Code lang="json">{`{
  "request_id": 1610097140,
  "description": "Description",
  "currency": "USDT",
  "network": "ETH",
  "amount": 0.134,
  "order_id": "20408",
  "redirect_url": "https://my-site.com"
}`}</Code>
        </Endpoint>

        <Endpoint method="POST" path="/api/v1/merchant/balance" desc="Баланс мерчанта за валютою.">
          <Code lang="json">{`{ "request_id": 1610097140, "currency": "USDT" }`}</Code>
        </Endpoint>
      </div>

      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-100">
        <h2 className="mb-4 text-xl font-bold text-slate-900">Webhook (Result URL)</h2>
        <p className="text-sm text-slate-500">При зміні статусу інвойсу (<code>Paid, Cancelled, Partially, Overpayment, Expired</code>) FozPay надсилає POST на ваш <b>Result URL</b>. Поверніть <code>{"{\"status\":\"done\"}"}</code> щоб перевести інвойс у <code>Completed</code>.</p>
        <Code lang="json">{`{
  "id": "1APW8SGN",
  "order_id": 123,
  "currency": "BTC",
  "payment_currency": "USD",
  "status": "Paid",
  "amount": 0.0001,
  "price": "15",
  "address": "BTCADDRESS",
  "network_type": "Main",
  "time_create": 1728036773,
  "time_done": 1728036900
}`}</Code>
      </div>
    </div>
  );
}
