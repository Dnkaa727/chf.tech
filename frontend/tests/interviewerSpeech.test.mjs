import test from 'node:test';
import assert from 'node:assert/strict';
import { InterviewerSpeech, speechChunks } from '../src/services/speech/interviewerSpeech.ts';

const ru = { lang: 'ru-RU', localService: true };
const message = (id, text, authorKind = 'ai') => ({ id, text, authorKind });
function setup(t, voices = [ru]) {
  const spoken = [];
  let cancelled = 0;
  const listeners = new Map();
  const synth = {
    getVoices: () => voices,
    speak: u => spoken.push(u),
    cancel: () => cancelled++,
    addEventListener: (event, cb) => listeners.set(event, cb),
    removeEventListener: (event, cb) => { if (listeners.get(event) === cb) listeners.delete(event); },
  };
  const controller = new InterviewerSpeech(synth, text => ({ text }));
  const disconnect = controller.connect();
  t.after(disconnect);
  return { controller, spoken, listeners, disconnect, cancelled: () => cancelled, voices: next => { voices = next; listeners.get('voiceschanged')?.(); } };
}

test('speech is opt-in, follows feedback/question order, and ignores duplicate snapshots and candidate text', t => {
  const { controller: c, spoken } = setup(t);
  const initial = [message('q1', 'Первый вопрос?')];
  c.update(initial);
  assert.equal(spoken.length, 0);
  c.enable();
  assert.equal(spoken[0].voice, ru);
  assert.equal(c.getSnapshot().speaking, false);
  spoken[0].onstart();
  assert.equal(c.getSnapshot().speaking, true);
  const next = [...initial, message('a1', 'Ответ кандидата', 'candidate'), message('f1', 'Ты верно заметил блокировку.'), message('q2', 'Как это проверить?')];
  c.update(next);
  c.update(structuredClone(next));
  assert.equal(spoken.length, 1);
  spoken[0].onend();
  assert.equal(spoken[1].text, 'Ты верно заметил блокировку.');
  spoken[1].onend();
  assert.equal(spoken[2].text, 'Как это проверить?');
  spoken[2].onend();
  assert.equal(c.getSnapshot().busy, false);
  c.update(next);
  assert.equal(spoken.length, 3);
});

test('final feedback remains pending before and during speech', t => {
  const { controller: c, spoken } = setup(t);
  c.enable();
  const final = [message('final', 'Ты хорошо разобрал эту тему.')];
  assert.equal(c.hasUnread(final), true);
  c.update(final);
  assert.equal(c.hasUnread(final), false);
  assert.equal(c.getSnapshot().busy, true);
  spoken[0].onend();
  assert.equal(c.getSnapshot().busy, false);
});

test('mute cancels queued speech, stale callbacks cannot resume it; re-enable reads only latest', t => {
  const { controller: c, spoken, cancelled } = setup(t);
  c.update([message('q', 'Вопрос?')]);
  c.enable();
  const staleEnd = spoken[0].onend;
  c.update([message('q', 'Вопрос?'), message('f', 'Обратная связь.'), message('next', 'Следующий вопрос?')]);
  c.stop();
  staleEnd();
  assert.equal(cancelled(), 1);
  assert.equal(spoken.length, 1);
  assert.equal(c.getSnapshot().busy, false);
  c.enable();
  assert.equal(spoken[1].text, 'Следующий вопрос?');
  spoken[1].onend();
  assert.equal(c.getSnapshot().busy, false);
});

test('repeat explicitly rereads latest message without replaying transcript', t => {
  const { controller: c, spoken } = setup(t);
  c.update([message('old', 'Старая реплика.'), message('new', 'Текущий вопрос?')]);
  c.enable();
  spoken[0].onend();
  c.repeat();
  assert.deepEqual(spoken.map(s => s.text), ['Текущий вопрос?', 'Текущий вопрос?']);
});

test('voice loading and missing Russian voice do not silently select an English voice', t => {
  const { controller: c, spoken, voices } = setup(t, []);
  c.update([message('q', 'Вопрос?')]);
  c.enable();
  assert.equal(spoken.length, 0);
  voices([{ lang: 'en-US', localService: true }]);
  c.enable();
  assert.equal(spoken.length, 0);
  voices([ru]);
  c.enable();
  assert.equal(spoken[0].voice, ru);
});

test('speech failures stop animation/queue and allow explicit retry', t => {
  const { controller: c, spoken } = setup(t);
  c.update([message('q', 'Вопрос?')]);
  c.enable();
  spoken[0].onstart();
  spoken[0].onerror({ error: 'not-allowed' });
  assert.equal(c.getSnapshot().enabled, false);
  assert.equal(c.getSnapshot().speaking, false);
  assert.match(c.getSnapshot().error, /Не удалось/);
  c.enable();
  assert.equal(spoken.length, 2);
  assert.equal(c.getSnapshot().error, null);
});

test('unmount removes voice listeners and stops the active utterance', t => {
  const { controller: c, spoken, listeners, disconnect, cancelled } = setup(t);
  c.update([message('q', 'Вопрос?')]);
  c.enable();
  disconnect();
  assert.equal(listeners.size, 0);
  assert.equal(cancelled(), 1);
  assert.equal(spoken[0].onend, null);
});

test('unsupported browser remains usable without speech', () => {
  const c = new InterviewerSpeech(null, () => { throw new Error('Not supported'); });
  c.update([message('q', 'Вопрос?')]);
  c.enable();
  assert.equal(c.getSnapshot().enabled, false);
  assert.equal(c.hasUnread([message('q', 'Вопрос?')]), false);
});

test('long feedback is split without losing words or punctuation', () => {
  const text = 'Ты верно описал цикл событий. ' + 'Теперь рассмотрим детали '.repeat(30) + 'Готов?';
  const chunks = speechChunks(text);
  assert.ok(chunks.every(c => c.length <= 180));
  assert.equal(chunks.join(' '), text.trim());
});
