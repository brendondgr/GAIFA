/* @ds-bundle: {"format":4,"namespace":"Lcpp","components":[{"name":"Button"},{"name":"Badge"},{"name":"StatusDot"},{"name":"Toggle"},{"name":"Segmented"},{"name":"Field"},{"name":"MemoryMeter"},{"name":"RelayPill"},{"name":"Toast"},{"name":"Banner"},{"name":"Card"},{"name":"Table"},{"name":"Tabs"},{"name":"Kbd"},{"name":"Skeleton"},{"name":"EmptyState"},{"name":"LogLine"},{"name":"NavItem"},{"name":"Dialog"},{"name":"InstanceCard"}]} */
/* lcpp components — vanilla DOM factories. No framework. Each returns an HTMLElement.
   window.Lcpp.Button({label:'Launch', variant:'primary'}) etc. Styles live in bundle.css. */
(function () {
  'use strict';
  var SVG_NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    if (children != null) [].concat(children).forEach(function (c) { if (c != null) n.append(c); });
    return n;
  }
  var ICONS = {
    plus: 'M12 5v14M5 12h14', x: 'M18 6L6 18M6 6l12 12', check: 'M20 6L9 17l-5-5', alert: 'M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
    info: 'M12 16v-4m0-4h.01M22 12a10 10 0 11-20 0 10 10 0 0120 0z', copy: 'M8 8h12v12H8zM16 8V4H4v12h4', play: 'M6 4l14 8-14 8z', square: 'M6 6h12v12H6z', refresh: 'M3 12a9 9 0 0115.5-6.3L21 8M21 3v5h-5M21 12a9 9 0 01-15.5 6.3L3 16M3 21v-5h5',
    logs: 'M4 6h16M4 12h10M4 18h13', more: 'M5 12h.01M12 12h.01M19 12h.01', chevron: 'M9 18l6-6-6-6', down: 'M6 9l6 6 6-6', external: 'M14 4h6v6M20 4l-9 9M18 13v6H5V6h6',
    grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z', list: 'M4 6h16M4 12h16M4 18h16', cpu: 'M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m14-6h2m-2 6h2M6 5h12a1 1 0 011 1v12a1 1 0 01-1 1H6a1 1 0 01-1-1V6a1 1 0 011-1zm3 4h6v6H9z',
    box: 'M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8', chat: 'M21 12a8 8 0 01-8 8H7l-4 3V12a8 8 0 018-8h2a8 8 0 018 8z', relay: 'M5 12h4m6 0h4M9 12a3 3 0 106 0 3 3 0 00-6 0zM5 12a2 2 0 11-4 0 2 2 0 014 0zm18 0a2 2 0 11-4 0 2 2 0 014 0z',
    settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1l2-1.5-2-3.5-2.4 1a7.5 7.5 0 00-1.7-1L14.8 3H9.2l-.4 2.6a7.5 7.5 0 00-1.7 1l-2.4-1-2 3.5 2 1.5a7.4 7.4 0 000 2l-2 1.5 2 3.5 2.4-1a7.5 7.5 0 001.7 1l.4 2.6h5.6l.4-2.6a7.5 7.5 0 001.7-1l2.4 1 2-3.5-2-1.5c.1-.3.1-.7.1-1z',
    download: 'M12 3v12m-5-5l5 5 5-5M4 19h16', search: 'M11 4a7 7 0 100 14 7 7 0 000-14zm9 16l-4.3-4.3', menu: 'M4 7h16M4 12h16M4 17h16', sun: 'M12 3v2m0 14v2M4.2 4.2l1.4 1.4m12.8 12.8l1.4 1.4M3 12h2m14 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z',
    moon: 'M21 13A8 8 0 1111 3a6 6 0 0010 10z', arrowdown: 'M12 5v14m-6-6l6 6 6-6', trash: 'M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3', edit: 'M4 20h4l10-10-4-4L4 16v4zM13 7l4 4', bolt: 'M13 2L4 14h7l-1 8 9-12h-7l1-8z'
  };
  function Icon(name, size) {
    var s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'icon'); s.setAttribute('aria-hidden', 'true');
    if (size) { s.style.width = size + 'px'; s.style.height = size + 'px'; }
    var p = document.createElementNS(SVG_NS, 'path'); p.setAttribute('d', ICONS[name] || ICONS.info); s.append(p); return s;
  }
  function Logo(size) {
    var s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', size || 24); s.setAttribute('height', size || 24); s.setAttribute('aria-hidden', 'true');
    s.innerHTML = '<rect x="1" y="1" width="22" height="22" rx="6" fill="#ffb224"/><path d="M7 7.5l5 4.5-5 4.5" fill="none" stroke="#1a1200" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M13 17h4" stroke="#1a1200" stroke-width="2.4" stroke-linecap="round"/>';
    return s;
  }
  function Button(o) {
    o = o || {};
    var cls = ['btn']; if (o.variant) cls.push('btn-' + o.variant); if (o.size) cls.push('btn-' + o.size); if (o.icon && !o.label) cls.push('btn-icon'); if (o.loading) cls.push('is-loading');
    var b = el('button', { class: cls.join(' '), type: o.type || 'button', disabled: !!o.disabled, 'aria-label': o.icon && !o.label ? o.title : null, title: o.title, onClick: o.onClick });
    if (o.icon) b.append(Icon(o.icon)); if (o.label) b.append(document.createTextNode(o.label)); return b;
  }
  function Badge(o) { o = typeof o === 'string' ? { label: o } : (o || {}); return el('span', { class: 'badge' + (o.tone ? ' badge-' + o.tone : ''), text: o.label }); }
  function Chip(o) { var c = el('button', { class: 'chip', type: 'button', onClick: o.onClick }, [o.dot ? el('span', { class: 'dot dot-' + o.dot }) : null, o.label]); if (o.removable) c.append(el('span', { class: 'x', 'aria-hidden': 'true', text: '×' })); return c; }
  var STATE_TONE = { starting: 'amber', ready: 'green', stopping: 'amber', failed: 'red', pending: 'amber', registered: 'cyan', error: 'red', off: 'muted', healthy: 'green', degraded: 'amber', unknown: 'muted' };
  function StatusDot(o) {
    o = typeof o === 'string' ? { state: o } : (o || {});
    var tone = o.tone || STATE_TONE[o.state] || 'muted'; var pulse = o.pulse != null ? o.pulse : /starting|stopping|pending/.test(o.state || '');
    var d = el('span', { class: 'dot ' + (tone === 'muted' ? 'dot-off' : 'dot-' + tone) + (pulse ? ' pulse' : ''), style: { color: 'var(--' + ({ amber: 'accent-ink', green: 'green-ink', red: 'red-ink', cyan: 'cyan-ink', purple: 'purple-ink', muted: 'text-mut' })[tone] + ')' } });
    if (o.label === false) return d;
    return el('span', { class: 'status status-' + tone, role: 'status' }, [d, el('span', { text: o.label || o.state })]);
  }
  function Toggle(o) {
    o = o || {}; var input = el('input', { type: 'checkbox', class: 'toggle' + (o.tone === 'cyan' ? ' toggle-cyan' : ''), role: 'switch', checked: !!o.checked, disabled: !!o.disabled, 'aria-checked': o.checked ? 'true' : 'false', onChange: function (e) { input.setAttribute('aria-checked', input.checked); o.onChange && o.onChange(input.checked, e); } });
    if (!o.label) { input.setAttribute('aria-label', o.title || 'toggle'); return input; }
    return el('label', { class: 'switch', title: o.title }, [input, el('span', { text: o.label })]);
  }
  function Segmented(o) {
    var wrap = el('div', { class: 'seg' + (o.size === 'sm' ? ' seg-sm' : ''), role: 'group', 'aria-label': o.label }); var value = o.value;
    o.options.forEach(function (opt) {
      var b = el('button', { type: 'button', 'aria-pressed': String(opt.value === value), text: opt.label, onClick: function () { value = opt.value; wrap.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); }); b.setAttribute('aria-pressed', 'true'); o.onChange && o.onChange(value); } });
      if (opt.icon) b.prepend(Icon(opt.icon)); wrap.append(b);
    });
    return wrap;
  }
  var fid = 0;
  function Field(o) {
    var id = o.id || ('f' + (++fid)); var control;
    if (o.type === 'select') { control = el('select', { class: 'select', id: id, disabled: !!o.disabled }); (o.options || []).forEach(function (op) { control.append(el('option', { value: op.value, selected: op.value === o.value, text: op.label })); }); }
    else if (o.type === 'textarea') control = el('textarea', { class: 'textarea' + (o.mono ? ' mono' : ''), id: id, placeholder: o.placeholder, text: o.value });
    else control = el('input', { class: 'input' + (o.mono ? ' mono' : '') + (o.ok ? ' is-ok' : ''), id: id, type: o.type || 'text', value: o.value, placeholder: o.placeholder, disabled: !!o.disabled, min: o.min, max: o.max, step: o.step, autocomplete: 'off', spellcheck: 'false' });
    if (o.error) control.setAttribute('aria-invalid', 'true');
    if (o.onInput) control.addEventListener('input', function () { o.onInput(control.value, control); });
    if (o.onChange) control.addEventListener('change', function () { o.onChange(control.value, control); });
    var help = o.error ? el('div', { class: 'help help-err', text: '✗ ' + o.error }) : o.ok ? el('div', { class: 'help help-ok', text: '✓ ' + o.ok }) : o.help ? el('div', { class: 'help', text: o.help }) : null;
    if (help) { help.id = id + '-help'; control.setAttribute('aria-describedby', help.id); }
    var f = el('div', { class: 'field' }, [el('label', { class: 'label', for: id }, [o.label, o.optional ? el('span', { class: 'opt', text: 'optional' }) : null]), o.trailing ? el('div', { class: 'input-row' }, [control, o.trailing]) : control, help]);
    f.control = control; f.setHelp = function (kind, text) { var h = f.querySelector('.help'); if (!h) { h = el('div', { class: 'help' }); h.id = id + '-help'; f.append(h); control.setAttribute('aria-describedby', h.id); } h.className = 'help' + (kind ? ' help-' + kind : ''); h.textContent = (kind === 'err' ? '✗ ' : kind === 'ok' ? '✓ ' : '') + (text || ''); control.classList.toggle('is-ok', kind === 'ok'); if (kind === 'err') control.setAttribute('aria-invalid', 'true'); else control.removeAttribute('aria-invalid'); };
    return f;
  }
  function MemoryMeter(o) {
    var pct = o.total ? Math.round(100 * o.used / o.total) : 0; var cls = 'meter' + (pct > 92 ? ' crit' : pct > 80 ? ' warn' : '');
    var fmt = o.format || function (b) { return (b / 1073741824).toFixed(1) + ' GB'; };
    return el('div', { class: cls, role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': pct, 'aria-label': o.label + ' ' + fmt(o.used) + ' of ' + fmt(o.total) }, [el('span', { class: 'meter-label', text: o.label }), el('div', { class: 'meter-bar' }, el('div', { class: 'meter-fill', style: { width: pct + '%' } })), el('span', { class: 'meter-val', text: fmt(o.used) + ' / ' + fmt(o.total) })]);
  }
  function RelayPill(o) { var ok = !!o.reachable; return el('span', { class: 'pill ' + (ok ? 'pill-ok' : 'pill-off'), role: 'status', title: o.title || (ok ? 'Relay reachable' : 'Relay unreachable') }, [el('span', { text: 'Relay' }), el('span', { class: 'dot ' + (ok ? 'dot-cyan' : 'dot-off'), 'aria-hidden': 'true' }), el('span', { text: ok ? 'connected' : 'unreachable' })]); }
  function Toast(o) { var t = el('div', { class: 'toast ' + (o.kind === 'error' ? 'toast-err' : o.kind === 'success' ? 'toast-ok' : ''), role: o.kind === 'error' ? 'alert' : 'status' }, [Icon(o.kind === 'error' ? 'alert' : o.kind === 'success' ? 'check' : 'info'), el('div', { class: 'toast-body', text: o.message }), Button({ icon: 'x', variant: 'ghost', size: 'sm', title: 'Dismiss', onClick: function () { o.onDismiss ? o.onDismiss(t) : t.remove(); } })]); return t; }
  function Banner(o) { var b = el('div', { class: 'banner' + (o.kind ? ' banner-' + o.kind : ''), role: o.kind ? 'status' : 'alert' }, [Icon(o.kind === 'info' ? 'info' : 'alert'), el('div', { html: o.html, text: o.html ? null : o.message }), el('span', { class: 'spacer' })]); (o.actions || []).forEach(function (a) { b.append(a); }); return b; }
  function Card(o) { o = o || {}; var c = el('section', { class: 'card' + (o.class ? ' ' + o.class : '') }); if (o.title || o.actions) c.append(el('div', { class: 'card-head' }, [el('h3', { text: o.title }), o.actions ? el('div', { class: 'row' }, o.actions) : null])); c.append(el('div', { class: 'card-body' }, o.body)); if (o.footer) c.append(el('div', { class: 'card-foot' }, o.footer)); return c; }
  function Table(o) { var t = el('table', { class: 'table' }); var thead = el('thead'); var tr = el('tr'); o.columns.forEach(function (c) { tr.append(el('th', { class: c.num ? 'num' : null, text: c.label, scope: 'col' })); }); thead.append(tr); t.append(thead); var tb = el('tbody'); (o.rows || []).forEach(function (r) { var row = el('tr', { class: r.class }); o.columns.forEach(function (c) { var v = typeof c.cell === 'function' ? c.cell(r) : r[c.key]; row.append(el('td', { class: c.num ? 'num' : null }, v)); }); tb.append(row); }); t.append(tb); return el('div', { class: 'table-wrap' }, t); }
  function Tabs(o) { var wrap = el('div', { class: 'tabs', role: 'tablist' }); var value = o.value; o.tabs.forEach(function (tab) { var b = el('button', { type: 'button', role: 'tab', 'aria-selected': String(tab.value === value), text: tab.label, onClick: function () { value = tab.value; wrap.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-selected', 'false'); }); b.setAttribute('aria-selected', 'true'); o.onChange && o.onChange(value); } }); wrap.append(b); }); return wrap; }
  function Kbd(k) { return el('kbd', { class: 'kbd', text: k }); }
  function Skeleton(o) { o = o || {}; return el('span', { class: 'skeleton', 'aria-hidden': 'true', style: { width: o.width || '100%', height: o.height || '14px' } }); }
  function EmptyState(o) { return el('div', { class: 'empty' }, [o.icon ? Icon(o.icon, 28) : null, el('h3', { text: o.title }), o.body ? el('p', { style: { margin: 0 }, text: o.body }) : null, o.actions ? el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '8px' } }, o.actions) : null]); }
  function LogLine(l) { var t = l.text || ''; var cls = 'log-line ' + (l.stream || 'stdout'); if (/error|failed/i.test(t)) cls += ' err'; else if (/warn/i.test(t)) cls += ' warn'; var d = new Date((l.ts || 0) * 1000); var ts = l.ts ? d.toTimeString().slice(0, 8) : ''; return el('div', { class: cls }, [el('span', { class: 'ts', text: ts }), el('span', { text: t })]); }
  function NavItem(o) { var a = el('a', { class: 'nav-item', href: o.href || '#', 'aria-current': o.current ? 'page' : null, onClick: o.onClick }, [o.icon ? Icon(o.icon) : null, el('span', { text: o.label }), o.count != null ? el('span', { class: 'count', text: String(o.count) }) : null]); return a; }
  function Dialog(o) {
    var d = el('dialog', { class: 'dialog', 'aria-labelledby': 'dlg-title' });
    var closeBtn = Button({ icon: 'x', variant: 'ghost', title: 'Close', onClick: function () { d.close('cancel'); } });
    d.append(el('div', { class: 'dialog-head' }, [el('h2', { id: 'dlg-title', text: o.title }), closeBtn]), el('div', { class: 'dialog-body' }, o.body), el('div', { class: 'dialog-foot' }, o.actions));
    return d;
  }
  function InstanceCard(i, h) {
    h = h || {}; var st = STATE_TONE[i.state] || 'muted';
    var card = el('article', { class: 'card inst-card' + (i.state === 'failed' ? ' is-failed' : ''), tabindex: '0', 'aria-label': i.name + ', ' + i.state });
    card.append(el('div', { class: 'head' }, [el('div', { class: 'stack', style: { gap: '4px' } }, [el('div', { class: 'row' }, [el('span', { class: 'name', text: i.name }), Badge({ label: i.kind, tone: i.kind === 'router' ? 'purple' : null })]), StatusDot({ state: i.state, label: i.state + (i.state === 'starting' && i.elapsed != null ? ' · ' + i.elapsed + 's' : '') })]), Button({ icon: 'more', variant: 'ghost', title: 'More', onClick: h.onMore })]));
    if (i.kind === 'router') { var ul = el('ul', { class: 'models' }); (i.models || []).forEach(function (m) { ul.append(el('li', {}, [el('span', { class: 'dot ' + (m.loaded ? 'dot-green' : 'dot-off'), 'aria-hidden': 'true' }), el('span', { text: m.id }), el('span', { class: 'muted small', text: m.loaded ? 'loaded' : 'unloaded' }), Button({ label: m.loaded ? 'Unload' : 'Load', size: 'sm', onClick: function () { h.onModel && h.onModel(m.id, !m.loaded); } })])); }); card.append(ul); }
    else card.append(el('div', { class: 'model' }, [el('b', { text: i.model_name || i.model_id }), i.nickname ? ' · ' + i.nickname : null]));
    card.append(el('div', { class: 'endpoint' }, [el('code', { text: i.url }), Button({ icon: 'copy', variant: 'ghost', size: 'sm', title: 'Copy endpoint', onClick: h.onCopy })]));
    card.append(el('div', { class: 'meta' }, [el('span', { text: 'up ' + (i.uptime || '—') }), el('span', { text: 'rss ' + (i.rss || '—') }), el('span', { class: 'dim', text: 'pid ' + (i.pid == null ? '—' : i.pid) })]));
    var params = el('div', { class: 'row' }); (i.badges || []).forEach(function (b) { params.append(Badge(b)); }); card.append(params);
    var r = i.relay || { state: 'off' }; var rt = STATE_TONE[r.state] || 'muted';
    card.append(el('div', { class: 'relay' }, [Toggle({ checked: r.state !== 'off', tone: 'cyan', title: 'Publish to Relay', onChange: h.onPublish }), StatusDot({ state: r.state, label: r.label || (r.state === 'registered' ? 'registered' : r.state === 'pending' ? 'pending' : r.state === 'error' ? 'error · ' + (r.error || '') : 'not published') }), r.alias ? Badge({ label: r.alias, tone: 'cyan' }) : null, r.health ? el('span', { class: 'muted small', text: 'relay ' + r.health }) : null]));
    if (i.state === 'failed') { var log = el('div', { class: 'log' }); (i.last_log_lines || []).forEach(function (t) { log.append(LogLine({ text: t })); }); card.append(el('div', { class: 'err' }, [el('div', { class: 'status status-red' }, [Icon('alert'), i.last_error || 'failed']), log, el('div', { class: 'row', style: { marginTop: '8px' } }, [Button({ label: 'View logs', size: 'sm', onClick: h.onLogs }), Button({ label: 'Retry', size: 'sm', onClick: h.onRetry }), Button({ label: 'Dismiss', size: 'sm', variant: 'ghost', onClick: h.onDismiss })])])); }
    else card.append(el('div', { class: 'actions' }, [Button({ label: 'Logs', icon: 'logs', size: 'sm', onClick: h.onLogs }), Button({ label: 'Try it', icon: 'chat', size: 'sm', disabled: i.state !== 'ready', onClick: h.onTry }), Button({ label: 'Restart', icon: 'refresh', size: 'sm', onClick: h.onRestart }), Button({ label: 'Stop', icon: 'square', size: 'sm', variant: 'danger', onClick: h.onStop }), Button({ icon: 'copy', size: 'sm', title: 'Copy command', onClick: h.onCopyCmd })]));
    return card;
  }
  window.Lcpp = { el: el, Icon: Icon, Logo: Logo, Button: Button, Badge: Badge, Chip: Chip, StatusDot: StatusDot, Toggle: Toggle, Segmented: Segmented, Field: Field, MemoryMeter: MemoryMeter, RelayPill: RelayPill, Toast: Toast, Banner: Banner, Card: Card, Table: Table, Tabs: Tabs, Kbd: Kbd, Skeleton: Skeleton, EmptyState: EmptyState, LogLine: LogLine, NavItem: NavItem, Dialog: Dialog, InstanceCard: InstanceCard, STATE_TONE: STATE_TONE };
})();
