import test from 'node:test';
import assert from 'node:assert/strict';
import { InterviewerSpeech } from '../src/services/speech/interviewerSpeech.ts';

const message = (id, text = id, authorKind = 'ai') => ({ id, text, authorKind, audioUrl: `/audio/${id}` });
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(t, customLoader) {
  const requests = [], played = [];
  let unlocks = 0, disposed = false, finish;
  const player = {
    async unlock() { unlocks++; },
    play(data, signal, onPlaying) {
      played.push(new TextDecoder().decode(data));
      onPlaying(true);
      return new Promise(resolve => {
        finish = () => { onPlaying(false); resolve(); };
        signal.addEventListener('abort', finish, { once: true });
      });
    },
    stop() { finish?.(); },
    dispose() { disposed = true; },
  };
  const loader = async (m, signal) => {
    requests.push(m.id);
    return customLoader ? customLoader(m, signal) : new TextEncoder().encode(m.id).buffer;
  };
  const c = new InterviewerSpeech(player, loader);
  const cleanup = c.connect();
  t.after(cleanup);
  return { c, requests, played, player, cleanup, end: () => finish(), unlocks: () => unlocks, disposed: () => disposed };
}

test('opt-in, AI-only ordered playback; duplicate HTTP/WS snapshots never duplicate requests', async t => {
  const { c, requests, played, end } = setup(t);
  const initial = [message('q1')];
  c.update(initial);
  assert.deepEqual(requests, []);
  c.enable();
  await tick();
  assert.equal(c.getSnapshot().speaking, true);
  const next = [...initial, message('a1', 'Ответ', 'candidate'), message('feedback'), message('q2')];
  c.update(next);
  c.update(structuredClone(next));
  assert.deepEqual(requests, ['q1']);
  end(); await tick();
  assert.deepEqual(played, ['q1', 'feedback']);
  end(); await tick();
  assert.deepEqual(played, ['q1', 'feedback', 'q2']);
  end(); await tick();
  c.update(next);
  assert.equal(c.getSnapshot().busy, false);
  assert.deepEqual(requests, played);
});

test('final feedback is pending while generation runs and remains busy until audio ends', async t => {
  let release;
  const { c, end } = setup(t, () => new Promise(resolve => { release = resolve; }));
  c.enable();
  const final = [message('final')];
  assert.equal(c.hasUnread(final), true);
  c.update(final);
  await tick();
  assert.equal(c.getSnapshot().busy, true);
  assert.equal(c.getSnapshot().speaking, false);
  release(new ArrayBuffer(8)); await tick();
  assert.equal(c.getSnapshot().speaking, true);
  end(); await tick();
  assert.equal(c.getSnapshot().busy, false);
});

test('mute aborts generation and an old response cannot play over a new request', async t => {
  const pending = [];
  const { c, played } = setup(t, (m, signal) => new Promise(resolve => pending.push({ resolve, signal })));
  c.update([message('old')]); c.enable(); await tick();
  c.stop();
  assert.equal(pending[0].signal.aborted, true);
  c.update([message('old'), message('new')]); c.enable(); await tick();
  pending[0].resolve(new TextEncoder().encode('old').buffer); await tick();
  assert.deepEqual(played, []);
  pending[1].resolve(new TextEncoder().encode('new').buffer); await tick();
  assert.deepEqual(played, ['new']);
});

test('repeat reads only the latest reply; muted messages are not replayed as a backlog', async t => {
  const { c, played, end } = setup(t);
  c.update([message('old'), message('current')]); c.enable(); await tick();
  end(); await tick(); c.repeat(); await tick();
  assert.deepEqual(played, ['current', 'current']);
});

test('backend error is visible, does not auto-retry paid generation, and allows explicit retry', async t => {
  let fail = true;
  const { c, requests, played } = setup(t, () => {
    if (fail) throw new Error('Проверь ключ GenAPI');
    return new ArrayBuffer(1);
  });
  c.update([message('q')]); c.enable(); await tick();
  assert.equal(c.getSnapshot().error, 'Проверь ключ GenAPI');
  assert.equal(c.getSnapshot().enabled, false);
  assert.equal(c.getSnapshot().busy, false);
  c.update([message('q')]); await tick();
  assert.equal(requests.length, 1);
  fail = false; c.enable(); await tick();
  assert.equal(c.getSnapshot().error, null);
  assert.equal(played.length, 1);
});

test('unmount stops audio and releases the audio context', async t => {
  const { c, cleanup, disposed } = setup(t);
  c.update([message('q')]); c.enable(); await tick();
  cleanup(); await tick();
  assert.equal(c.getSnapshot().speaking, false);
  assert.equal(disposed(), true);
});

test('unsupported browser does not request audio', () => {
  const c = new InterviewerSpeech(null, () => { throw new Error('must not fetch'); });
  c.update([message('q')]); c.enable();
  assert.equal(c.getSnapshot().available, false);
  assert.equal(c.hasUnread([message('q')]), false);
});

test('audio unlock happens synchronously in the user gesture and failure blocks generation', async t => {
  const { c, player, requests } = setup(t);
  let called = false;
  player.unlock = () => { called = true; return Promise.reject(new Error('Разреши звук')); };
  c.update([message('q')]); c.enable();
  assert.equal(called, true);
  await tick();
  assert.deepEqual(requests, []);
  assert.equal(c.getSnapshot().error, 'Разреши звук');
});
