import { reactive } from 'vue'

import { api, onUnauthorized } from '@/api'

// 全局登录状态：App.vue 根据它决定显示登录页还是推送管理界面。
export const auth = reactive({
  checked: false,
  enabled: true,
  authenticated: false,
  loading: false,
  error: '',
})

onUnauthorized(() => {
  if (auth.enabled) auth.authenticated = false
})

export async function loadAuth() {
  try {
    const data = await api.auth.status()
    auth.enabled = !!data?.enabled
    auth.authenticated = !auth.enabled || !!data?.authenticated
  } catch {
    // 服务暂时不可用时不强行挡在登录页，保留原来的错误提示行为。
    auth.enabled = false
    auth.authenticated = true
  } finally {
    auth.checked = true
  }
}

export async function signIn(password) {
  if (auth.loading) return false
  auth.loading = true
  auth.error = ''
  try {
    await api.auth.login(password)
    auth.enabled = true
    auth.authenticated = true
    return true
  } catch (err) {
    auth.error = err?.message || '登录失败'
    return false
  } finally {
    auth.loading = false
  }
}

export async function signOut() {
  try {
    await api.auth.logout()
  } catch {
    /* 退出失败也回登录页，服务端会话到期后自然失效 */
  }
  auth.authenticated = false
  auth.error = ''
}
