import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { LanguageProvider, useLang } from "@/lib/i18n";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import Wallet from "@/pages/Wallet";
import Requests from "@/pages/Requests";
import Recovery from "@/pages/Recovery";
import Contacts from "@/pages/Contacts";
import Settings from "@/pages/Settings";
import ApiDocs from "@/pages/ApiDocs";
import Checkout from "@/pages/Checkout";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex min-h-screen items-center justify-center text-slate-400">…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function InfoPage({ titleKey, text }) {
  const { t } = useLang();
  return (
    <div className="oki-fade-up mx-auto max-w-3xl rounded-3xl bg-white p-8 shadow-sm border border-slate-100">
      <h1 className="text-2xl font-bold text-slate-900">{t(titleKey)}</h1>
      <p className="mt-3 text-slate-500">{text}</p>
    </div>
  );
}

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) return <AuthCallback />;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/checkout/:id" element={<Checkout />} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/wallet" element={<Protected><Wallet /></Protected>} />
      <Route path="/requests" element={<Protected><Requests /></Protected>} />
      <Route path="/recovery" element={<Protected><Recovery /></Protected>} />
      <Route path="/contacts" element={<Protected><Contacts /></Protected>} />
      <Route path="/settings" element={<Protected><Settings /></Protected>} />
      <Route path="/docs" element={<Protected><ApiDocs /></Protected>} />
      <Route path="/commissions" element={<Protected><InfoPage titleKey="commissions" text="Комісії залежать від валюти та мережі. Детальні тарифи доступні у розділі API Документація → /v1/private/coins." /></Protected>} />
      <Route path="/about" element={<Protected><InfoPage titleKey="about" text="FozPay — крипто-платіжний шлюз для прийому та обміну криптовалют без KYC для транзитних платежів." /></Protected>} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <BrowserRouter>
          <Toaster position="top-right" richColors />
          <AppRouter />
        </BrowserRouter>
      </AuthProvider>
    </LanguageProvider>
  );
}
