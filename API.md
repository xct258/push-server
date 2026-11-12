# push-server 接口文档

这是 push-server 唯一的完整接口说明，包含 **REST API、鉴权、MQTT 接入、客户端在线状态（presence）和脚本示例**。

- 服务地址：`http://<服务器IP>:8383`
- 生产环境如果走了反向代理，把下面的 `http://<host>:8383` 换成你的 HTTPS 域名即可
- 所有时间字符串默认使用 **Asia/Shanghai**
- 请求和响应默认使用 `application/json; charset=utf-8`

在线自动文档：

- `http://<host>:8383/api/docs`：按 OpenAPI 自动生成的接口说明页
- `http://<host>:8383/docs`：FastAPI 自带 Swagger
- `http://<host>:8383/openapi.json`：OpenAPI JSON，可用于生成 SDK / 客户端

---

## 1. 鉴权

### 1.1 统一登录（SSO）

push-server 不再提供本地登录页和 `/api/auth/login`，登录统一由 `auth-server` 完成：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AUTH_ENABLED` | `true` | 是否启用登录校验 |
| `SERVICE_ID` | `push-server` | 本服务的服务 ID |
| `SERVICE_SECRET` | 空 | 本服务自己的签名密钥 |
| `SERVICE_TOKEN_VERSION` | `1` | 本服务的 Token 版本 |
| `SSO_LOGIN_URL` | 空 | 统一登录页地址，未登录页面 302 到这里 |
| `SSO_COOKIE_NAME` | `sso_push_server` | 本服务的 Cookie 名 |
| `SSO_COOKIE_DOMAIN` | 空 | 父域，退出登录时用于清 Cookie |
| `SSO_ALLOWED_REDIRECT_SUFFIX` | 空 | 允许登录后跳转的后缀 |
| `PUSH_SERVER_TOKEN` | 空 | 服务间调用令牌 |

查看当前登录状态：

```http
GET /api/auth/status
```

退出登录（清除父域 Cookie）：

```http
POST /api/auth/logout
```

接口未登录返回 `401`；页面未登录返回 `302` 到 `https://auth.o1-1.xct258.top/login?service=push-server&next=...`。

### 1.2 服务间令牌

保护接口也接受请求头：

```http
X-Push-Token: <PUSH_SERVER_TOKEN>
```

适合脚本、TaskOps、自动化任务调用，不需要登录 Cookie。

### 1.3 哪些接口需要鉴权

| 接口 | 是否受保护 |
| --- | --- |
| `/api/auth/*` | 否 |
| `/api/health` | 否 |
| `/api/docs` | 是（启用统一登录时） |
| `/docs`、`/openapi.json` | 否 |
| `/api/push` | 否 |
| `/api/task`、`/api/task/*` | 中间件放行，但有 `PUSH_SERVER_TOKEN` 时会校验 `X-Push-Token` |
| `/records` | 是 |
| `/api/repush` | 是 |
| `/api/tasks` | 是 |
| `/api/clients` | 是 |
| `/api/events` | 是 |

未登录访问保护接口返回：

```json
{"detail": "未登录或登录已过期"}
```

HTTP 状态码 `401`。

---

## 2. REST API

## 2.1 推送消息

### `POST /api/push`

保存一条推送记录，可选同时发布到 MQTT。服务器脚本通常用这个接口上报状态。

请求体：

