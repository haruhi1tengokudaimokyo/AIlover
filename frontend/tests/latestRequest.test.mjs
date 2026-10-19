import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createLatestRequest } from '../src/js/utils/latestRequest.js'

test('latestRequest：只有最后一次请求的响应被接受', () => {
  const guard = createLatestRequest()
  const stale = guard.next()
  const fresh = guard.next()
  assert.equal(guard.isLatest(stale), false)
  assert.equal(guard.isLatest(fresh), true)
})

test('latestRequest：invalidate 让所有在途响应失效（搜索重置/组件卸载）', () => {
  const guard = createLatestRequest()
  const inflight = guard.next()
  assert.equal(guard.isLatest(inflight), true)
  guard.invalidate()
  assert.equal(guard.isLatest(inflight), false)
  // invalidate 之后发起的新请求正常工作
  const after = guard.next()
  assert.equal(guard.isLatest(after), true)
})

test('latestRequest：连续 reset 场景下旧响应不会覆盖新结果', () => {
  const guard = createLatestRequest()
  const first = guard.next()
  guard.invalidate() // 第一次 reset
  const second = guard.next()
  guard.invalidate() // 第二次 reset
  const third = guard.next()
  assert.equal(guard.isLatest(first), false)
  assert.equal(guard.isLatest(second), false)
  assert.equal(guard.isLatest(third), true)
})
