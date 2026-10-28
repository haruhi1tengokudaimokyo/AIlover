import { test } from 'node:test'
import assert from 'node:assert/strict'
import { featuredCharacters } from '../src/js/utils/featuredCharacters.js'

test('four installed game characters use the same featured card without dropping the fourth', () => {
  const characters = ['hika', 'mugi', 'ayame', 'hotaru'].map((slug, id) => ({ id, slug, assets: { portrait_url: `/media/${slug}.webp` } }))
  const before = JSON.stringify(characters)
  assert.deepEqual(featuredCharacters(characters).map(row => row.slug), ['hika', 'mugi', 'ayame', 'hotaru'])
  assert.equal(JSON.stringify(characters), before)
})

test('search uses the common results grid and game portraits precede avatar-only cards', () => {
  const characters = [{ id: 1 }, { id: 2, assets: { portrait_url: '/media/hotaru.webp' } }]
  assert.deepEqual(featuredCharacters(characters, '萤'), [])
  assert.equal(featuredCharacters(characters)[0].id, 2)
})
