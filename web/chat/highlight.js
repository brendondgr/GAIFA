// A small code highlighter shared by the chat's code blocks and the outputs viewer (plan 24.7):
// keywords, strings, numbers and comments, one line at a time, every character escaped. No library
// (nothing loads from a CDN). Pure (no DOM), tested in utils/tests/web/citations.test.mjs and chat.test.mjs.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

const WORDS = {
  python: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return self True try while with yield',
  shell: 'case do done elif else esac exit export fi for function if in local return set then until while echo',
  sql: 'select from where and or not insert into values update set delete create table index join left right inner outer on group by order having limit as null is in like distinct union',
  rust: 'as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false',
  c: 'auto break case catch char class const continue default delete do double else enum extern false float for friend goto if inline int long namespace new nullptr private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while bool',
  js: 'async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield interface type enum implements',
  conf: 'true false null yes no on off',
};
const FAMILY = { python: 'python', shell: 'shell', fish: 'shell', powershell: 'shell', sql: 'sql', rust: 'rust', go: 'go',
  c: 'c', cpp: 'c', java: 'c', csharp: 'c', kotlin: 'c', swift: 'c', php: 'js', javascript: 'js', typescript: 'js', tsx: 'js', jsx: 'js', json: 'js', ruby: 'python', lua: 'python', r: 'python', julia: 'python',
  toml: 'conf', yaml: 'conf', ini: 'conf', env: 'conf', dockerfile: 'shell', makefile: 'shell' };
// What people write after ``` → the names above.
const ALIAS = { py: 'python', python3: 'python', sh: 'shell', bash: 'shell', zsh: 'shell', console: 'shell', shellsession: 'shell', ps1: 'powershell', pwsh: 'powershell',
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', node: 'javascript', ts: 'typescript', rs: 'rust', golang: 'go', 'c++': 'cpp', cc: 'cpp', cxx: 'cpp', h: 'c', hpp: 'cpp',
  'c#': 'csharp', cs: 'csharp', kt: 'kotlin', rb: 'ruby', yml: 'yaml', jsonc: 'json', json5: 'json', docker: 'dockerfile', make: 'makefile', mk: 'makefile', psql: 'sql', postgres: 'sql', sqlite: 'sql', mysql: 'sql' };
const HASH = new Set(['python', 'shell', 'conf']);
const KW = Object.fromEntries(Object.entries(WORDS).map(([k, v]) => [k, new Set(v.split(' '))]));

/** A fence's language word (```py, ```C++) → the highlighter's name for it ('python', 'cpp'), or the word lowercased. */
export const normLang = lang => { const l = String(lang || '').toLowerCase(); return ALIAS[l] || l; };

/** One line of code as HTML: every character escaped, keywords, strings, numbers and comments in spans. */
export function highlightLine(line, lang) {
  lang = normLang(lang);
  if (lang === 'diff' || lang === 'patch') {
    const cls = /^(\+\+\+|---)/.test(line) ? 'k' : line[0] === '+' ? 's' : line[0] === '-' ? 'd' : line.startsWith('@@') ? 'n' : '';
    return cls ? `<span class="${cls}">${esc(line)}</span>` : esc(line);
  }
  const fam = FAMILY[lang], kw = KW[fam];
  if (!fam) return esc(line);
  const comment = HASH.has(fam) ? '#.*' : fam === 'sql' ? '--.*' : '\\/\\/.*|\\/\\*.*?(?:\\*\\/|$)';
  const rx = new RegExp(`(${comment})|("(?:[^"\\\\]|\\\\.)*"?|'(?:[^'\\\\]|\\\\.)*'?|\`[^\`]*\`?)|(\\b\\d[\\d_.xXa-fA-F]*\\b)|([A-Za-z_][\\w]*)`, 'g');
  let out = '', last = 0;
  for (const m of line.matchAll(rx)) {
    out += esc(line.slice(last, m.index));
    const t = esc(m[0]);
    out += m[1] ? `<span class="c">${t}</span>` : m[2] ? `<span class="s">${t}</span>` : m[3] ? `<span class="n">${t}</span>`
      : kw && (kw.has(m[4]) || (fam === 'sql' && kw.has(m[4].toLowerCase()))) ? `<span class="k">${t}</span>` : t;
    last = m.index + m[0].length;
  }
  return out + esc(line.slice(last));
}

/** A whole block of code, line by line. */
export const highlight = (code, lang) => String(code ?? '').split('\n').map(l => highlightLine(l, lang)).join('\n');
