// The embed model in use and Change… (plan capability-enablement 7.3), in words: shared by Settings → Agent → Memory
// (web/settings/blocks-agent.js) and the Embeddings page (services/embed/ui/page.js). `d` is the embed mod's
// GET /v1/models: {model, models: [{id, name, dim, kinds, full, size_gb, weights, in_use}], switch}.
// Written by us, not Claude Design.

const KIND_WORDS = { text: 'text', image: 'pictures', audio: 'audio', video: 'video' };

function list(words) {
  return words.length < 2 ? words.join('') : `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

/** What a model reads, in words. */
export function reads(m) {
  return m?.full ? 'text, pictures, audio and video' : list((m?.kinds || ['text']).map(k => KIND_WORDS[k] || k));
}

/** The model in use, in a line. */
export function inUseText(d) {
  const m = (d?.models || []).find(x => x.id === d?.model);
  if (!m) return d?.model ? `Search uses ${d.model}.` : 'The embed mod isn’t answering.';
  return `Search uses ${m.name} (${m.dim}-d; reads ${reads(m)}).`;
}

/** The models it could change to: there, and not the one in use. */
export function others(d) {
  return (d?.models || []).filter(m => m.weights && m.id !== d?.model);
}

/** What changing to `m` gives up, if anything. */
export function changeNote(m) {
  if (!m) return '';
  if (m.full) return 'Reads every kind, like EmbeddingGemma 2.';
  return `Reads ${reads(m)} only: pictures, audio and video are found by their titles and prompts, and searching for them by kind says it needs the full model.`;
}

/** A switch in progress (or just finished), in words; '' when there is none. */
export function switchText(d) {
  const sw = d?.switch;
  if (!sw) return '';
  const now = (d.models || []).find(x => x.id === d.model)?.name || d.model;
  if (sw.state === 'building') {
    const left = sw.pending ? `, ${sw.pending} to go` : '';
    return `Building ${sw.name}’s index: ${sw.done || 0} done${left}. Search uses ${now} until it’s ready.` + (sw.error ? ` Last problem: ${sw.error}` : '');
  }
  if (sw.state === 'done') return `${sw.name}’s index is ready: the mod is restarting on it.`;
  if (sw.state === 'failed') return `Changing to ${sw.name} failed: ${sw.error || 'see the embed log'}. ${now} stays in use.`;
  if (sw.state === 'cancelled') return `Changing to ${sw.name} was stopped. ${now} stays in use.`;
  return '';
}

export const busy = d => d?.switch?.state === 'building';
