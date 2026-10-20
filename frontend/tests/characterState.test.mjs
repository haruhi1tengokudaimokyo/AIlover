import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reduceCharacterState, STATE_LABELS } from '../src/stage/characterState.ts'

const reduce = reduceCharacterState

function play(state, ...events) {
  return events.reduce(reduce, state)
}

test('语音链路：idle → thinking → speaking → idle', () => {
  let s = 'idle'
  s = reduce(s, 'stream-open')
  assert.equal(s, 'thinking') // SSE 已开、尚无内容
  s = reduce(s, 'stream-content')
  assert.equal(s, 'thinking') // 仅有文本帧时仍是思考/输出中
  s = reduce(s, 'stream-audio')
  assert.equal(s, 'speaking') // 音频帧到达 → 正在说
  s = reduce(s, 'stream-audio')
  assert.equal(s, 'speaking')
  s = reduce(s, 'stream-done')
  assert.equal(s, 'idle')
})

test('纯文字链路（语音关闭）：全程 thinking，完成后回 idle', () => {
  const s = play('idle', 'stream-open', 'stream-content', 'stream-content', 'stream-done')
  assert.equal(s, 'idle')
  assert.equal(play('idle', 'stream-open', 'stream-content'), 'thinking')
})

test('VAD：speech start → listening，speech end → idle', () => {
  let s = reduce('idle', 'vad-speech-start')
  assert.equal(s, 'listening')
  s = reduce(s, 'vad-speech-end')
  assert.equal(s, 'idle')
})

test('barge-in：speaking 中被用户开口打断 → interrupted → listening', () => {
  let s = play('idle', 'stream-open', 'stream-audio')
  assert.equal(s, 'speaking')
  s = reduce(s, 'stop') // Microphone onSpeechStart 触发的 stop
  assert.equal(s, 'interrupted')
  s = reduce(s, 'vad-speech-start')
  assert.equal(s, 'listening')
  // 语音转文字后发出新消息 → thinking
  s = reduce(s, 'stream-open')
  assert.equal(s, 'thinking')
})

test('用户手动停止：thinking/speaking → interrupted，reset 回 idle', () => {
  assert.equal(reduce('thinking', 'stop'), 'interrupted')
  assert.equal(reduce('speaking', 'stop'), 'interrupted')
  assert.equal(reduce('listening', 'stop'), 'interrupted')
  assert.equal(reduce('interrupted', 'reset'), 'idle')
  // 新一次发送直接从 interrupted 进入 thinking
  assert.equal(reduce('interrupted', 'stream-open'), 'thinking')
})

test('error 帧：任何活动状态 → error，reset 恢复 idle', () => {
  for (const from of ['idle', 'listening', 'thinking', 'speaking', 'interrupted']) {
    assert.equal(reduce(from, 'error'), 'error')
  }
  assert.equal(reduce('error', 'reset'), 'idle')
  // 错误后重试（新 SSE 打开）直接进入 thinking
  assert.equal(reduce('error', 'stream-open'), 'thinking')
})

test('非法迁移是 no-op：异步乱序事件不会破坏状态', () => {
  assert.equal(reduce('idle', 'stop'), 'idle') // 没有进行中的回复时 stop 不产生 interrupted
  assert.equal(reduce('idle', 'vad-speech-end'), 'idle')
  assert.equal(reduce('speaking', 'vad-speech-end'), 'speaking') // 说话中漏掉的 VAD end 不打断
  assert.equal(reduce('error', 'stream-done'), 'error') // 迟到的心跳/完成帧不清除错误
})

test('新一轮发送覆盖旧状态：stream-open 可从 listening 进入 thinking', () => {
  assert.equal(reduce('listening', 'stream-open'), 'thinking')
})

test('每个状态都有徽标文案定义', () => {
  for (const state of ['idle', 'listening', 'thinking', 'speaking', 'interrupted', 'error']) {
    assert.equal(typeof STATE_LABELS[state], 'string')
  }
  assert.equal(STATE_LABELS.idle, '') // idle 不展示徽标
})
