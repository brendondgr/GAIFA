// Design study (not wired into the app): the page that lays the options out, steps the sample turn
// through its stages, and keeps the reader's picks. Open /design/chat-activity.html on the hub.

import { h, T, MONO, Icon, Btn, Badge, cardSt, R, KIT_CSS, ctxFor } from './activity-kit.js';
import { MD_CSS } from '../chat/chat-md.js';
import { CARD_CSS } from '../chat/chat-cards.js';
import { OptToday, OptFold, OptRail, OptChapters, OptPanel, OptChips } from './activity-options.js';
import { OptMix } from './activity-mix.js';
import { DetailVariant, ThinkVariant, OutputVariant, QuietVariant, ApprovalVariant } from './activity-parts.js';
import { STAGES, stageData, buildTurn } from './activity-model.js';

const DARK = { '--bg': '#0B0E14', '--sb': '#0D1119', '--card': '#11151D', '--inset': '#131926', '--hov': '#161C28', '--row': '#1A2130', '--bd': '#1D2430', '--bds': '#2A3547', '--bdh': '#3A4A63',
  '--tx': '#E6EAF2', '--mut': '#8A94A6', '--dim': '#737D90', '--acc': '#FFB224', '--acct': '#FFB224', '--cy': '#58C4DD', '--gr': '#3FB950', '--rd': '#F85149', '--pu': '#BC8CFF',
  '--tacc': 'rgba(255,178,36,.13)', '--tcy': 'rgba(88,196,221,.13)', '--tgr': 'rgba(63,185,80,.13)', '--trd': 'rgba(248,81,73,.13)', '--tpu': 'rgba(188,140,255,.13)', '--ov': 'rgba(3,5,9,.62)' };
// the shell's light theme (web/Hub.dc.html LIGHT)
const LIGHT = { '--bg': '#F5F6F8', '--sb': '#EEF0F3', '--card': '#FFFFFF', '--inset': '#F1F3F6', '--hov': '#E9ECF1', '--row': '#F4F6F9', '--bd': '#E0E4EA', '--bds': '#C9D0DA', '--bdh': '#A6B0BF',
  '--tx': '#0E1420', '--mut': '#4A5568', '--dim': '#687385', '--acc': '#FFB224', '--acct': '#8F5300', '--cy': '#0A6E88', '--gr': '#1A7F37', '--rd': '#CF222E', '--pu': '#7A45D6',
  '--tacc': 'rgba(255,178,36,.18)', '--tcy': 'rgba(10,110,136,.10)', '--tgr': 'rgba(26,127,55,.10)', '--trd': 'rgba(207,34,46,.09)', '--tpu': 'rgba(122,69,214,.10)', '--ov': 'rgba(20,26,36,.35)' };

