<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import FilterCombo from '@/components/FilterCombo.vue'
import Pagination from '@/components/Pagination.vue'
import RecordCard from '@/components/RecordCard.vue'
import { api } from '@/api'
import { useToast } from '@/composables/useToast'
import { uiState } from '@/store'

const PAGE = 10
const { push } = useToast()

const records = ref([])
const total = ref(0)
const page = ref(1)
const serverFilter = ref('')
const topicFilter = ref('')
const serverOptions = ref([])
const topicOptions = ref([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref(false)
const firstLoaded = ref(false)

let lastFingerprint = ''
let lastTotal = null
let es = null
let abort = null

function fingerprint(list, t) {
  let s = String(t) + '|'
  for (const r of list) {
    s +=
      r.id + ':' + r.server_name + ':' + r.topic + ':' + r.created_at + ':' +
      r.mode + ':' + (r.push_to_mqtt ? 1 : 0) + ':' + (r.status || '') + ':' + (r.title || '') + ':' + r.message + ';'
  }
  return s
}

function buildParams() {
  const p = { limit: PAGE, offset: (page.value - 1) * PAGE }
  if (serverFilter.value) p.server_name = serverFilter.value
  if (topicFilter.value) p.topic = topicFilter.value
  return p
}

async function loadData(silent = false) {
  if (abort) abort.abort()
  abort = new AbortController()
  // 已有数据时进入「刷新态」：不清空列表，避免筛选/刷新时整页闪烁
  if (firstLoaded.value) refreshing.value = true
  try {
    const data = await api.records(buildParams())
    const isPageOne = page.value === 1
    const fp = isPageOne ? fingerprint(data.records, data.total) : null

    if (isPageOne && !silent) {
      if (fp !== lastFingerprint) {
        lastFingerprint = fp
        records.value = data.records
      }
    } else {
      records.value = data.records
      if (isPageOne) lastFingerprint = fp
    }

    total.value = data.total
    lastTotal = data.total
    error.value = false
    uiState.connected = true
    uiState.hasNew = 0
    firstLoaded.value = true
  } catch (err) {
    if (err?.name === 'AbortError') return
    error.value = true
    uiState.connected = false
    if (!firstLoaded.value) loading.value = false
  } finally {
    loading.value = false
    refreshing.value = false
    abort = null
  }
}

/** 拉取全部记录构建筛选选项（分页遍历，最多 500/页）。 */
async function loadOptions() {
  try {
    const params = { limit: 500 }
    if (serverFilter.value) params.server_name = serverFilter.value
    if (topicFilter.value) params.topic = topicFilter.value
    const all = []
    let offset = 0
    for (;;) {
      const data = await api.records({ ...params, offset })
      all.push(...data.records)
      if (all.length >= data.total || data.records.length === 0) break
      offset += data.records.length
    }
    serverOptions.value = [...new Set(all.map((r) => r.server_name).filter(Boolean))].sort()
    topicOptions.value = [...new Set(all.map((r) => r.topic).filter(Boolean))].sort()
  } catch {
    /* 选项获取失败则保持现状 */
  }
}

function refresh() {
  page.value = 1
  lastFingerprint = ''
  loadData()
  loadOptions()
}

function changePage(p) {
  page.value = p
  lastFingerprint = ''
  loadData()
}

function clearFilters() {
  serverFilter.value = ''
  topicFilter.value = ''
}

function onCardFilter({ type, value }) {
  if (type === 'server') serverFilter.value = value
  else topicFilter.value = value
}

async function onRepush(record) {
  try {
    await api.repush(record.server_name, record.id)
    push('已重新推送：' + (record.title || record.topic), 'success')
    // 刷新当前页，让 push_result 更新
    loadData()
  } catch (err) {
    push('重新推送失败：' + (err?.message || '未知错误'), 'error', 4000)
  }
}

function connectSse() {
  try {
    es = new EventSource(api.eventsUrl())
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data)
        if (ev.type === 'new' && lastTotal !== null && ev.total > lastTotal) {
          uiState.hasNew = ev.total - lastTotal
        }
      } catch {
        /* 忽略坏帧 */
      }
    }
    es.onopen = () => {
      uiState.connected = true
    }
    es.onerror = () => {
      uiState.connected = false
    }
  } catch {
    uiState.connected = false
  }
}

function onVisibility() {
  if (!document.hidden && firstLoaded.value && uiState.view === 'records') loadData(true)
}

// 顶栏「加载新消息」触发
watch(
  () => uiState.refreshTick,
  () => {
    if (uiState.view === 'records') refresh()
  },
)

