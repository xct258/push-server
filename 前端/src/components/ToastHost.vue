<script setup>
import { useToast } from '@/composables/useToast'

const { toastState, dismiss } = useToast()

const TYPE_STYLE = {
  success: 'border-emerald-400/40 text-emerald-200',
  error: 'border-rose-400/40 text-rose-200',
  warn: 'border-amber-400/40 text-amber-200',
  info: 'border-sky-400/40 text-sky-100',
}
const TYPE_ICON = { success: '✓', error: '✕', warn: '!', info: 'i' }
</script>

<template>
  <div class="fixed bottom-4 left-1/2 z-[200] flex w-full max-w-sm -translate-x-1/2 flex-col items-center gap-2 px-4 pointer-events-none">
    <div
      v-for="t in toastState.items"
      :key="t.id"
      class="glass pointer-events-auto flex w-full items-center gap-2.5 rounded-xl border px-3.5 py-2.5 shadow-lg shadow-black/30 animate-scale-in"
      :class="TYPE_STYLE[t.type] || TYPE_STYLE.info"
    >
      <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-bold">
        {{ TYPE_ICON[t.type] || 'i' }}
      </span>
      <span class="min-w-0 flex-1 text-[13px] leading-snug break-words">{{ t.message }}</span>
      <button
        class="shrink-0 rounded px-1 text-sm opacity-60 transition hover:opacity-100"
        @click="dismiss(t.id)"
      >×</button>
    </div>
  </div>
</template>