const PARTS = [
  { id: 'mix', title: 'Your mix', stage: true, result: true,
    blurb: 'Your picks put together: A\'s fold, closed to start (its header carries the live status and the thinking peek); open it for the steps, open a step for the 2b sentence; 3a+3c thinking; 4c strip with a capped preview; 5b plain words; 6c approval docked on the composer.',
    options: [{ id: 'mix', tag: '✓', name: 'Your mix', C: OptMix, idea: 'Play it through the stages above. Click the status line to open the steps, then any step for its detail.' }] },
  { id: 'activity', title: 'The activity block', stage: true,
    blurb: 'How one turn of work is drawn: thinking, lookups, tool calls, approvals and the answer. Use the stage bar above to play the same turn through each option.',
    options: [
      { id: 'today', tag: 'Now', name: 'Today', C: OptToday, idea: 'The current page: the real buildView and cards, unchanged.',
        pros: ['Everything is visible'], cons: ['One card per event, 10+ cards per turn', 'Nothing shows while it thinks (Show thinking off)', 'Lookups look like real work', 'A Stop on every card'] },
      { id: 'A', tag: 'A', name: 'One fold per turn', C: OptFold, idea: 'Like Claude: a live status line while it works, a list of steps underneath; when it\'s done it folds to "Ran 2 tools · 2m 58s". Approvals, outputs and the answer sit outside the fold.',
        pros: ['Calmest finished thread', 'One place to look while it runs', 'Results are never hidden'], cons: ['Outputs are separated from the step that made them', 'Narration is hidden once it folds'] },
      { id: 'B', tag: 'B', name: 'Timeline rail', C: OptRail, idea: 'Like a coding agent: every step is a node on a thin rail, the agent\'s short updates between them, each output right under the tool that made it. Stays open.',
        pros: ['Easiest to follow cause and effect', 'Good for long, chained jobs'], cons: ['Long turns stay long', 'Lookups and thinking take rows'] },
      { id: 'C', tag: 'C', name: 'Chapters', C: OptChapters, idea: 'One card per step that did real work ("Generated an image", "Made a 3D model"), with the agent\'s update as its subtitle; the step\'s output right below it. Lookups shrink to one line.',
        pros: ['Reads like a short report', 'Big steps are obvious', 'Running step opens itself'], cons: ['Cards again (fewer, but heavier)', 'Short turns feel boxy'] },
      { id: 'D', tag: 'D', name: 'Status line + Activity panel', C: OptPanel, idea: 'The thread keeps one line per turn (live status, then the summary). Everything else opens in a side panel with Activity.',
        pros: ['Cleanest thread of all', 'Details have room in the panel'], cons: ['Details are a click and a context switch away', 'Panel needs width (a drawer on phones)'] },
      { id: 'E', tag: 'E', name: 'Words + tool chips', C: OptChips, idea: 'The agent\'s updates as normal text; under each, a row of chips (Tools ✓, Image 18s, 3D model 63%). Click a chip to open its detail; a running chip fills with progress.',
        pros: ['Very compact for many tools', 'Progress is visible at a glance'], cons: ['Chips hold little text', 'Detail opens away from the chip on narrow screens'] },
    ] },
  { id: 'detail', title: 'What opening a step shows', blurb: 'Click a step in any option: this is what it opens to. Shown for the image and the 3D call of the finished turn.',
    options: [
      { id: 'list', tag: '2a', name: 'Settings list', C: p => h(DetailVariant, { ...p, variant: 'list' }), idea: 'Plain names and values, outputs as #n chips, the result, then "Raw call" for the JSON.' },
      { id: 'sentence', tag: '2b', name: 'One sentence', C: p => h(DetailVariant, { ...p, variant: 'sentence' }), idea: 'What it did in a sentence, the prompt quoted, the result; "Raw call" for the JSON.' },
      { id: 'json', tag: '2c', name: 'Raw JSON (today)', C: p => h(DetailVariant, { ...p, variant: 'json' }), idea: 'Arguments and the whole result envelope as JSON.' },
    ] },
  { id: 'thinking', title: 'Thinking', blurb: 'What you see while the model reasons, and what\'s left afterwards. The thinking text is never shown in full unless you open it.',
    options: [
      { id: 'status', tag: '3a', name: 'Status only', C: p => h(ThinkVariant, { ...p, variant: 'status' }), idea: '"Thinking…" in the live line; nothing is kept afterwards.' },
      { id: 'fold', tag: '3b', name: 'Folded row', C: p => h(ThinkVariant, { ...p, variant: 'fold' }), idea: '"Thinking…" then "Thought for 3s ›" in the step list; opens to the text.' },
      { id: 'peek', tag: '3c', name: 'Live peek', C: p => h(ThinkVariant, { ...p, variant: 'peek' }), idea: 'Like Gemini: the last two lines of thought fade by while it thinks, then fold to "Thought for 3s ›".' },
    ] },
  { id: 'outputs', title: 'How big outputs are', blurb: 'The images and 3D models a turn made.',
    options: [
      { id: 'full', tag: '4a', name: 'Full card (today)', C: p => h(OutputVariant, { ...p, variant: 'full' }), idea: 'Column-wide preview, prompt and next-step buttons per output.' },
      { id: 'tiles', tag: '4b', name: 'Tiles', C: p => h(OutputVariant, { ...p, variant: 'tiles' }), idea: 'Small tiles side by side; open, download and More (edit, animate, make 3D).' },
      { id: 'strip', tag: '4c', name: 'Strip + one big', C: p => h(OutputVariant, { ...p, variant: 'strip' }), idea: 'Thumbnails in a strip, the picked one shown as the full card.' },
    ] },
  { id: 'quiet', title: 'Lookups, retries and notes', blurb: 'A turn where the agent read a guide, called 3D with the wrong engine, got an error, and retried.',
    options: [
      { id: 'hidden', tag: '5a', name: 'Hidden', C: p => h(QuietVariant, { ...p, variant: 'hidden' }), idea: 'Only the successful work shows; the retry is a note on its row; "Show all" brings the rest back.' },
      { id: 'muted', tag: '5b', name: 'Muted, in plain words', C: p => h(QuietVariant, { ...p, variant: 'muted' }), idea: 'Everything is a row, lookups greyed, the error in a sentence (code under Raw).' },
      { id: 'full', tag: '5c', name: 'Everything (today)', C: p => h(QuietVariant, { ...p, variant: 'full' }), idea: 'Tool names, error codes and the agent\'s internal notes as they are now.' },
    ] },
  { id: 'approval', title: 'Where approvals go', blurb: 'The 3D call needs your OK. The card is the real approval card.',
    options: [
      { id: 'below', tag: '6a', name: 'Below the block', C: p => h(ApprovalVariant, { ...p, variant: 'below' }), idea: 'The fold keeps its status line ("Waiting for you…"); the card sits under it.' },
      { id: 'inline', tag: '6b', name: 'Inside the step list', C: p => h(ApprovalVariant, { ...p, variant: 'inline' }), idea: 'The block opens itself and the step becomes the card.' },
      { id: 'dock', tag: '6c', name: 'Docked on the composer', C: p => h(ApprovalVariant, { ...p, variant: 'dock' }), idea: 'Like Claude Code\'s permission prompt: the card waits above the message box.' },
    ] },
];

