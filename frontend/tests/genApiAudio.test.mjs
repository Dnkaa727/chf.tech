import test from 'node:test';
import assert from 'node:assert/strict';
import { loadInterviewAudio } from '../src/services/speech/genApiAudio.ts';

test('loads audio from backend with no provider token and abort support', async t => {
  const signal = new AbortController().signal;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url,'http://localhost:8081/api/conferences/room/messages/q/audio');
    assert.deepEqual(options,{method:'POST',signal});
    return new Response('audio',{headers:{'Content-Type':'audio/ogg'}});
  });
  const data = await loadInterviewAudio({audioUrl:'http://localhost:8081/api/conferences/room/messages/q/audio'},signal);
  assert.equal(new TextDecoder().decode(data),'audio');
});

test('shows safe backend errors instead of attempting to decode them', async t => {
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:'Проверь ключ GenAPI'}),{status:503}));
  await assert.rejects(loadInterviewAudio({audioUrl:'/audio'},new AbortController().signal),/Проверь ключ/);
});

test('rejects HTML success response and unavailable message', async t => {
  t.mock.method(globalThis,'fetch',async()=>new Response('<html>error</html>',{headers:{'Content-Type':'text/html'}}));
  await assert.rejects(loadInterviewAudio({audioUrl:'/audio'},new AbortController().signal),/некорректное аудио/);
  await assert.rejects(loadInterviewAudio({},new AbortController().signal),/недоступно/);
});
