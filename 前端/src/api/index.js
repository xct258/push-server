// 统一 API 客户端。
// push-server 接口分两段：历史记录走 /records（无前缀），其余走 /api 前缀。
// 开发：vite.config.js 里把 /api、/records 反代到本机 push-server（8383）。
// 生产：与后端同源，直接命中；如部署在不同源可用 VITE_API_BASE 指定 /api 前缀。

const API_PREFIX = import.meta.env.VITE_API_BASE || '/api'
const RECORDS_PATH = import.meta.env.VITE_RECORDS_BASE || '/records'

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

// 会话失效统一回调：auth.js 注册后，任何接口 401 都会切回登录页。
let unauthorizedHandler = null
export function onUnauthorized(fn) {
  unauthorizedHandler = fn
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const options = { method, headers: {}, signal }
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(path, options)
  } catch (err) {
    throw new ApiError('无法连接服务器，请确认 push-server 已启动', 0, err)
  }

  if (!res.ok) {
    if (res.status === 401) unauthorizedHandler?.()
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      detail = data?.detail || detail
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status)
  }

  if (res.status === 204) return null
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

function qs(params) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  )
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const api = {
  /** 登录状态 / 登录 / 退出。 */
  auth: {
    status: () => request(`${API_PREFIX}/auth/status`),
    logout: () => request(`${API_PREFIX}/auth/logout`, { method: 'POST' }),
  },

  /** 查询推送记录：server_name 精确、topic 模糊、分页。 */
  records: (params = {}) => request(`${RECORDS_PATH}${qs(params)}`),

  /** 重新推送一条已保存的记录到 MQTT。 */
  repush: (serverName, id) =>
    request(`${API_PREFIX}/repush`, {
      method: 'POST',
      body: { server_name: serverName, id },
    }),

  /** 查询定时任务，可按状态筛选。 */
  tasks: (params = {}) => request(`${API_PREFIX}/tasks${qs(params)}`),

  /** 查询客户端在线状态（由客户端通过 MQTT presence 主题上报）。 */
  clients: () => request(`${API_PREFIX}/clients`),

  /** 删除一条离线客户端记录；设备下次上线会自动重新出现。 */
  deleteClient: (suffix) =>
    request(`${API_PREFIX}/clients/${encodeURIComponent(suffix)}`, { method: 'DELETE' }),

  /** SSE 事件流地址（新消息提醒）。 */
  eventsUrl: () => `${API_PREFIX}/events`,

  /** 在线 API 文档页（OpenAPI 自动生成，含参数表与 curl 示例）。 */
  docsUrl: () => `${API_PREFIX}/docs`,
}
