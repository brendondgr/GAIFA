// The Settings page's agent blocks (plan settings-redesign 1.3, 2.1): the cards of web/chat/ that the schema
// places one by one, and the pickers that write the page's draft (the judge's model, how pages are screened).
// Each takes `{ctx, row}`. Written by us (web/PATCHES.md).

import { h, T } from '../chat/chat-ui.js';
import { AgentNotes, ModelsCard, DocumentsCard, InstructionsCard, MemoryCard, SkillsCard, ModesCard, GrantsList } from '../chat/chat-settings.js';
import { ScreenModelPick } from '../chat/chat-webprefs.js';
import { SpeechInputPanel } from '../chat/chat-speech-input.js';
import { JudgedList, JudgeModelPick, judgeStatusText, JUDGE_HINT } from '../chat/chat-judge.js';

const p = ctx => ({ api: ctx.api, toast: ctx.toast });
const wrap = C => ({ ctx }) => h(C, p(ctx));
const pad = (...kids) => h('div', { style: { padding: '14px 0', display: 'flex', flexDirection: 'column', gap: 10 } }, ...kids);

/** The judge's decision model (always the decide mod's, web-approvals), on the draft; its status from GET /api/judge/status. */
function JudgeModelBlock({ ctx }) {
  const st = ctx.judgeStatus, j = ctx.draft?.judge || {};
  return pad(
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
      h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, 'Judge model'),
        h('div', { style: { fontSize: 12, color: T.mut } }, 'In Auto, it runs commands, fetches and deletes it’s sure you asked for, and asks you about the rest. ' + JUDGE_HINT)),
      h(JudgeModelPick, { st, value: j, onChange: v => ctx.setDraft(d => { d.judge = { ...d.judge, ...v }; }) })),
    st ? h('div', { role: 'status', style: { fontSize: 12, color: st.available ? T.mut : T.acct } }, judgeStatusText(st)) : null);
}

function ScreenModelBlock({ ctx }) {
  return h(ScreenModelPick, { screen: ctx.draft?.screen, reading: ctx.reading, onChange: patch => ctx.setDraft(d => { d.screen = { ...d.screen, ...patch }; }) });
}

/** The judged calls; "Always allow" saves the rule at once (ctx.allowCommand, settings-that-stick 2.2). */
function JudgedBlock({ ctx }) {
  const allow = ctx.draft?.judge?.allow_commands || [];
  return pad(h(JudgedList, { api: ctx.api, controls: false, allowed: allow, onAllow: ctx.allowCommand }));
}

/** The microphones in order (4.3): the dictation panel on the draft's speech_input, its other fields being rows. */
function MicsBlock({ ctx }) {
  return pad(h(SpeechInputPanel, { api: ctx.api, toast: ctx.toast, fields: false, value: ctx.draft?.speech_input,
    onChange: v => ctx.setDraft(d => { d.speech_input = { ...d.speech_input, ...v }; }) }));
}
/** What the voice mod says about the speech model, in words (plan voice-speech-model 3.2). `st`: its GET /v1/status. */
export function voiceModelText(st, quant, hasMod = true) {
  if (!hasMod) return 'The Voice mod isn’t installed: gaifa setup voice. Until then voice mode uses the chat’s model.';
  if (!st) return 'The Voice mod isn’t running. Voice mode starts it, or uses the chat’s model when it can’t.';
  const m = (st.models || []).find(x => x.quant === quant), eng = st.engine || {};
  if (m && !m.present) return `LFM3-Omni-2B ${m.label} isn’t downloaded: gaifa setup voice.`;
  const name = `LFM3-Omni-2B ${m?.label || ''}`.trim();
  if (eng.state === 'ready' && eng.quant === quant) return `${name}, loaded. It unloads after 5 minutes without a conversation.`;
  if (eng.state === 'ready') return `${eng.label} is loaded; ${name} loads the next time voice mode starts.`;
  if (eng.state === 'failed') return `${name} failed to load: ${eng.error || 'see the Voice mod’s log'}`;
  return `${name}, not loaded. It loads in about a second when voice mode starts (about 5 GB).`;
}
function VoiceModelStatus({ ctx }) {
  const has = !ctx.services || ctx.services.some(s => s.id === 'voice');
  return h('div', { role: 'status', style: { padding: '12px 0', fontSize: 12.5, color: T.mut } }, voiceModelText(ctx.voiceModel, ctx.draft?.voice_mode?.quant || 'q4_k_m', has));
}
const LearningLink = () => h('div', { style: { padding: '12px 0' } }, h('a', { href: '#/s/agent/learning', style: { fontSize: 12.5 } }, 'Open Memory & learning →'));

export const AGENT_BLOCKS = {
  AgentNotes: wrap(AgentNotes), ModelsCard: ({ ctx }) => pad(h(ModelsCard, { ...p(ctx), bare: true })), DocumentsCard: wrap(DocumentsCard),
  InstructionsCard: wrap(InstructionsCard), MemoryCard: wrap(MemoryCard), SkillsCard: wrap(SkillsCard), LearningLink, MicsBlock, VoiceModelStatus,
  ModesCard: () => pad(h(ModesCard)), GrantsList: ({ ctx }) => pad(h(GrantsList, p(ctx))),
  JudgedList: JudgedBlock, JudgeModelBlock, ScreenModelBlock,
};
