// "Chat has no model", said plainly (plan capability-enablement 6.3): from the agent's status `llm` ({url, kind: relay |
// direct, answers, models, detail}), the words and the one fix that fits: start the relay, add a server in Settings →
// LLMs, or change your own server's URL. Pure; the Chat page's banner and Settings → LLMs use it.

/** null when Chat has a model; else {text, fix: {kind: 'start_relay' | 'add_server' | 'change_url', label, href?}}. */
export function noModel(llm) {
  if (!llm || (llm.answers && (llm.models || []).length)) return null;
  if (llm.kind === 'relay' && !llm.answers)
    return { text: `Chat has no model: nothing answers at ${llm.url}`, fix: { kind: 'start_relay', label: 'Start LLM Relay' } };
  if (llm.kind === 'relay')
    return { text: 'Chat has no model: the relay serves no chat model', fix: { kind: 'add_server', label: 'Add a server in Settings → LLMs', href: '#/settings/llms' } };
  return { text: `Chat has no model: ${llm.answers ? `${llm.url} lists no model` : (llm.detail || `nothing answers at ${llm.url}`)}`,
    fix: { kind: 'change_url', label: 'Change the server in Settings → LLMs', href: '#/settings/llms' } };
}
