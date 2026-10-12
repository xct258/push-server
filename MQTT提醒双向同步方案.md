# TaskOps ↔ push-server ↔ MQTT 客户端 双向同步方案（修改文档）

> 状态：草案，待完善后评审开工。
> 涉及仓库：`push-server`（本仓库，主改）＋ `web-TaskOps`（投递与回写）。
> 约定：TaskOps 是任务真相源；push-server 是提醒投递 + 交互层；全链路时间用 ISO + 时区（上海）。

---

## 1. 背景与目标

- TaskOps 待办开启 MQTT 提醒后，把提醒任务推给 push-server。
- push-server 存下定时任务，到点推送给 MQTT 客户端。
- 客户端可反馈「完成」或「推迟」。
- push-server 把反馈回调给 TaskOps，同步任务状态。

---

## 2. 总体架构

```
TaskOps 后端 (:8481)                      push-server (:8383 + mosquitto)              MQTT 客户端
┌─────────────────┐  (A) POST /api/task  ┌──────────────────────────┐  (C) 定时publish ┌──────────┐
│ 待办 CRUD       │ ────────────────────▶ │ 定时任务存储 + 调度循环   │ ───────────────▶ │ 订阅下行 │
│ 开关/时间/删除   │  client_ref=todo-{id} │ pending→sent→done        │  taskops/todo  │  弹窗提醒 │
└─────────────────┘                      └──────────────────────────┘                └──────────┘
        ▲                                          │                                        │
        │                                          │ (D) 回调                               │ (E) 反馈
        │              (B) PUT /todos/{id}/processed│                                        │ MQTT上行主题（主）
        └────────────────── processed / snooze ◀──┘                                        │ REST（备用）
```

- (A) TaskOps → push-server：建 / 改 / 删提醒任务，同步调用，失败即时报错。
- (B) push-server → TaskOps：反馈回调，异步 + 重试，复用现有 `processed` / `snooze` 接口。
- (C) push-server → 客户端：到点 publish，结构化 JSON（含 `task_id`）。
- (E) 客户端 → push-server：MQTT 上行主题为主，REST 接口备用。

---

## 3. 完整时序

### 3.1 创建提醒任务

```
用户(TaskOps前端) → TaskOps后端: 新建待办 + 开MQTT提醒 + 推送时间
TaskOps后端 → push-server: POST /api/task {client_ref: todo-123, ...}
push-server → TaskOps后端: {task_id: 7}（存 todos.push_task_id）
TaskOps后端 → 用户: 创建成功
```

### 3.2 到点推送（精确唤醒，不轮询）

```
push-server调度: 取最早 pending 任务，delay = schedule_at - now
  → await asyncio.wait_for(变更事件.wait(), timeout=delay)
被唤醒后: 推送所有 schedule_at<=now 的任务 → 状态 pending → sent
  → 重新计算下一个 delay，继续睡
唤醒条件(三者任一): ① 到达最早任务时间 ② 新建/更新/取消任务(变更事件)
  ③ 兜底每 5 分钟重载一次(防文件被外部改、时钟漂移)
push-server → MQTT(主题 taskops/todo): {task_id: 7, ...}
```

- 过期任务（`schedule_at` 已过）：`delay<=0`，立即推。
- 无 `pending` 任务：无限等变更事件（`timeout=None`）。
- 误唤醒（提前醒 / 事件抖动）：重算后仍是未来则继续睡，不空推。

### 3.3 客户端反馈 → 回调同步

```
客户端 → push-server(主题 taskops/feedback): {task_id: 7, action: done}
push-server: 任务状态 sent → done
push-server → TaskOps: PUT /api/todos/123/processed
TaskOps: 完成（循环任务自动顺延，并 POST 新 /api/task 建下一期，形成闭环）

客户端 → push-server: {task_id: 7, action: snooze, snooze_minutes: 60}
push-server: schedule_at += 60分钟，状态 sent → pending
push-server → TaskOps: POST /api/todos/123/snooze（扩展回写新时间，见 4.6）
```

### 3.4 变更与取消

