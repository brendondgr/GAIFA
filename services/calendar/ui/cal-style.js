// The Calendar's styles (calendar plan 3.2; the brief §11.15): the hub's colour tokens, an 8 px grid, 48 px hour
// rows, the accent for today and now. One <style> for the page and the Chat panel.

export const CSS = `
.cal{container-type:inline-size;position:relative;--cal-hour:48px;--cal-line:var(--bd,#1D2430);--cal-soft:var(--inset,#131926);display:flex;flex:1;min-height:0;min-width:0;color:var(--tx,#E6EAF2);font-size:13px;background:var(--bg,#0B0E14)}
.cal *{box-sizing:border-box}
.cal button{font:inherit}
.cal-side{width:248px;flex:none;border-right:1px solid var(--cal-line);display:flex;flex-direction:column;gap:16px;padding:14px 12px;overflow-y:auto;scrollbar-width:thin}
.cal-main{flex:1;min-width:0;display:flex;flex-direction:column;min-height:0}
.cal-head{display:flex;flex-direction:column;gap:8px;padding:10px 16px;border-bottom:1px solid var(--cal-line);flex:none}
.cal-hrow{display:flex;align-items:center;gap:6px;min-width:0}
.cal .cal-sidebtn{display:none}
.cal-title{font-size:16px;font-weight:600;letter-spacing:-.01em;margin:0 8px 0 4px;white-space:nowrap}
.cal-btn{height:30px;padding:0 11px;border-radius:7px;border:1px solid var(--bds,#2A3547);background:var(--cal-soft);color:var(--tx,#E6EAF2);cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:12.5px;white-space:nowrap}
.cal-btn:hover{background:var(--hov,#161C28)}
.cal-btn.pri{background:var(--acc,#FFB224);color:#1A1200;border-color:transparent;font-weight:600}
.cal-btn.ghost{background:transparent;border-color:transparent;color:var(--mut,#8A94A6)}
.cal-btn.ghost:hover{color:var(--tx,#E6EAF2);background:var(--hov,#161C28)}
.cal-btn.icon{width:30px;padding:0;justify-content:center}
.cal-seg{display:inline-flex;border:1px solid var(--bds,#2A3547);border-radius:7px;overflow:hidden}
.cal-seg button{height:28px;padding:0 11px;border:0;background:transparent;color:var(--mut,#8A94A6);cursor:pointer;font-size:12.5px}
.cal-seg button[aria-pressed=true]{background:var(--hov,#161C28);color:var(--tx,#E6EAF2);font-weight:600}
.cal-input{height:30px;padding:0 10px;border-radius:7px;border:1px solid var(--bds,#2A3547);background:var(--sb,#0D1119);color:var(--tx,#E6EAF2);font:inherit;font-size:12.5px;min-width:0}
.cal-input:focus,.cal-btn:focus-visible,.cal-seg button:focus-visible{outline:2px solid var(--acc,#FFB224);outline-offset:1px}
.cal-quick{position:relative;flex:1 1 auto;min-width:0;display:flex;flex-direction:column}
.cal-quick .cal-input{width:100%}
.cal-preview{position:absolute;top:34px;left:0;right:0;z-index:30;background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);border-radius:8px;padding:8px 10px;font-size:12px;color:var(--mut,#8A94A6);box-shadow:0 10px 30px rgba(0,0,0,.35)}
.cal-preview b{color:var(--tx,#E6EAF2);font-weight:600}
.cal-sec{display:flex;flex-direction:column;gap:6px}
.cal-sec h3{margin:0;font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--mut,#8A94A6);display:flex;align-items:center;gap:6px}
.cal-sec h3 span{flex:1}
.cal-row{display:flex;align-items:center;gap:8px;min-height:28px;padding:2px 6px;border-radius:6px;cursor:pointer}
.cal-row:hover{background:var(--hov,#161C28)}
.cal-dot{width:10px;height:10px;border-radius:3px;flex:none}
.cal-check{width:15px;height:15px;border-radius:4px;border:1.5px solid var(--bds,#2A3547);flex:none;display:grid;place-items:center;cursor:pointer;background:transparent;padding:0}
.cal-check[aria-checked=true]{background:var(--acc,#FFB224);border-color:var(--acc,#FFB224)}
.cal-muted{color:var(--mut,#8A94A6);font-size:12px}
.cal-small{font-size:11.5px}
.cal-mini{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;text-align:center;font-size:11.5px}
.cal-mini button{height:26px;border:0;border-radius:6px;background:transparent;color:var(--tx,#E6EAF2);cursor:pointer;padding:0}
.cal-mini button:hover{background:var(--hov,#161C28)}
.cal-mini .out{color:var(--dim,#5D6778)}
.cal-mini .in{background:var(--cal-soft)}
.cal-mini .today{color:var(--acc,#FFB224);font-weight:700}
.cal-mini .sel{background:var(--acc,#FFB224);color:#1A1200;font-weight:700}
.cal-mini .wd{color:var(--mut,#8A94A6);font-size:10.5px;height:20px;line-height:20px}
.cal-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
/* day and week */
.cal-days{display:grid;border-bottom:1px solid var(--cal-line);flex:none}
.cal-dayhd{padding:8px 6px 6px;text-align:center;font-size:11.5px;color:var(--mut,#8A94A6);border-left:1px solid var(--cal-line);cursor:pointer}
.cal-dayhd b{display:block;font-size:20px;font-weight:500;color:var(--tx,#E6EAF2);line-height:1.2}
.cal-dayhd.today b{color:var(--acc,#FFB224);font-weight:700}
.cal-dayhd.wkend{background:rgba(127,127,127,.03)}
.cal-allday{display:grid;position:relative;border-bottom:1px solid var(--cal-line);flex:none;min-height:26px}
.cal-scroll{flex:1;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;position:relative}
.cal-grid{display:grid;position:relative}
.cal-gutter{font-size:10.5px;color:var(--mut,#8A94A6);text-align:right;padding-right:8px}
.cal-gutter div{height:var(--cal-hour);transform:translateY(-7px)}
.cal-col{position:relative;border-left:1px solid var(--cal-line);background-image:linear-gradient(var(--cal-line) 1px,transparent 1px);background-size:100% var(--cal-hour)}
.cal-col.wkend{background-color:rgba(127,127,127,.03)}
.cal-work{position:absolute;left:0;right:0;background:rgba(127,127,127,.045);pointer-events:none}
.cal-ev{position:absolute;border-radius:6px;padding:3px 6px;font-size:11.5px;line-height:1.3;overflow:hidden;cursor:pointer;border-left:3px solid var(--c);background:color-mix(in srgb,var(--c) 18%,var(--card,#11151D));color:var(--tx,#E6EAF2);user-select:none}
.cal-ev:hover{background:color-mix(in srgb,var(--c) 26%,var(--card,#11151D))}
.cal-ev .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-ev .s{color:var(--mut,#8A94A6);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-ev.focus{background:repeating-linear-gradient(135deg,color-mix(in srgb,var(--c) 14%,var(--card,#11151D)) 0 6px,color-mix(in srgb,var(--c) 22%,var(--card,#11151D)) 6px 12px)}
.cal-ev.free{opacity:.75;border-left-style:dashed}
.cal-ev.ghost{opacity:.55;outline:1px dashed var(--c);pointer-events:none}
.cal-ev .rs{position:absolute;left:0;right:0;bottom:0;height:6px;cursor:ns-resize}
.cal-bar{position:absolute;height:20px;border-radius:5px;padding:0 6px;font-size:11.5px;line-height:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;background:color-mix(in srgb,var(--c) 22%,var(--card,#11151D));border-left:3px solid var(--c)}
.cal-bar.todo{background:transparent;border:1px solid color-mix(in srgb,var(--c) 60%,transparent);border-left-width:3px}
.cal-bar.done{text-decoration:line-through;opacity:.6}
.cal-todo{position:absolute;left:3px;right:3px;height:18px;border-radius:9px;padding:0 6px 0 4px;font-size:11px;line-height:18px;display:flex;gap:4px;align-items:center;background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);overflow:hidden;white-space:nowrap;cursor:pointer;z-index:2}
.cal-now{position:absolute;left:0;right:0;height:2px;background:var(--acc,#FFB224);z-index:3;pointer-events:none}
.cal-now::before{content:'';position:absolute;left:-5px;top:-4px;width:10px;height:10px;border-radius:50%;background:var(--acc,#FFB224)}
.cal-more{font-size:11px;color:var(--mut,#8A94A6);cursor:pointer}
.cal-rep{opacity:.7;font-size:10px;margin-left:3px}
/* month */
.cal-month{flex:1;display:grid;grid-template-rows:auto;min-height:0;overflow-y:auto}
.cal-mhd{display:grid;grid-template-columns:repeat(7,1fr);border-bottom:1px solid var(--cal-line)}
.cal-mhd div{padding:6px 8px;font-size:11px;color:var(--mut,#8A94A6);text-transform:uppercase;letter-spacing:.06em}
.cal-week{display:grid;grid-template-columns:repeat(7,1fr);position:relative;border-bottom:1px solid var(--cal-line);min-height:112px}
.cal-cell{border-left:1px solid var(--cal-line);padding:4px 6px 6px;display:flex;flex-direction:column;gap:2px;min-width:0;cursor:pointer}
.cal-cell:first-child{border-left:0}
.cal-cell .n{font-size:12px;width:24px;height:24px;display:grid;place-items:center;border-radius:50%;align-self:flex-start}
.cal-cell.out .n{color:var(--dim,#5D6778)}
.cal-cell.today .n{background:var(--acc,#FFB224);color:#1A1200;font-weight:700}
.cal-cell.wkend{background:rgba(127,127,127,.03)}
.cal-chip{display:flex;align-items:center;gap:5px;font-size:11.5px;white-space:nowrap;overflow:hidden;padding:1px 4px;border-radius:4px;cursor:pointer;min-width:0}
.cal-chip:hover{background:var(--hov,#161C28)}
.cal-chip .d{width:7px;height:7px;border-radius:50%;flex:none;background:var(--c)}
.cal-chip .tm{color:var(--mut,#8A94A6);flex:none}
.cal-chip .tt{overflow:hidden;text-overflow:ellipsis}
/* agenda */
.cal-agenda{flex:1;overflow-y:auto;padding:8px 16px 24px;scrollbar-width:thin}
.cal-aday{display:grid;grid-template-columns:120px 1fr;gap:12px;padding:10px 0;border-bottom:1px solid var(--cal-line)}
.cal-aday .dd{font-size:12px;color:var(--mut,#8A94A6);padding-top:4px}
.cal-aday .dd.today{color:var(--acc,#FFB224);font-weight:600}
.cal-arow{display:flex;align-items:center;gap:10px;padding:5px 8px;border-radius:6px;cursor:pointer;min-width:0}
.cal-arow:hover{background:var(--hov,#161C28)}
.cal-arow .tm{width:110px;flex:none;font-size:12px;color:var(--mut,#8A94A6);font-variant-numeric:tabular-nums}
.cal-arow .tt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* popover, sheet, dialog, snackbar */
.cal-pop{position:fixed;z-index:60;width:300px;background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);border-radius:10px;box-shadow:0 16px 40px rgba(0,0,0,.45);padding:14px;display:flex;flex-direction:column;gap:8px}
.cal-pop h4{margin:0;font-size:14px;display:flex;gap:8px;align-items:flex-start}
.cal-sheet{position:absolute;top:0;right:0;bottom:0;width:min(420px,100%);z-index:50;background:var(--card,#11151D);border-left:1px solid var(--bds,#2A3547);box-shadow:-16px 0 40px rgba(0,0,0,.35);display:flex;flex-direction:column}
.cal-sheet .bd{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;scrollbar-width:thin}
.cal-sheet .ft{padding:12px 16px;border-top:1px solid var(--cal-line);display:flex;gap:8px;align-items:center}
.cal-field{display:flex;flex-direction:column;gap:4px;min-width:0}
.cal-field>span{font-size:11.5px;color:var(--mut,#8A94A6)}
.cal-field .cal-input,.cal-field select,.cal-field textarea{width:100%}
.cal-field textarea{height:auto;padding:8px 10px;resize:vertical}
.cal-two{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.cal-dialog{position:fixed;inset:0;z-index:80;background:rgba(0,0,0,.45);display:grid;place-items:center}
.cal-dialog>div{width:min(380px,92vw);background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:10px}
.cal-snack{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:90;background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);border-radius:10px;padding:8px 8px 8px 14px;display:flex;gap:12px;align-items:center;box-shadow:0 12px 34px rgba(0,0,0,.4);font-size:12.5px}
.cal-days-pick{display:flex;gap:4px;flex-wrap:wrap}
.cal-days-pick button{width:34px;height:28px;border-radius:6px;border:1px solid var(--bds,#2A3547);background:transparent;color:var(--mut,#8A94A6);cursor:pointer;font-size:11.5px}
.cal-days-pick button[aria-pressed=true]{background:var(--acc,#FFB224);color:#1A1200;border-color:transparent;font-weight:600}
@container (max-width:880px){.cal .cal-sidebtn{display:inline-flex}.cal-side{display:none}.cal-side.open{display:flex;position:absolute;z-index:45;top:0;bottom:0;left:0;background:var(--bg,#0B0E14);box-shadow:16px 0 40px rgba(0,0,0,.35)}}
@container (max-width:600px){.cal-head{padding:8px 10px}.cal-title{font-size:14px;margin:0 2px}.cal-hrow{flex-wrap:wrap}.cal-aday{grid-template-columns:1fr}.cal-arow .tm{width:86px}}
`;

