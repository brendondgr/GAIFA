// Settings → General → Network (plan lan-access 2.2): open GAIFA to other devices on your network, or close it.
// Off by default; it needs a password and a restart of GAIFA. On this machine: the switch, the password, the
// addresses to open, the firewall command, the devices signed in. On a device on the network: read-only, and
// Sign out. The pure parts (`lanSummary`, `firewallCommand`, `lanSteps`) are tested in settings-lan.test.mjs.
// Written by us (web/PATCHES.md).

import { h, T, MONO } from '../chat/chat-ui.js';
import { Toggle, label11 } from './rows.js';

const R = () => globalThis.React;
export const MIN_PASSWORD = 12;

/** One line for where it stands. */
export function lanSummary(st) {
  if (!st) return 'Other devices on your network';
  if (st.remote) return 'You are signed in from another device';
  if (!st.enabled) return st.listening ? 'Off: restart GAIFA to close it' : 'Off: GAIFA answers this machine only';
  if (!st.has_password) return 'On, but no password is set';
  if (!st.listening) return 'On: restart GAIFA to open it';
  const n = (st.devices || []).length;
  return `Open to your network · ${n} device${n === 1 ? '' : 's'} signed in`;
}

/** The command that opens the ports on Fedora's firewall (GAIFA never runs sudo; it is the user's to run). */
export const firewallCommand = st => {
  const ports = [st?.port || 7000, ...(st?.https && st.https !== 'off' ? [st.https_port || 7443] : [])];   // HTTPS too, unless turned off
  return `sudo firewall-cmd --permanent ${ports.map(p => `--add-port=${p}/tcp`).join(' ')} && sudo firewall-cmd --reload`;
};

/** What is left to do, in order: 'password', 'switch', 'restart', or null when it is open. */
export function lanSteps(st) {
  if (!st || st.remote) return null;
  if (!!st.enabled !== !!st.listening && (st.has_password || !st.enabled)) return 'restart';   // on or off: applies when GAIFA restarts
  if (!st.has_password) return 'password';
  if (!st.enabled) return 'switch';
  return null;
}

const ago = ts => {
  const s = Math.max(0, Date.now() / 1000 - (ts || 0));
  return s < 90 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
const btn = (o = {}) => ({ height: 28, padding: '0 10px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', ...o });
const codeBox = (text, onCopy) => h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
  h('code', { style: { fontFamily: MONO, fontSize: 12, padding: '6px 8px', borderRadius: 6, background: T.inset, overflowWrap: 'anywhere', flex: '1 1 260px' } }, text),
  h('button', { type: 'button', style: btn(), onClick: () => onCopy(text) }, 'Copy'));

