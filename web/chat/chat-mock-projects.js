// The chat mock's projects (plan projects 1.3, `?mock`): the agent's /v1/projects routes on in-memory projects, with the
// same shapes as services/agent/agent/api_projects.py. Two fixture projects: Thesis (instructions, two environments, a
// folder of its own, two files and two pages, a fact in its memory, defaults) and Garden planner (bare). Every change is a
// `{type: 'project', id, project}` event to the `watchProjects` listeners, and sources a `project_source` one, as the
// agent's streams opened with watch=projects send them. `k` is chat-mock.js's helpers: { threads, newThread, emit, net,
// err, now, rid, pub }.

const HOUR = 3600;

export function createProjectMocks({ threads, newThread, emit, net, err, now, rid, pub }) {
  const projects = new Map(), sources = new Map(), facts = new Map(), folders = new Map(), watchers = new Set();
  let seeded = false;

  const P = pid => { const p = projects.get(pid); if (!p) throw err(404, `no project '${pid}'`, 'unknown_project'); return p; };
  const inProject = pid => [...threads.values()].filter(t => t.thread.settings?.project === pid);
  const activity = p => Math.max(p.updated, ...inProject(p.id).map(t => t.thread.updated));
  const row = p => ({ ...structuredClone(p), activity: activity(p), chats: inProject(p.id).filter(t => !t.thread.archived).length,
    source_count: (sources.get(p.id) || []).length });
  const full = p => ({ ...row(p), sources: structuredClone(sources.get(p.id) || []) });
  const tell = ev => watchers.forEach(f => { try { f(ev); } catch { /* a listener's own error */ } });
  const changed = pid => { const p = projects.get(pid); tell({ type: 'project', thread_id: null, seq: null, id: pid, project: p ? row(p) : null }); };
  const sourceEvent = (pid, s) => tell({ type: 'project_source', thread_id: null, seq: null, id: pid, source: structuredClone(s) });

  function make(body, ts = now()) {
    const name = String(body.name || '').trim().replace(/\s+/g, ' ');
    if (!name) throw err(422, 'a project needs a name', 'bad_name');
    if ((body.instructions || '').length > 16000) throw err(422, 'the instructions are at most 16,000 characters', 'too_long');
    const p = { id: rid('p_').slice(0, 12), name, description: body.description || '', instructions: body.instructions || '',
      environments: [...new Set(body.environments || [])], own_env: null, defaults: { ...(body.defaults || {}) }, memory_entity: rid('e_'),
      pinned: false, created: ts, updated: ts };
    projects.set(p.id, p); sources.set(p.id, []); facts.set(p.id, []); folders.set(p.id, []);
    return p;
  }
  function addSrc(pid, s, ts = now()) {
    const list = sources.get(pid);
    if (list.length >= 200) throw err(409, 'a project holds at most 200 files and pages', 'too_many_sources');
    if (list.some(x => (s.kind === 'file' && x.output_id === s.output_id) || (s.kind === 'page' && x.url === s.url))) throw err(409, `that ${s.kind} is in the project already`, 'exists');
    const src = { id: rid('src_').slice(0, 14), project_id: pid, kind: s.kind, output_id: s.output_id || null, url: s.url || null,
      title: s.title || s.url || s.output_id, max_age_s: s.kind === 'page' ? (s.max_age_s === undefined ? HOUR : s.max_age_s) : null,
      fetched: s.fetched ?? (s.kind === 'page' ? ts : null), chars: s.chars || 0, status: s.status || 'ok', error: s.error || null, added: ts,
      position: list.length };
    list.push(src);
    return src;
  }
  function seed() {
    if (seeded) return;
    seeded = true;
    const t0 = now();
    const a = make({ name: 'Thesis', description: 'Chapter drafts and the literature review for the thesis on alpine glaciers.',
      instructions: '- Answer in British English.\n- Cite sources as #n p.14 or src_…:line.\n- Keep summaries under 200 words.',
      environments: ['thesis', 'default'], defaults: { model: 'skynet', mode: 'accept_edits', disabled: ['comfy'], skills: ['comfy/comfy'] } }, t0 - 6 * 86400);
    a.own_env = 'proj-' + a.id.slice(2); a.pinned = true;
    folders.set(a.id, [{ id: 'thesis-notes', path: '/home/user/Documents/thesis-notes', level: 'edit', name: '' }]);
    addSrc(a.id, { kind: 'file', output_id: 'o_mock_paper', title: 'Glacier mass balance 2024.pdf', chars: 48200 }, t0 - 5 * 86400);
    addSrc(a.id, { kind: 'file', output_id: 'o_mock_notes', title: 'Chapter 2 notes.md', chars: 9100 }, t0 - 4 * 86400);
    addSrc(a.id, { kind: 'page', url: 'https://wgms.ch/latest-glacier-mass-balance-data/', title: 'Latest glacier mass balance data', chars: 15400, fetched: t0 - 2 * HOUR }, t0 - 3 * 86400);
    addSrc(a.id, { kind: 'page', url: 'https://news.example.org/alps-summer-melt', title: 'Alps summer melt', status: 'error', error: 'the page timed out after 20 s',
      chars: 6200, fetched: t0 - 30 * HOUR, max_age_s: 6 * HOUR }, t0 - 2 * 86400);
    facts.get(a.id).push({ id: 'f_mock_deadline', text: 'The thesis draft is due on December 1.', kind: 'fact', source: 'learned', state: 'current', recorded: t0 - 86400 });
    const b = make({ name: 'Garden planner', description: 'What to plant where, and when.' }, t0 - 9 * 86400);
    for (const [title, pid, ago] of [['Literature review outline', a.id, 3 * HOUR], ['Mass balance figures', a.id, 26 * HOUR], ['Tomatoes by the fence', b.id, 8 * 86400]]) {
      const t = newThread({ title, settings: { project: pid, ...(projects.get(pid).environments[0] ? { environment: projects.get(pid).environments[0] } : {}) } });
      emit(t, 'user', { text: title });
      emit(t, 'assistant', { text: `Notes for “${title}”.`, step: rid('s_'), model: 'skynet' });
      t.thread.updated = t0 - ago;
    }
  }

  /** A new chat's body in a project, as the agent's new_chat: the project's defaults under the request's own settings. */
  function newChatBody(body = {}) {
    seed();
    const pid = body.settings?.project;
    if (!pid) return body;
    const p = P(pid), d = p.defaults || {};
    const base = Object.fromEntries(['disabled', 'pinned', 'mcp_on'].filter(k => d[k]?.length).map(k => [k, [...d[k]]]));
    if (p.environments[0]) base.environment = p.environments[0];
    return { ...body, model: body.model || d.model || null, mode: body.mode || d.mode || 'manual', settings: { ...base, ...body.settings } };
  }
  /** A thread patch that moves a chat into a project (its primary environment) or out (`project: null`). */
  function movePatch(settings, patch) {
    seed();
    const out = { ...settings, ...patch };
    if (!('project' in patch)) return out;
    if (!patch.project) { delete out.project; return out; }
    const p = P(patch.project);
    if (p.environments[0] && !('environment' in patch)) out.environment = p.environments[0];
    return out;
  }

  const sortBy = { name: (a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()), created: (a, b) => b.created - a.created };
  return {
    newChatBody, movePatch, seed,
    async projects({ q, sort = 'activity' } = {}) {
      seed(); await net();
      const qq = (q || '').toLowerCase();
      return [...projects.values()].filter(p => !qq || p.name.toLowerCase().includes(qq) || p.description.toLowerCase().includes(qq))
        .map(row).sort((a, b) => (b.pinned - a.pinned) || (sortBy[sort] || ((x, y) => y.activity - x.activity))(a, b));
    },
    async project(pid) { seed(); await net(); return full(P(pid)); },
    async createProject(body = {}) { seed(); await net(); const p = make(body); changed(p.id); return full(p); },
    async patchProject(pid, patch = {}) {
      seed(); await net();
      const p = P(pid), old = p.environments[0];
      if (patch.name != null && !String(patch.name).trim()) throw err(422, 'a project needs a name', 'bad_name');
      for (const k of ['name', 'description', 'instructions', 'pinned']) if (patch[k] != null) p[k] = k === 'name' ? String(patch[k]).trim() : patch[k];
      if (patch.environments) p.environments = [...new Set(patch.environments)];
      if (patch.defaults) p.defaults = Object.fromEntries(Object.entries(patch.defaults).filter(([, v]) => v != null));
      if (Object.keys(patch).some(k => k !== 'pinned')) p.updated = now();   // a pin isn't activity
      if (p.environments[0] && p.environments[0] !== old) inProject(pid).forEach(t => { t.thread.settings = { ...t.thread.settings, environment: p.environments[0] }; });
      changed(pid);
      return full(p);
    },
    async deleteProject(pid) {
      seed(); await net(); P(pid);
      const chats = inProject(pid);
      chats.forEach(t => { const s = { ...t.thread.settings }; delete s.project; t.thread.settings = s; });
      projects.delete(pid); sources.delete(pid); facts.delete(pid); folders.delete(pid);
      changed(pid);
      return { deleted: pid, chats: chats.length };
    },
    async projectThreads(pid, { q, archived, limit = 200, sort = 'updated', offset = 0 } = {}) {
      seed(); await net(); P(pid);
      const qq = (q || '').toLowerCase();
      const order = { title: (a, b) => a.thread.title.toLowerCase().localeCompare(b.thread.title.toLowerCase()), created: (a, b) => b.thread.created - a.thread.created }[sort]
        || ((a, b) => b.thread.updated - a.thread.updated);
      return inProject(pid).filter(t => !!t.thread.archived === !!archived).filter(t => !qq || t.thread.title.toLowerCase().includes(qq))
        .sort(order).slice(offset, offset + limit).map(pub);
    },
    async addSource(pid, body) {
      seed(); await net(); P(pid);
      if (body.kind === 'page' && !/^https?:\/\//.test(body.url || '')) throw err(422, 'a page needs an http(s) URL', 'bad_url');
      const s = addSrc(pid, { ...body, title: body.kind === 'page' ? (body.url || '').replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '') : (body.title || body.output_id), chars: body.kind === 'page' ? 8000 : 4000 });
      projects.get(pid).updated = now();
      sourceEvent(pid, s); changed(pid);
      return structuredClone(s);
    },
    async patchSource(pid, sid, patch = {}) {
      seed(); await net();
      const list = sources.get(P(pid).id), s = list.find(x => x.id === sid);
      if (!s) throw err(404, `no source '${sid}'`, 'unknown_source');
      if (patch.title != null) s.title = patch.title;
      if ('max_age_s' in patch) s.max_age_s = patch.max_age_s;
      if (patch.position != null) { list.splice(list.indexOf(s), 1); list.splice(Math.max(0, Math.min(list.length, patch.position)), 0, s); list.forEach((x, i) => { x.position = i; }); }
      sourceEvent(pid, s);
      return structuredClone(s);
    },
    async removeSource(pid, sid) {
      seed(); await net();
      const list = sources.get(P(pid).id), i = list.findIndex(x => x.id === sid);
      if (i < 0) throw err(404, `no source '${sid}'`, 'unknown_source');
      list.splice(i, 1); changed(pid);
      return { removed: sid };
    },
    async refreshSource(pid, sid) {
      seed(); await net();
      const s = (sources.get(P(pid).id) || []).find(x => x.id === sid);
      if (!s) throw err(404, `no source '${sid}'`, 'unknown_source');
      if (s.kind !== 'page') throw err(422, 'only pages are fetched again', 'not_a_page');
      s.status = 'fetching'; sourceEvent(pid, s);
      await net();
      Object.assign(s, { status: 'ok', error: null, fetched: now(), output_id: rid('o_') });
      sourceEvent(pid, s);
      return structuredClone(s);
    },
    watchProjects(onEvent) { watchers.add(onEvent); return { close() { watchers.delete(onEvent); } }; },
    // Phase 2.3 and 4.2's routes, for the project page's panels
    async projectFolders(pid) { seed(); await net(); P(pid); return structuredClone(folders.get(pid)); },
    async addProjectFolder(pid, { path, level = 'read' }) {
      seed(); await net(); const p = P(pid);
      if (!String(path || '').startsWith('/')) throw err(422, 'a folder is a full path', 'bad_path');
      const list = folders.get(pid);
      if (list.some(f => f.path === path)) throw err(409, `${path} is already in the project`, 'exists');
      const f = { id: path.split('/').filter(Boolean).pop().toLowerCase().replace(/[^a-z0-9._-]+/g, '-') || 'folder', path, level, name: '' };
      list.push(f); p.own_env = p.own_env || 'proj-' + pid.slice(2); p.updated = now(); changed(pid);
      return structuredClone(f);
    },
    async patchProjectFolder(pid, fid, { level }) {
      seed(); await net(); const f = (folders.get(P(pid).id) || []).find(x => x.id === fid);
      if (!f) throw err(404, `no folder '${fid}'`, 'unknown_folder');
      if (level) f.level = level; changed(pid);
      return structuredClone(f);
    },
    async removeProjectFolder(pid, fid) {
      seed(); await net(); const list = folders.get(P(pid).id), i = list.findIndex(x => x.id === fid);
      if (i < 0) throw err(404, `no folder '${fid}'`, 'unknown_folder');
      list.splice(i, 1); changed(pid);
      return { removed: fid };
    },
    async projectMemory(pid) { seed(); await net(); const p = P(pid); return { entity: { id: p.memory_entity, name: p.name, kind: 'project' }, facts: structuredClone(facts.get(pid)) }; },
    async patchProjectFact(pid, fid, { text }) {
      seed(); await net(); const f = (facts.get(P(pid).id) || []).find(x => x.id === fid);
      if (!f) throw err(404, `no fact '${fid}'`, 'not_found');
      f.text = text; return structuredClone(f);
    },
    async forgetProjectFact(pid, fid) {
      seed(); await net(); const list = facts.get(P(pid).id), i = list.findIndex(x => x.id === fid);
      if (i < 0) throw err(404, `no fact '${fid}'`, 'not_found');
      list.splice(i, 1); return { forgotten: fid };
    },
  };
}