```
用户改时间/内容 → TaskOps → POST /api/task（同 client_ref = 更新，不建重复）
用户关闭提醒/删除待办 → TaskOps → DELETE /api/task/ref/todo-123（到点跳过）
```

`DELETE /api/task/ref/{client_ref}` 是调用方同步取消，不反向回调 TaskOps；同时清除该任务的待重试/失败回调状态。push 网页手动取消则通过反馈接口发送 `action: cancelled`，回调 TaskOps 的完成接口。

---

## 4. 接口契约

### 4.1 `POST /api/task`（push-server 新增，按 `client_ref` 幂等 upsert）

请求：

```json
{
  "server_name": "taskops",
  "client_ref": "todo-123",
  "topic": "taskops/todo",
  "title": "交电费",
  "message": "主卧电表，户号…",
  "schedule_at": "2026-10-12T20:30:00+08:00",
  "recurring": false
}
```

响应：`{"code": 200, "task_id": 7, "action": "created|updated"}`。

字段说明：`server_name/topic/message` 口径与现有 `/api/push` 一致；
`client_ref` 为 TaskOps 侧唯一标识（格式 `todo-{id}`），用于更新 / 取消 / 回调定位；
`schedule_at` 必填，过去时间视为立即到期（下轮调度即推）。

### 4.2 任务管理（push-server 新增）

| 接口 | 用途 |
| --- | --- |
| `PUT /api/task/{task_id}` | 同 4.1（TaskOps 存回执后可用） |
| `DELETE /api/task/ref/{client_ref}` | 取消任务（TaskOps 删待办 / 关提醒时调） |
| `GET /api/tasks?status=pending&server_name=taskops` | 查任务（对账 / 调试） |

### 4.3 下行 MQTT（push-server → 客户端，到点 publish）

- 主题：`{base}/{task_id}`（如 `taskops/todo/7`，`base` 由任务的 `topic` 字段定，默认 `PUSH_TOPIC`），`qos=1, retained=false`。
- payload：纯文本（人类可直接读），格式 `【待办提醒】{title}\n{message}`（无标题只发正文）：

```
【待办提醒】交电费
主卧电表，户号…
到期：2026-10-12
```

- 设计取舍：身份放主题里（客户端取主题最后一段即 `task_id`），正文保持零解析可读；
  通用 MQTT 客户端订阅 `taskops/todo/#` 肉眼即见人话。普通 `/api/push` 通道保持原文投递，不受影响。

### 4.4 上行 MQTT 反馈（客户端 → push-server，主通道，需常驻订阅）

- 主题：`taskops/feedback`（`FEEDBACK_TOPIC` 可配）。
- payload（二选一）：

```json
{"task_id":7,"action":"done"}
{"task_id":7,"action":"snooze","snooze_minutes":60}
{"task_id":7,"action":"cancelled"}
```

- `snooze_minutes` 缺省 60，必须为正整数。
- push-server 校验 `task_id` 存在且未终态（`done/cancelled` 的反馈忽略 + 记日志）。

### 4.5 REST 反馈（备用通道，push-server 新增）

`POST /api/task/{task_id}/feedback`，body 与 4.4 相同，处理逻辑与 MQTT 上行完全一致（抽同一函数）。

### 4.6 回调 TaskOps（push-server → TaskOps，异步 + 重试）

- `done` → `PUT {TASKOPS_BASE}/api/todos/{id}/processed`（复用；循环任务自动顺延）。
- `cancelled` → 同一完成接口，附带 `note: 任务已取消`，用于 push 网页/客户端手动取消。
- `snooze` → `POST {TASKOPS_BASE}/api/todos/{id}/snooze`，并扩展该接口接受可选字段回写新时间：

```json
{"note": "客户端推迟60分钟", "mqtt_at": "2026-10-12T21:30:00+08:00", "callback_ref": "push-7-snooze-2026-10-12T21:30:00+08:00"}
```

