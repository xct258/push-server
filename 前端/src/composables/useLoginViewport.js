import { onMounted, onUnmounted, ref } from 'vue'

/**
 * 登录页的键盘 / 滚动适配。
 *
 * - 返回 keyboardInset：键盘遮挡的高度，登录卡片据此增加底部留白，从而整体上移；
 *   Android（interactive-widget=resizes-content）由布局视口自行收缩，这里会得到 0，不会重复上移。
 * - 挂载期间锁定页面滚动，卸载时恢复，避免 iOS 聚焦输入框时页面被拖动。
 */
export function useLoginViewport() {
  const keyboardInset = ref(0)
  let viewport = null
  let saved = null

  function measure() {
    if (!viewport) {
      keyboardInset.value = 0
      return
    }
    const overlap = window.innerHeight - (viewport.height + viewport.offsetTop)
    // 小于 100px 视为地址栏 / 工具栏变化，避免登录卡片来回抖动
    keyboardInset.value = overlap > 100 ? Math.round(overlap) : 0
  }

  onMounted(() => {
    const html = document.documentElement
    const body = document.body
    saved = {
      htmlOverflow: html.style.overflow,
      bodyOverflow: body.style.overflow,
      bodyOverscroll: body.style.overscrollBehavior,
    }
    html.style.overflow = 'hidden'
    body.style.overflow = 'hidden'
    body.style.overscrollBehavior = 'none'

    viewport = window.visualViewport
    if (viewport) {
      viewport.addEventListener('resize', measure)
      viewport.addEventListener('scroll', measure)
    }
    window.addEventListener('resize', measure)
    measure()
  })

  onUnmounted(() => {
    if (viewport) {
      viewport.removeEventListener('resize', measure)
      viewport.removeEventListener('scroll', measure)
    }
    window.removeEventListener('resize', measure)
    if (saved) {
      document.documentElement.style.overflow = saved.htmlOverflow
      document.body.style.overflow = saved.bodyOverflow
      document.body.style.overscrollBehavior = saved.bodyOverscroll
    }
  })

  return keyboardInset
}
