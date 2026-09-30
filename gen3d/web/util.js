// Shared helpers: API client, formatting, DOM, icons.

export const $ = (id) => document.getElementById(id);

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

function detailText(d) {
  if (!d) return "";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (typeof e === "string" ? e : `${(e.loc || []).slice(-1)[0] ?? ""}: ${e.msg}`)).join("; ");
  return JSON.stringify(d);
}

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["content-type"] = "application/json"; }
  let r;
  try { r = await fetch(path, opts); } catch (e) { throw new ApiError(0, "Can't reach 3DGenerate. Is the service running? (gen3d start)"); }
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) throw new ApiError(r.status, detailText(data?.detail ?? data) || `${r.status} ${r.statusText}`);
  return data;
}

export function fmtDur(s) {
  if (s == null || !isFinite(s)) return "–";
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return `${m}m ${String(r).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export const fmtClock = (epochS) => new Date(epochS * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const fmtWhen = (epochS) => {
  const d = new Date(epochS * 1000), now = new Date();
  return d.toDateString() === now.toDateString() ? fmtClock(epochS)
    : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + fmtClock(epochS);
};
export const fmtNum = (n) => (n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k" : String(n));
export const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;

let toastTimer;
export function toast(msg, ms = 3200) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem("gen3d." + key));
    localStorage.setItem("gen3d." + key, JSON.stringify(value));
  } catch { return undefined; }
}

const P = (d) => `<svg viewBox="0 0 24 24">${d}</svg>`;
export const ICON = {
  cube: P('<path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="M12 22V12M21 7l-9 5-9-5"/>'),
  check: P('<path d="M5 12l5 5L20 7"/>'),
  x: P('<path d="M6 6l12 12M18 6L6 18"/>'),
  trash: P('<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>'),
  retry: P('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'),
  download: P('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'),
  split: P('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
  rig: P('<circle cx="12" cy="5" r="2"/><path d="M12 7v6M12 13l-5 7M12 13l5 7M5 9l7 2 7-2"/>'),
  box3d: P('<path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="M12 22V12M21 7l-9 5-9-5"/>'),
  stop: P('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
  file: P('<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/>'),
  copy: P('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>'),
  continue: P('<path d="M5 12h14M13 6l6 6-6 6"/>'),
};
