<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { selectRenderer, type StageCharacter } from './renderer'
import type { CharacterState } from './characterState'
import { STATE_LABELS } from './characterState'
import fallback from '@/assets/default-avatar.svg'
const props = defineProps<{ character: StageCharacter; state: CharacterState; immersive?: boolean }>()
const portraitFailed = ref(false)
const photoFailed = ref(false)
const backgroundFailed = ref(false)
watch(() => props.character.id, () => { portraitFailed.value = photoFailed.value = backgroundFailed.value = false })
const portrait = computed(() => !portraitFailed.value && props.character.assets?.portrait_url)
</script>

<template>
  <section class="character-stage" :class="{ 'stage-immersive': immersive }" :data-state="state" :data-renderer="selectRenderer(character.assets)" :aria-label="`${character.name}的角色舞台`">
    <img v-if="character.background_image && !backgroundFailed" class="stage-scenery" :src="character.background_image" alt="" @error="backgroundFailed = true" />
    <div class="stage-shade"></div>
    <div class="stage-caption"><span class="stage-eyebrow">A MOMENT WITH YOU</span><h1>{{ character.name }}</h1><p>{{ character.description || character.profile }}</p></div>
    <Transition name="portrait" appear>
      <img v-if="portrait" :key="portrait" class="stage-portrait" :src="portrait" :alt="character.name" @error="portraitFailed = true" />
      <div v-else class="stage-photo-frame"><img :src="photoFailed ? fallback : character.photo || fallback" :alt="character.name" @error="photoFailed = true" /><span>{{ character.name }}</span></div>
    </Transition>
    <div class="stage-status" role="status"><i :class="{ active: state === 'speaking' }"></i>{{ STATE_LABELS[state] || '在这里，陪着你' }}</div>
    <span class="stage-edition">AIlover / Companion Studio</span>
    <slot></slot>
  </section>
</template>

<style scoped>
.character-stage{position:relative;isolation:isolate;min-width:0;min-height:0;overflow:hidden;background:radial-gradient(ellipse at 70% 20%,#73608b60,transparent 65%),linear-gradient(135deg,#30273f,#171323);color:#fff}
.stage-scenery,.stage-shade{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:-2}.stage-scenery{opacity:.65}.stage-shade{z-index:-1;background:linear-gradient(90deg,rgba(22,16,34,.72),transparent 80%),linear-gradient(0deg,#181321e8,transparent 55%)}
.stage-caption{position:absolute;left:7%;top:10%;max-width:55%;z-index:2;text-shadow:0 2px 20px #0008}.stage-eyebrow{font-size:10px;letter-spacing:.25em;color:#efc8dc}.stage-caption h1{font-family:var(--font-display);font-size:clamp(28px,4vw,58px);margin:18px 0}.stage-caption p{font-size:13px;line-height:1.9;opacity:.7;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.stage-portrait{position:absolute;inset:4% 0 0 auto;height:100%;width:88%;object-fit:contain;object-position:bottom right;filter:drop-shadow(0 12px 28px #0005)}
.stage-photo-frame{position:absolute;right:9%;top:24%;width:min(58%,420px);aspect-ratio:4/5;padding:10px;background:#ffffff12;border:1px solid #ffffff30;transform:rotate(3deg);box-shadow:0 24px 70px #0005}.stage-photo-frame img{width:100%;height:90%;object-fit:cover;object-position:top}.stage-photo-frame span{display:block;text-align:center;padding-top:10px;font-family:var(--font-display)}
.stage-status{position:absolute;left:7%;bottom:7%;display:flex;align-items:center;gap:9px;font-size:12px;letter-spacing:.08em}.stage-status i{height:6px;width:6px;background:#e7bbcc;border-radius:50%}.stage-status i.active{animation:voice 700ms ease-in-out infinite alternate}.stage-edition{position:absolute;right:24px;bottom:25px;font-size:9px;letter-spacing:.12em;opacity:.5}
.portrait-enter-active{transition:opacity 600ms,transform 600ms}.portrait-enter-from{opacity:0;transform:translateX(16px)}@keyframes voice{to{box-shadow:0 0 0 6px #e7bbcc25}}
@media(max-width:767px){.stage-caption{top:10%;left:6%;max-width:48%}.stage-caption h1{margin:8px 0;font-size:27px}.stage-caption p{font-size:11px;-webkit-line-clamp:2}.stage-eyebrow{font-size:8px}.stage-portrait{width:75%;height:185%;top:0;object-position:top right}.stage-immersive .stage-portrait{width:80%;height:100%}.stage-status{bottom:9%;left:6%;font-size:10px}.stage-edition{display:none}.stage-photo-frame{top:10%;height:85%;width:auto;aspect-ratio:4/5}.stage-photo-frame span{font-size:10px;padding-top:2px}}
</style>
