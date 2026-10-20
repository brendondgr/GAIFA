// The composer's files (plan 24.6): which files can be uploaded (images, video, audio, text, code and
// documents, the hub's kinds of plan 24.1), long pastes as files, and the attachment chips' icons and sizes.

export const MEDIA_EXT = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'avif', 'mp4', 'webm', 'mov', 'mkv', 'wav', 'mp3', 'flac', 'ogg', 'opus', 'm4a', 'aac'];
export const TEXT_EXT = ['md', 'markdown', 'txt', 'log', 'rst',
  'py', 'js', 'mjs', 'ts', 'tsx', 'jsx', 'rs', 'go', 'c', 'h', 'cpp', 'hpp', 'cc', 'java', 'kt', 'swift', 'rb', 'php', 'lua',
  'sh', 'bash', 'zsh', 'fish', 'ps1', 'sql', 'r', 'jl', 'cs',
  'toml', 'yaml', 'yml', 'ini', 'cfg', 'conf', 'env.example', 'xml', 'html', 'htm', 'css', 'scss',
  'json', 'jsonl', 'csv', 'tsv', 'srt', 'vtt', 'ipynb'];
export const DOC_EXT = ['pdf', 'docx', 'epub', 'pptx', 'xlsx', 'odt'];
/** The file picker's `accept`. */
export const ACCEPT = ['image/*', 'video/*', 'audio/*', ...[...TEXT_EXT, ...DOC_EXT].map(e => '.' + e)].join(',');

/** The extension that sets the kind, lower case ("env.example" is one). */
export function extOf(name) {
  const n = String(name || '').toLowerCase();
  if (n.endsWith('env.example')) return 'env.example';
  const i = n.lastIndexOf('.');
  return i < 0 ? '' : n.slice(i + 1);
}

/** The kind the hub will give a file: image, video, audio, text, document, or null (not uploadable). */
export function kindOf(name, type = '') {
  const e = extOf(name), m = /^(image|video|audio)\//.exec(type || '');
  if (m) return m[1];
  if (MEDIA_EXT.includes(e)) return ['mp4', 'webm', 'mov', 'mkv'].includes(e) ? 'video' : ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'avif'].includes(e) ? 'image' : 'audio';
  if (TEXT_EXT.includes(e)) return 'text';
  if (DOC_EXT.includes(e)) return 'document';
  return null;
}

/** The files in a drop or paste (or a file picker) that can be uploaded. */
export function uploadable(list) {
  return [...(list || [])].filter(f => f && kindOf(f.name, f.type));
}

export const PASTE_CHARS = 2000, PASTE_LINES = 40;
const LANG_EXT = { python: 'py', py: 'py', javascript: 'js', js: 'js', mjs: 'js', typescript: 'ts', ts: 'ts', tsx: 'tsx', jsx: 'jsx',
  json: 'json', jsonl: 'jsonl', bash: 'sh', sh: 'sh', shell: 'sh', zsh: 'sh', fish: 'fish', console: 'sh', rust: 'rs', rs: 'rs', go: 'go',
  c: 'c', h: 'c', cpp: 'cpp', 'c++': 'cpp', java: 'java', kotlin: 'kt', kt: 'kt', swift: 'swift', ruby: 'rb', rb: 'rb', php: 'php',
  lua: 'lua', sql: 'sql', r: 'r', julia: 'jl', csharp: 'cs', cs: 'cs', 'c#': 'cs', powershell: 'ps1', ps1: 'ps1', yaml: 'yaml', yml: 'yaml',
  toml: 'toml', ini: 'ini', xml: 'xml', html: 'html', css: 'css', scss: 'scss', markdown: 'md', md: 'md', csv: 'csv', tsv: 'tsv', text: 'txt', txt: 'txt' };

const two = n => String(n).padStart(2, '0');

/** A paste over 2000 characters or 40 lines as a file `{name, body}` (else null): `pasted-HHMMSS.md`,
 *  or the language's extension when the whole paste is one fenced block (its inside becomes the file),
 *  or `.json` when it parses as JSON. */
export function pasteFile(text, now = new Date()) {
  const t = String(text || '');
  if (t.length <= PASTE_CHARS && t.split('\n').length <= PASTE_LINES) return null;
  const base = `pasted-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  const m = /^\s*(`{3,}|~{3,})([\w+#.-]*)[^\n]*\n([\s\S]*?)\n\1\s*$/.exec(t);
  if (m && !new RegExp('^' + m[1][0] + '{3,}', 'm').test(m[3])) {
    const ext = LANG_EXT[m[2].toLowerCase()];
    if (ext) return { name: `${base}.${ext}`, body: m[3] + '\n' };
  }
  const s = t.trim();
  if (/^[[{]/.test(s)) { try { JSON.parse(s); return { name: `${base}.json`, body: s + '\n' }; } catch { /* not JSON */ } }
  return { name: `${base}.md`, body: t };
}

/** An uploaded output as an attachment chip. */
export const toChip = o => ({ id: o.id, kind: o.kind, title: o.title, preview: o.preview || (o.kind === 'image' ? o.url : null), ...(o.subtype ? { subtype: o.subtype } : {}) });

/** The chip's icon: by kind, and code for code. */
export function chipIcon(a) {
  if (a.kind === 'text') return /^(code|config|web|data):|notebook/.test(a.subtype || '') ? 'code' : 'doc';
  return { image: 'image', video: 'video', audio: 'wave', model3d: 'cube', document: 'doc' }[a.kind] || 'clip';
}

/** "12 pages" / "40 lines" once the text is known (`outputText`), else ''. */
export function chipSize(a) {
  if (a.pages) return `${a.pages} page${a.pages === 1 ? '' : 's'}`;
  if (a.lines) return `${a.lines} line${a.lines === 1 ? '' : 's'}`;
  return '';
}
