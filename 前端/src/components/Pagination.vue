<script setup>
import { computed } from 'vue'

const props = defineProps({
  page: { type: Number, required: true },
  total: { type: Number, required: true },
  pageSize: { type: Number, default: 10 },
  /** 筛选条件（仅用于展示 chips） */
  filters: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['change'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const chips = computed(() =>
  Object.entries(props.filters)
    .filter(([, v]) => v)
    .map(([k, v]) => ({ key: k, value: v })),
)
</script>

<template>
  <div v-if="total > 0" class="flex flex-wrap items-center justify-center gap-4 py-4">
    <button
      class="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-[13px] text-indigo-300 transition hover:border-indigo-400/40 hover:bg-indigo-400/10 disabled:pointer-events-none disabled:opacity-30"
      :disabled="page <= 1"
      @click="emit('change', page - 1)"
    >
      ‹ 上一页
    </button>
    <div class="flex flex-wrap items-center justify-center gap-2 text-[12px] text-slate-400">
      <span
        v-for="c in chips"
        :key="c.key"
        class="rounded-full border border-indigo-400/25 bg-indigo-400/10 px-2 py-0.5 text-[11px] text-indigo-300"
      >
        {{ c.key === 'server' ? '服务器' : '主题' }}: {{ c.value }}
      </span>
      <span class="whitespace-nowrap">第 {{ page }} / {{ totalPages }} 页</span>
    </div>
    <button
      class="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-[13px] text-indigo-300 transition hover:border-indigo-400/40 hover:bg-indigo-400/10 disabled:pointer-events-none disabled:opacity-30"
      :disabled="page >= totalPages"
      @click="emit('change', page + 1)"
    >
      下一页 ›
    </button>
  </div>
</template>
