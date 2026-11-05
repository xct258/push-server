// 状态元数据：推送记录 status / 定时任务 status / 推送结果，统一从这里取文案与配色。
export const MSG_STATUS = {
  ok: { label: '正常', text: 'text-emerald-400', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/30', dot: 'bg-emerald-400', bar: 'from-emerald-400' },
  warn: { label: '警告', text: 'text-amber-400', bg: 'bg-amber-400/10', ring: 'ring-amber-400/30', dot: 'bg-amber-400', bar: 'from-amber-400' },
  error: { label: '异常', text: 'text-rose-400', bg: 'bg-rose-400/10', ring: 'ring-rose-400/30', dot: 'bg-rose-400', bar: 'from-rose-400' },
  info: { label: '信息', text: 'text-sky-400', bg: 'bg-sky-400/10', ring: 'ring-sky-400/30', dot: 'bg-sky-400', bar: 'from-sky-400' },
}

export const TASK_STATUS = {
  pending: { label: '待推送', text: 'text-indigo-300', bg: 'bg-indigo-400/10', ring: 'ring-indigo-400/30', dot: 'bg-indigo-400' },
  sent: { label: '已发送', text: 'text-amber-300', bg: 'bg-amber-400/10', ring: 'ring-amber-400/30', dot: 'bg-amber-400' },
  done: { label: '已完成', text: 'text-emerald-300', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/30', dot: 'bg-emerald-400' },
  cancelled: { label: '已取消', text: 'text-slate-400', bg: 'bg-slate-400/10', ring: 'ring-slate-400/30', dot: 'bg-slate-400' },
}

export const PUSH_RESULT = {
  success: { label: '推送成功', text: 'text-emerald-400', bg: 'bg-emerald-400/10' },
  failed: { label: '推送失败', text: 'text-rose-400', bg: 'bg-rose-400/10' },
  skipped: { label: '未推送', text: 'text-slate-400', bg: 'bg-slate-500/10' },
}

export const STATUS_META = {
  ok: { label: '正常', class: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30', bar: 'from-emerald-400' },
  warn: { label: '警告', class: 'text-amber-400 bg-amber-400/10 border-amber-400/30', bar: 'from-amber-400' },
  error: { label: '异常', class: 'text-rose-400 bg-rose-400/10 border-rose-400/30', bar: 'from-rose-400' },
  info: { label: '信息', class: 'text-sky-400 bg-sky-400/10 border-sky-400/30', bar: 'from-sky-400' },
}

export function fmtSched(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 待推送倒计时文案；非 pending 返回阶段说明。 */
export function countdownText(t, now = Date.now()) {
  if (t.status !== 'pending') return t.status === 'sent' ? '已发送，待客户端反馈' : ''
  const ms = new Date(t.schedule_at).getTime() - now
  if (Number.isNaN(ms)) return ''
  if (ms <= 0) return '已到点，等待推送'
  const m = Math.floor(ms / 60000)
  const h = Math.floor(m / 60)
  const d = Math.floor(h / 24)
  if (d > 0) return `还有 ${d} 天 ${h % 24} 时`
  if (h > 0) return `还有 ${h} 时 ${m % 60} 分`
  if (m > 0) return `还有 ${m} 分`
  return `还有 ${Math.floor(ms / 1000)} 秒`
}
