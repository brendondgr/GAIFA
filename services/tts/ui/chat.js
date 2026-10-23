// Speech in Chat (plan 45.4): the live card for tts_speak, after the prototype the user approved
// (docs/reference/live-cards-2026-10/). While it's made, the waveform grows from the audio the job has made so
// far (GET …/speech/jobs/{id}/audio, through the hub) and the text fills in a line at a time, the line being
// spoken shimmering; "Play while it speaks" plays it from the first chunk. When done: a waveform you click to seek,
// the line playing highlighted, and the output's buttons. Loaded from `[ui] chat` (plan 44.1).

const BARS = 120;

/** The text as the card shows it: its non-empty lines, long ones split at sentence ends (as the mod splits them). */
export function linesOf(text) {
  const out = [];
  for (let line of String(text || '').split('\n')) {
    line = line.trim();
    if (!line) continue;
    if (line.length <= 160) out.push(line);
    else out.push(...line.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean));
  }
  return out.length ? out : [String(text || '').trim()];
}

/** Bar heights (0..1) for `n` bars over 16-bit samples; `made` of `total` seconds fills that share of the bars. */
export function peaksOf(samples, n = BARS) {
  const out = new Array(n).fill(0);
  if (!samples || !samples.length) return out;
  const per = samples.length / n;
  let max = 1;
  for (let i = 0; i < n; i++) {
    let m = 0;
    const a = Math.floor(i * per), b = Math.max(a + 1, Math.floor((i + 1) * per));
    for (let j = a; j < b && j < samples.length; j += 4) { const v = Math.abs(samples[j]); if (v > m) m = v; }
    out[i] = m; if (m > max) max = m;
  }
  return out.map(v => v / max);
}

/** The line at `frac` (0..1) of the way through, by characters. */
export function lineAt(lines, frac) {
  const total = lines.reduce((s, l) => s + l.length + 1, 0);
  let at = 0;
  for (let i = 0; i < lines.length; i++) { at += lines[i].length + 1; if (at / total > frac) return i; }
  return lines.length - 1;
}

