# MQTT 推送中心前端

用 **Vue 3 + Vite + Tailwind CSS** 重写并重新设计的推送中心管理页面，对接 push-server 的接口。
视觉上采用深色「推送中心」风格：渐变光晕背景 + 毛玻璃顶栏 + 状态色卡片。

## 功能模块

| 模块 | 说明 | 对接接口 |
| --- | --- | --- |
| 推送记录 | 服务器/主题筛选（可搜索下拉）、分页、状态统计、Markdown 正文、展开全文、复制原文、按服务器/主题点击快速筛选、重新推送 | `GET /records`、`POST /api/repush` |
| 实时提醒 | SSE 监听新消息，顶栏出现「N 条新消息」按钮，点击拉取 | `GET /api/events` |
| 定时任务 | 状态筛选（待推送/已发送/已完成/已取消）、待推送倒计时（每秒刷新）、10s 自动轮询 | `GET /api/tasks` |

- 消息按 `status` 显示级别：正常（emerald）/ 警告（amber）/ 异常（rose）/ 信息（sky）。
- 卡片内点击主题/服务器名即可作为筛选条件。
- 顶栏连接指示灯实时反映后端连通状态。
- 顶栏「?」按钮可打开应用内**使用说明**（帮助页），涵盖两视图的操作指南。

## 目录结构

```
前端/
├── index.html              # 应用入口
├── vite.config.js          # 开发代理：/api、/records -> http://127.0.0.1:8383
├── tailwind.config.js      # 主题（配色 / 动画）
├── postcss.config.js
├── public/favicon.svg
└── src/
    ├── main.js
    ├── App.vue             # 外壳：背景光晕 / 顶栏 / 视图切换 / Toast
    ├── style.css           # Tailwind + 全局基调 + Markdown 排版
    ├── api/index.js        # 统一请求封装与接口
    ├── store.js            # 跨组件 UI 状态（标签、连接、新消息）
    ├── composables/        # Toast / 倒计时时钟
    ├── utils/              # Markdown 渲染、状态文案
    ├── components/         # 顶栏、筛选下拉、记录卡、任务卡、分页、Markdown 视图等
    └── views/              # 推送记录、定时任务两个视图
```

## 本地开发

先启动 push-server（默认 `8383`）：

```bash
cd push-server/容器相关脚本
uvicorn main:app --host 0.0.0.0 --port 8383
```

再启动前端：

```bash
cd push-server/前端
npm install
npm run dev        # http://localhost:5180，/api 与 /records 自动代理到 127.0.0.1:8383
```

若后端不在默认地址，可覆盖代理目标：

```bash
VITE_PROXY_TARGET=http://192.168.1.10:8383 npm run dev
```

> 通过隧道/反代域名（如 `*.xct258.top`）访问 dev server 时，
> `vite.config.js` 已在 `server.allowedHosts` / `preview.allowedHosts` 中放行 `.xct258.top`。
> 换了别的隧道域名时，把对应后缀加进去即可。

## 生产构建与部署

```bash
npm run build      # 产物输出到 前端/dist
```

构建产物是纯静态文件，无 history 路由依赖。

- 后端托管（推荐）：`main.py` 会自动识别 `前端/dist`（本地布局）或 `static/`（容器布局）并托管 `/`、`/assets`、`/favicon.svg`。本地开发布局无需额外配置，`uvicorn` 启动即用最新构建。
- Nginx：把 `dist/` 作为站点根目录，并将 `/api`、`/records` 反代到 push-server。

## 容器构建

镜像构建时 `init-components.sh` 会在容器内安装 Node.js、下载仓库源码、执行 `npm install && npm run build`，
产物落到 `/usr/local/bin/frontend`；`start.sh` 启动时清空重铺到 `/rec/static`，由 `main.py` 托管。

## 设计说明

- 单视口锁定：页面本身不滚动，仅主内容区内部滚动；移动端顶栏折行、筛选区自适应。
- 深色基调：`#070b14` 底 + indigo/sky 渐变光晕，玻璃拟态面板，状态色贯穿卡片/徽章/统计。
- Markdown 渲染使用 `marked` + `DOMPurify`，正文带展开/收起与「复制原文」。
