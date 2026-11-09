// The workspace mod on the mock (plan chat-history 1.2): its environments, so the Chat page's sidebar can group
// `?mock`'s chats by environment (5 per section, then Show more) and the header chip shows. Only what the chat
// pages read: the environments (list, create, rename), and no folders or skills. The chats themselves are
// chat/chat-mock-history.js's. Written by us, not Claude Design.

export const WORKSPACE_SVC = { id: 'workspace', name: 'Workspace', description: 'Folders the agent may read or edit, grouped in environments', icon: 'folder', port: 5103,
  used: 0.05 * 2 ** 30, stats: [{ label: 'Environments', value: 4 }], priority: 7 };

export function workspaceMock({ ok, upstream, now }) {
  const t0 = now() - 40 * 86400;
  const env = (id, name, folders = [], created = t0) => ({ id, name, default: id === 'default', none: id === 'none', created, updated: created, folders });
  const envs = [env('none', 'None'), env('default', 'Default'),
    env('ariadne', 'Ariadne', [{ id: 'f_ariadne', path: '~/Projects/ariadne', name: 'ariadne', level: 'edit' }], t0 + 86400),
    env('thesis', 'Thesis', [{ id: 'f_thesis', path: '~/Documents/thesis', name: 'thesis', level: 'read' }], t0 + 2 * 86400)];
  const find = id => { const e = envs.find(x => x.id === id); if (!e) throw upstream(404, `no environment '${id}'`); return e; };
  return {
    'GET /health': () => ok({ status: 'ok' }),
    'GET /v1/environments': () => ok({ environments: envs.map(e => ({ ...e, folders: e.folders.map(f => ({ ...f })) })) }),
    'GET /v1/environments/{eid}': ({ pp }) => ok(find(pp.eid)),
    'POST /v1/environments': ({ json }) => {
      const name = String(json?.name || '').trim(); if (!name) throw upstream(422, 'name: field required');
      const e = env(name.toLowerCase().replace(/[^a-z0-9]+/g, '-'), name, [], now()); envs.push(e); return ok(e, 201);
    },
    'PUT /v1/environments/{eid}': ({ pp, json }) => { const e = find(pp.eid); if (e.none) throw upstream(422, 'None has no folders, so it can\'t be renamed');
      e.name = String(json?.name || e.name); e.updated = now(); return ok(e); },
    'GET /v1/folders': () => ok({ folders: [] }),
    'GET /v1/skills': () => ok({ skills: [] }),
  };
}
