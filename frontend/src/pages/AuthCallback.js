import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const hash = window.location.hash || "";
    const sid = new URLSearchParams(hash.replace(/^#/, "")).get("session_id");
    if (!sid) { navigate("/login"); return; }
    (async () => {
      try {
        const { data } = await api.post("/auth/google/session", { session_id: sid });
        setUser(data.user);
        window.history.replaceState(null, "", "/dashboard");
        navigate("/dashboard");
      } catch {
        navigate("/login");
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="animate-pulse text-slate-500">Авторизація…</div>
    </div>
  );
}
