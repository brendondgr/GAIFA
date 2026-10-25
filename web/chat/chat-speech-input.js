// Settings → Speech → Dictation, and the composer microphone's menu (plan 29.4). The microphones in order of
// preference (matched by label, because browsers change device ids), the one that would be used now, a
// level meter to test it, and the dictation language, stt preset and button mode. Everything is saved in
// the hub's settings (`speech_input`, config.toml), so it survives restarts and works in any browser on
// this machine. The device logic itself is in chat-mic.js.

import { h, T, Icon, Btn, Badge } from './chat-ui.js';
import { audioInputs, pickMic, normLabel, levelOf, LevelBar, speechSettings, BROWSER_DEFAULT } from './chat-mic.js';

const R = () => globalThis.React;
const PRESETS = [['fast', 'Fast'], ['balanced', 'Balanced (default)'], ['accurate', 'Accurate'], ['best', 'Best']];
const MODES = [['both', 'Click or hold'], ['toggle', 'Click to start and stop'], ['hold', 'Hold to talk']];

/** The list as shown: the ranked labels (present or not), then microphones present but not ranked. */
export function micRows(devices, prefs) {
  const inputs = audioInputs(devices).filter(d => d.label);
  const ranked = prefs.map((label, rank) => ({ label, rank, present: inputs.some(d => normLabel(d.label) === normLabel(label)) }));
  const rest = inputs.filter(d => !prefs.some(p => normLabel(p) === normLabel(d.label))).map(d => ({ label: d.label, rank: null, present: true }));
  return [...ranked, ...rest];
}

/** A live level for `mic` without dictating: calls `onLevel` about ten times a second; returns stop(). */
export async function meter(media, mic, onLevel) {
  const stream = await media.getUserMedia({ audio: mic?.deviceId ? { deviceId: { exact: mic.deviceId } } : true });
  const ctx = new AudioContext(), an = ctx.createAnalyser();
  an.fftSize = 2048;
  ctx.createMediaStreamSource(stream).connect(an);
  const buf = new Float32Array(an.fftSize);
  const t = setInterval(() => { an.getFloatTimeDomainData(buf); onLevel(levelOf(buf)); }, 100);
  return () => { clearInterval(t); stream.getTracks().forEach(x => x.stop()); ctx.close().catch(() => {}); };
}

/** The microphones, a level test and (unless `fields` is false) language, model and button mode. Alone (the composer's
 *  menu) it loads and saves `speech_input` itself; given `value` and `onChange` (the Settings page, settings-redesign 4.3)
 *  it edits the page's draft instead and saves nothing. */
