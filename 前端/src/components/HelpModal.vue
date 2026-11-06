<script setup>
import { onMounted, onUnmounted } from 'vue'

import { api } from '@/api'

const emit = defineEmits(['close'])

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div
    class="fixed inset-0 z-[150] flex items-center justify-center bg-black/60 p-3 backdrop-blur-sm animate-fade-in"
    @click.self="emit('close')"
  >
    <div class="glass flex h-full w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-white/10 shadow-2xl shadow-black/50 animate-scale-in">
      <!-- 头部 -->
      <header class="flex shrink-0 items-center gap-3 border-b border-white/10 px-5 py-3.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-sky-500 text-sm font-bold text-white">
          ?
        </div>
        <div class="leading-tight">
          <h2 class="text-[15px] font-bold text-white">使用说明</h2>
          <p class="text-[11px] text-slate-400">MQTT 推送中心 · 前端操作指南</p>
        </div>
        <button
          class="ml-auto flex h-7 w-7 items-center justify-center rounded-lg text-lg text-slate-400 transition hover:bg-white/10 hover:text-white"
          title="关闭（Esc）"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <!-- 内容 -->
      <div class="custom-scroll min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4 text-[13px] leading-relaxed text-slate-300">
        <!-- 界面概览 -->
        <section>
          <h3 class="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-white">
            <span class="h-1.5 w-1.5 rounded-full bg-indigo-400" /> 界面概览
          </h3>
          <ul class="space-y-1.5 pl-5 list-disc">
            <li>顶栏包含品牌、视图切换（<b class="text-indigo-300">推送记录</b> / <b class="text-indigo-300">定时任务</b>）、连接状态与「新消息」提示。</li>
            <li>连接状态灯：<span class="text-emerald-400">绿点</span> = 已连接，<span class="text-rose-400">红点</span> = 连接失败。</li>
            <li>两个视图：推送记录（历史消息一览）与定时任务（单向待办推送）。</li>
          </ul>
        </section>

        <!-- 推送记录 -->
        <section>
          <h3 class="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-white">
            <span class="h-1.5 w-1.5 rounded-full bg-emerald-400" /> 推送记录
          </h3>
          <ul class="space-y-1.5 pl-5 list-disc">
            <li>
              <b class="text-slate-100">筛选：</b>顶部「服务器 / 主题」下拉框，点击弹出候选列表，可输入关键字过滤；选「全部」清除该筛选。
              点击记录卡片上的主题标签或服务器名，也可快速筛选；「清除筛选」按钮一键清空。
            </li>
            <li>
              <b class="text-slate-100">状态徽章：</b><span class="text-emerald-400">正常</span>（ok）·
              <span class="text-amber-400">警告</span>（warn）· <span class="text-rose-400">异常</span>（error）·
              <span class="text-sky-400">信息</span>（info）。
            </li>
            <li>
              <b class="text-slate-100">模式徽章：</b><span class="text-amber-300">覆盖</span> = 同 服务器+分类+主题+标题 的记录会被覆盖；
              <span class="text-slate-400">持续</span> = 每次推送追加一条新记录。
            </li>
            <li><b class="text-slate-100">正文：</b>支持 Markdown；内容较长时出现「展开全文 / 收起」。</li>
            <li><b class="text-slate-100">复制：</b>卡片右上角「复制」按钮，复制消息原文（转纯文本）。</li>
            <li>
              <b class="text-slate-100">重新推送：</b>点击底部推送结果徽章
              （<span class="text-emerald-400">推送成功</span> / <span class="text-rose-400">推送失败</span> /
              <span class="text-slate-400">未推送</span>）即可把该条重新投递到 MQTT。
            </li>
            <li><b class="text-slate-100">分页：</b>每页 10 条，上一页 / 下一页切换。</li>
            <li>
              <b class="text-slate-100">新消息提醒：</b>通过 SSE 实时监听，有新推送时顶栏出现
              「⚡ N 条新消息」，点击自动回到记录页并刷新。
            </li>
          </ul>
        </section>

        <!-- 定时任务 -->
        <section>
          <h3 class="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-white">
            <span class="h-1.5 w-1.5 rounded-full bg-amber-400" /> 定时任务
          </h3>
          <ul class="space-y-1.5 pl-5 list-disc">
            <li><b class="text-slate-100">状态筛选：</b>全部 / 待推送 / 已发送 / 已完成 / 已取消。</li>
            <li>
              <b class="text-slate-100">任务卡片：</b>状态徽章、标题、任务编号（#id）、Markdown 消息正文、
              下行主题、来源标识（client_ref）、排期时间。
            </li>
            <li><b class="text-slate-100">倒计时：</b>仅「待推送」任务显示剩余时间；到点后由服务端自动推送到下行主题。</li>
            <li><b class="text-slate-100">自动刷新：</b>停留在该页时每 10 秒轮询一次最新状态。</li>
          </ul>
        </section>

        <!-- 接口调用 -->
        <section>
          <h3 class="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-white">
            <span class="h-1.5 w-1.5 rounded-full bg-sky-400" /> 接口调用
          </h3>
          <p class="mb-2 text-slate-400">
            完整在线接口文档（OpenAPI 自动生成，含参数表与 curl 示例，可一键复制）：
            <a
              :href="api.docsUrl()"
              target="_blank"
              rel="noopener"
              class="font-mono text-[12.5px] text-indigo-300 underline decoration-indigo-400/40 underline-offset-2 hover:text-indigo-200"
            >
              {{ api.docsUrl() }}
            </a>
          </p>

          <details open class="group mt-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <summary class="cursor-pointer select-none px-3.5 py-2 text-[13px] font-medium text-slate-200">
              <b class="font-mono text-[12.5px] text-indigo-300">POST /api/push</b>　推送消息（服务器脚本上报）
            </summary>
            <div class="px-3.5 pb-3">
              <pre class="mt-1 overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11.5px] leading-relaxed text-slate-300"><code>curl -X POST http://&lt;服务器IP&gt;:8383/api/push \
  -H 'Content-Type: application/json' \
  -d '{
    "server_name": "o1-debian-1",   # 来源服务器
    "category": "service",          # 必填：service 服务通知 / todo 待办提醒
    "topic": "server/khx-live",     # 项目 / 服务主题
    "title": "录播备份上传脚本",      # 项目里的脚本 / 任务名
    "message": "上传成功（支持 Markdown）",
    "status": "ok",                 # ok / warn / error / info
    "push_to_mqtt": true,           # 是否推送 MQTT（布尔，不带引号）
    "msg_type": "markdown",         # 可选，固定 markdown
    "mode": "append"                # append 追加 / overwrite 覆盖
  }'</code></pre>
              <p class="mt-2 text-[12px] leading-relaxed text-slate-400">
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">mode=overwrite</code>
                按 服务器+分类+主题+标题 匹配覆盖；<code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">status</code>
                是消息自身状态，与响应里的
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">push_result</code>（MQTT 投递结果）不是一回事。
              </p>
            </div>
          </details>

          <details class="mt-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <summary class="cursor-pointer select-none px-3.5 py-2 text-[13px] font-medium text-slate-200">
              <b class="font-mono text-[12.5px] text-indigo-300">POST /api/repush</b>　重新推送已保存的记录
            </summary>
            <div class="px-3.5 pb-3">
              <pre class="mt-1 overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11.5px] text-slate-300"><code>curl -X POST http://&lt;服务器IP&gt;:8383/api/repush \
  -H 'Content-Type: application/json' \
  -d '{"server_name": "server-1", "id": 1}'</code></pre>
            </div>
          </details>

          <details class="mt-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <summary class="cursor-pointer select-none px-3.5 py-2 text-[13px] font-medium text-slate-200">
              <b class="font-mono text-[12.5px] text-indigo-300">GET /records</b>　查询推送记录（分页 / 筛选）
            </summary>
            <div class="px-3.5 pb-3">
              <pre class="mt-1 overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11.5px] text-slate-300"><code>GET /records?server_name=server-1&amp;topic=test&amp;limit=50&amp;offset=0</code></pre>
              <p class="mt-2 text-[12px] text-slate-400">
                参数：<code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">server_name</code> 精确筛选 ·
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">topic</code> 模糊筛选 ·
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">limit</code> 默认 100（1-500）·
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">offset</code> 偏移量。
              </p>
            </div>
          </details>

          <details class="mt-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <summary class="cursor-pointer select-none px-3.5 py-2 text-[13px] font-medium text-slate-200">
              <b class="font-mono text-[12.5px] text-indigo-300">GET /api/tasks</b>　查询定时任务
            </summary>
            <div class="px-3.5 pb-3">
              <pre class="mt-1 overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11.5px] text-slate-300"><code>GET /api/tasks?status=pending&amp;limit=200</code></pre>
              <p class="mt-2 text-[12px] text-slate-400">
                参数：<code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">status</code>
                pending / sent / done / cancelled ·
                <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">server_name</code> 按服务筛选。
              </p>
            </div>
          </details>

          <details class="mt-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <summary class="cursor-pointer select-none px-3.5 py-2 text-[13px] font-medium text-slate-200">
              <b class="font-mono text-[12.5px] text-indigo-300">GET /api/events</b>　SSE 事件流（新消息实时提醒）
            </summary>
            <div class="px-3.5 pb-3">
              <pre class="mt-1 overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11.5px] text-slate-300"><code>GET /api/events
→ data: {"type":"new","total":6}</code></pre>
              <p class="mt-2 text-[12px] text-slate-400">
                新推送后推送事件 <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">{type:"new",total:N}</code>，
                前端据此弹出「N 条新消息」；另有 <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">GET /api/health</code> 健康检查。
              </p>
            </div>
          </details>
        </section>

        <!-- 数据与说明 -->
        <section>
          <h3 class="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-white">
            <span class="h-1.5 w-1.5 rounded-full bg-amber-400" /> 数据与说明
          </h3>
          <ul class="space-y-1.5 pl-5 list-disc">
            <li>推送记录按服务器分文件保存，每台服务器最多保留最近 100 条。</li>
            <li>消息正文支持 Markdown（代码块、表格、引用等）。</li>
            <li>推送结果（success / failed / skipped）是 MQTT 投递结果，与消息自身状态（ok / warn / error / info）不是一回事。</li>
            <li>定时任务接口写操作（创建 / 更新 / 取消）在开启 <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">PUSH_SERVER_TOKEN</code> 时需携带请求头 <code class="rounded bg-white/10 px-1 py-0.5 font-mono text-[11px]">X-Push-Token</code>。</li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>
