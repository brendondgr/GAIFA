// Risks and grants on the approval card (plan 25.3): the risk's word and colour, the grant key in
// words ("on github.com", "in ~/Projects/foo"), which buttons a card offers, and which arguments of
// an `execute` tool are its code. Pure functions (no React), shared by the chat's card, the
// Approvals popover, the API tab and Settings → Agent. Written by us (web/PATCHES.md).

// Badge tones (chat-ui.js Badge): new in plan 25 are network (cyan) and execute (amber).
export const RISK_TONE = { read: 'green', write: 'purple', generate: 'purple', network: 'cyan', execute: 'accent', destructive: 'red' };
export const RISK_WORD = { read: 'reads', write: 'writes', generate: 'generates', network: 'uses the internet', execute: 'runs code', destructive: 'deletes' };
// An `always` grant for these needs a second confirm on the card (the hub asks for `confirm: true`).
export const CONFIRM_RISKS = ['execute', 'destructive'];
const CODE_NAMES = ['code', 'command', 'script', 'cmd', 'source', 'shell'];

/** The call's grant key from its arguments, as the hub reads it (utils/tools/grants.py key_of). */
export function grantKeyOf(kind, args = {}) {
  if (!kind || !args || typeof args !== 'object') return null;
  const i = kind.indexOf(':'), k = kind.slice(0, i), what = kind.slice(i + 1);
  if (k === 'const') return what;
  if (k === 'arg') { const v = args[what]; return v == null || v === '' ? null : typeof v === 'string' ? v : JSON.stringify(v); }
  if (kind === 'url:host') {
    try { const h = new URL(String(args.url)).hostname; return h ? h.toLowerCase().replace(/\.$/, '') : null; } catch { return null; }
  }
  return null;
}

/** What a grant covers, in words: "on github.com", "in ~/Projects/foo", "every search"; null: every call. */
export function grantText(kind, key) {
  if (!kind || key == null) return null;
  if (kind === 'url:host') return `on ${key}`;
  if (kind.startsWith('arg:')) { const n = kind.slice(4); return /folder|dir|path|repo|workspace/.test(n) ? `in ${key}` : `${n} ${key}`; }
  if (kind.startsWith('const:')) return `every ${key} call`;
  return key;
}

/**
 * The buttons of an approval card. `thread`: the call came from a chat ("Allow in this chat" needs
 * one). Each is {remember, label, confirm?}; `confirm` asks a second time before deciding.
 */
export function approvalButtons(risk, { thread = false } = {}) {
  const out = [{ remember: 'once', label: 'Allow once', primary: true }];
  if (thread) out.push({ remember: 'thread', label: 'Allow in this chat' });
  out.push({ remember: 'always', label: 'Always allow', ...(CONFIRM_RISKS.includes(risk) ? { confirm: true } : {}) });
  return out;
}

/** The text of the second confirm for an `always` grant. */
export function confirmText(tool, risk, cover) {
  const what = risk === 'execute' ? 'run code with' : 'delete with';
  return `Always let the agent ${what} ${tool}${cover ? ` (${cover})` : ''}, in every chat and from MCP, without asking? You can revoke it in Settings → Agent.`;
}

/** The decided card's words for how it was allowed. */
export function rememberText(remember) {
  return remember === 'thread' ? 'Allowed in this chat' : remember === 'always' ? 'Always allowed' : null;
}

/** The arguments of an `execute` tool that hold its code or command: shown whole, monospaced, editable. */
export function codeFields(schema, risk) {
  if (risk !== 'execute') return [];
  const props = schema?.properties || {};
  return Object.keys(props).filter(k => {
    const p = props[k] || {};
    if (p.type && p.type !== 'string') return false;
    return p.format === 'code' || p['x-code'] || CODE_NAMES.includes(k);
  });
}
