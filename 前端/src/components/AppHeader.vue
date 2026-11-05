<script setup>
defineProps({
  view: { type: String, required: true },
  connected: { type: Boolean, default: true },
  hasNew: { type: Number, default: 0 },
})

const emit = defineEmits(['change-view', 'load-new', 'toggle-help'])
</script>

<template>
  <header class="glass sticky top-0 z-40 border-b border-white/10">
    <div class="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:px-6">
      <!-- 品牌 -->
      <div class="flex items-center gap-2.5">
        <div class="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 shadow-lg shadow-indigo-500/30">
          <svg viewBox="0 0 24 24" class="h-5 w-5 text-white" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.5 5.5l2 2M16.5 16.5l2 2M18.5 5.5l-2 2M7.5 16.5l-2 2" stroke-linecap="round" />
          </svg>
          <span class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-950" :class="connected ? 'bg-emerald-400 animate-pulse-ring' : 'bg-rose-500'" />
        </div>
        <div class="leading-tight">
          <h1 class="text-[15px] font-bold tracking-wide text-white">MQTT 推送中心</h1>
          <p class="text-[11px] text-slate-400">{{ view === 'records' ? '推送记录 · 历史消息一览' : '定时任务 · 单向待办推送' }}</p>
        </div>
      </div>

      <!-- 标签切换 -->
      <nav class="order-3 flex w-full gap-1 rounded-xl border border-white/10 bg-slate-900/60 p-1 sm:order-none sm:ml-auto sm:w-auto">
        <button
          class="flex-1 sm:flex-none rounded-lg px-3 py-1.5 text-[13px] transition"
          :class="view === 'records' ? 'bg-indigo-500/20 text-indigo-200 shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          @click="emit('change-view', 'records')"
        >
          推送记录
        </button>
        <button
          class="flex-1 sm:flex-none rounded-lg px-3 py-1.5 text-[13px] transition"
          :class="view === 'tasks' ? 'bg-indigo-500/20 text-indigo-200 shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          @click="emit('change-view', 'tasks')"
        >
          定时任务
        </button>
      </nav>

      <!-- 状态 + 新消息 + 帮助 -->
      <div class="order-2 ml-auto flex items-center gap-2.5 sm:order-none sm:ml-0">
        <div class="flex items-center gap-1.5 text-[12px]" :class="connected ? 'text-emerald-300' : 'text-rose-400'">
          <span class="h-2 w-2 rounded-full" :class="connected ? 'bg-emerald-400 animate-pulse-ring' : 'bg-rose-500'" />
          {{ connected ? '已连接' : '连接失败' }}
        </div>
        <button
          class="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-[13px] font-semibold text-slate-400 transition hover:border-indigo-400/40 hover:bg-indigo-400/10 hover:text-indigo-200"
          title="使用说明"
          @click="emit('toggle-help')"
        >
          ?
        </button>
        <button
          v-if="hasNew > 0"
          class="animate-fade-in rounded-full bg-emerald-400/90 px-3 py-1 text-[12px] font-semibold text-emerald-950 shadow-lg shadow-emerald-500/30 transition hover:bg-emerald-300"
          @click="emit('load-new')"
        >
          ⚡ {{ hasNew }} 条新消息
        </button>
      </div>
    </div>
  </header>
</template>
