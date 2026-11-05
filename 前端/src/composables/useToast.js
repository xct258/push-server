import { reactive } from 'vue'

// 轻量 Toast：单例状态 + 挂载组件 <ToastHost/>。
const state = reactive({ items: [] })
let seq = 0

export function useToast() {
  function push(message, type = 'info', duration = 2600) {
    const id = ++seq
    state.items.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => dismiss(id), duration)
    }
  }
  function dismiss(id) {
    const i = state.items.findIndex((t) => t.id === id)
    if (i >= 0) state.items.splice(i, 1)
  }
  return { toastState: state, push, dismiss }
}
