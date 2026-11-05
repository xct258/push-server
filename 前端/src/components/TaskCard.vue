<script setup>
import { computed } from 'vue'
import MarkdownView from './MarkdownView.vue'
import { TASK_STATUS, countdownText, fmtSched } from '@/utils/meta'
import { useNow } from '@/composables/useNow'

const props = defineProps({
  task: { type: Object, required: true },
  /** 外部提供的当前时间戳（由视图统一驱动，避免每卡一个定时器） */
  now: { type: Number, default: 0 },
})

const internalNow = useNow(props.now <= 0)
const current = computed(() => (props.now > 0 ? props.now : internalNow.now.value))

const st = computed(() => TASK_STATUS[props.task.status] || TASK_STATUS.cancelled)
const title = computed(() => props.task.title || props.task.client_ref || `#${props.task.task_id}`)
const countdown = computed(() => countdownText(props.task, current.value))
</script>

<template>
  <article class="rounded-2xl border border-white/10 bg-white/[0.04] p-4 transition duration-200 hover:border-white/20 hover:bg-white/[0.06] animate-fade-up">
    <div class="flex flex-wrap items-center gap-2">
      <span
        class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold"
        :class="`${st.text} ${st.bg} border-white/10`"
      >
        <span class="h-1.5 w-1.5 rounded-full" :class="st.dot" />
        {{ st.label }}
      </span>
      <h3 class="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-slate-100">{{ title }}</h3>
      <span class="shrink-0 font-mono text-[11px] text-slate-500">#{{ task.task_id }}</span>
    </div>

    <div class="mt-2">
      <MarkdownView :text="task.message || ''" :clamp-height="160" />
    </div>

    <footer class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-2.5 text-[12px] text-slate-400">
      <span class="rounded-md bg-white/5 px-1.5 py-0.5 font-mono text-[11.5px] text-sky-300/80">
        {{ task.topic || '-' }}
      </span>
      <span>{{ task.client_ref || task.server_name || '-' }}</span>
      <span class="text-slate-500">
        排期 {{ fmtSched(task.schedule_at) }}
      </span>
      <span
        v-if="countdown"
        class="ml-auto font-medium"
        :class="task.status === 'pending' ? 'text-indigo-300' : 'text-slate-500'"
      >
        {{ countdown }}
      </span>
    </footer>
  </article>
</template>
