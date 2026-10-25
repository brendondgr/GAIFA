// The Settings page's agent blocks (plan settings-redesign 1.3): the cards of web/chat/ that the schema places
// one by one. Each takes `{ctx, row}` and passes the page's api and toast on. Written by us (web/PATCHES.md).

import { h } from '../chat/chat-ui.js';
import { AgentNotes, ModelsCard, DocumentsCard, InstructionsCard, MemoryCard, SkillsCard, LearningSection, ModesCard, GrantsList, section } from '../chat/chat-settings.js';
import { WebReadingSection } from '../chat/chat-webprefs.js';
import { SpeechInputSection } from '../chat/chat-speech-input.js';
import { SpeechOutputSection } from '../chat/chat-speak.js';
import { JudgedList } from '../chat/chat-judge.js';
import { PermissionRules } from '../chat/chat-rules.js';

const p = ctx => ({ api: ctx.api, toast: ctx.toast });
const wrap = C => ({ ctx }) => h(C, p(ctx));

export const AGENT_BLOCKS = {
  AgentNotes: wrap(AgentNotes), ModelsCard: wrap(ModelsCard), DocumentsCard: wrap(DocumentsCard), WebReadingSection: wrap(WebReadingSection),
  InstructionsCard: wrap(InstructionsCard), MemoryCard: wrap(MemoryCard), SkillsCard: wrap(SkillsCard), LearningSection: wrap(LearningSection),
  SpeechInputSection: wrap(SpeechInputSection), SpeechOutputSection: wrap(SpeechOutputSection),
  ModesCard: () => h(ModesCard), PermissionRules: ({ ctx }) => h(PermissionRules, { api: ctx.api }), GrantsList: wrap(GrantsList), JudgedList: ({ ctx }) => h(JudgedList, { api: ctx.api }),
  // Phase 1: the Permissions card as it was (modes, tool rules, grants, the judge and its calls)
  PermissionsCard: ({ ctx }) => section('Permissions', h(ModesCard), h(PermissionRules, { api: ctx.api }), h(GrantsList, p(ctx)), h(JudgedList, { api: ctx.api })),
};
