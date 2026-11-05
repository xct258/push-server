import { reactive } from 'vue'

// 跨组件共享的 UI 状态：顶栏标签、连接状态、新消息提示、倒计时刷新信号。
export const uiState = reactive({
  view: 'records',
  connected: true,
  hasNew: 0,
  // 手动刷新信号：header 的「加载新消息」点击后 +1，RecordsView 监听后重新拉取。
  refreshTick: 0,
})

export function requestRefresh() {
  uiState.refreshTick += 1
}
