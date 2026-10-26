// Skills in Settings → Agent (skill-sources 3.2): how the list is grouped, and reading what the user picks to upload
// (a folder, a zip or a SKILL.md) into the agent's POST /v1/skills body. Written by us (web/PATCHES.md).

/** The agent's skills by where they come from: yours (uploaded or copied, and the learner's), then each mod's. */
export function groupSkills(skills = []) {
  const groups = new Map([['mine', { key: 'mine', title: 'Yours', items: [] }], ['learned', { key: 'learned', title: 'Learned', items: [] }]]);
  for (const s of skills) {
    const key = s.source === 'user' ? 'mine' : s.source === 'harness' ? 'learned' : 'mod:' + s.source;
    if (!groups.has(key)) groups.set(key, { key, title: s.source, items: [] });
    groups.get(key).items.push(s);
  }
  return [...groups.values()].filter(g => g.items.length);
}

function b64(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/** The upload body for picked files: one .zip → {zip}; otherwise every file with its path in the picked folder
 *  (`webkitRelativePath`) or its name → {files: [{path, data}]}. Hidden files are left out. */
export async function uploadBody(files, replace = false) {
  const list = [...files].filter(f => !(f.webkitRelativePath || f.name).split('/').some(p => p.startsWith('.')));
  if (list.length === 1 && /\.zip$/i.test(list[0].name)) return { zip: b64(await list[0].arrayBuffer()), ...(replace ? { replace } : {}) };
  const out = [];
  for (const f of list) out.push({ path: f.webkitRelativePath || f.name, data: b64(await f.arrayBuffer()) });
  return { files: out, ...(replace ? { replace } : {}) };
}
