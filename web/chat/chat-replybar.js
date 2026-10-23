// The row under a finished reply (AssistantCard in chat-cards.js): the Sources pill (when the turn searched
// or read the web; chat-sources.js), Copy with its three ways (chat-copy.js), then the thumbs. Hidden while
// the reply streams or its turn still runs. `ctx.turn` is the reply's turn (chat-activity.js's TurnView
// passes it); a reply outside a turn gets Copy and the thumbs only.

import { SpeakButton } from './chat-speak.js';
import { h } from './chat-ui.js';
import { turnSources, SourcesPill, useAttachedPages } from './chat-sources.js';
import { CopyButton } from './chat-copy.js';

const R = () => globalThis.React;

export function ReplyBar({ text, ctx, thumbs }) {
  const React = R(), turn = ctx?.turn || null;
  const attached = useAttachedPages(turn, ctx);   // pages attached before docs carried their URL
  const src = React.useMemo(() => (turn ? turnSources(turn, attached) : null), [turn, attached.length]);
  if (turn?.running) return null;
  return h('div', { role: 'group', 'aria-label': 'Reply actions', style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, minWidth: 0, marginTop: 4 } },
    src && (src.read.length || src.found.length) ? h(SourcesPill, { src, ctx }) : null,
    h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 2 } },   // no opacity here: it would make the menus see-through
      h(CopyButton, { text, turn, src, ctx }), h(SpeakButton, { text, ctx }), thumbs || null));   // SpeakButton: plan 49.1
}
