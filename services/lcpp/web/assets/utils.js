/* lcpp — utils: formatting, small helpers. No DOM. */
export const GB = 1024 ** 3, MB = 1024 ** 2;
export const fmtGB = b => b == null ? '—' : (b / GB).toFixed(1) + ' GB';
export const fmtBytes = b => b == null ? '—' : b >= GB ? fmtGB(b) : Math.round(b / MB) + ' MB';
export const fmtDur = s => { s = Math.max(0, Math.floor(s)); if (s < 60) return s + 's'; const m = Math.floor(s / 60), hh = Math.floor(m / 60), d = Math.floor(hh / 24); if (hh < 1) return m + 'm ' + (s % 60) + 's'; if (d < 1) return hh + 'h ' + (m % 60) + 'm'; return d + 'd ' + (hh % 24) + 'h'; };
export const ago = ts => fmtDur(Date.now() / 1000 - ts) + ' ago';
export const nowS = () => Date.now() / 1000;
export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const shq = s => /^[A-Za-z0-9_./:=+-]+$/.test(s) ? s : "'" + String(s).replace(/'/g, "'\\''") + "'";
export const argvToCmd = argv => (argv || []).map(shq).join(' ');
export const clone = o => JSON.parse(JSON.stringify(o));
export const deepEq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export const NAME_RE = /^[a-z0-9][a-z0-9-]{0,47}$/;
export const CTX_PRESETS = [4096, 8192, 16384, 32768, 65536, 131072, 262144];
export const ctxLabel = n => n >= 1024 ? (n / 1024) + 'k' : String(n);
export const modelNick = m => (m && m.nicknames && m.nicknames[0]) || (m && m.id) || '';
export function loadPref(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } }
export function savePref(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable: fine */ } }
export function download(name, text) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
