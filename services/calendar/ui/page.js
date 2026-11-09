// The Calendar's page module (calendar plan Phase 3). Until the page lands, the mod's tab says where it is.
import { panel, header, requireRunning } from '/mod-kit.js';

export default {
  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the calendar')) return;
    el.replaceChildren(panel([header('Calendar', 'Events, to-dos and reminders')]));
  },
};