function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } }

function App() {
  const React = R(), [stage, setStage] = React.useState(2), [playing, setPlaying] = React.useState(false);
  const [theme, setTheme] = React.useState(() => load('dz.theme', matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));
  const [picks, setPicks] = React.useState(() => load('dz.picks', { activity: 'A', detail: 'sentence', thinking: 'peek', outputs: 'strip', quiet: 'muted', approval: 'dock' })), [notes, setNotes] = React.useState(() => load('dz.notes', ''));
  const [showThinking, setShowThinking] = React.useState(false), [copied, setCopied] = React.useState(false);
  React.useEffect(() => { const st = document.documentElement.style; Object.entries(theme === 'light' ? LIGHT : DARK).forEach(([k, v]) => st.setProperty(k, v)); document.documentElement.dataset.theme = theme; save('dz.theme', theme); }, [theme]);
  React.useEffect(() => { save('dz.picks', picks); }, [picks]);
  React.useEffect(() => { save('dz.notes', notes); }, [notes]);
  React.useEffect(() => {
    if (!playing) return undefined;
    const t = setInterval(() => setStage(s => { if (s >= STAGES.length - 1) { setPlaying(false); return s; } return s + 1; }), 2200);
    return () => clearInterval(t);
  }, [playing]);
  const d = stageData(stage), turn = buildTurn(d.events, d.live, d.running, d.now);
  const pick = (part, id) => setPicks(p => ({ ...p, [part]: p[part] === id ? undefined : id }));
  const summary = PARTS.filter(p => !p.result).map(p => { const o = p.options.find(x => x.id === picks[p.id]); return `${p.title}: ${o ? `${o.tag} ${o.name}` : '(no pick)'}`; }).join('\n') + (notes.trim() ? `\nNotes: ${notes.trim()}` : '');
  const copy = () => navigator.clipboard?.writeText(summary).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); }, () => {});

  const bar = h('header', { style: { position: 'sticky', top: 0, zIndex: 20, background: T.sb, borderBottom: '1px solid ' + T.bd } },
    h('div', { style: { maxWidth: 1180, margin: '0 auto', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
      h('span', { style: { display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 } }, h('span', { style: { color: T.pu, display: 'flex' } }, h(Icon, { d: 'chat', size: 16 })), 'Chat activity · design options'),
      h('span', { style: { flex: 1 } }),
      h('span', { style: { fontSize: 11.5, color: T.mut } }, 'Stage'),
      h('div', { role: 'radiogroup', 'aria-label': 'Stage of the sample turn', style: { display: 'flex', flexWrap: 'wrap', gap: 2, padding: 2, borderRadius: 8, border: '1px solid ' + T.bd, background: T.bg } },
        STAGES.map((s, i) => h('button', { key: s.id, type: 'button', role: 'radio', 'aria-checked': i === stage ? 'true' : 'false', onClick: () => { setPlaying(false); setStage(i); },
          style: { height: 26, padding: '0 9px', borderRadius: 6, border: 0, font: 'inherit', fontSize: 12, cursor: 'pointer', background: i === stage ? T.tacc : 'none', color: i === stage ? T.acct : T.mut, fontWeight: i === stage ? 600 : 400 } },
        `${i + 1} ${s.label}`))),
      h(Btn, { sm: true, kind: playing ? 'sec' : 'pri', icon: playing ? 'stop' : 'play', label: playing ? 'Pause' : 'Play', onClick: () => { if (!playing && stage >= STAGES.length - 1) setStage(0); setPlaying(!playing); } }),
      h(Btn, { sm: true, icon: theme === 'light' ? 'bulb' : 'eye', label: theme === 'light' ? 'Light' : 'Dark', title: 'Switch theme', onClick: () => setTheme(theme === 'light' ? 'dark' : 'light') })));

  const nav = h('nav', { 'aria-label': 'Parts', style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
    PARTS.map((p, i) => h('a', { key: p.id, href: '#' + p.id, style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px', borderRadius: 99, border: '1px solid ' + T.bds, color: T.tx, textDecoration: 'none', fontSize: 12.5 } },
      h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.dim } }, p.result ? '★' : i), p.title, picks[p.id] ? h(Badge, { tone: 'green' }, (p.options.find(o => o.id === picks[p.id]) || {}).tag) : null)),
    h('a', { href: '#picks', style: { display: 'inline-flex', alignItems: 'center', height: 28, padding: '0 10px', borderRadius: 99, background: T.tpu, color: T.pu, textDecoration: 'none', fontSize: 12.5, fontWeight: 500 } }, 'Your picks'));

  const optionCard = (p, o) => {
    const ctx = ctxFor({ outputs: turn.outputs, running: turn.running, showThinking });
    const on = picks[p.id] === o.id;
    return h('article', { key: o.id, id: `${p.id}-${o.id}`, style: { ...cardSt({ pad: 14, gap: 12, accent: on ? T.gr : T.bd }), scrollMarginTop: 70 } },
      h('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' } },
        h('span', { style: { minWidth: 28, height: 24, padding: '0 6px', borderRadius: 6, display: 'grid', placeItems: 'center', background: o.id === 'today' ? T.hov : T.tpu, color: o.id === 'today' ? T.mut : T.pu, fontFamily: MONO, fontWeight: 600, fontSize: 12, flex: 'none' } }, o.tag),
        h('div', { style: { flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 } },
          h('h3', { style: { margin: 0, fontSize: 14.5, fontWeight: 600 } }, o.name),
          h('p', { style: { margin: 0, color: T.mut, fontSize: 12.5, lineHeight: 1.5 } }, o.idea)),
        o.id === 'today' ? h(Btn, { sm: true, kind: showThinking ? 'purple' : 'sec', icon: 'bulb', label: showThinking ? 'Show thinking: on' : 'Show thinking: off', onClick: () => setShowThinking(!showThinking) }) : null,
        o.id !== 'today' && !p.result ? h(Btn, { sm: true, kind: on ? 'pri' : 'sec', icon: on ? 'check' : null, label: on ? 'Picked' : 'Pick this', onClick: () => pick(p.id, o.id) }) : null),
      o.pros ? h('div', { style: { display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 12 } },
        h('ul', { style: { margin: 0, paddingLeft: 16, color: T.gr, flex: '1 1 220px' } }, o.pros.map(x => h('li', { key: x }, h('span', { style: { color: T.tx } }, x)))),
        h('ul', { style: { margin: 0, paddingLeft: 16, color: T.rd, flex: '1 1 220px' } }, o.cons.map(x => h('li', { key: x }, h('span', { style: { color: T.tx } }, x))))) : null,
      h(o.C, { key: p.stage ? stage : 0, turn, ctx, events: d.events, live: d.live }));
  };

  return h('div', null, bar,
    h('main', { style: { maxWidth: 1180, margin: '0 auto', padding: '20px 16px 80px', display: 'flex', flexDirection: 'column', gap: 26 } },
      h('section', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        h('h1', { style: { margin: 0, fontSize: 21, fontWeight: 600, letterSpacing: '-.01em' } }, 'How should the chat show what the agent is doing?'),
        h('p', { style: { margin: 0, color: T.mut, maxWidth: 820, lineHeight: 1.55 } },
          'Every option draws the same real turn ("make a samurai, then turn it into 3D") from the agent\'s actual event format, with the real chat kit: its tokens, icons, Markdown, result cards and approval card. Part 1 is the big choice; Parts 2–6 are the smaller choices inside it. Click around: steps, thinking, chips and the Activity button all open. Press ',
          h('strong', null, 'Pick this'), ' on the ones you like and copy your picks at the bottom.'),
        nav),
      PARTS.map((p, i) => h('section', { key: p.id, id: p.id, style: { display: 'flex', flexDirection: 'column', gap: 12, scrollMarginTop: 64 } },
        h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', borderBottom: '1px solid ' + T.bd, paddingBottom: 8 } },
          h('span', { style: { fontFamily: MONO, color: p.result ? T.gr : T.dim, fontSize: 13 } }, p.result ? 'Result' : `Part ${i}`),
          h('h2', { style: { margin: 0, fontSize: 17, fontWeight: 600 } }, p.title),
          p.stage ? h(Badge, { tone: 'accent' }, `stage ${stage + 1}: ${STAGES[stage].label}`) : null),
        h('p', { style: { margin: 0, color: T.mut, fontSize: 12.5 } }, p.blurb),
        h('div', { style: p.stage ? { display: 'flex', flexDirection: 'column', gap: 16 } : { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))', gap: 14, alignItems: 'start' } },
          p.options.map(o => optionCard(p, o))))),
      h('section', { id: 'picks', style: { ...cardSt({ pad: 16, gap: 10 }), scrollMarginTop: 64 } },
        h('h2', { style: { margin: 0, fontSize: 17, fontWeight: 600 } }, 'Your picks'),
        h('pre', { style: { margin: 0, padding: '10px 12px', borderRadius: 6, background: T.inset, border: '1px solid ' + T.bd, fontFamily: MONO, fontSize: 12, whiteSpace: 'pre-wrap' } }, summary),
        h('textarea', { value: notes, onChange: e => setNotes(e.target.value), rows: 3, placeholder: 'Notes: mix and match, what to change…', style: { padding: '8px 10px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, resize: 'vertical' } }),
        h('div', { style: { display: 'flex', gap: 8 } }, h(Btn, { kind: 'pri', icon: copied ? 'check' : 'copy', label: copied ? 'Copied' : 'Copy picks', onClick: copy }),
          h(Btn, { kind: 'ghost', label: 'Clear', onClick: () => { setPicks({}); setNotes(''); } })))));
}

const css = document.createElement('style');
css.textContent = MD_CSS + CARD_CSS + KIT_CSS + `.aichat-dots span{display:inline-block;width:5px;height:5px;margin-right:3px;border-radius:9px;background:var(--mut);animation:aichatpulse 1.2s ease-in-out infinite}
.aichat-dots span:nth-child(2){animation-delay:.2s}.aichat-dots span:nth-child(3){animation-delay:.4s}`;
document.head.appendChild(css);
const root = document.getElementById('root');
globalThis.ReactDOM.createRoot(root).render(h(App));
