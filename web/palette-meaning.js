// The header's Search (Ctrl K) also searches by meaning while the embed mod runs: after a short
// pause on 3+ characters it asks the embed mod's library for outputs (`POST /api/s/embed/v1/search`)
// and the agent for chats (`GET /api/s/agent/v1/chats/search`), and lists the closest few under the
// name matches, each with its similarity score (score.js). Name matches carry no score: they are
// ranked by how well the letters match, which is not a similarity. The pure parts (shouldSearch,
// meaningItems, mergePalette) are tested in utils/tests/web/score.test.mjs.

export { ScoreBadge, fmtScore } from './score.js';

export const MIN_CHARS = 3;
export const WAIT_MS = 350;
export const LIMIT = 8;
const enc = encodeURIComponent;

/** Search by meaning for this query: long enough, and the embed mod is running. */
export function shouldSearch(q, services, meaning) {
  return String(q || '').trim().length >= MIN_CHARS && !!meaning?.canSearch?.(services);
}

/** Output rows (outputs/meaning.js `rows`) and chats (the agent's chat search) as palette entries,
 * best score first, the top `limit`. */
export function meaningItems({ outputs = [], chats = [] } = {}, limit = LIMIT) {
  const o = (outputs || []).map(r => ({ key: 'output:' + r.id, kind: 'output', label: r.title || r.id, sub: 'Output · by meaning',
    href: '#/outputs/' + enc(r.id), score: r.score }));
  const c = (chats || []).map(r => ({ key: 'chat:' + r.thread_id, kind: 'chat', label: r.title || 'Chat', sub: 'Chat · by meaning',
    href: r.link || '#/chat/' + enc(r.thread_id), score: r.score }));
  const n = x => (Number.isFinite(Number(x.score)) && x.score !== null ? Number(x.score) : -Infinity);
  return [...o, ...c].sort((a, b) => n(b) - n(a)).slice(0, limit);
}

/** Name matches first, then the meaning matches; a name match the meaning search also found gives way
 * to the scored entry. */
export function mergePalette(keyword, meaning) {
  const keys = new Set((meaning || []).map(m => m.key));
  return [...(keyword || []).filter(x => !x.key || !keys.has(x.key)), ...(meaning || [])];
}

/** Both searches at once; either may fail (the agent or the embed mod is down) without losing the other.
 * `err` only when both failed. */
export async function searchMeaning({ api, chat, meaning, q, limit = LIMIT }) {
  const [o, c] = await Promise.allSettled([meaning.search(api, q),
    chat?.searchChats ? chat.searchChats(q, limit) : Promise.resolve([])]);
  const outputs = o.status === 'fulfilled' ? meaning.rows(o.value?.results) : [];
  const chats = c.status === 'fulfilled' ? c.value || [] : [];
  const why = r => r?.detail || String(r?.message || r);
  return { items: meaningItems({ outputs, chats }, limit), err: o.status === 'rejected' && c.status === 'rejected' ? why(o.reason) : '' };
}
