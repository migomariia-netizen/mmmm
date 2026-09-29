import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

const saved = localStorage.getItem("oki_token");
if (saved) api.defaults.headers.common["Authorization"] = `Bearer ${saved}`;

export function setToken(token) {
  if (token) {
    localStorage.setItem("oki_token", token);
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    localStorage.removeItem("oki_token");
    delete api.defaults.headers.common["Authorization"];
  }
}

export function apiErr(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data?.error ?? e?.response?.data?.message;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  return e?.message || "Помилка. Спробуйте ще раз.";
}

export default api;
