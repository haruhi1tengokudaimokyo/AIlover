// Each callback is bound to its own MediaSource and generation; never to globals.
export class OrderedAudioPlayer {
  constructor({ audio = new Audio(), createSource = () => new MediaSource(),
    supported = () => typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg'),
    createURL = source => URL.createObjectURL(source), revokeURL = url => URL.revokeObjectURL(url),
    onError = () => {}, onState = () => {}, clock = () => performance.now() } = {}) {
    Object.assign(this, { audio, createSource, supported, createURL, revokeURL, onError, onState, clock })
    this.generation = null
    this.source = null
    this.buffer = null
    this.url = null
    this.pending = new Map()
    this.queue = []
    this.expected = 0
    this.bytes = 0
    this.ended = false
    this.failed = false
  }

  start(generation) {
    this.stop()
    this.generation = generation
    this.failed = false
    this.ended = false
    this.expected = 0
    if (!this.supported()) { this.fail('当前浏览器不支持流式语音，可继续文字聊天'); return }
    const source = this.createSource()
    this.source = source
    this.url = this.createURL(source)
    this.audio.src = this.url
    const report = state => {
      if (this.generation === generation && this.source === source) this.onState(state, generation)
    }
    this.playbackHandlers = { playing: () => report('speaking'), waiting: () => report('waiting'),
      ended: () => report('idle'), error: () => {
        if (this.generation === generation && this.source === source) this.fail('语音播放失败，文字回复继续显示')
      } }
    for (const [event, callback] of Object.entries(this.playbackHandlers)) this.audio.addEventListener?.(event, callback)
    source.addEventListener('sourceopen', () => {
      if (this.generation !== generation || this.source !== source || this.failed) return
      try {
        const buffer = source.addSourceBuffer('audio/mpeg')
        this.buffer = buffer
        buffer.addEventListener('updateend', () => {
          if (this.generation === generation && this.source === source && this.buffer === buffer) this.drain()
        })
        buffer.addEventListener('error', () => {
          if (this.generation === generation && this.buffer === buffer) this.fail('语音播放失败，文字回复继续显示')
        })
        this.drain()
      } catch { this.fail('语音格式不可播放，文字回复继续显示') }
    }, { once: true })
    this.audio.play().catch(() => {
      if (this.generation === generation && this.source === source) this.fail('浏览器阻止自动播放，请检查语音权限')
    })
  }

  accept(generation, sequence, base64) {
    if (this.failed || this.generation !== generation || !Number.isSafeInteger(sequence) || sequence < 0) return false
    if (sequence < this.expected || this.pending.has(sequence)) return false
    try {
      const decoded = Uint8Array.from(atob(base64), char => char.charCodeAt(0))
      if (this.pending.size + this.queue.length >= 128 || this.bytes + decoded.byteLength > 4 * 1024 * 1024) {
        this.fail('语音播放队列已达上限，继续文字回复')
        return false
      }
      this.pending.set(sequence, decoded)
      this.bytes += decoded.byteLength
      while (this.pending.has(this.expected)) {
        this.queue.push(this.pending.get(this.expected))
        this.pending.delete(this.expected++)
      }
      this.drain()
      return true
    } catch { this.fail('语音数据损坏，继续文字回复'); return false }
  }

  finish(generation) {
    if (this.generation !== generation || this.failed) return
    if (this.pending.size) { this.fail('语音片段缺失，继续文字回复'); return }
    // Text-only/degraded responses legitimately contain no audio packets.
    if (this.expected === 0) { this.stop(); return }
    this.ended = true
    this.drain()
  }

  drain() {
    if (this.failed || !this.buffer || this.buffer.updating || this.source?.readyState !== 'open') return
    try {
      if (this.queue.length) {
        const chunk = this.queue.shift()
        this.bytes -= chunk.byteLength
        this.buffer.appendBuffer(chunk)
      } else if (this.ended) this.source.endOfStream()
    } catch { this.fail('语音缓冲不可用，继续文字回复') }
  }

  fail(message) {
    this.stop()
    this.failed = true
    this.onError(message)
  }

  stop() {
    const started = this.clock()
    if (this.playbackHandlers) {
      for (const [event, callback] of Object.entries(this.playbackHandlers)) this.audio.removeEventListener?.(event, callback)
      this.playbackHandlers = null
    }
    this.onState('idle', this.generation)
    this.generation = null // invalidate callbacks before touching browser resources
    this.audio.pause()
    this.pending.clear()
    this.queue = []
    this.bytes = 0
    const buffer = this.buffer
    this.buffer = null
    if (buffer?.updating) { try { buffer.abort() } catch { /* detached buffer */ } }
    this.source = null
    this.ended = false
    if (this.url) this.revokeURL(this.url)
    this.url = null
    this.audio.removeAttribute('src')
    this.audio.load()
    return { stop_playback_ms: this.clock() - started, queue_empty: true, paused: this.audio.paused }
  }
}