```json
{
  "server_name": "o1-debian-1",
  "category": "service",
  "topic": "server/khx-live",
  "title": "录播备份上传脚本",
  "message": "上传成功",
  "status": "ok",
  "push_to_mqtt": true,
  "msg_type": "markdown",
  "mode": "append"
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `server_name` | string | 是 | 来源服务器名，记录保存在 `push_records/{server_name}.json` |
| `category` | string | 是 | `service` 服务通知 / `todo` 待办提醒；决定 MQTT 下行格式和客户端卡片布局 |
| `topic` | string | 是 | 项目 / 服务主题，例如 `server/khx-live` |
| `title` | string | 是 | 脚本 / 任务名称，不能为空 |
| `message` | string | 是 | 仅消息正文，支持 Markdown；服务通知的服务器/服务名/状态由服务端自动拼头，不要把 `【服务通知】` 手写进 `message` |
| `status` | string | 是 | `ok` / `warn` / `error` / `info` |
| `push_to_mqtt` | bool | 是 | 只允许 JSON 布尔值 `true` / `false`，不要传字符串 |
| `msg_type` | string | 否 | 固定为 `markdown` |
| `mode` | string | 否 | `append`（默认，追加）或 `overwrite`（覆盖同 `server_name + category + topic + title` 的记录） |

响应：

```json
{
  "code": 200,
  "record_id": 12,
  "status": "ok",
  "detail": "消息已投递至 MQTT"
}
```

说明：

- `status` 是消息自身状态
- `push_result` 是 MQTT 投递结果：`success` / `failed` / `skipped`
- 每个 `server_name` 最多保留最近 100 条记录
- `mode=overwrite` 使用 `server_name + category + topic + title` 四者匹配

**下行 payload 由服务端按 `category` 自动生成**：

- `category=service`：
  ```text
  【服务通知】{server_name}
  【服务】{title}
  【状态】{status}

  {message}
  ```
- `category=todo`：
  ```text
  【待办提醒】{title}
  {message}
  ```

所以调用方只需要传正文 `message`，不需要自己拼 `【服务通知】` 或 `【待办提醒】` 前缀。服务端同时兼容已经手写前缀的旧调用，不会重复套头。

校验失败时返回 `422`：

```json
{
  "code": 422,
  "errors": [
    {"field": "push_to_mqtt", "message": "字段 'push_to_mqtt' 只允许传入 true 或 false"}
  ]
}
```

## 2.2 重新推送记录

### `POST /api/repush`

```json
{
  "server_name": "server-1",
  "id": 1
}
```

- 按记录里的 `category` 重新生成下行 payload，不会直接发送保存的 `message` 原文
- 记录不存在：`404`
- MQTT 发布失败：`500`
- 成功：`{"code":200,"detail":"消息已重新推送"}`

## 2.3 查询推送记录

### `GET /records`

```http
GET /records?server_name=server-1&topic=test&limit=50&offset=0
```

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `server_name` | string | — | 精确筛选 |
| `topic` | string | — | 主题模糊匹配，不区分大小写 |
| `limit` | int | 100 | 1–500 |
| `offset` | int | 0 | 偏移量 |

响应：

```json
{
  "total": 123,
  "offset": 0,
  "limit": 50,
  "records": [
    {
      "id": 1,
      "server_name": "server-1",
      "category": "service",
      "topic": "server/khx-live",
      "title": "备份脚本",
      "message": "上传成功",
      "status": "ok",
      "push_to_mqtt": true,
      "push_result": "success",
      "msg_type": "markdown",
      "mode": "append",
      "created_at": "2026-11-06 12:00:00"
    }
  ]
}
```

## 2.4 定时任务

### `POST /api/task`

按 `server_name + client_ref` 幂等创建或更新。已存在则更新并重置为 `pending`。

```json
{
  "server_name": "taskops",
  "category": "todo",
  "client_ref": "todo-123",
  "topic": "taskops/todo",
  "title": "交电费",
  "message": "主卧电表，户号123456",
  "schedule_at": "2026-11-07T20:30:00+08:00",
  "recurring": false
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `server_name` | string | 是 | 来源服务 |
| `category` | string | 是 | `service` / `todo`；TaskOps 待办固定传 `todo` |
| `client_ref` | string | 是 | 调用方唯一标识，同服务下重复即更新 |
| `topic` | string | 否 | 空则使用服务端 `PUSH_TOPIC`，默认 `taskops/todo` |
| `title` | string | 否 | 标题；`category=todo` 时作为待办标题 |
| `message` | string | 是 | 仅正文，支持 Markdown；下行前缀由服务端按 `category` 生成 |
| `schedule_at` | string | 是 | ISO 时间；无时区按 Asia/Shanghai |
| `recurring` | bool | 否 | 仅标记循环任务，下一期由调用方重新创建 |

响应：

```json
{
  "code": 200,
  "task_id": 7,
  "action": "created",
  "task": { "...": "任务对象" }
}
```

### `PUT /api/task/{task_id}`

按 ID 更新任务。字段都可选：

```json
{
  "title": "新的标题",
  "message": "新的正文",
  "schedule_at": "2026-11-08T09:00:00+08:00",
  "recurring": false
}
```

终态任务被修改后会重新回到 `pending`。任务不存在返回 `404`。

### `DELETE /api/task/ref/{client_ref}`

按调用方唯一标识取消任务：

```http
DELETE /api/task/ref/todo-123?server_name=taskops
```

`server_name` 可选；不传则取消所有服务下相同 `client_ref` 的非终态任务。

响应：

```json
{"code": 200, "cancelled": 1}
```

### `GET /api/tasks`

```http
GET /api/tasks?server_name=taskops&status=pending&limit=100
```

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `server_name` | string | — | 按服务筛选 |
| `status` | string | — | `pending` / `sent` / `cancelled` |
| `limit` | int | 100 | 最大 500 |

响应：

```json
{
  "total": 1,
  "tasks": [
    {
      "task_id": 7,
      "server_name": "taskops",
      "category": "todo",
      "client_ref": "todo-123",
      "topic": "taskops/todo",
      "title": "交电费",
      "message": "主卧电表，户号123456",
      "schedule_at": "2026-11-07T20:30:00+08:00",
      "recurring": false,
      "status": "pending",
      "created_at": "2026-11-06 12:00:00",
      "updated_at": "2026-11-06 12:00:00"
    }
  ]
}
```

任务状态：

| 状态 | 说明 |
| --- | --- |
| `pending` | 等待到点推送 |
| `sent` | 已推送 |
| `cancelled` | 已取消 |
| `done` | 终态保留值，当前接口不会主动写入 |

## 2.5 客户端在线状态

### `GET /api/clients`

```http
GET /api/clients
GET /api/clients?online=true
```

响应：

```json
{
  "total": 2,
  "online": 1,
  "clients": [
    {
      "client_id": "windows_1a2b3c4d",
      "suffix": "1a2b3c4d",
      "online": true,
      "platform": "windows",
      "topic": "taskops/todo/#",
      "name": "DESKTOP-ABC",
      "version": "1.3.0",
      "last_seen": "2026-11-06 12:00:00",
      "last_seen_epoch": 1793937600,
      "status_changed": "2026-11-06 11:58:00",
      "status_changed_epoch": 1793937480
    }
  ],
  "topic": "$presence/clients",
  "ttl_seconds": 180
}
```

- `topic` 是客户端上报的**订阅主题**
- `last_seen` 是最后一次心跳时间
- `status_changed` 是最近一次在线/离线状态变化时间
- 服务端超过 `PRESENCE_TTL_SECONDS`（默认 180 秒）没有心跳会显示离线

### `DELETE /api/clients/{suffix}`

删除离线客户端记录：

```http
DELETE /api/clients/1a2b3c4d
```

- 在线客户端返回 `409`
- 不存在返回 `404`
- 只清理展示和 retained 消息，不拉黑设备；设备下次上线会重新出现

## 2.6 健康检查

### `GET /api/health`

```json
{"status": "running"}
```

## 2.7 SSE 事件流

### `GET /api/events`

服务端推送新记录事件，15 秒一次心跳保活：

```text
data: {"type":"new","total":12}

: keep-alive
```

需要登录 Cookie 或 `X-Push-Token`。

---

## 3. MQTT 接入

### 3.1 Broker 地址

| 方式 | 地址 | 说明 |
| --- | --- | --- |
| WSS | `wss://push-server.o1-1.xct258.top/mqtt` | **客户端默认**，公网可用 |
| WS | `ws://<host>:9001/mqtt` | 局域网直连 Mosquitto |
| TCP | `mqtt://<host>:1883` | 仅 broker 同机；1883 默认绑 `127.0.0.1` |

参数：

| 项 | 值 |
| --- | --- |
| 协议 | MQTT 3.1.1 / 5.0 |
| 鉴权 | 匿名（当前部署） |
| KeepAlive | 60 秒 |
| QoS | 1 |
| Clean Session | Windows 默认 `true`；Android 为离线排队使用 `false` |
| Retained | 业务消息 `false`；presence 使用 retained |

> Android 使用持久会话时，broker 会保留旧订阅。切换订阅主题前必须先取消旧主题，否则新旧主题会同时收信。

### 3.2 下行主题与 payload

订阅：

```text
{base}/#
```

默认：

```text
taskops/todo/#
```

服务端到点发布到：

```text
{base}/{task_id}
```

payload 为纯文本，按 `category` 分两种格式。

**待办提醒（`category=todo`）**：

```text
【待办提醒】交电费
主卧电表，户号123456
到期：2026-10-12
```

- 首行前缀 `【待办提醒】` 后面是标题
- 剩余行是正文
- 主题尾段是 `task_id`
- 正文可以是 Markdown；客户端应用内会渲染，系统通知会转成纯文本

**服务通知（`category=service`）**：

```text
【服务通知】o1-debian-1
【服务】录播备份上传脚本
【状态】ok

上传成功
```

- 第一行 `【服务通知】` 后面是 `server_name`
- `【服务】` 后面是脚本 / 任务名（请求里的 `title`）
- `【状态】` 是 `ok / warn / error / info`
- 空行之后是完整 Markdown 正文
- 卡片标题使用服务器名，服务行使用 `【服务】` 的值
- 客户端按首行 marker 分派，两种格式不混用

### 3.3 presence 在线状态

客户端连接后向：

```text
$presence/clients/{client_id}
```

发布 retained JSON：

```json
{
  "client_id": "windows_1a2b3c4d",
  "suffix": "1a2b3c4d",
  "topic": "taskops/todo/#",
  "name": "DESKTOP-ABC",
  "platform": "windows",
  "version": "1.3.0",
  "online": true,
  "ts": "2026-11-06T12:00:00+08:00"
}
```

约定：

- 连接成功后发布 `online=true`，retained
- 每 60 秒用 QoS1 + retained 刷新一次心跳
- 收到消息、MQTT 重连、亮屏/解锁时也会补发在线状态
- 主动停止时发布 `online=false`
- Android 客户端不使用 MQTT Will，异常断线由心跳 + `PRESENCE_TTL_SECONDS` 兜底；
  Windows / 旧客户端仍可用 Will，服务端会比较 `ts`，丢弃迟到的旧 Will
- `$` 开头的主题不会被业务订阅的 `#` 匹配，不会触发提醒
- 服务端以 `suffix` 作为设备唯一标识
- 自定义前缀改变但 suffix 不变时，仍视为同一台设备
- `status_changed` 只在在线/离线状态真正变化时更新

---

## 4. 脚本示例

### 4.1 curl 推送

```bash
curl -X POST 'http://<host>:8383/api/push' \
  -H 'Content-Type: application/json' \
  -d '{
    "server_name": "server-1",
    "category": "service",
    "topic": "server/backup",
    "title": "备份脚本",
    "message": "上传成功",
    "status": "ok",
    "push_to_mqtt": true,
    "msg_type": "markdown",
    "mode": "append"
  }'
```

### 4.2 Python 推送

```python
import requests

requests.post(
    "http://<host>:8383/api/push",
    json={
        "server_name": "server-1",
        "category": "service",
        "topic": "server/backup",
        "title": "备份脚本",
        "message": "**上传成功**",
        "status": "ok",
        "push_to_mqtt": True,
        "msg_type": "markdown",
        "mode": "append",
    },
    timeout=10,
).raise_for_status()
```

### 4.3 带服务令牌查询

```bash
curl -H "X-Push-Token: $PUSH_SERVER_TOKEN" \
  'http://<host>:8383/api/clients'
```

### 4.4 MQTT 旁路监听

```bash
mosquitto_sub -h <host> -p 1883 \
  -t 'taskops/todo/#' -v
```

WebSocket：

```bash
mosquitto_sub --url 'ws://<host>:9001/mqtt' \
  -t 'taskops/todo/#' -v
```

---

## 5. 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `AUTH_ENABLED` | `true` | 是否启用统一登录校验 |
| `SERVICE_ID` | `push-server` | 本服务的服务 ID |
| `SERVICE_SECRET` | 空 | 本服务自己的签名密钥 |
| `SERVICE_TOKEN_VERSION` | `1` | 本服务的 Token 版本 |
| `SSO_LOGIN_URL` | 空 | 统一登录页地址；未登录页面 302 到这里 |
| `SSO_COOKIE_NAME` | `sso_push_server` | 本服务的 Cookie 名 |
| `SSO_COOKIE_DOMAIN` | 空 | 父域，退出登录时清 Cookie |
| `SSO_ALLOWED_REDIRECT_SUFFIX` | 空 | 允许登录后跳转的后缀 |
| `PUSH_SERVER_TOKEN` | 空 | 服务间调用令牌 |
| `PUSH_TOPIC` | `taskops/todo` | 默认 MQTT 下行 base |
| `PRESENCE_TTL_SECONDS` | `180` | 客户端心跳超时时间 |
| `MQTT_WS_PORT` | `9001` | Mosquitto WebSocket 端口 |
| `UVICORN_PORT` | `8383` | REST API 端口 |
| `TASK_RESYNC_INTERVAL` | `300` | 定时任务兜底重载秒数 |

---

## 6. 错误约定

普通错误：

```json
{"detail": "错误说明"}
```

请求体校验错误：

```json
{
  "code": 422,
  "errors": [
    {"field": "title", "message": "缺少必填字段 'title'"}
  ]
}
```

常见状态码：

| 状态码 | 说明 |
| --- | --- |
| 200 | 成功 |
| 400 | 参数格式错误 |
| 401 | 未登录 / 会话过期 |
| 403 | 服务令牌错误 |
| 404 | 任务 / 记录 / 客户端不存在 |
| 409 | 在线客户端不能删除 |
| 422 | 请求体校验失败 |
| 500 | 服务内部错误 |