- MQTT 推送时间使用 `mqtt_at`：回调只更新 MQTT 精确排期，不修改到期日/提醒日，也不再次投递给 push-server。TaskOps 页面不带 `mqtt_at` 的手动推迟仍按天或循环周期顺延。
- `callback_ref` 由任务 ID、动作和新排期组成，同一次回调的重试保持一致，TaskOps 用它跳过重复回写。
- 回调返回 404 表示对应待办已不存在，标为 `skipped` 并停止重试；网络故障及服务端临时错误仍按原规则重试。
- 回调失败 → 任务记 `callback`=`pending`，回调任务内按 `30s×次数（封顶300s）` 退避重试，最多 10 次后记 `failed` + 日志（实现注：精确唤醒下没有固定“下轮”，故重试内聚在回调任务里）。
- 鉴权（可选）：回调与投递统一带 `X-Callback-Token` / `Authorization`，两边对等配置（见第 6 节）。

---

## 5. 任务状态机与存储

### 5.1 状态机

```
pending ──到点publish──▶ sent ──反馈done──▶ done（回调TaskOps processed）
  │                        │
  │                        └──反馈snooze──▶ pending（schedule_at顺延，回调TaskOps snooze）
  │
  └──TaskOps DELETE──▶ cancelled（终态，到点跳过）
```

- `sent` 未反馈是否超时重发：v1 先不做（列入 9.3 可选）。
- 回调失败不阻塞状态流转，记 `callback_pending` 独立重试。

### 5.2 存储：独立 `tasks.json`（push-server 新增，不复用 records）

原因：现有 records 按 server 封顶 100 条会被挤掉，定时任务不能混进去。
单 worker + asyncio 锁，任务量小够用；以后量大再迁 SQLite。

单条示例：

```json
{
  "task_id": 7,
  "server_name": "taskops",
  "client_ref": "todo-123",
  "topic": "taskops/todo",
  "title": "交电费",
  "message": "…",
  "schedule_at": "2026-10-12T20:30:00+08:00",
  "recurring": false,
  "status": "pending",
  "callback": "none",
  "retry": 0,
  "created_at": "2026-10-11 17:30:00",
  "updated_at": "2026-10-11 17:30:00"
}
```

### 5.3 调度器实现要点（精确唤醒）

- 单 `asyncio.Task` 跑循环，`asyncio.Event` 做变更通知；
  `POST/PUT/DELETE /api/task*` 改完 `tasks.json` 后必须触发事件，循环被打断后重算 `delay`。
- 用 `asyncio.wait_for(event.wait(), timeout=delay)` 而不是裸 `sleep`，保证任务变更能打断长睡；
  `set/clear` 竞态用任务版本号规避（每次变更版本号 +1，循环对比版本号决定是否重算，实现时落实）。
- 服务关闭（`lifespan` 退出）时 cancel 调度任务，优雅退出。
- 时钟回拨：靠兜底重载 + 每次唤醒重算，最坏延迟一个兜底周期。

---

## 6. 配置项

| 哪边 | 变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| TaskOps | `PUSH_SERVER_URL` | `https://push-server.o1-1.xct258.top` | 投递目标（调其 `/api/task`，注意不是 `/push`，已实测 404） |
| TaskOps | `PUSH_SERVER_TOKEN` | 空 | 投递鉴权（可选） |
| push-server | `TASKOPS_BASE_URL` | `http://127.0.0.1:8481` | 回调目标（内网） |
| push-server | `TASKOPS_TOKEN` | 空 | 回调鉴权（可选） |
| push-server | `PUSH_TOPIC` / `FEEDBACK_TOPIC` | `taskops/todo` / `taskops/feedback` | 上下行主题 |
| push-server | `TASK_RESYNC_INTERVAL` | `300` | 兜底重载间隔（秒）；正常唤醒由最早任务时间 + 变更事件驱动 |

---

## 7. 异常与重试策略

