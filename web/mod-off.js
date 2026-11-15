// One box for a mod that isn't on (plan capability-enablement 3.3), drawn by its availability (utils/services/availability.py):
// not set up → Set up (a small setup runs from the button, a bigger one asks first), or have your coding agent do it;
// turned off → Turn on; stopped → Start; starting → no button; failed → the error, Start and View logs; can't run → why;
// broken → the manifest's errors. Every mod page reaches it through mod-kit.js `requireRunning`.
// Written by us, not Claude Design. Plain DOM, as the page modules are.

import { h } from './mod-ui.js';

export const SMALL_GB = 0.5;     // a setup under this, with no question and no host problem, runs straight from the button

/** The availability status the box draws: the hub's, or the state's when an older hub gave none. */
export function statusOf(svc) {
  const st = svc?.availability?.status;
  if (st) return st === 'on' && svc.state === 'starting' ? 'starting' : st;
  if (svc?.manifest_errors?.length) return 'broken';
  if (svc?.state === 'starting') return 'starting';
  if (svc?.state === 'failed') return 'failed';
  if (svc?.enabled === false) return 'off';
  return svc?.state === 'ready' || svc?.state === 'degraded' ? 'on' : 'starts_on_use';
}

/** Is this setup small enough to run from the button: no question, under SMALL_GB, no host problem. */
export function isSmall(plan) {
  if (!plan) return false;
  const hostBad = (plan.host || []).some(x => x && x.ok === false && (!x.gpu || plan.gpu));   // a GPU-only check doesn't matter to a CPU mod
  return !(plan.questions || []).length && (plan.disk_gb ?? 99) < SMALL_GB && !hostBad && !(plan.blocking || []).length;
}

/** What it installs, in a line: the steps' words and the size. */
export function installs(plan) {
  if (!plan) return '';
  const what = (plan.steps || []).map(s => s.what).filter(Boolean).join('; ');
  const gb = plan.disk_gb != null ? `${plan.disk_gb < 1 ? plan.disk_gb.toFixed(1) : Math.round(plan.disk_gb)} GB` : '';
  return [what, gb && `about ${gb} in all`].filter(Boolean).join(' · ');
}

const firstLine = t => String(t || '').split('\n\nLast log lines:')[0].split('\n')[0].trim();

/** The box's words and buttons for a service: {status, title, body, buttons: [{id, label, primary?}], agent: bool}. */
export function offView(svc, what = 'this page', plan = null) {
  const name = svc?.name || svc?.id || 'This mod', st = statusOf(svc), av = svc?.availability || {};
  const gives = svc?.provides ? `It lets GAIFA ${svc.provides}.` : '';
  switch (st) {
    case 'not_set_up':
      return { status: st, title: `${name} isn't set up on this machine`,
        body: [gives, plan ? `Setting it up: ${installs(plan)}.` : ''].filter(Boolean).join(' '),
        buttons: [{ id: 'setup', label: `Set up ${name}`, primary: true }], agent: true, small: isSmall(plan) };
    case 'off':
      return { status: st, title: `${name} is turned off`, body: [gives, `Turn it on to use ${what}.`].filter(Boolean).join(' '),
        buttons: [{ id: 'enable', label: `Turn on ${name}`, primary: true }] };
    case 'starting':
      return { status: st, title: `${name} is starting…`, body: 'This page opens as soon as it is ready.', buttons: [] };
    case 'failed':
      return { status: st, title: `${name} didn't start`, body: firstLine(svc.last_error) || av.why || 'The process exited.',
        buttons: [{ id: 'start', label: `Start ${name}`, primary: true }, { id: 'logs', label: 'View logs' }] };
    case 'cant_run':
      return { status: st, title: `${name} can't run on this machine`, body: av.why || svc.unavailable || '', buttons: [{ id: 'setup', label: `Set up ${name} again`, primary: true }], agent: true };
    case 'broken':
      return { status: st, title: `${name} has a problem in its service.toml`, body: (svc.manifest_errors || []).join(' · ') || av.why || '',
        buttons: [{ id: 'logs', label: 'Show details' }] };
    default:
      return { status: st, title: `${name} is not running`, body: `Start it to use ${what}.`, buttons: [{ id: 'start', label: `Start ${name}`, primary: true }] };
  }
}

