import { test } from 'node:test'
import assert from 'node:assert/strict'
import { OrderedAudioPlayer } from '../src/js/utils/orderedAudio.js'

class Events {
  constructor() { this.listeners = new Map() }
  addEventListener(name, callback) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), callback])
  }
  fire(name) { for (const callback of this.listeners.get(name) || []) callback() }
}
class Buffer extends Events {
  constructor() { super(); this.updating = false; this.appended = []; this.aborted = false }
  appendBuffer(data) { this.appended.push([...data]); this.updating = true }
  complete() { this.updating = false; this.fire('updateend') }
  abort() { this.updating = false; this.aborted = true; this.fire('updateend') }
}
class Source extends Events {
  constructor() { super(); this.readyState = 'closed'; this.created = 0 }
  open() { this.readyState = 'open'; this.fire('sourceopen') }
  addSourceBuffer() { ++this.created; this.buffer = new Buffer(); return this.buffer }
  endOfStream() { this.readyState = 'ended' }
}
function fixture() {
  const sources = [], revoked = [], errors = []
  const audio = { paused: true, src: '', pause() { this.paused = true }, play() { this.paused = false; return Promise.resolve() },
    removeAttribute() { this.src = '' }, load() {} }
  const player = new OrderedAudioPlayer({ audio, createSource: () => { const source = new Source(); sources.push(source); return source },
    supported: () => true, createURL: () => `mock:${sources.length}`, revokeURL: url => revoked.push(url),
    onError: error => errors.push(error) })
  return { player, sources, revoked, errors, audio }
}
const encoded = byte => btoa(String.fromCharCode(byte))

test('out of order chunks play once in sequence and finish drains', () => {
  const { player, sources } = fixture()
  player.start('A')
  player.accept('A', 1, encoded(2)); player.accept('A', 0, encoded(1))
  assert.equal(player.accept('A', 0, encoded(9)), false)
  sources[0].open()
  player.finish('A')
  assert.deepEqual(sources[0].buffer.appended, [[1]])
  sources[0].buffer.complete()
  assert.deepEqual(sources[0].buffer.appended, [[1], [2]])
  sources[0].buffer.complete()
  assert.equal(sources[0].readyState, 'ended')
})

test('late sourceopen and updateend cannot mutate the next generation', () => {
  const { player, sources } = fixture()
  player.start('A'); const old = sources[0]
  player.start('B'); old.open()
  assert.equal(old.created, 0)
  sources[1].open(); player.accept('B', 0, encoded(2))
  const staleBuffer = sources[1].buffer
  player.start('C'); sources[2].open()
  staleBuffer.complete()
  assert.equal(player.accept('B', 1, encoded(3)), false)
  assert.deepEqual(sources[2].buffer.appended, [])
})

test('stop is idempotent, releases URL, aborts buffer and empties queues', () => {
  const { player, sources, revoked, audio } = fixture()
  player.start('A'); sources[0].open(); player.accept('A', 0, encoded(1)); player.accept('A', 2, encoded(3))
  const state = player.stop(); player.stop()
  assert.equal(state.paused, true)
  assert.equal(state.queue_empty, true)
  assert.ok(state.stop_playback_ms >= 0)
  assert.equal(sources[0].buffer.aborted, true)
  assert.equal(audio.src, '')
  assert.deepEqual(revoked, ['mock:1'])
  assert.equal(player.pending.size, 0)
})

test('missing chunk, invalid base64 and overflow degrade without playback hang', () => {
  for (const failure of ['gap', 'invalid', 'overflow']) {
    const { player, errors } = fixture()
    player.start('A')
    if (failure === 'gap') { player.accept('A', 1, encoded(2)); player.finish('A') }
    if (failure === 'invalid') player.accept('A', 0, '$invalid$')
    if (failure === 'overflow') for (let i = 0; i <= 128; ++i) player.accept('A', i, encoded(1))
    assert.equal(errors.length, 1)
    assert.equal(player.failed, true)
    assert.equal(player.pending.size, 0)
  }
})

test('unsupported browser degrades to text without allocating a source', () => {
  const { player, sources, errors } = fixture()
  player.supported = () => false
  player.start('A')
  assert.equal(sources.length, 0)
  assert.equal(errors.length, 1)
  assert.equal(player.accept('A', 0, encoded(1)), false)
})