export function SpeechInputPanel({ api, compact = false, toast = () => {}, media = globalThis.navigator?.mediaDevices, value, onChange, fields = true }) {
  const React = R();
  const [prefs, setPrefs] = React.useState(null), [devices, setDevices] = React.useState([]);
  const [level, setLevel] = React.useState(null), [err, setErr] = React.useState(null);
  const stopMeter = React.useRef(null);
  const refresh = () => media?.enumerateDevices?.().then(setDevices).catch(() => setDevices([]));
  React.useEffect(() => {
    if (!onChange) speechSettings(api).then(setPrefs);
    refresh();
    media?.addEventListener?.('devicechange', refresh);
    return () => { media?.removeEventListener?.('devicechange', refresh); stopMeter.current?.(); };
  }, []);
  if (onChange) return panelBody({ prefs: value || { mics: [], language: '', preset: 'balanced', mode: 'both' }, save: patch => onChange({ ...value, ...patch }) });
  if (!prefs) return h('span', { style: { color: T.mut, fontSize: 12 } }, 'Loading…');
  return panelBody({ prefs, save: async patch => {
    const next = { ...prefs, ...patch };
    setPrefs(next); setErr(null);
    try { const r = await api.saveSettings({ speech_input: next }); setPrefs(r.settings.speech_input); }
    catch (e) { setErr(e.detail || String(e)); toast(e.detail || String(e), 'error'); }
  } });
  function panelBody({ prefs, save }) {
  const named = audioInputs(devices).some(d => d.label);
  const rows = micRows(devices, prefs.mics);
  const active = pickMic(devices, prefs.mics) || BROWSER_DEFAULT;
  const move = (i, d) => { const m = [...prefs.mics]; [m[i], m[i + d]] = [m[i + d], m[i]]; save({ mics: m }); };
  const reveal = async () => {
    try { (await media.getUserMedia({ audio: true })).getTracks().forEach(t => t.stop()); refresh(); }
    catch (e) { setErr(e?.name === 'NotAllowedError' ? 'Microphone access was refused' : e?.message || 'No microphone'); }
  };
  const test = async () => {
    if (stopMeter.current) { stopMeter.current(); stopMeter.current = null; setLevel(null); return; }
    try { stopMeter.current = await meter(media, active, setLevel); setLevel(0); }
    catch (e) { setErr(e?.message || 'Could not open the microphone'); }
  };
  const lbl = (t, hint) => h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } }, h('span', { style: { fontWeight: 500, fontSize: 12.5 } }, t),
    hint && !compact ? h('span', { style: { fontSize: 12, color: T.mut } }, hint) : null);
  const ctl = { height: 28, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5 };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12.5 } },
    lbl('Microphones, most preferred first', 'The first one plugged in is used; if it is unplugged the next takes over, and a higher one takes over again when it is plugged back in.'),
    !named ? h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
      h('span', { style: { color: T.mut, fontSize: 12 } }, 'The browser shows microphone names once it may use one.'),
      h(Btn, { sm: true, icon: 'mic', label: 'Show microphones', onClick: reveal })) : null,
    h('div', { role: 'list', 'aria-label': 'Microphones', style: { display: 'flex', flexDirection: 'column', gap: 4 } },
      rows.length ? rows.map(r => h('div', { key: r.label, role: 'listitem', style: { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px', borderRadius: 6, border: '1px solid ' + T.bd, background: normLabel(r.label) === normLabel(active.label) ? T.hov : 'transparent' } },
        h('span', { style: { fontFamily: 'inherit', width: 18, color: T.dim, fontSize: 11.5 } }, r.rank == null ? '–' : r.rank + 1),
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: r.present ? T.tx : T.mut }, title: r.label }, r.label),
        normLabel(r.label) === normLabel(active.label) ? h(Badge, { tone: 'green' }, 'in use') : !r.present ? h(Badge, null, 'unplugged') : null,
        r.rank == null ? h(Btn, { sm: true, kind: 'ghost', icon: 'plus', title: `Add ${r.label} to the list`, onClick: () => save({ mics: [...prefs.mics, r.label] }) })
          : h('span', { style: { display: 'inline-flex' } },
            h(Btn, { sm: true, kind: 'ghost', title: 'Prefer it more', 'aria-label': `Prefer ${r.label} more`, disabled: r.rank === 0, onClick: () => move(r.rank, -1) }, h(Icon, { d: 'chevD', size: 13, style: { transform: 'rotate(180deg)' } })),
            h(Btn, { sm: true, kind: 'ghost', title: 'Prefer it less', 'aria-label': `Prefer ${r.label} less`, disabled: r.rank === prefs.mics.length - 1, onClick: () => move(r.rank, 1) }, h(Icon, { d: 'chevD', size: 13 })),
            h(Btn, { sm: true, kind: 'ghost', icon: 'x', title: `Remove ${r.label} from the list`, onClick: () => save({ mics: prefs.mics.filter(x => x !== r.label) }) }))))
        : h('span', { style: { color: T.mut, fontSize: 12 } }, 'No microphones found.')),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
      h('span', { style: { color: T.mut, fontSize: 12, flex: 1, minWidth: 160 } }, !named ? 'Which one is used shows once the browser may use a microphone.' : prefs.mics.length && active === BROWSER_DEFAULT ? 'None of these is plugged in: the browser’s default microphone is used.' : `Dictation uses ${active.label}.`),
      level != null ? h(LevelBar, { level, width: 90 }) : null,
      h(Btn, { sm: true, kind: level != null ? 'pri' : 'sec', icon: 'mic', label: level != null ? 'Stop test' : 'Test level', onClick: test })),
    !fields ? null : h('div', { style: { display: 'grid', gridTemplateColumns: compact ? '1fr' : 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 } },
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, lbl('Language', 'An ISO code such as en or de; empty detects it.'),
        h('input', { 'aria-label': 'Language', defaultValue: prefs.language, placeholder: 'detect', maxLength: 3, style: ctl,
          onBlur: e => { const v = e.target.value.trim().toLowerCase(); if (v !== prefs.language) (/^([a-z]{2,3})?$/.test(v) ? save({ language: v }) : setErr('Language: two or three letters, or empty')); } })),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, lbl('Model', 'Balanced (small) keeps up live; Accurate is slower to commit.'),
        h('select', { 'aria-label': 'Preset', value: prefs.preset, onChange: e => save({ preset: e.target.value }), style: ctl }, PRESETS.map(([v, l]) => h('option', { key: v, value: v }, l)))),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, lbl('The microphone button'),
        h('select', { 'aria-label': 'Button mode', value: prefs.mode, onChange: e => save({ mode: e.target.value }), style: ctl }, MODES.map(([v, l]) => h('option', { key: v, value: v }, l))))),
    err ? h('span', { role: 'alert', style: { color: T.rd, fontSize: 12 } }, err) : null);
  }
}
