import type { CharacterState } from './characterState'

export interface CharacterAssets {
  portrait_url?: string | null
  live2d?: { model_url: string; licensed: boolean } | null
}
export interface StageCharacter {
  id: number
  name: string
  profile: string
  description?: string
  photo: string
  background_image: string
  greeting?: string
  quick_replies?: string[]
  assets?: CharacterAssets
}
/** Runtime integrations must implement this lifecycle; static mode never needs WebGL. */
export interface CharacterRendererAdapter {
  mount(container: HTMLElement, assets: CharacterAssets): Promise<void>
  setState(state: CharacterState): void
  dispose(): void
}
export function selectRenderer(assets?: CharacterAssets, runtimeAvailable = false, webglAvailable = false): 'static' | 'live2d' {
  return assets?.live2d?.licensed && assets.live2d.model_url.endsWith('.model3.json') && runtimeAvailable && webglAvailable ? 'live2d' : 'static'
}
