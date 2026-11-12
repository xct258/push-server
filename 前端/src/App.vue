<script setup>
import { onMounted, ref } from 'vue'

import AppHeader from '@/components/AppHeader.vue'
import HelpModal from '@/components/HelpModal.vue'
import ToastHost from '@/components/ToastHost.vue'
import { auth, loadAuth } from '@/auth'
import { requestRefresh, uiState } from '@/store'
import ClientsView from '@/views/ClientsView.vue'
import RecordsView from '@/views/RecordsView.vue'
import TasksView from '@/views/TasksView.vue'

const helpOpen = ref(false)

onMounted(() => loadAuth())

function changeView(v) {
  uiState.view = v
}

function loadNew() {
  uiState.hasNew = 0
  changeView('records')
  requestRefresh()
}
</script>

<template>
  <div class="relative flex h-full w-full flex-col overflow-hidden bg-ink-950 text-slate-200">
    <!-- 背景光晕 -->
    <div class="pointer-events-none absolute inset-0 -z-0">
      <div class="absolute -top-40 left-1/2 h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-indigo-600/20 blur-[130px]" />
      <div class="absolute -bottom-48 -right-24 h-[360px] w-[560px] rounded-full bg-sky-600/15 blur-[130px]" />
      <div class="absolute inset-0 bg-[radial-gradient(1100px_520px_at_50%_-220px,#0f1b3d_0%,#070b14_60%)]" />
    </div>

    <div v-if="!auth.checked || !auth.authenticated" class="relative z-10 flex flex-1 items-center justify-center">
      <div class="text-center animate-pulse">
        <div class="text-sm font-semibold tracking-[0.25em] text-slate-400">
          {{ auth.checked ? '未登录，正在跳转登录中心…' : 'CHECKING ACCESS…' }}
        </div>
        <a
          v-if="auth.checked && auth.loginUrl"
          :href="auth.loginUrl"
          class="mt-3 inline-block text-xs text-indigo-300 hover:text-indigo-200"
        >
          手动前往登录
        </a>
      </div>
    </div>

    <template v-else>
      <AppHeader
        class="relative z-30"
        :view="uiState.view"
        :connected="uiState.connected"
        :has-new="uiState.hasNew"
        @change-view="changeView"
        @load-new="loadNew"
        @toggle-help="helpOpen = !helpOpen"
      />

      <main class="relative z-10 mx-auto w-full max-w-5xl min-h-0 flex-1 px-4 py-3 sm:px-6">
        <RecordsView v-show="uiState.view === 'records'" class="h-full" />
        <TasksView v-show="uiState.view === 'tasks'" class="h-full" />
        <ClientsView v-show="uiState.view === 'clients'" class="h-full" />
      </main>

      <footer class="relative z-10 shrink-0 border-t border-white/5 py-2 text-center text-[11px] text-slate-600">
        MQTT 推送中心 · 记录按服务器保留最近 100 条 · REST 服务 :8383
      </footer>

      <HelpModal v-if="helpOpen" @close="helpOpen = false" />
    </template>

    <ToastHost />
  </div>
</template>
