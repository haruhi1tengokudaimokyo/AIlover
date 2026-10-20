import { test } from 'node:test'
import assert from 'node:assert/strict'
import { selectRenderer } from '../src/stage/renderer.ts'

test('static rendering remains available without models, runtime, WebGL or a license', () => {
  assert.equal(selectRenderer(), 'static')
  const assets = { live2d: { model_url: '/models/example.model3.json', licensed: true } }
  assert.equal(selectRenderer(assets, false, true), 'static')
  assert.equal(selectRenderer(assets, true, false), 'static')
  assert.equal(selectRenderer({ live2d: { ...assets.live2d, licensed: false } }, true, true), 'static')
  assert.equal(selectRenderer({ live2d: { ...assets.live2d, model_url: '/invalid.png' } }, true, true), 'static')
  assert.equal(selectRenderer(assets, true, true), 'live2d')
})
