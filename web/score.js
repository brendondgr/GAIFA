// The similarity score of a search by meaning, drawn the same way wherever one shows: the chat list's
// "By meaning" results, the header's Search (Ctrl K) and the Outputs page's "By meaning" list. The
// score is the embed mod's cosine similarity between the search and the match (EmbeddingGemma 2, as
// it returns it, rounded to 3 places): higher is closer, and there is no minimum, so a search always
// finds its nearest few. The badge is "0.58" with a tiny bar filled to the score. The pure parts
// (fmtScore, scoreWidth, scoreTitle) are tested in utils/tests/web/score.test.mjs.

const R = () => globalThis.React;
const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";
export const SCORE_TIP = 'Similarity to your search';

/** "0.58" (two places), or '' when there is no score. */
export function fmtScore(s) {
  const n = typeof s === 'string' && s.trim() ? Number(s) : s;
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '';
}

/** The bar's fill in percent: the score clamped to 0–1. */
export function scoreWidth(s) {
  const n = Number(s);
  return Number.isFinite(n) ? Math.round(Math.max(0, Math.min(1, n)) * 100) : 0;
}

/** The badge's tooltip: "Similarity to your search: 0.58 (higher is closer)". */
export function scoreTitle(s) {
  const f = fmtScore(s);
  return f ? `${SCORE_TIP}: ${f} (higher is closer)` : SCORE_TIP;
}

/** The small muted badge on the right of a result: a tiny bar and the score. Nothing without a score. */
export function ScoreBadge({ score, style }) {
  const f = fmtScore(score);
  if (!f) return null;
  const h = R().createElement;
  return h('span', { className: 'aih-score', title: scoreTitle(score), 'aria-label': `${SCORE_TIP} ${f}`,
    style: { display: 'inline-flex', alignItems: 'center', gap: 4, flex: 'none', height: 16, padding: '0 5px', borderRadius: 4,
      border: '1px solid var(--bd,#1D2430)', fontFamily: MONO, fontSize: 10.5, lineHeight: 1, color: 'var(--mut,#8A94A6)', whiteSpace: 'nowrap', ...style } },
    h('span', { 'aria-hidden': true, style: { width: 16, height: 3, borderRadius: 2, background: 'var(--bds,#2A3547)', overflow: 'hidden', flex: 'none' } },
      h('span', { style: { display: 'block', height: '100%', width: `${scoreWidth(score)}%`, background: 'var(--cy,#58C4DD)', opacity: 0.75 } })),
    f);
}
