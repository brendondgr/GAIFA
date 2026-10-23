// Mods' chat modules (plan 44.1): a mod with `[ui] chat = "ui/chat.js"` in its service.toml brings its own cards.
// The Chat page imports each installed mod's `chat_url` once per page load and calls its default export:
//
//   export default function setup(chat) {
//     chat.registerStep('comfy_generate_image', { … });          // step words (chat-steps.js)
//     chat.registerCard('step:comfy_generate_image', MyLiveCard); // a tool's opened step, its result, …
//   }
//
// `chat` = { version, registerCard, registerPreview, registerAction, registerStep, live, ui, api }. A module that
// fails to load or throws in setup is logged and skipped, and whatever it registered before throwing is undone.
// Deleting the mod's folder removes its module (and so its cards) with it.

export const CHAT_API_VERSION = 1;
const loaded = new Map();     // url → { mod, undo: [fn], error? }

/** Wraps the registries so every registration a module makes can be undone. */
export function recorder(chat, undo) {
  const wrap = f => (...a) => { const u = f(...a); if (typeof u === 'function') undo.push(u); return u; };
  return { ...chat, version: CHAT_API_VERSION, registerCard: wrap(chat.registerCard), registerPreview: wrap(chat.registerPreview),
    registerAction: wrap(chat.registerAction), registerStep: wrap(chat.registerStep) };
}

/** Loads the chat modules of `services` (those with a `chat_url`), each once. Returns [{mod, ok, error?}].
 *  `importer` is `import()` (tests pass their own). Services without a module, or already loaded, are skipped. */
export async function loadChatModules(services, chat, importer = u => import(u)) {
  const todo = (services || []).filter(s => s && s.chat_url && !loaded.has(s.chat_url));
  return Promise.all(todo.map(async s => {
    const rec = { mod: s.id, undo: [] };
    loaded.set(s.chat_url, rec);
    try {
      const m = await importer(s.chat_url + (s.chat_url.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(s.version || '0'));
      const setup = m && m.default;
      if (typeof setup !== 'function') throw new Error('its default export is not setup(chat)');
      await setup(recorder(chat, rec.undo));
      return { mod: s.id, ok: true };
    } catch (e) {
      rec.undo.splice(0).forEach(u => { try { u(); } catch { /* already gone */ } });
      rec.error = e && e.message ? e.message : String(e);
      console.error(`[chat] ${s.id}'s chat module was skipped:`, e);
      return { mod: s.id, ok: false, error: rec.error };
    }
  }));
}

/** For tests: forget what was loaded (and undo it). */
export function resetChatModules() {
  for (const r of loaded.values()) r.undo.splice(0).forEach(u => { try { u(); } catch { /* gone */ } });
  loaded.clear();
}