- TaskOps → push-server 投递失败：内存改完→先同步→再 commit，失败 rollback + 502，前端 toast，用户重试（不自动补，无孤儿任务）。
- TaskOps 删除待办：先 cancel 对端任务（失败 502 不删行）；一次性完成：cancel 对端 best-effort（失败只记日志，幽灵推送打到已完成任务时回调是空操作）。
- 回调重放（`callback_ref` 已见过）：跳过推进、只补同步，防重复顺延。
- 调度 publish 抛异常（broker 挂了）：本轮跳过 + 日志，任务保持 `pending`，下次唤醒继续。
- 误唤醒（提前醒 / 事件抖动）：重算 `delay`，仍是未来则继续睡，不空推。
- 服务关闭：cancel 调度任务，正在进行的 publish 做完当前条目后退出。
- 回调 TaskOps 失败：`callback`=`pending`，按 `30s×次数（封顶300s）` 退避重试，最多 10 次 → `failed` + 日志人工对账。
- 反馈指向不存在 / 已终态任务：忽略 + 日志（防野消息）。
- TaskOps 重启 / push-server 重启：任务全在 `tasks.json`，重启后调度继续（`sent` 的任务视为已送达，不重发）。

---

## 8. 已确认决策

1. 反馈通道：MQTT 上行主题为主 ＋ REST 备用，两者同一处理函数。
2. 推迟粒度：分钟级精确（`snooze_minutes`，缺省 60），TaskOps 侧扩展 `snooze` 接口回写。
3. 存储：独立 `tasks.json`，不复用 records。

---

## 9. 实施步骤（评审通过后按此开工）

### 阶段一：push-server

- [ ] `tasks.json` 存取层（读写 + asyncio 锁 + 幂等 upsert）。
- [ ] `POST/PUT/DELETE/GET /api/task*` 接口。
- [ ] 精确唤醒调度（`lifespan` 启动：最早任务时间 + 变更事件 + 兜底重载，到点 publish 下行 JSON）。
- [ ] paho 常驻订阅上行 `FEEDBACK_TOPIC`（`on_message` → 反馈处理函数）。
- [ ] `POST /api/task/{id}/feedback`（复用同一处理函数）。
- [ ] 回调 TaskOps（`processed` / `snooze` + 重试计数）。
- [ ] 鉴权 token（可选，如定下来）。
- [ ] 管理页展示任务列表（可选，看要不要）。

### 阶段二：web-TaskOps

- [ ] `todos` 加列：`mqtt_enabled`（开关）、`mqtt_at`（精确排期）、`push_task_id`（回执）、`last_callback_ref`（回调幂等）。
- [ ] 创建 / 编辑 / 删除待办时同步 `POST/DELETE /api/task`（失败 502 报错）。
- [ ] `processed` 成功后：循环任务自动 POST 新 `/api/task` 建下一期。
- [ ] 扩展 `POST /todos/{id}/snooze`：接受 `note` / `mqtt_at` 回写。
- [ ] 前端：MQTT 开关 + 推送时间选择 + 任务状态回显。

### 阶段三：联调

- [ ] push-server 本地桩验证全链路（建任务 → 到点 → 反馈 → 回调）。
- [ ] 真实 broker + 真实客户端验证。
- [ ] 异常演练：broker 挂 / TaskOps 挂 / 野消息 / 重复反馈。

---

## 10. 客户端设计建议（客户端未设计时按此来）

- 订阅 `{base}/#`（如 `taskops/todo/#`，QoS 1），payload 直接展示，主题尾段取 `task_id`。
- 两个按钮：完成 → `{"task_id":N,"action":"done"}`；推迟 → `{"task_id":N,"action":"snooze","snooze_minutes":60}`，
  发到上行主题（默认 `taskops/feedback`，QoS 1）；点后本地置灰防重复。
- 每次收到都展示（snooze 后的重推本来就是一条新提醒；QoS 重传的极偶发重复可忽略，不做去重）。
- APP 类客户端：重连后调 `GET /api/tasks?status=pending` 补拉离线期间错过的提醒。

## 11. 待完善（TODO）

- [ ] MQTT 客户端具体形态（设备 / APP）落地后，确认主题命名与按钮交互细节。
- [ ] `TASKOPS_BASE_URL` 生产值（隧道域名还是内网 IP）。
- [ ] 鉴权 token 要不要上？要的话两边配什么值。
- [ ] `snooze_minutes` 缺省值最终定多少。
- [ ] `sent` 未反馈要不要超时重发（v1 做不做）。
- [ ] 下行 payload 字段增减（如需不需要带 `due_time` / 优先级）。
- [ ] 管理页要不要展示任务列表。
- [ ] 兜底重载间隔最终值（默认 300s 是否合适）。