// 筛选变化（防抖 200ms）
let filterTimer = null
watch(
  [serverFilter, topicFilter],
  () => {
    clearTimeout(filterTimer)
    filterTimer = setTimeout(refresh, 200)
  },
)

onMounted(() => {
  refresh()
  connectSse()
  document.addEventListener('visibilitychange', onVisibility)
})

onUnmounted(() => {
  if (es) es.close()
  if (abort) abort.abort()
  document.removeEventListener('visibilitychange', onVisibility)
})

const summary = computed(() => {
  const s = { ok: 0, warn: 0, error: 0, info: 0 }
  for (const r of records.value) {
    const k = r.status || 'info'
    if (s[k] !== undefined) s[k]++
  }
  return s
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 筛选栏 -->
    <div class="shrink-0 border-b border-white/5 pb-3">
      <div class="flex flex-wrap items-end gap-3">
        <FilterCombo
          v-model="serverFilter"
          :options="serverOptions"
          label="服务器"
          placeholder="全部"
          class="min-w-[160px] flex-1 sm:flex-none sm:w-48"
        />
        <FilterCombo
          v-model="topicFilter"
          :options="topicOptions"
          label="主题"
          placeholder="全部"
          class="min-w-[160px] flex-1 sm:flex-none sm:w-56"
        />
        <button
          v-if="serverFilter || topicFilter"
          class="h-8 shrink-0 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[12px] text-slate-400 transition hover:border-rose-400/40 hover:bg-rose-400/10 hover:text-rose-300"
          @click="clearFilters"
        >
          ✕ 清除筛选
        </button>
      </div>

      <!-- 统计条 -->
      <div class="mt-2.5 flex flex-wrap items-center gap-2 text-[12px]">
        <span v-if="refreshing" class="inline-flex items-center gap-1.5 text-slate-500">
          <span class="h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-transparent" />
          刷新中
        </span>
        <template v-if="records.length">
          <span class="text-emerald-400">正常 {{ summary.ok }}</span>
          <span class="text-amber-400">警告 {{ summary.warn }}</span>
          <span class="text-rose-400">异常 {{ summary.error }}</span>
          <span class="text-sky-400">信息 {{ summary.info }}</span>
        </template>
      </div>
    </div>

    <!-- 列表区 -->
    <div class="custom-scroll min-h-0 flex-1 overflow-y-auto py-3">
      <!-- 骨架屏：仅首次加载时显示 -->
      <div v-if="loading && records.length === 0" class="space-y-3">
        <div v-for="i in 3" :key="i" class="animate-pulse rounded-2xl border border-white/5 bg-white/[0.03] p-4">
          <div class="flex gap-2">
            <div class="h-5 w-28 rounded-md bg-white/10"></div>
            <div class="h-5 w-12 rounded-full bg-white/10"></div>
          </div>
          <div class="mt-3 h-4 w-3/5 rounded bg-white/10"></div>
          <div class="mt-2 h-3 w-full rounded bg-white/5"></div>
          <div class="mt-1.5 h-3 w-4/5 rounded bg-white/5"></div>
          <div class="mt-4 h-3 w-2/5 rounded bg-white/10"></div>
        </div>
      </div>

      <!-- 错误 -->
      <div v-else-if="error && records.length === 0" class="flex flex-col items-center gap-3 py-16 text-center">
        <div class="text-4xl">🔌</div>
        <p class="text-sm text-slate-400">无法连接到服务器</p>
        <button
          class="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-[13px] text-indigo-300 transition hover:border-indigo-400/40"
          @click="refresh"
        >
          重试
        </button>
      </div>

      <!-- 空态 -->
      <div v-else-if="records.length === 0" class="flex flex-col items-center gap-2 py-16 text-center">
        <div class="text-4xl">📭</div>
        <p class="text-sm text-slate-400">{{ serverFilter || topicFilter ? '无匹配的推送记录' : '暂无推送记录' }}</p>
      </div>

      <!-- 卡片 -->
      <div v-else class="space-y-3">
        <RecordCard
          v-for="r in records"
          :key="r.id"
          :record="r"
          @filter="onCardFilter"
          @repush="onRepush"
        />
      </div>
    </div>

    <!-- 分页 -->
    <Pagination
      v-if="!loading && total > 0"
      class="shrink-0"
      :page="page"
      :total="total"
      :page-size="PAGE"
      :filters="{ server: serverFilter, topic: topicFilter }"
      @change="changePage"
    />
  </div>
</template>
