import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ShieldCheck, Lock } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useLang } from "@/lib/i18n";
import api, { setToken, apiErr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/Layout";

export default function Login() {
  const { setUser } = useAuth();
  const { t, lang, setLang } = useLang();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needs2FA, setNeeds2FA] = useState(false);
  const [busy, setBusy] = useState(false);

  const doLogin = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/auth/login", { email, password, otp: otp || undefined });
      setToken(data.access_token);
      setUser && setUser(data.user);
      navigate("/dashboard");
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (detail && typeof detail === "object" && (detail.error === "2FA_REQUIRED" || detail.error === "2FA_INVALID")) {
        setNeeds2FA(true);
        toast.info(detail.message || "Введіть код Google Authenticator");
      } else {
        toast.error(apiErr(err));
      }
    } finally { setBusy(false); }
  };

  const google = () => {
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      {/* floating orbs */}
      <div className="pointer-events-none absolute -left-24 top-10 h-72 w-72 rounded-full bg-violet-500/30 blur-3xl foz-float" />
      <div className="pointer-events-none absolute -right-16 bottom-0 h-80 w-80 rounded-full bg-fuchsia-500/25 blur-3xl foz-float" style={{ animationDelay: "1.5s" }} />

      <div className="absolute right-5 top-5">
        <button onClick={() => setLang(lang === "uk" ? "en" : "uk")} data-testid="login-lang"
          className="rounded-full glass px-3 py-1.5 text-sm font-semibold text-slate-700">
          {lang.toUpperCase()}
        </button>
      </div>

      <div className="oki-fade-up relative w-full max-w-md rounded-[2rem] glass p-8 shadow-2xl">
        <div className="mb-2 flex justify-center"><Logo size="text-2xl" /></div>
        <p className="mb-7 text-center text-sm text-slate-500">{t("login_sub")}</p>

        <form onSubmit={doLogin} className="space-y-4">
          <div>
            <Label>{t("email")}</Label>
            <Input data-testid="login-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 rounded-xl border-white/60" placeholder="admin@fozpay.io" />
          </div>
          <div>
            <Label>{t("password")}</Label>
            <Input data-testid="login-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 rounded-xl border-white/60" placeholder="••••••••" />
          </div>
          {needs2FA && (
            <div>
              <Label className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" /> Код Google Authenticator</Label>
              <Input data-testid="login-otp" value={otp} onChange={(e) => setOtp(e.target.value)} className="mt-1 rounded-xl tracking-widest text-center" placeholder="123 456" inputMode="numeric" maxLength={6} autoFocus />
            </div>
          )}
          <Button data-testid="login-submit" disabled={busy} className="w-full rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-600 py-6 text-base font-bold shadow-lg shadow-fuchsia-500/30 hover:opacity-95">
            {busy ? "..." : t("login_btn")}
          </Button>
        </form>

        <div className="my-5 flex items-center gap-3 text-xs text-slate-400">
          <div className="h-px flex-1 bg-white/50" /> OR <div className="h-px flex-1 bg-white/50" />
        </div>
        <Button data-testid="google-login" onClick={google} variant="outline" className="w-full rounded-full border-white/60 bg-white/40">
          <img alt="g" src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" className="mr-2 h-4 w-4" />
          {t("google_btn")}
        </Button>

        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-slate-500">
          <Lock className="h-3.5 w-3.5" /> Реєстрація закрита — акаунти створює адміністратор
        </div>
      </div>
    </div>
  );
}
