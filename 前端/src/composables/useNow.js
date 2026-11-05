import { onUnmounted, ref } from 'vue'

// 每 1 秒跳动一次的当前时间戳，用于倒计时/时钟类展示。
// enabled=false 时只返回当前值，不启动定时器（由父级统一驱动）。
export function useNow(enabled = true) {
  const now = ref(Date.now())
  let timer = null
  if (enabled) {
    timer = setInterval(() => {
      now.value = Date.now()
    }, 1000)
  }
  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })
  return { now }
}
