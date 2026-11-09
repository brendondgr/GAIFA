// calendar 2.2: mods' notifications as toasts (web/notify.js): Open, actions through the hub's proxy, staying
// open, replacing one with the same key, at most five; and a `badge` event on the services list.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const N = await import(pathToFileURL(path.join(root, 'web/notify.js')).href);

const ev = (o = {}) => ({ type: 'notification', id: 'a1', service: 'calendar', title: 'Lunch with Sam', body: 'in 10 min', route: '#/calendar?item=c_1',
  key: 'f_1', actions: [{ label: 'Snooze 10 min', op: 'POST /v1/alerts/f_1/snooze' }, { label: 'Bad', op: 'GET /v1/x' }], ...o });

test('a notification is a toast that stays, with its route and actions', () => {
  const t = N.toastOf(ev());
  assert.equal(t.sticky, true);
  assert.equal(t.title, 'Lunch with Sam');
  assert.equal(t.route, '#/calendar?item=c_1');
  assert.deepEqual(t.actions, [{ label: 'Snooze 10 min', method: 'POST', path: '/v1/alerts/f_1/snooze', url: '/api/s/calendar/v1/alerts/f_1/snooze' }]);
  assert.equal(N.toastOf(ev({ level: 'warn' })).level, 'warn');
  assert.deepEqual(N.actionCall('Bad Id', 'POST /x'), { method: null, path: null, url: null });
});

test('the same key replaces; at most five', () => {
  let list = [N.toastOf(ev())];
  list = N.addToast(list, N.toastOf(ev({ id: 'a2', title: 'Lunch (snoozed)' })));
  assert.equal(list.length, 1);
  assert.equal(list[0].title, 'Lunch (snoozed)');
  for (let i = 0; i < 7; i++) list = N.addToast(list, N.toastOf(ev({ id: 'x' + i, key: 'k' + i, title: 'T' + i })));
  assert.equal(list.length, N.MAX_TOASTS);
  assert.equal(list.at(-1).title, 'T6');
});

test('a badge event changes one service', () => {
  const svcs = [{ id: 'calendar' }, { id: 'web', badge: 2 }];
  assert.deepEqual(N.withBadge(svcs, { service: 'calendar', unread: 4 }), [{ id: 'calendar', badge: 4 }, { id: 'web', badge: 2 }]);
  assert.equal(N.withBadge(svcs, { service: 'web', unread: 0 })[1].badge, null);
});
