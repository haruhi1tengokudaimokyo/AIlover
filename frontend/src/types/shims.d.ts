/**
 * 既有 JS 模块的 TS 声明（tsconfig 未开 allowJs，.ts/.vue(ts) 引用 .js 需要显式类型）。
 * 只声明 Phase 2 新代码用到的部分，行为以各 .js 实现为准。
 */
declare module '@/js/http/api.js' {
  import type { AxiosInstance } from 'axios'
  const api: AxiosInstance
  export default api
}

declare module '@/js/http/streamApi.js' {
  export interface StreamApiOptions {
    method?: string
    headers?: Record<string, string>
    body?: Record<string, unknown>
    signal?: AbortSignal
    onmessage?: (data: any, isDone: boolean) => void
    onerror?: (err: unknown) => void
    onclose?: () => void
  }
  export default function streamApi(url: string, options?: StreamApiOptions): Promise<unknown>
}

declare module '@/js/utils/orderedAudio.js' {
  export interface OrderedAudioPlayerOptions {
    onError?: (message: string) => void
  }
  /** 代际绑定的有序音频播放器（实现见 orderedAudio.js，含完整单测） */
  export class OrderedAudioPlayer {
    constructor(options?: OrderedAudioPlayerOptions)
    start(generation: string): void
    accept(generation: string, sequence: number, base64: string): boolean
    finish(generation: string): void
    stop(): unknown
  }
}

declare module '@/js/utils/avatar.js' {
  export function avatarFallback(event: Event): void
}

declare module '@/stores/user.js' {
  export interface UserStore {
    id: number
    username: string
    photo: string
    profile: string
    accessToken: string
    hasPulledUserInfo: boolean
    isLogin(): boolean
    setAccessToken(token: string): void
    setUserInfo(data: { user_id: number; username: string; photo: string; profile: string }): void
    logout(): void
    setHasPulledUserInfo(status: boolean): void
  }
  export function useUserStore(): UserStore
}
