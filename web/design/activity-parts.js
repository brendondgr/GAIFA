// Design study (not wired into the app): Parts 2–6, the smaller choices inside whichever activity
// block wins — what an opened step shows, thinking, output size, lookups and retries, approvals.

import { h, T, MONO, Icon, Btn, Badge, cardSt, R, Mark, Time, LiveLine, ToolRow, ThinkRow, OutputTile, Md, ellip, Outputs, Approval, useOpen, label11 } from './activity-kit.js';
import { ErrorBox } from '../chat/chat-cards.js';
import { FoldBlock } from './activity-options.js';
import { buildTurn, stageData, ERROR_EVENTS, fmtDur } from './activity-model.js';

const col = (gap, ...kids) => h('div', { style: { display: 'flex', flexDirection: 'column', gap, minWidth: 0 } }, ...kids);
const mini = (...kids) => h('div', { style: { background: T.bg, border: '1px solid ' + T.bd, borderRadius: 8, padding: '12px 12px', display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } }, ...kids);
const cap = t => h('div', { style: { fontSize: 11, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase', color: T.dim } }, t);
const turnAt = i => { const d = stageData(i); return buildTurn(d.events, d.live, d.running, d.now); };

// ---------- 2. What opening a step shows ----------
export function DetailVariant({ variant, ctx }) {
  const turn = turnAt(6), tools = turn.tools.filter(t => !t.lookup), [isOpen, toggle] = useOpen(['c3', 'c4']);
  return mini(tools.map(t => h(ToolRow, { key: t.id, tool: t, turn, ctx, variant, open: isOpen(t.id), onToggle: () => toggle(t.id) })));
}

// ---------- 3. Thinking ----------
export function ThinkVariant({ variant }) {
  const during = turnAt(0), after = turnAt(6), s = after.steps[1], live = during.steps[0];
  const [isOpen, toggle] = useOpen();
  const imgRow = h(ToolRow, { tool: s.tools[0], turn: after, open: false, onToggle: () => {} });
  const narr = h('div', { style: { padding: '0 0 0 21px' } }, h(Md, { text: s.narration.text, size: 12.5 }));
  const whileEl = variant === 'status' ? h(LiveLine, { status: { text: 'Thinking', icon: 'bulb' }, elapsed: 2 })
    : h(ThinkRow, { thinking: live.thinking, peek: variant === 'peek', open: isOpen('w'), onToggle: () => toggle('w') });
  const afterEl = variant === 'status' ? col(2, narr, imgRow)
    : col(2, h(ThinkRow, { thinking: s.thinking, open: isOpen('a'), onToggle: () => toggle('a') }), narr, imgRow);
  return col(8, cap('While it thinks'), mini(whileEl), cap('Afterwards'), mini(afterEl));
}

// ---------- 4. How big outputs are ----------
export function OutputVariant({ variant, ctx }) {
  const React = R(), turn = turnAt(6), outs = turn.outputs, [sel, setSel] = React.useState(outs[0].n);
  if (variant === 'full') return mini(h(Outputs, { outputs: outs, ctx }));
  if (variant === 'tiles') return mini(h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } }, outs.map(o => h(OutputTile, { key: o.n, o, size: 128 }))));
  const big = outs.find(o => o.n === sel);
  return mini(
    h('div', { style: { display: 'flex', gap: 6 } }, outs.map(o => h('button', { key: o.n, type: 'button', onClick: () => setSel(o.n), title: o.title,
      style: { position: 'relative', padding: 0, borderRadius: 6, border: '2px solid ' + (o.n === sel ? T.cy : 'transparent'), background: 'none', cursor: 'pointer' } },
      h('img', { src: o.preview, alt: o.title, style: { display: 'block', width: 64, height: 64, objectFit: 'cover', borderRadius: 4, background: T.inset } }),
      h('span', { style: { position: 'absolute', left: 3, bottom: 3, fontFamily: MONO, fontSize: 10, fontWeight: 600, padding: '0 4px', borderRadius: 3, background: T.card, color: T.pu } }, '#' + o.n)))),
    h('div', { className: 'dz-cap' }, h(Outputs, { outputs: [big], ctx })));
}

