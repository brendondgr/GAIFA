// Settings hashes (plan settings-redesign 2.2): `#/settings/<section>[/<group>[/<row>]]`, with the old section
// names kept as aliases. Pure; tested in utils/tests/web/settings-route.test.mjs. Written by us (web/PATCHES.md).

// Old hash → where it lives now (docs and the palette linked these).
export const ALIASES = {
  paths: ['machine', 'storage'], memory: ['machine', 'memory'], interface: ['general', 'interface'],
  'agent/permissions': ['permissions'], 'about/hardware': ['machine', 'hardware'],
};

/** `parts` after `settings` (['machine', 'memory', 'reserve']) → {section, group, row}; unknown parts dropped, no section → the first. */
export function parseSettingsRoute(parts, sections) {
  let p = (parts || []).filter(Boolean);
  const two = p.slice(0, 2).join('/');
  if (ALIASES[two]) p = [...ALIASES[two], ...p.slice(2)];
  else if (ALIASES[p[0]]) p = [...ALIASES[p[0]], ...p.slice(1)];
  const sec = sections.find(s => s.id === p[0]) || null;
  const grp = sec?.groups.find(g => g.id === p[1]) || null;
  const row = grp?.rows.find(r => r.id === p[2]) || null;
  return { section: (sec || sections[0])?.id || null, group: grp?.id || null, row: row?.id || null, known: !!sec || !p.length };
}

/** The hash for a place. */
export const settingsHash = (section, group, row) => '#/settings/' + [section, group, row].filter(Boolean).map(encodeURIComponent).join('/');

/** Where you are, as words: ['Machine', 'Memory'] (the header's "where you are" and the tab title). */
export function settingsPlace(parts, sections) {
  const r = parseSettingsRoute(parts, sections), sec = sections.find(s => s.id === r.section);
  if (!sec) return [];
  const grp = r.group ? sec.groups.find(g => g.id === r.group) : null;
  return [sec.label, ...(grp && grp.label !== sec.label ? [grp.label] : [])];
}
