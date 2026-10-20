<script setup lang="js">
import KeyboardIcon from "@/components/character/icons/KeyboardIcon.vue";
import {onBeforeUnmount, onMounted, ref} from "vue";
import {MicVAD} from "@ricky0123/vad-web";
import api from "@/js/http/api.js";

const emit = defineEmits(['close', 'send', 'stop', 'error', 'state'])
const isSpeaking = ref(false)
let vadInstance = null;
let disposed = false;
let recordingVersion = 0;
let asrController = null;

const startRecording = async () => {
  const baseUrl = import.meta.env.DEV ? '/vad/' : '/static/frontend/vad/';
  try {
    const instance = await MicVAD.new({
      baseAssetPath: baseUrl,
      onSpeechStart: () => {
        if (disposed) return;
        ++recordingVersion;
        asrController?.abort();
        isSpeaking.value = true;
        emit('stop')
        emit('state', 'listening')
      },
      onSpeechEnd: (audio) => {
        if (disposed) return;
        isSpeaking.value = false;
        emit('state', 'thinking');
        const pcm16 = float32ToInt16(audio);
        sendToBackend(pcm16, recordingVersion);
      },
      ortConfig: (ort) => {
        ort.env.wasm.wasmPaths = baseUrl;
        ort.env.logLevel = "error";
      },
      positiveSpeechThreshold: 0.8,
      negativeSpeechThreshold: 0.65,
      minSpeechFrames: 5,
      redemptionFrames: 5,
    });

    if (disposed) { await instance.destroy(); return; }
    vadInstance = instance;
    await instance.start();
  } catch (e) {
    if (disposed) return;
    console.error("VAD 初始化失败:", e);
    emit('error', '麦克风初始化失败，请检查麦克风权限和语音资源，或改用文字输入');
  }
};
// 将 Float32 转 PCM 16-bit
const float32ToInt16 = (float32Array) => {
  const buffer = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    buffer[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return buffer.buffer;
};

const sendToBackend = async (arrayBuffer, version) => {
  asrController?.abort();
  const controller = new AbortController();
  asrController = controller;
  const blob = new Blob([arrayBuffer], { type: "audio/pcm" });
  const formData = new FormData();
  formData.append("audio", blob,'voice.pcm');

  try{
    const res = await api.post('/api/friend/message/asr/asr/', formData, { signal: controller.signal })
    if (disposed || version !== recordingVersion || controller !== asrController) return;
    const data = res.data
    if (data.result === 'success' && data.text?.trim()) {
      emit('send', null, data.text)
    } else {
      emit('state', 'idle')
      emit('error', data.result === 'success' ? '没有听清楚，再说一次吧' : data.result || '语音识别失败')
    }
  } catch (err) {
    if (disposed || controller.signal.aborted || version !== recordingVersion) return;
    emit('error', err.response?.data?.result || '语音识别失败，请改用文字输入')
  }
};

onMounted(() => {
  startRecording()
})

onBeforeUnmount(() => {
  disposed = true;
  ++recordingVersion;
  asrController?.abort();
  if (vadInstance) {
    Promise.resolve(vadInstance.destroy()).catch(() => {})
    vadInstance = null
  }
})
</script>

<template>
  <div class="relative h-12 flex items-center bg-base-300 rounded-xl">
    <div v-if="isSpeaking" class="flex items-center justify-center gap-1 h-6 flex-1">
      <div
        v-for="i in 32" :key="i"
        class="w-0.5 bg-blue-400 rounded-full animate-wave"
        :style="{ animationDelay: `${i * 0.1}s` }"
      ></div>
    </div>
    <div v-else class="text-white/50 text-base w-full text-center">
      语音输入
    </div>
    <button type="button" aria-label="切换文字输入" @click="emit('close'); emit('state', 'idle')" class="absolute right-2 w-8 h-8 flex justify-center items-center cursor-pointer">
      <KeyboardIcon />
    </button>
  </div>

</template>

<style scoped>
.animate-wave {
  height: 4px;
  animation: wave-animation 0.6s ease-in-out infinite alternate;
}

@keyframes wave-animation {
  0% { height: 4px; opacity: 0.3; }
  100% { height: 20px; opacity: 1; }
}
</style>
