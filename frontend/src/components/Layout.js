import React, { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Wallet, Receipt, Users, Settings, LogOut,
  ChevronDown, Menu, X, ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useLang } from "@/lib/i18n";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV = [
  { key: "dashboard", path: "/dashboard", icon: LayoutDashboard },
  { key: "wallet", path: "/wallet", icon: Wallet },
  { key: "requests", path: "/requests", icon: Receipt },
  { key: "recovery", path: "/recovery", icon: ShieldCheck },
  { key: "contacts", path: "/contacts", icon: Users },
  { key: "settings", path: "/settings", icon: Settings },
];

export function Logo({ size = "text-xl" }) {
  return (
    <div className="flex items-center gap-2.5" data-testid="foz-logo">
      <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-purple-600 font-extrabold text-white shadow-lg shadow-fuchsia-500/30">
        <span className="font-display">F</span>
      </div>
      <span className={`${size} font-extrabold tracking-tight font-display`}>
        <span className="text-slate-900">Foz</span><span className="foz-grad-text">Pay</span>
      </span>
    </div>
  );
}

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const { t, lang, setLang } = useLang();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const initials = (user?.name || user?.email || "F").slice(0, 2).toUpperCase();

  const topLinks = [
    { key: "commissions", path: "/commissions" },
    { key: "api_docs", path: "/docs" },
    { key: "about", path: "/about" },
  ];

  return (
    <div className="min-h-screen">
      {/* Topbar */}
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/40 glass px-4 sm:px-6">
        <div className="flex items-center gap-8">
          <button className="lg:hidden" onClick={() => setOpen(!open)} data-testid="sidebar-toggle">
            {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
          <Logo />
          <nav className="hidden items-center gap-6 md:flex">
            {topLinks.map((l) => (
              <NavLink key={l.key} to={l.path} data-testid={`top-${l.key}`}
                className="text-sm font-semibold text-slate-600 transition-colors hover:text-violet-600">
                {t(l.key)}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          {user?.role === "admin" && (
            <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-600 px-3 py-1 text-xs font-bold text-white shadow">
              ADMIN
            </span>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button data-testid="lang-switch" className="flex items-center gap-1 rounded-full px-2 py-1 text-sm font-semibold text-slate-600 hover:bg-white/60">
                {lang.toUpperCase()} <ChevronDown className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="glass border border-white/50">
              <DropdownMenuItem onClick={() => setLang("uk")} data-testid="lang-uk">UK · Українська</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setLang("en")} data-testid="lang-en">EN · English</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button data-testid="user-menu" className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-600 text-sm font-bold text-white shadow-lg shadow-fuchsia-500/30">
                {initials}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="glass border border-white/50 w-56">
              <div className="px-2 py-1.5 text-xs text-slate-500">{user?.email}</div>
              <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn" className="text-rose-600 focus:text-rose-600">
                <LogOut className="mr-2 h-4 w-4" /> {t("logout")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <aside className={`fixed inset-y-16 left-0 z-20 w-64 transform border-r border-white/40 glass p-4 transition-transform lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
          <nav className="space-y-1.5">
            {NAV.map((n) => {
              const Icon = n.icon;
              return (
                <NavLink key={n.key} to={n.path} onClick={() => setOpen(false)} data-testid={`nav-${n.key}`}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition-all ${
                      isActive
                        ? "bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white shadow-lg shadow-fuchsia-500/25"
                        : "text-slate-600 hover:bg-white/60"
                    }`}>
                  <Icon className="h-5 w-5" /> {t(n.key)}
                </NavLink>
              );
            })}
          </nav>
          <div className="mt-6 rounded-2xl glass-dark p-4 text-xs text-violet-100">
            <div className="font-bold text-white">FozPay Gateway</div>
            <div className="mt-1 opacity-80">Прийом · Обмін · Вивід криптовалют через гарячий гаманець.</div>
          </div>
        </aside>

        <main className="min-h-[calc(100vh-4rem)] w-full min-w-0 flex-1 overflow-x-hidden p-4 sm:p-6 lg:p-8">{children}</main>
      </div>
    </div>
  );
}
