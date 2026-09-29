import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Copy } from "lucide-react";
import api, { apiErr } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const NETWORKS = [
  { id: 0, name: "Bitcoin" }, { id: 1, name: "ERC 20" }, { id: 2, name: "TRC 20" },
  { id: 4, name: "BEP 20" }, { id: 5, name: "Solana" }, { id: 6, name: "Polygon" },
  { id: 7, name: "Arbitrum" }, { id: 8, name: "Litecoin" },
];

export default function Contacts() {
  const { t } = useLang();
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [net, setNet] = useState(1);

  const load = () => api.get("/contacts").then((r) => setList(r.data.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const add = async () => {
    try {
      await api.post("/contacts", { name, address, network_id: net });
      toast.success(t("saved")); setOpen(false); setName(""); setAddress(""); load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const del = async (id) => { await api.delete(`/contacts/${id}`); load(); };

  return (
    <div className="space-y-6 oki-fade-up">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">{t("contacts")}</h1>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button data-testid="open-add-contact" className="rounded-full bg-blue-600 hover:bg-blue-700"><Plus className="mr-2 h-4 w-4" />{t("add_contact")}</Button>
          </DialogTrigger>
          <DialogContent className="bg-white sm:max-w-md">
            <DialogHeader><DialogTitle>{t("add_contact")}</DialogTitle></DialogHeader>
            <div className="space-y-4">
              <div><Label>{t("contact_name")}</Label><Input data-testid="contact-name" value={name} onChange={(e) => setName(e.target.value)} className="rounded-xl mt-1" /></div>
              <div><Label>{t("address")}</Label><Input data-testid="contact-address" value={address} onChange={(e) => setAddress(e.target.value)} className="rounded-xl mt-1" /></div>
              <div><Label>{t("network")}</Label>
                <Select value={String(net)} onValueChange={(v) => setNet(Number(v))}>
                  <SelectTrigger data-testid="contact-network" className="rounded-xl mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-white border border-slate-200">{NETWORKS.map((n) => <SelectItem key={n.id} value={String(n.id)}>{n.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter><Button data-testid="save-contact" disabled={!name || !address} onClick={add} className="w-full rounded-full bg-blue-600 hover:bg-blue-700">{t("save_contact")}</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((c) => (
          <div key={c.contact_id} data-testid={`contact-${c.contact_id}`} className="rounded-2xl bg-white p-5 shadow-sm border border-slate-100">
            <div className="flex items-start justify-between">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br from-slate-100 to-slate-200 font-bold text-slate-600">{c.name.slice(0, 2).toUpperCase()}</div>
              <Button size="icon" variant="ghost" data-testid={`del-contact-${c.contact_id}`} onClick={() => del(c.contact_id)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>
            </div>
            <div className="mt-3 font-semibold text-slate-800">{c.name}</div>
            <div className="text-xs text-slate-400">{c.network}</div>
            <div className="mt-2 flex items-center gap-2 rounded-lg bg-slate-50 p-2">
              <code className="flex-1 truncate text-xs text-slate-600">{c.address}</code>
              <button onClick={() => { navigator.clipboard.writeText(c.address); toast.success(t("copied")); }}><Copy className="h-3.5 w-3.5 text-slate-400" /></button>
            </div>
          </div>
        ))}
      </div>
      {list.length === 0 && <div className="rounded-3xl bg-white p-12 text-center text-sm text-slate-400 border border-slate-100">{t("no_data")}</div>}
    </div>
  );
}
