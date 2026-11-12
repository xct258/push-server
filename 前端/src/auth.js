import { reactive } from 'vue'

import { api, onUnauthorized } from '@/api'

// 全局登录状态：由统一登录中心（auth-server）签发的共享 Cookie 决定。
// 本应用不再提供登录页，未登录统一跳转到 auth-server。
export const auth = reactive({
  checked: false,
  enabled: true,
  authenticated: false,
  loginUrl: '',
})

function goLogin() {
  if (!auth.loginUrl) return false
  const next = encodeURIComponent(window.location.href)
  const sep = auth.loginUrl.includes('?') ? '&' : '?'
  window.location.replace(`${auth.loginUrl}${sep}next=${next}`)
  return true
}

onUnauthorized(() => {
  if (auth.enabled && goLogin()) return
  if (auth.enabled) auth.authenticated = false
})

export async function loadAuth() {
  try {
    const data = await api.auth.status()
    auth.enabled = !!data?.enabled
    auth.loginUrl = data?.login_url || ''
    auth.authenticated = !auth.enabled || !!data?.authenticated
  } catch {
    // 服务暂时不可用时不强行挡在登录页，保留原来的错误提示行为。
    auth.enabled = false
    auth.authenticated = true
  }

  if (auth.enabled && !auth.authenticated && auth.loginUrl) {
    goLogin()
    return
  }
  auth.checked = true
}

export async function signOut() {
  try {
    await api.auth.logout()
  } catch {
    /* 退出失败也回登录页，服务端会话到期后自然失效 */
  }
  auth.authenticated = false
  if (auth.loginUrl) goLogin()
}
