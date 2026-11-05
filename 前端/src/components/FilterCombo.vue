<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '全部' },
  label: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const open = ref(false)
const keyword = ref(props.modelValue)
const highlight = ref(-1)
const inputRef = ref(null)
const listRef = ref(null)

// 外部清空/选中时（清除筛选按钮、卡片点击筛选）同步回输入框
watch(
  () => props.modelValue,
  (v) => {
    if (keyword.value !== v) keyword.value = v
  },
)

const matched = computed(() => {
  const q = keyword.value.trim()
  const list = props.options.slice()
  if (!q) return list
  try {
    const re = new RegExp(q, 'i')
    return list.filter((v) => re.test(v))
  } catch {
    return list.filter((v) => v.toLowerCase().includes(q.toLowerCase()))
  }
})

const filtered = computed(() =>
  matched.value.map((v) => {
    const q = keyword.value.trim()
    let before = v
    let hl = ''
    let after = ''
    if (q) {
      try {
        const re = new RegExp(`(${q})`, 'i')
        const parts = v.split(re)
        const idx = parts.findIndex((p) => p && p.toLowerCase() === q.toLowerCase())
        if (idx >= 0) {
          before = parts.slice(0, idx).join('')
          hl = parts[idx]
          after = parts.slice(idx + 1).join('')
        }
      } catch {
        const i = v.toLowerCase().indexOf(q.toLowerCase())
        if (i >= 0) {
          before = v.slice(0, i)
          hl = v.slice(i, i + q.length)
          after = v.slice(i + q.length)
        }
      }
    }
    return { value: v, before, hl, after }
  }),
)

function show() {
  open.value = true
  highlight.value = -1
  requestAnimationFrame(() => {
    const el = listRef.value
    if (el) el.scrollTop = 0
  })
}

function hide() {
  open.value = false
  highlight.value = -1
}

function select(value) {
  emit('update:modelValue', value)
  keyword.value = value
  emit('change', value)
  hide()
  inputRef.value?.blur()
}

function clear() {
  select('')
}

function onInput() {
  emit('update:modelValue', keyword.value)
  emit('change', keyword.value)
  show()
}

function onKeydown(e) {
  const items = [...(listRef.value?.querySelectorAll('[data-opt]') || [])]
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    highlight.value = Math.min(highlight.value + 1, items.length - 1)
    scrollToItem()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    highlight.value = Math.max(highlight.value - 1, 0)
    scrollToItem()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (highlight.value >= 0 && items[highlight.value]) {
      select(items[highlight.value].textContent)
    } else {
      select(keyword.value)
    }
  } else if (e.key === 'Escape') {
    if (open.value) hide()
    else if (keyword.value) select('')
  }
}

function scrollToItem() {
  const el = listRef.value?.querySelector('[data-opt][data-active]')
  el?.scrollIntoView({ block: 'nearest' })
}

function onBlur() {
  // 延迟关闭，允许点击下拉项
  setTimeout(() => hide(), 150)
}

function onOutside(e) {
  if (!e.target.closest('[data-combo-root]')) hide()
}

document.addEventListener('mousedown', onOutside)
onUnmounted(() => document.removeEventListener('mousedown', onOutside))
</script>

<template>
  <div data-combo-root class="relative min-w-0">
    <div class="flex items-center gap-1.5" @mousedown.stop>
      <span v-if="label" class="shrink-0 text-xs text-slate-400 whitespace-nowrap">{{ label }}</span>
      <div class="relative min-w-0 flex-1">
        <input
          ref="inputRef"
          v-model="keyword"
          type="text"
          autocomplete="off"
          :placeholder="placeholder"
          class="h-8 w-full min-w-0 rounded-lg border border-white/10 bg-slate-900/70 px-2.5 pr-7 text-[13px] text-slate-200 placeholder:text-slate-500 outline-none transition focus:border-indigo-400/60 focus:bg-slate-900 focus:ring-2 focus:ring-indigo-400/20"
          @focus="show"
          @input="onInput"
          @keydown="onKeydown"
          @blur="onBlur"
        />
        <button
          v-if="modelValue"
          class="absolute right-1.5 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-[11px] text-slate-300 transition hover:bg-white/20"
          @mousedown.prevent="clear"
        >×</button>
      </div>
    </div>

    <div
      v-if="open"
      class="absolute left-0 top-full z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-xl border border-white/10 bg-slate-900/95 shadow-2xl shadow-black/50 backdrop-blur-xl animate-scale-in custom-scroll"
      @mousedown.stop
    >
      <button
        data-opt
        class="block w-full truncate px-3 py-1.5 text-left text-[13px] text-slate-300 transition hover:bg-white/5 hover:text-indigo-200"
        :class="!modelValue ? 'bg-white/5 text-indigo-200' : ''"
        @click="select('')"
      >
        <span v-if="!modelValue">✓ </span>全部
      </button>
      <div v-if="filtered.length === 0" class="px-3 py-2 text-center text-xs text-slate-500">无匹配</div>
      <button
        v-for="(item, i) in filtered"
        v-else
        :key="item.value"
        data-opt
        :data-active="i === highlight"
        class="block w-full truncate px-3 py-1.5 text-left text-[13px] text-slate-200 transition"
        :class="[i === highlight ? 'bg-white/10 text-indigo-200' : 'hover:bg-white/5 hover:text-indigo-200', item.value === modelValue ? 'text-indigo-200' : '']"
        @mouseenter="highlight = i"
        @click="select(item.value)"
      >
        <span v-if="item.value === modelValue">✓ </span>{{ item.before }}<strong class="text-indigo-300">{{ item.hl }}</strong>{{ item.after }}
      </button>
    </div>
  </div>
</template>
