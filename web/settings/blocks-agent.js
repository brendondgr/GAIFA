// The Settings page's agent blocks (plan settings-redesign 1.3, 2.1): the cards of web/chat/ that the schema
// places one by one, and the pickers that write the page's draft (the judge's model, how pages are screened).
// Each takes `{ctx, row}`. Written by us (web/PATCHES.md).

import { h, T } from '../chat/chat-ui.js';
import { AgentNotes, ModelsCard, DocumentsCard, InstructionsCard, MemoryCard, SkillsCard, LearningSection, ModesCard, GrantsList, section } from '../chat/chat-settings.js';
import { WebReadingSection, ScreenModelPick } from '../chat/chat-webprefs.js';
import { SpeechInputSection } from '../chat/chat-speech-input.js';
import { SpeechOutputSection } from '../chat/chat-speak.js';
import { JudgedList, JudgeModelPick, judgeStatusText } from '../chat/chat-judge.js';
import { PermissionRules } from '../chat/chat-rules.js';

const p = ctx => ({ api: ctx.api, toast: ctx.toast });
const wrap = C => ({ ctx }) => h(C, p(ctx));
const pad = (...kids) => h('div', { style: { padding: '14px 0', display: 'flex', flexDirection: 'column', gap: 10 } }, ...kids);

/** The judge's backend and model, on the draft; its status (whether it answers) from GET /api/judge/status. */
function JudgeModelBlock({ ctx }) {
  const st = ctx.judgeStatus, j = ctx.draft?.judge || {};
  return pad(
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
      h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, 'Judge model'),
        h('div', { style: { fontSize: 12, color: T.mut } }, 'In Auto, it runs commands, fetches and deletes it’s sure you asked for, and asks you about the rest.')),
      h(JudgeModelPick, { st, value: j, onChange: v => ctx.setDraft(d => { d.judge = { ...d.judge, ...v }; }) })),
    st ? h('div', { role: 'status', style: { fontSize: 12, color: st.available ? T.mut : T.acct } }, judgeStatusText(st)) : null);
}

function ScreenModelBlock({ ctx }) {
  return h(ScreenModelPick, { screen: ctx.draft?.screen, reading: ctx.reading, onChange: patch => ctx.setDraft(d => { d.screen = { ...d.screen, ...patch }; }) });
}

/** The judged calls; "Always allow" adds the rule to the draft. */
function JudgedBlock({ ctx }) {
  const allow = ctx.draft?.judge?.allow_commands || [];
  return pad(h(JudgedList, { api: ctx.api, controls: false, allowed: allow,
    onAllow: rule => ctx.setDraft(d => { d.judge.allow_commands = [...new Set([...(d.judge.allow_commands || []), rule])]; }) }));
}

export const AGENT_BLOCKS = {
  AgentNotes: wrap(AgentNotes), ModelsCard: ({ ctx }) => pad(h(ModelsCard, { ...p(ctx), bare: true })), DocumentsCard: wrap(DocumentsCard), WebReadingSection: wrap(WebReadingSection),
  InstructionsCard: wrap(InstructionsCard), MemoryCard: wrap(MemoryCard), SkillsCard: wrap(SkillsCard), LearningSection: wrap(LearningSection),
  SpeechInputSection: wrap(SpeechInputSection), SpeechOutputSection: wrap(SpeechOutputSection),
  ModesCard: () => pad(h(ModesCard)), PermissionRules: ({ ctx }) => h(PermissionRules, { api: ctx.api }), GrantsList: ({ ctx }) => pad(h(GrantsList, p(ctx))),
  JudgedList: JudgedBlock, JudgeModelBlock, ScreenModelBlock,
  PermissionsCard: ({ ctx }) => section('Permissions', h(ModesCard), h(PermissionRules, { api: ctx.api }), h(GrantsList, p(ctx)), h(JudgedList, { api: ctx.api })),
};