const btnSt = primary => `height:30px;padding:0 14px;border-radius:7px;font:inherit;font-size:12.5px;cursor:pointer;${primary
  ? 'border:0;background:var(--acc,#FFB224);color:#1A1200;font-weight:600' : 'border:1px solid var(--bds,#2A3547);background:transparent;color:var(--tx,#E6EAF2)'}`;

/** Fill `el` with the box for ctx.service. `ctx` is a page module's context (api, toast, confirm). */
export function modOff(el, ctx, what = 'this page') {
  const svc = ctx.service, api = ctx.api, id = svc.id;
  const box = h('div', { 'data-mod-off': statusOf(svc), style: 'padding:40px 20px;display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;border:1px dashed var(--bds,#2A3547);border-radius:12px' });
  el.append(box);
  let plan = null, busy = false;
  const fail = e => { busy = false; ctx.toast?.(e?.detail || e?.message || String(e), 'error'); draw(); };
  const progress = h('pre', { style: 'display:none;margin:0;max-width:560px;width:100%;max-height:140px;overflow:auto;text-align:left;font-size:11px;padding:8px 10px;border-radius:6px;background:var(--inset,#131926)' });
  const runSetup = async () => {
    busy = true; draw();
    try {
      await api.startSetup([id]);
      progress.style.display = 'block';
      const off = ctx.on?.('setup', ev => {
        const j = ev.job || ev;
        if (!j || !(j.ids || []).includes(id)) return;
        progress.textContent = (j.lines || []).slice(-12).join('\n');
        if (j.state !== 'running') {
          off?.(); busy = false;
          if (j.state === 'done') ctx.toast?.(`${svc.name} is set up`, 'success');
          else if (j.state === 'needs_you') { globalThis.dispatchEvent?.(new CustomEvent('gaifa:setup', { detail: { ids: [id] } })); }
          else ctx.toast?.(j.error || `Setting up ${svc.name} ${j.state}`, 'error');
          draw();
        }
      });
    } catch (e) { fail(e); }
  };
  const act = async b => {
    if (busy) return;
    if (b.id === 'start') { busy = true; draw(); api.startService(id).catch(fail); return; }
    if (b.id === 'logs') { location.hash = `#/s/${id}/${statusOf(svc) === 'broken' ? 'settings' : 'logs'}`; return; }
    if (b.id === 'enable') {
      busy = true; draw();
      try { await api.saveServiceConfig(id, { enabled: true }); await api.startService(id); } catch (e) { fail(e); }
      return;
    }
    if (b.id === 'setup') {
      if (isSmall(plan)) return runSetup();
      // a bigger setup: the Set up dialog (setup-dialog.js) when the page has it, else ask here with the plan's words
      if (globalThis.dispatchEvent && globalThis.GAIFA_SETUP_DIALOG) { globalThis.dispatchEvent(new CustomEvent('gaifa:setup', { detail: { ids: [id] } })); return; }
      const ok = await ctx.confirm?.({ title: `Set up ${svc.name}?`, body: installs(plan) || `This runs gaifa setup ${id}.` });
      if (ok) runSetup();
    }
  };
  const agentLink = () => h('button', { type: 'button', style: 'background:none;border:0;padding:0;color:var(--mut,#8A94A6);font:inherit;font-size:12px;cursor:pointer;text-decoration:underline',
    onclick: async () => {
      try {
        const text = await api.getSetupPrompt([id]);
        await globalThis.navigator?.clipboard?.writeText(text);
        ctx.toast?.('Copied: paste it into Claude Code or Codex', 'success');
      } catch (e) { fail(e); }
    } }, 'or have your coding agent do it (copy a prompt)');
  function draw() {
    const v = offView(svc, what, plan);
    box.replaceChildren(...[
      h('h2', { style: 'margin:0;font-size:16px' }, v.title),
      v.body ? h('p', { style: 'margin:0;color:var(--mut,#8A94A6);max-width:480px;overflow-wrap:anywhere' }, v.body) : null,
      v.buttons.length ? h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;justify-content:center' },
        v.buttons.map(b => h('button', { type: 'button', disabled: busy, style: btnSt(b.primary) + (busy ? ';opacity:.6;cursor:default' : ''), onclick: () => act(b) },
          busy && b.primary ? b.label + '…' : b.label))) : null,
      v.agent ? agentLink() : null, progress].filter(Boolean));      // replaceChildren would write "null" for a missing part
  }
  draw();
  if (statusOf(svc) === 'not_set_up' && api.getSetupPlan) api.getSetupPlan([id]).then(p => { plan = p; draw(); }, () => {});
  return box;
}
