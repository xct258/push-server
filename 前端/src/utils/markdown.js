import DOMPurify from 'dompurify'
import { marked } from 'marked'

// 渲染 Markdown → 安全 HTML。marked + DOMPurify，带缓存避免重复解析。
const mdCache = new Map()

marked.setOptions({ breaks: true, gfm: true })

export function renderMarkdown(text) {
  const key = String(text ?? '')
  const hit = mdCache.get(key)
  if (hit !== undefined) return hit
  let html
  try {
    html = DOMPurify.sanitize(marked.parse(key))
  } catch {
    html = String(key).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[c]).replace(/\n/g, '<br>')
  }
  if (mdCache.size > 500) mdCache.clear()
  mdCache.set(key, html)
  return html
}

/** 从 Markdown 提取纯文本（用于复制原文）。 */
export function markdownToText(text) {
  const div = document.createElement('div')
  div.innerHTML = renderMarkdown(text)
  return div.textContent
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 兜底：隐藏 textarea + execCommand
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.cssText = 'position:fixed;top:-100px;opacity:0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    document.body.removeChild(ta)
    return ok
  }
}