// ---------- 5. Lookups, retries and notes ----------
export function QuietVariant({ variant, ctx }) {
  const turn = buildTurn(ERROR_EVENTS, {}, false, 0), [isOpen, toggle] = useOpen(), [all, setAll] = R().useState(false);
  const [look, bad, good] = turn.tools;
  const note = h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.mut, padding: '2px 0 2px 21px' } }, h(Icon, { d: 'info', size: 12 }), 'The model\'s reply was empty; asked again');
  let rows;
  if (variant === 'hidden' && !all) {
    const merged = { ...good, detail: good.detail + ' · fixed a setting, retried once' };
    rows = [h(ToolRow, { key: 'g', tool: merged, turn, ctx, open: isOpen('g'), onToggle: () => toggle('g') }),
      h('button', { key: 'more', type: 'button', className: 'dz-link', onClick: () => setAll(true), style: { alignSelf: 'flex-start', border: 0, background: 'none', padding: '2px 0 0 21px', font: 'inherit', fontSize: 12, cursor: 'pointer' } }, '1 lookup, 1 failed try and 1 note hidden · Show all')];
  } else if (variant === 'full') {
    rows = [h(ToolRow, { key: 'l', tool: look, turn, ctx, quietLookups: false, open: isOpen('l'), onToggle: () => toggle('l') }),
      h(ToolRow, { key: 'b', tool: { ...bad, label: 'Make 3D', detail: 'gen3d_make_3d' }, turn, ctx, variant: 'json', open: isOpen('b'), onToggle: () => toggle('b') }),
      h('div', { key: 'e', style: { paddingLeft: 21 } }, h(ErrorBox, { error: bad.result.error })),
      h('div', { key: 'n', style: { display: 'flex', justifyContent: 'center', gap: 6, fontSize: 12, color: T.mut } }, h(Icon, { d: 'info', size: 12 }), 'the model\'s reply was empty; asked again'),
      h(ToolRow, { key: 'g', tool: { ...good, label: 'Make 3D', detail: 'gen3d_make_3d' }, turn, ctx, variant: 'json', open: isOpen('g'), onToggle: () => toggle('g') })];
  } else {
    const plain = { ...bad, label: 'Couldn\'t make the 3D model', detail: 'Cube3D can\'t use a picture' };
    rows = [h(ToolRow, { key: 'l', tool: look, turn, ctx, open: isOpen('l'), onToggle: () => toggle('l') }),
      h(ToolRow, { key: 'b', tool: plain, turn, ctx, open: isOpen('b'), onToggle: () => toggle('b') }),
      variant === 'muted' ? note : null,
      h(ToolRow, { key: 'g', tool: good, turn, ctx, open: isOpen('g'), onToggle: () => toggle('g') })];
  }
  return mini(h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.mut } },
    h(Icon, { d: 'tool', size: 13 }), turn.summary.text, h('span', { style: { color: T.dim } }, '·'), h(Time, { s: turn.elapsed })),
  h('div', { style: { marginLeft: 6, paddingLeft: 12, borderLeft: '1px solid ' + T.bds, display: 'flex', flexDirection: 'column', gap: 2 } }, rows));
}

// ---------- 6. Where approvals go ----------
export function ApprovalVariant({ variant, ctx: c0 }) {
  const turn = turnAt(3), ctx = { ...c0, outputs: turn.outputs };
  if (variant === 'below') return mini(h(FoldBlock, { turn, ctx, startOpen: false }), turn.pending.map(t => h(Approval, { key: t.id, tool: t, ctx })), h(Outputs, { outputs: turn.outputs, ctx }));
  if (variant === 'inline') return mini(h(FoldBlock, { turn, ctx, inlineApproval: true, startOpen: true }), h(Outputs, { outputs: turn.outputs, ctx }));
  // docked: the card sits on top of the composer until it's answered; the thread shows a short line.
  return mini(h(FoldBlock, { turn, ctx, startOpen: false }), h(Outputs, { outputs: turn.outputs, ctx }),
    h('div', { style: { borderTop: '1px solid ' + T.bd, margin: '4px -12px -12px', padding: 10, display: 'flex', flexDirection: 'column', gap: 8, background: T.sb, borderRadius: '0 0 8px 8px' } },
      turn.pending.map(t => h(Approval, { key: t.id, tool: t, ctx })),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, height: 40, padding: '0 10px', borderRadius: 10, border: '1px solid ' + T.bds, background: T.card, color: T.dim, fontSize: 13 } },
        h('span', { style: { flex: 1 } }, 'Reply, or approve above…'), h(Btn, { sm: true, kind: 'ghost', icon: 'stop', title: 'Stop' }))));
}