export function ensureCss(doc = globalThis.document) {
  if (!doc || doc.getElementById('cal-css')) return;
  const el = doc.createElement('style');
  el.id = 'cal-css';
  el.textContent = CSS;
  doc.head.appendChild(el);
}

/** A tiny DOM builder for the calendar's own pieces: el('div.cls', {attrs}, ...children). */
export function el(sel, attrs, ...kids) {
  const [tag, ...cls] = sel.split('.');
  const n = document.createElement(tag || 'div');
  if (cls.length) n.className = cls.join(' ');
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'style' && typeof v === 'object') { for (const [sk, sv] of Object.entries(v)) n.style.setProperty(sk.startsWith('--') ? sk : sk.replace(/[A-Z]/g, c => '-' + c.toLowerCase()), sv); }
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') n.className += ' ' + v;
    else if (k in n && typeof v !== 'string') n[k] = v;
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}

/** A 16 px stroke icon. */
export function icon(d, size = 16) {
  const ns = 'http://www.w3.org/2000/svg', s = document.createElementNS(ns, 'svg');
  s.setAttribute('width', size); s.setAttribute('height', size); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none');
  s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ns, 'path'); p.setAttribute('d', d); s.append(p);
  return s;
}
export const I = {
  left: 'M15 18l-6-6 6-6', right: 'M9 18l6-6-6-6', plus: 'M12 5v14M5 12h14', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  x: 'M6 6l12 12M18 6L6 18', repeat: 'M17 2l3 3-3 3M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3M20 13v2a4 4 0 0 1-4 4H4',
  bell: 'M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 21h4', check: 'M5 12l5 5L20 7', trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  menu: 'M4 6h16M4 12h16M4 18h16', clock: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', pin: 'M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12zM12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16', download: 'M12 4v12M7 11l5 5 5-5M4 20h16', gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
};
