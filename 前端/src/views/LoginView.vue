<script setup>
import { onMounted, ref } from 'vue'

import { auth, signIn } from '@/auth'
import { useLoginViewport } from '@/composables/useLoginViewport'

const password = ref('')
const inputEl = ref(null)
const keyboardInset = useLoginViewport()

onMounted(() => inputEl.value?.focus())

async function submit() {
  if (!password.value || auth.loading) return
  const ok = await signIn(password.value)
  if (!ok) {
    password.value = ''
    inputEl.value?.focus()
  }
}
</script>

<template>
  <div
    class="relative z-10 flex min-h-0 flex-1 items-center justify-center px-4 py-6 overflow-hidden transition-[padding-bottom] duration-200 ease-out"
    :style="keyboardInset ? { paddingBottom: `${keyboardInset + 24}px` } : undefined"
  >
    <form
      class="w-full max-w-sm rounded-2xl border border-white/10 bg-slate-900/80 p-6 shadow-2xl shadow-indigo-950/40 animate-scale-in"
      @submit.prevent="submit"
    >
      <div class="mb-5 flex items-center gap-2.5">
        <div class="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 shadow-lg shadow-indigo-500/30">
          <svg viewBox="0 0 24 24" class="h-5 w-5 text-white" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.5 5.5l2 2M16.5 16.5l2 2M18.5 5.5l-2 2M7.5 16.5l-2 2" stroke-linecap="round" />
          </svg>
        </div>
        <div class="leading-tight">
          <h1 class="text-[15px] font-bold tracking-wide text-white">MQTT 推送中心</h1>
          <p class="text-[11px] text-slate-400">请输入访问密码后继续</p>
        </div>
      </div>

      <label class="mb-1.5 block text-[11px] text-slate-500" for="push-password">访问密码</label>
      <input
        id="push-password"
        ref="inputEl"
        v-model="password"
        type="password"
        autocomplete="current-password"
        placeholder="••••••••"
        class="w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 text-sm text-white placeholder-slate-600 transition focus:border-indigo-400 focus:outline-none"
        @input="auth.error = ''"
      />

      <p v-if="auth.error" class="mt-2 text-[11px] text-rose-300">{{ auth.error }}</p>

      <button
        type="submit"
        :disabled="auth.loading || !password"
        class="mt-4 w-full rounded-xl border border-indigo-400/30 bg-indigo-500 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition hover:bg-indigo-400 active:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {{ auth.loading ? '验证中…' : '进入推送中心' }}
      </button>
    </form>
  </div>
</template>
