<script setup>
import { computed, ref } from 'vue'
import MarkdownView from './MarkdownView.vue'
import { PUSH_RESULT, STATUS_META } from '@/utils/meta'
import { copyText, markdownToText } from '@/utils/markdown'

const props = defineProps({
  record: { type: Object, required: true },
})

const emit = defineEmits(['filter', 'repush'])

const status = computed(() => STATUS_META[props.record.status] || STATUS_META.info)
const pushResult = computed(() => {
  const ps = props.record.push_result || (props.record.push_to_mqtt ? 'success' : 'skipped')
  return PUSH_RESULT[ps] || PUSH_RESULT.skipped
})
const copyTitle = computed(() => {
  const ps = props.record.push_result || (props.record.push_to_mqtt ? 'success' : 'skipped')
  return ps === 'success'
    ? '推送成功，点击重新推送'
    : ps === 'failed'
      ? '推送失败，点击重试'
      : '未推送 MQTT，点击手动推送'
})

const copied = ref(false)
const busy = ref(false)

async function onCopy() {
  if (copied.value) return
  const text = `${props.record.title ? props.record.title + '\n\n' : ''}${props.record.message ?? ''}`
  const ok = await copyText(markdownToText(text))
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
}

async function onRepush() {
  if (busy.value) return
  busy.value = true
  emit('repush', props.record)
  setTimeout(() => (busy.value = false), 2200)
}
</script>

<template>
  <article
    class="relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04] transition duration-200 hover:border-white/20 hover:bg-white/[0.06] hover:shadow-lg hover:shadow-black/30 animate-fade-up"
  >
    <!-- 状态色竖条 -->
    <span class="absolute inset-y-0 left-0 w-1 bg-gradient-to-b" :class="`${status.bar} to-transparent`" />

    <div class="flex flex-wrap items-center gap-2 px-4 pt-3.5">
      <button
        class="max-w-[220px] truncate rounded-md bg-indigo-400/10 px-2 py-0.5 font-mono text-[12px] text-indigo-300 transition hover:bg-indigo-400/20"
        title="点击筛选该主题"
        @click="emit('filter', { type: 'topic', value: record.topic })"
      >
        {{ record.topic }}
      </button>
      <span class="rounded-full border px-2 py-0.5 text-[11px] font-semibold" :class="status.class">
        {{ status.label }}
      </span>
      <span
        v-if="record.mode"
        class="rounded-full px-2 py-0.5 text-[11px]"
        :class="record.mode === 'overwrite' ? 'bg-amber-400/10 text-amber-300' : 'bg-white/5 text-slate-400'"
      >
        {{ record.mode === 'overwrite' ? '覆盖' : '持续' }}
      </span>
    </div>

    <h3 v-if="record.title" class="selectable mt-2.5 px-4 text-[14px] font-semibold text-slate-100 leading-snug">
      {{ record.title }}
    </h3>

    <div class="mt-2 px-4">
      <div class="relative">
        <MarkdownView :text="record.message" :clamp-height="240" />
        <button
          class="absolute right-0 top-0 rounded-lg border border-white/10 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-400 backdrop-blur transition hover:border-white/25 hover:text-slate-100"
          :class="copied ? '!border-emerald-400/60 !text-emerald-300' : ''"
          title="复制消息原文"
          @click="onCopy"
        >
          {{ copied ? '✓ 已复制' : '复制' }}
        </button>
      </div>
    </div>

    <footer class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-white/5 px-4 py-2.5 text-[12px] text-slate-400">
      <button
        class="selectable text-slate-200 transition hover:text-indigo-300"
        title="点击筛选该服务器"
        @click="emit('filter', { type: 'server', value: record.server_name })"
      >
        {{ record.server_name || '-' }}
      </button>
      <span class="text-slate-500">{{ record.created_at }}</span>
      <button
        class="ml-auto inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] transition"
        :class="[pushResult.bg, pushResult.text, busy ? 'opacity-50' : 'hover:brightness-125']"
        :title="copyTitle"
        :disabled="busy"
        @click="onRepush"
      >
        <span v-if="busy" class="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
        {{ busy ? '推送中...' : pushResult.label }}
      </button>
    </footer>
  </article>
</template>
