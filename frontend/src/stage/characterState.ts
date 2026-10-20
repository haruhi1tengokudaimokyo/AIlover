/**
 * 角色状态机（docs/UI_REDESIGN.md §4）
 * idle | listening | thinking | speaking | interrupted | error
 *
 * 纯函数 reducer：只由真实事件驱动，不做关键词情绪猜测。
 * 事件来源：
 *  - VAD：vad-speech-start / vad-speech-end（barge-in 打断由调用方先发 stop 再发 vad-speech-start）
 *  - SSE：stream-open（已开流、尚无内容）/ stream-content / stream-audio / stream-done / error
 *  - 用户：stop / reset（从 error、interrupted 等回到 idle）
 *
 * 说明：speaking 只表示「语音实际在播」这一状态事实，不含口型同步。
 * 纯文本流（语音关闭）期间停留在 thinking。
 * stream-audio 是旧状态事件名（视为 playback-start 别名）；网络帧到达不应派发它。
 * 工作区使用 InputField 转发的实际 HTMLAudioElement playing/waiting/ended 事件。
 */

export type CharacterState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'interrupted'
  | 'error'

export type CharacterEvent =
  | 'vad-speech-start'
  | 'vad-speech-end'
  | 'stream-open'
  | 'stream-content'
  | 'stream-audio'
  | 'stream-done'
  | 'stop'
  | 'error'
  | 'reset'

/** 非法迁移视为 no-op：异步事件乱序到达时状态机不崩溃、不跳变。 */
const TRANSITIONS: Record<CharacterEvent, Partial<Record<CharacterState, CharacterState>>> = {
  'vad-speech-start': {
    idle: 'listening',
    listening: 'listening',
    thinking: 'listening',
    speaking: 'listening',
    interrupted: 'listening',
    error: 'listening',
  },
  'vad-speech-end': {
    listening: 'idle',
  },
  'stream-open': {
    idle: 'thinking',
    listening: 'thinking',
    thinking: 'thinking',
    interrupted: 'thinking',
    error: 'thinking',
  },
  'stream-content': {
    idle: 'thinking',
    listening: 'thinking',
    thinking: 'thinking',
    interrupted: 'thinking',
    error: 'thinking',
  },
  'stream-audio': {
    idle: 'speaking',
    listening: 'speaking',
    thinking: 'speaking',
    speaking: 'speaking',
    interrupted: 'speaking',
    error: 'speaking',
  },
  'stream-done': {
    thinking: 'idle',
    speaking: 'idle',
    listening: 'idle',
    idle: 'idle',
  },
  stop: {
    listening: 'interrupted',
    thinking: 'interrupted',
    speaking: 'interrupted',
  },
  error: {
    idle: 'error',
    listening: 'error',
    thinking: 'error',
    speaking: 'error',
    interrupted: 'error',
    error: 'error',
  },
  reset: {
    idle: 'idle',
    listening: 'idle',
    thinking: 'idle',
    speaking: 'idle',
    interrupted: 'idle',
    error: 'idle',
  },
}

export function reduceCharacterState(
  state: CharacterState,
  event: CharacterEvent,
): CharacterState {
  return TRANSITIONS[event][state] ?? state
}

/** 状态徽标文案（空串表示不展示徽标） */
export const STATE_LABELS: Record<CharacterState, string> = {
  idle: '',
  listening: '聆听中',
  thinking: '思考中',
  speaking: '正在说',
  interrupted: '已停止',
  error: '出错了',
}
