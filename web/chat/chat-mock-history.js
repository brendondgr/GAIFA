// The mock's older chats (plan chat-history 1.2): enough of them, over enough days and environments, that every
// date heading (Today, Yesterday, the two days before, Last week, Older, another year), the sidebar's 20 then
// Show all, and an environment's 5 then Show more all show in `?mock`. Two are archived. The environments are
// the mock workspace mod's (web/mock-workspace.js). Written by us (web/PATCHES.md).

const H = 3600, D = 86400;
// [title, environment (null: none set), age of the last activity in seconds, archived]
export const HISTORY = [
  ['Tidy the README intro', 'ariadne', 0.4 * H],
  ['Why does the build cache miss?', 'ariadne', 1.5 * H],
  ['Birthday card for Mom', null, 2.2 * H],
  ['Weekly grocery list', 'none', 3 * H],
  ['Rename the outputs by date', 'ariadne', 5 * H],
  ['Lo-fi loop for the demo video', null, 26 * H],
  ['Summarize the reviewer comments', 'thesis', 28 * H],
  ['Low-poly lighthouse', null, 30 * H],
  ['Fix the flaky upload test', 'ariadne', 2 * D + 2 * H],
  ['Chapter 3 outline', 'thesis', 2 * D + 5 * H],
  ['A voice for the narrator', null, 3 * D + H],
  ['Port the parser to Rust?', 'ariadne', 3 * D + 6 * H, true],
  ['Related work: retrieval', 'thesis', 4 * D + 3 * H],
  ['Watercolor postcards', null, 5 * D],
  ['Bench numbers for the GPU box', 'ariadne', 6 * D + 2 * H],
  ['Abstract, second pass', 'thesis', 6 * D + 9 * H],
  ['Packing list for the trip', 'none', 7 * D + 2 * H],
  ['Clean up the logging', 'ariadne', 9 * D],
  ['Figure 2 colors', 'thesis', 12 * D],
  ['Sea shanty in my voice', null, 15 * D],
  ['Migrate the config to TOML', 'ariadne', 21 * D],
  ['Defense slides', 'thesis', 26 * D],
  ['Character sheet: the fox knight', null, 33 * D, true],
  ['Dependency audit', 'ariadne', 47 * D],
  ['Survey questions draft', 'thesis', 60 * D],
  ['Old recipe conversions', 'none', 90 * D],
  ['First try at the CLI', 'ariadne', 200 * D],
  ['Proposal budget table', 'thesis', 380 * D],
];

/** Makes the chats with the mock's own `newThread` and `emit`; each has a question and a short reply. */
export function seedHistory({ newThread, emit, now }) {
  for (const [title, env, age, archived] of HISTORY) {
    const t = newThread({ title, settings: env ? { environment: env } : {} });
    emit(t, 'user', { text: title.endsWith('?') ? title : `Help me with this: ${title.toLowerCase()}.` });
    emit(t, 'assistant', { text: 'Sure. Here is a first pass; tell me what to change.', model: 'skynet' });
    for (const e of t.events) e.ts = now() - age;
    Object.assign(t.thread, { updated: now() - age, created: now() - age - 2 * H, archived: !!archived });
  }
}
