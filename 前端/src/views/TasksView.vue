<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'

import TaskCard from '@/components/TaskCard.vue'
import { api } from '@/api'
import { useNow } from '@/composables/useNow'
import { uiState } from '@/store'

const FILTERS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待推送' },
  { value: 'sent', label: '已发送' },
  { value: 'done', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]

const tasks = ref([])
const status = ref('')
const loading = ref(true)
const firstLoaded = ref(false)
const { now } = useNow()

let pollTimer = null
let lastFingerprint = ''

async function loadTasks(silent = false) {
  try {
    const params = { limit: 200 }
    if (status.value) params.status = status.value
    const data = await api.tasks(params)

    const fp = data.tasks
      .map((t) => `${t.task_id}:${t.status}:${t.schedule_at}:${t.updated_at}`)
      .join(';')
    if (silent && fp === lastFingerprint) return

    lastFingerprint = fp
    tasks.value = data.tasks
    uiState.connected = true
    firstLoaded.value = true
  } catch {
    uiState.connected = false
    if (!firstLoaded.value) loading.value = false
  } finally {
    loading.value = false
  }
}

function switchStatus(v) {
  if (status.value === v) return
  status.value = v
  lastFingerprint = ''
  loading.value = true
  loadTasks()
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(() => {
    if (uiState.view === 'tasks' && !document.hidden) loadTasks(true)
  }, 10000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function onVisibility() {
  if (!document.hidden && uiState.view === 'tasks' && firstLoaded.value) loadTasks(true)
}

watch(
  () => uiState.view,
  (v) => {
    if (v === 'tasks') {
      if (!firstLoaded.value) loadTasks()
      startPoll()
    } else {
      stopPoll()
    }
  },
)

onMounted(() => {
  loadTasks()
  startPoll()
  document.addEventListener('visibilitychange', onVisibility)
})

onUnmounted(() => {
  stopPoll()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 状态筛选 -->
    <div class="shrink-0 border-b border-white/5 pb-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="f in FILTERS"
          :key="f.value"
          class="rounded-full border px-3 py-1 text-[12px] transition"
          :class="status === f.value ? 'border-indigo-400/50 bg-indigo-400/15 text-indigo-200' : 'border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/25'"
          @click="switchStatus(f.value)"
        >
          {{ f.label }}
        </button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="custom-scroll min-h-0 flex-1 overflow-y-auto py-3">
      <div v-if="loading && !firstLoaded" class="space-y-3">
        <div v-for="i in 4" :key="i" class="animate-pulse rounded-2xl border border-white/5 bg-white/[0.03] p-4">
          <div class="flex gap-2">
            <div class="h-5 w-16 rounded-full bg-white/10"></div>
            <div class="h-5 flex-1 rounded bg-white/10"></div>
          </div>
          <div class="mt-3 h-3 w-full rounded bg-white/5"></div>
          <div class="mt-2 h-3 w-3/4 rounded bg-white/5"></div>
        </div>
      </div>

      <div v-else-if="tasks.length === 0" class="flex flex-col items-center gap-2 py-16 text-center">
        <div class="text-4xl">📭</div>
        <p class="text-sm text-slate-400">{{ status ? '无此状态的定时任务' : '暂无定时任务' }}</p>
      </div>

      <div v-else class="space-y-3">
        <TaskCard v-for="t in tasks" :key="t.task_id" :task="t" :now="now" />
      </div>
    </div>
  </div>
</template>