/** 16-bit samples of a WAV (its data chunk), or null. */
export function wavSamples(buf) {
  const v = new DataView(buf);
  if (buf.byteLength < 44 || v.getUint32(0) !== 0x52494646) return null;
  let p = 12;
  while (p + 8 <= buf.byteLength) {
    const id = v.getUint32(p), len = v.getUint32(p + 4, true);
    if (id === 0x64617461) return new Int16Array(buf.slice(p + 8, p + 8 + (Math.min(len, buf.byteLength - p - 8) & ~1)));
    p += 8 + len + (len & 1);
  }
  return null;
}

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, { ActionBar } = chat.parts || {};
  const R = () => globalThis.React;

  function useStream(url) {          // the job's PCM as it's made: {samples, sr, done}
    const React = R(), [st, setSt] = React.useState({ samples: new Int16Array(0), sr: 24000, done: false });
    React.useEffect(() => {
      if (!url) return undefined;
      let alive = true, offset = 0, parts = [];
      (async () => {
        while (alive) {
          let r;
          try { r = await fetch(`${url}?offset=${offset}&wait=5`, { cache: 'no-store' }); } catch { break; }
          if (!r.ok) break;
          const buf = await r.arrayBuffer(), done = r.headers.get('X-Done') === '1', sr = +r.headers.get('X-Sample-Rate') || 24000;
          if (buf.byteLength) { parts.push(new Int16Array(buf.slice(0, buf.byteLength & ~1))); offset += buf.byteLength & ~1; }
          const all = new Int16Array(parts.reduce((s, p) => s + p.length, 0)); let o = 0;
          for (const p of parts) { all.set(p, o); o += p.length; }
          parts = [all];
          if (alive) setSt({ samples: all, sr, done });
          if (done) break;
        }
      })();
      return () => { alive = false; };
    }, [url]);
    return st;
  }

  function Wave({ peaks, made, played, onSeek }) {
    const n = peaks.length;
    return h('div', { onClick: onSeek, role: onSeek ? 'slider' : undefined, 'aria-label': onSeek ? 'Seek' : undefined,
      style: { display: 'flex', alignItems: 'center', gap: 2, height: 56, padding: '0 12px', cursor: onSeek ? 'pointer' : 'default' } },
      peaks.map((v, i) => {
        const x = i / n, on = x < made;
        return h('span', { key: i, style: { flex: 1, minWidth: 1, borderRadius: 1, height: on ? Math.max(3, v * 48) : 3,
          background: x < played ? 'var(--acc,#FFB224)' : on ? 'var(--mut,#8A94A6)' : 'rgba(138,148,166,.18)', transition: 'height .25s' } });
      }));
  }

  function SpeechCard({ ctx }) {
    const React = R(), { row, live, note, status, outputs } = ctx.liveCard;
    const args = row.item.call?.arguments || {}, out = outputs[0];
    const done = status === 'done', failed = status === 'failed' || status === 'error';
    const lines = React.useMemo(() => linesOf(args.text), [args.text]);
    const stream = useStream(!done && live?.audio ? live.audio : null);
    const [file, setFile] = React.useState(null), [playing, setPlaying] = React.useState(false), [t, setT] = React.useState(0);
    const audioRef = React.useRef(null), webRef = React.useRef(null);
    React.useEffect(() => {          // done: the saved clip's samples, for its waveform
      if (!done || !out?.url) return;
      fetch(out.url).then(r => r.arrayBuffer()).then(b => setFile(wavSamples(b))).catch(() => {});
    }, [done, out?.url]);
    const samples = done ? (file || stream.samples) : stream.samples;
    const peaks = React.useMemo(() => peaksOf(samples), [samples]);
    const madeS = stream.samples.length / stream.sr;
    const linesDone = done ? lines.length : live?.lines ? live.lines[0] : 0;
    const madeFrac = done ? 1 : live?.lines ? Math.min(1, (live.lines[0] + 0.5) / Math.max(1, live.lines[1])) : 0;
    const dur = audioRef.current?.duration || out?.duration_s || madeS || 1;
    const playFrac = playing || t ? Math.min(1, t / dur) : 0;
    const now = playing ? lineAt(lines, playFrac) : -1;

    React.useEffect(() => {          // the playhead while the saved clip plays
      if (!playing || webRef.current) return undefined;
      let raf = 0; const tick = () => { if (audioRef.current) setT(audioRef.current.currentTime); raf = requestAnimationFrame(tick); };
      raf = requestAnimationFrame(tick);
      return () => cancelAnimationFrame(raf);
    }, [playing]);
    React.useEffect(() => () => { webRef.current?.ctx.close().catch(() => {}); }, []);
    React.useEffect(() => {          // while it speaks: queue each new chunk after the last
      const w = webRef.current;
      if (!w || w.fed >= stream.samples.length) return;
      const chunk = stream.samples.subarray(w.fed), b = w.ctx.createBuffer(1, chunk.length, stream.sr), d = b.getChannelData(0);
      for (let i = 0; i < chunk.length; i++) d[i] = chunk[i] / 32768;
      const src = w.ctx.createBufferSource(); src.buffer = b; src.connect(w.ctx.destination);
      const at = Math.max(w.ctx.currentTime, w.next); src.start(at); w.next = at + b.duration; w.fed = stream.samples.length;
    }, [stream.samples, playing]);

    const playLive = () => {
      if (webRef.current) { webRef.current.ctx.close().catch(() => {}); webRef.current = null; setPlaying(false); return; }
      const AC = globalThis.AudioContext || globalThis.webkitAudioContext; if (!AC) return;
      webRef.current = { ctx: new AC(), fed: 0, next: 0 }; setPlaying(true); setT(0);
      const tick = () => { const w = webRef.current; if (!w) return; setT(w.ctx.currentTime); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    };
    const playFile = () => {
      const a = audioRef.current; if (!a) return;
      if (webRef.current) { webRef.current.ctx.close().catch(() => {}); webRef.current = null; }
      if (a.paused) { a.play(); setPlaying(true); } else { a.pause(); setPlaying(false); }
    };
    const seek = e => {
      const a = audioRef.current; if (!a || !done) return;
      const r = e.currentTarget.getBoundingClientRect(); a.currentTime = Math.max(0, (e.clientX - r.left) / r.width) * (a.duration || dur);
      setT(a.currentTime); if (a.paused) { a.play(); setPlaying(true); }
    };

    const voice = args.name || 'the default voice';
    const title = done ? 'Spoke' : failed ? "Couldn't speak it" : 'Speaking';
    const meta = done ? [fmt(out?.duration_s || dur), row.seconds != null ? `made in ${fmt(row.seconds)}` : null].filter(Boolean).join(' · ')
      : failed ? '' : live?.lines ? `line ${Math.min(live.lines[0] + 1, live.lines[1])}/${live.lines[1]}` + (live.eta_s != null ? ' · ' + kit.fmtLeft(live.eta_s) : '') : kit.metaText(live, status);
    const wait = !done && !failed && !stream.samples.length ? kit.waitInfo(live?.stage === 'speaking' ? null : live, note, { model: 'the voice', starting: 'Getting the voice ready' }) : null;
    const btn = (label, onClick, pri) => h('button', { type: 'button', onClick, style: { border: pri ? 0 : '1px solid var(--bd,#1D2430)', borderRadius: 6, padding: '3px 10px', fontSize: 12,
      background: pri ? 'var(--acc,#FFB224)' : 'transparent', color: pri ? '#1A1200' : 'var(--tx,#E6EAF2)', fontWeight: pri ? 600 : 400, cursor: 'pointer' } }, label);
    const foot = done && out ? [
      btn(playing ? '❚❚ Pause' : '▶ Play', playFile, true),
      h('span', { key: 'n', style: { fontFamily: kit.MONO, fontSize: 11, fontWeight: 600, color: 'var(--pu,#BC8CFF)' } }, out.n ? '#' + out.n : ''),
      h('span', { key: 'v' }, voice),
      ActionBar ? h('span', { key: 'a', style: { marginLeft: 'auto' } }, h(ActionBar, { output: out, ctx })) : null,
    ] : !failed && stream.samples.length ? [btn(playing ? '■ Stop' : '▶ Play while it speaks', playLive), h('span', { key: 'v' }, voice)] : null;

    return h(kit.LiveCard, { icon: 'audio', title, meta, pct: row.progress?.progress, done, failed, foot },
      wait ? h('div', { style: { position: 'relative', height: 56, margin: '0 12px', borderRadius: 6, overflow: 'hidden', background: 'var(--inset,#131926)' } },
        h(kit.Waiting, { title: wait.title, sub: wait.sub })) : h(Wave, { peaks, made: madeFrac, played: playFrac, onSeek: done ? seek : null }),
      h('div', { style: { maxHeight: 150, overflow: 'auto', padding: '4px 12px 8px', fontSize: 13, lineHeight: 1.55 } },
        lines.map((l, i) => h('div', { key: i, className: !done && !failed && i === linesDone ? 'lk-say' : undefined,
          style: { color: i === now ? 'var(--acc,#FFB224)' : done || i < linesDone ? 'var(--tx,#E6EAF2)' : 'var(--dim,#737D90)', transition: 'color .3s' } }, l))),
      done && out?.url ? h('audio', { ref: audioRef, src: out.url, preload: 'metadata', onEnded: () => { setPlaying(false); setT(0); }, style: { display: 'none' } }) : null);
  }

  chat.registerCard('live:tts_speak', ({ ctx }) => h(SpeechCard, { ctx }));
}

function fmt(s) {
  if (s == null || !isFinite(s)) return '';
  s = Math.round(s);
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
