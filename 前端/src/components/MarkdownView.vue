<script setup>
import { computed, ref, watch } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({
  text: { type: String, default: '' },
  /** 正文区固定高度，超过则显示「展开全文」 */
  clampHeight: { type: Number, default: 0 },
  /** 点击正文时复制原文 */
  copyable: { type: Boolean, default: false },
})

const emit = defineEmits(['copy'])

const html = computed(() => renderMarkdown(props.text))
const bodyRef = ref(null)
const expanded = ref(false)
const clamped = ref(false)

// 渲染后判断是否超出 clampHeight
watch(
  () => [props.text, props.clampHeight],
  async () => {
    expanded.value = false
    clamped.value = false
    await null // 等待 DOM 更新
    requestAnimationFrame(() => measure())
  },
  { immediate: true },
)

function measure() {
  const el = bodyRef.value
  if (!el) return
  if (props.clampHeight > 0 && el.scrollHeight > props.clampHeight) {
    clamped.value = true
  } else {
    clamped.value = false
  }
}

function toggle() {
  expanded.value = !expanded.value
  if (!expanded.value) {
    // 收起后重新测量一次（高度可能因渲染变化）
    requestAnimationFrame(() => measure())
  }
}
</script>

<template>
  <div class="relative">
    <div
      ref="bodyRef"
      class="md-view transition-[max-height] duration-300 ease-in-out overflow-hidden"
      :class="clamped && !expanded ? 'mask-fade' : ''"
      :style="clamped && !expanded ? { maxHeight: `${clampHeight}px` } : { maxHeight: 'none' }"
    >
      <div v-html="html" @click.capture="copyable && $emit('copy')" />
    </div>
    <button
      v-if="clamped"
      class="mt-2 inline-flex items-center gap-1 rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-indigo-300 transition hover:bg-white/10 hover:text-indigo-200"
      @click="toggle"
    >
      {{ expanded ? '收起 ↑' : '展开全文 ↓' }}
    </button>
  </div>
</template>

<style scoped>
.mask-fade {
  -webkit-mask-image: linear-gradient(to bottom, black 55%, transparent 100%);
  mask-image: linear-gradient(to bottom, black 55%, transparent 100%);
}
</style>