export function NetworkCard({ ctx }) {
  const React = R(), api = ctx.api;
  const [st, setSt] = React.useState(null), [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false);
  const [pw, setPw] = React.useState(''), [pw2, setPw2] = React.useState(''), [note, setNote] = React.useState(null);
  const load = () => api.getLan().then(setSt, setErr);
  React.useEffect(() => { load(); }, []);
  const run = async (fn, done) => {
    setBusy(true); setErr(null);
    try { const r = await fn(); if (done) setNote(done(r)); await load(); } catch (e) { setErr(e); }
    setBusy(false);
  };
  const copy = t => globalThis.navigator?.clipboard?.writeText(t).then(() => ctx.toast?.('Copied'), () => {});
  const restart = () => run(async () => {
    await api.restartHub();
    setNote('Restarting GAIFA… this page reloads when it is back.');
    const t0 = Date.now();
    await new Promise(r => setTimeout(r, 2500));
    while (Date.now() - t0 < 30000) { try { await api.getLan(); break; } catch { await new Promise(r => setTimeout(r, 1000)); } }
    globalThis.location?.reload();
  });
  const section = (...kids) => h('section', { 'aria-label': 'Network', style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 } }, ...kids);
  const errLine = err ? h('div', { role: 'alert', style: { fontSize: 13, color: T.rd } }, err.detail || String(err.message || err)) : null;
  if (!st) return section(h('h2', { style: label11 }, 'Other devices on your network'), errLine || h('div', { style: { fontSize: 13, color: T.mut } }, 'Loading…'));
  if (st.remote) {
    return section(h('h2', { style: label11 }, 'Other devices on your network'),
      h('div', { style: { fontSize: 13 } }, `You are signed in from ${st.me?.label || 'this device'} (${st.me?.addr || ''}). The network settings, the password and Bypass are changed on the GAIFA machine itself.`),
      h('button', { type: 'button', style: btn({ alignSelf: 'flex-start' }), onClick: async () => { await api.signOutThisDevice().catch(() => {}); globalThis.location?.reload(); } }, 'Sign out this device'));
  }
  const step = lanSteps(st), pwOk = pw.length >= MIN_PASSWORD && pw === pw2;
  const pwForm = h('form', { style: { display: 'flex', flexDirection: 'column', gap: 8 }, onSubmit: e => { e.preventDefault(); if (pwOk) run(() => api.setLanPassword(pw), () => { setPw(''); setPw2(''); return 'Password set. Every device signs in again.'; }); } },
    h('div', { style: { fontSize: 12.5, fontWeight: 600 } }, st.has_password ? 'Change the password' : 'Set a password first'),
    h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
      h('input', { type: 'password', autoComplete: 'new-password', placeholder: `Password (at least ${MIN_PASSWORD} characters)`, 'aria-label': 'Password for other devices', value: pw, onChange: e => setPw(e.target.value),
        style: { flex: '1 1 200px', height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 13 } }),
      h('input', { type: 'password', autoComplete: 'new-password', placeholder: 'Again', 'aria-label': 'The password again', value: pw2, onChange: e => setPw2(e.target.value),
        style: { flex: '1 1 140px', height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 13 } }),
      h('button', { type: 'submit', disabled: busy || !pwOk, style: btn({ opacity: pwOk ? 1 : 0.5 }) }, 'Set password')),
    pw && pw2 && pw !== pw2 ? h('div', { style: { fontSize: 12, color: T.rd } }, 'They differ.') : null);
  const devices = st.devices || [];
  return section(
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
      h('h2', { style: { ...label11, flex: 1 } }, 'Other devices on your network'),
      h(Toggle, { on: !!st.enabled, label: 'Open GAIFA to your network', disabled: busy || (!st.enabled && !st.has_password),
        onChange: v => run(() => api.saveLan({ enabled: v }), r => r.restart_required ? null : v ? 'Open to your network.' : 'Closed to the network.') })),
    h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Off by default. On, a phone or laptop on the same Wi-Fi or wired network opens GAIFA by this machine’s address and signs in with the password. ',
      'Only devices on your own network get in, never the internet; this machine never needs the password. Bypass, folder levels and these settings stay on this machine.'),
    errLine,
    note ? h('div', { role: 'status', style: { fontSize: 13 } }, note) : null,
    step === 'restart' ? h('div', { style: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '8px 10px', borderRadius: 7, background: T.inset } },
      h('span', { style: { fontSize: 13, flex: 1 } }, st.enabled ? 'Turned on: GAIFA starts listening on the network when it restarts.' : 'Turned off: GAIFA stops listening on the network when it restarts.'),
      h('button', { type: 'button', disabled: busy, style: btn(), onClick: restart }, 'Restart GAIFA now')) : null,
    st.enabled && st.listening ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
      h('div', { style: { fontSize: 12.5, fontWeight: 600 } }, 'On another device, open'),
      ...(st.urls || []).slice(0, 3).map(u => codeBox(u, copy))) : null,
    st.enabled && st.listening ? h('div', { style: { fontSize: 12.5, color: T.mut } }, st.https_listening
      ? ['Voice mode and dictation need the HTTPS address. Its browser warns once about GAIFA’s own certificate, or trust it there (',
        h('code', { key: 'c' }, '/lan/trust'), ' on that device). Certificate fingerprint: ', h('code', { key: 'f', style: { fontFamily: MONO, overflowWrap: 'anywhere' } }, st.ca_fingerprint || '—')]
      : 'No HTTPS (Settings → [hub.lan] https, or openssl is missing): voice mode and dictation won’t work on other devices.') : null,
    pwForm,
    st.enabled ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
      h('div', { style: { fontSize: 12.5, fontWeight: 600 } }, 'If other devices can’t reach it'),
      h('div', { style: { fontSize: 12.5, color: T.mut } }, 'This machine’s firewall blocks the port. Run this once in a terminal (it needs your password; GAIFA never runs sudo):'),
      codeBox(firewallCommand(st), copy)) : null,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('div', { style: { fontSize: 12.5, fontWeight: 600, flex: 1 } }, `Devices signed in (${devices.length})`),
        devices.length > 1 ? h('button', { type: 'button', style: btn(), disabled: busy, onClick: () => run(() => api.signOutLanDevice('all'), () => 'Every device is signed out.') }, 'Sign out everyone') : null),
      devices.length ? null : h('div', { style: { fontSize: 12.5, color: T.mut } }, 'None.'),
      ...devices.map(d => h('div', { key: d.id, style: { display: 'flex', gap: 10, alignItems: 'center', padding: '6px 10px', borderRadius: 7, background: T.inset, flexWrap: 'wrap' } },
        h('span', { style: { fontSize: 13, flex: '1 1 160px' } }, d.label),
        h('span', { style: { fontFamily: MONO, fontSize: 12, color: T.mut } }, d.addr),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'last used ' + ago(d.last)),
        h('button', { type: 'button', style: btn(), disabled: busy, onClick: () => run(() => api.signOutLanDevice(d.id), () => `${d.label} is signed out.`) }, 'Sign out')))));
}

export const LAN_BLOCKS = { NetworkCard };
