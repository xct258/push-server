<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { api } from '@/api'
import { useToast } from '@/composables/useToast'
import { useNow } from '@/composables/useNow'
import { uiState } from '@/store'

const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'online', label: '在线' },
  { value: 'offline', label: '离线' },
]

const PLATFORM_META = {
  android: { label: 'Android', icon: '🤖', class: 'bg-emerald-400/10 text-emerald-300' },
  windows: { label: 'Windows', icon: '🪟', class: 'bg-sky-400/10 text-sky-300' },
  linux: { label: 'Linux', icon: '🐧', class: 'bg-amber-400/10 text-amber-300' },
}

const clients = ref([])
const total = ref(0)
const online = ref(0)
const filter = ref('all')
const loading = ref(true)
const firstLoaded = ref(false)
const deleting = ref('')
const { now } = useNow()
const { push } = useToast()

let pollTimer = null
let lastFingerprint = ''

const visible = computed(() => {
  if (filter.value === 'online') return clients.value.filter((c) => c.online)
  if (filter.value === 'offline') return clients.value.filter((c) => !c.online)
  return clients.value
})

async function loadClients(silent = false) {
  try {
    const data = await api.clients()
    const fp = `${data.online}|${data.clients
      .map((c) => `${c.suffix}:${c.client_id}:${c.online}:${c.last_seen}:${c.status_changed}:${c.version}:${c.platform}:${c.topic}`)
      .join(';')}`
    if (silent && fp === lastFingerprint) return

    lastFingerprint = fp
    clients.value = data.clients || []
    total.value = clients.value.length
    online.value = data.online || 0
    uiState.connected = true
    firstLoaded.value = true
  } catch {
    uiState.connected = false
    if (!firstLoaded.value) loading.value = false
  } finally {
    loading.value = false
  }
}

function platformMeta(platform) {
  return PLATFORM_META[(platform || '').toLowerCase()] || {
    label: platform || '未知',
    icon: '📡',
    class: 'bg-white/5 text-slate-400',
  }
}

function ago(epoch) {
  if (!epoch) return '未知'
  const seconds = Math.max(0, Math.floor(now.value / 1000 - epoch))
  if (seconds < 10) return '刚刚'
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

async function onDelete(client) {
  const label = client.name || client.client_id
  if (!window.confirm(`删除离线客户端「${label}」？\n\n只清理当前记录，设备下次连接后会自动恢复。`)) return

  deleting.value = client.suffix
  try {
    await api.deleteClient(client.suffix)
    clients.value = clients.value.filter((c) => c.suffix !== client.suffix)
    total.value = clients.value.length
    push(`已删除离线客户端：${label}`, 'success')
  } catch (err) {
    push('删除失败：' + (err?.message || '未知错误'), 'error', 4000)
  } finally {
    deleting.value = ''
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(() => {
    if (uiState.view === 'clients' && !document.hidden) loadClients(true)
  }, 10000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function onVisibility() {
  if (!document.hidden && uiState.view === 'clients' && firstLoaded.value) loadClients(true)
}

watch(
  () => uiState.view,
  (v) => {
    if (v === 'clients') {
      if (!firstLoaded.value) loadClients()
      startPoll()
    } else {
      stopPoll()
    }
  },
)

onMounted(() => {
  loadClients()
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
    <div class="shrink-0 border-b border-white/5 pb-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="f in FILTERS"
          :key="f.value"
          class="rounded-full border px-3 py-1 text-[12px] transition"
          :class="filter === f.value ? 'border-indigo-400/50 bg-indigo-400/15 text-indigo-200' : 'border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/25'"
          @click="filter = f.value"
        >
          {{ f.label }}
          <span v-if="f.value === 'online'" class="ml-1 font-mono text-[11px] text-emerald-300/80">{{ online }}</span>
        </button>
      </div>

      <div class="mt-2.5 flex flex-wrap items-center gap-2 text-[12px] text-slate-500">
        <span>
          在线 <b class="font-mono text-emerald-300">{{ online }}</b>
          / 共 <b class="font-mono text-slate-300">{{ total }}</b> 个客户端
        </span>
        <span class="text-slate-600">·</span>
        <span>客户端每 60 秒上报一次，180 秒无心跳视为离线</span>
      </div>
    </div>

    <div class="custom-scroll min-h-0 flex-1 overflow-y-auto py-3">
      <div v-if="loading && !firstLoaded" class="space-y-3">
        <div v-for="i in 3" :key="i" class="animate-pulse rounded-2xl border border-white/5 bg-white/[0.03] p-4">
          <div class="h-5 w-40 rounded bg-white/10"></div>
          <div class="mt-3 h-3 w-3/4 rounded bg-white/5"></div>
        </div>
      </div>

      <div v-else-if="visible.length === 0" class="flex flex-col items-center gap-2 py-16 text-center">
        <div class="text-4xl">📡</div>
        <p class="text-sm text-slate-400">
          {{ filter === 'all' ? '暂无客户端上报在线状态' : `暂无${filter === 'online' ? '在线' : '离线'}客户端` }}
        </p>
        <p class="text-[12px] text-slate-600">客户端连接后会自动上报，升级到最新版客户端即可看到</p>
      </div>

      <div v-else class="space-y-3">
        <article
          v-for="c in visible"
          :key="c.client_id"
          class="rounded-2xl border border-white/10 bg-white/[0.04] p-4 transition duration-200 hover:border-white/20 hover:bg-white/[0.06]"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5 text-[11px] font-semibold"
              :class="c.online ? 'bg-emerald-400/10 text-emerald-300' : 'bg-white/5 text-slate-500'"
            >
              <span class="h-1.5 w-1.5 rounded-full" :class="c.online ? 'bg-emerald-400 animate-pulse-ring' : 'bg-slate-600'" />
              {{ c.online ? '在线' : '离线' }}
            </span>

            <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]" :class="platformMeta(c.platform).class">
              {{ platformMeta(c.platform).icon }} {{ platformMeta(c.platform).label }}
            </span>

            <h3 class="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-slate-100">
              {{ c.name || c.client_id }}
            </h3>
            <span class="shrink-0 text-[12px] text-slate-500" :title="`状态变化：${c.status_changed}`">状态变化 {{ ago(c.status_changed_epoch) }}</span>
          </div>

          <footer class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-2.5 text-[12px] text-slate-400">
            <span class="selectable rounded-md bg-white/5 px-1.5 py-0.5 font-mono text-[11.5px] text-sky-300/80">
              {{ c.client_id }}
            </span>
            <span class="rounded-md bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-slate-500" title="设备唯一后缀">
              #{{ c.suffix }}
            </span>
            <span v-if="c.topic"
                  class="rounded-md bg-indigo-400/10 px-1.5 py-0.5 font-mono text-[11px] text-indigo-300"
                  title="客户端订阅主题">
              {{ c.topic }}
            </span>
            <span v-if="c.version" class="text-slate-500">v{{ c.version }}</span>
            <span class="ml-auto text-slate-500">最后心跳 {{ c.last_seen }}</span>
            <button
              v-if="!c.online"
              class="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-slate-400 transition hover:border-rose-400/40 hover:bg-rose-400/10 hover:text-rose-300 disabled:opacity-50"
              :disabled="deleting === c.suffix"
              @click="onDelete(c)"
            >
              {{ deleting === c.suffix ? '删除中…' : '删除记录' }}
            </button>
          </footer>
        </article>
      </div>
    </div>
  </div>
</template>
