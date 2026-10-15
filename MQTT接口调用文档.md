# MQTT 接口调用文档（提醒客户端接入）

> 面向 MQTT 提醒客户端（手机 APP / 桌面通知 / ESP32 等）。
> 服务端：push-server（FastAPI + Mosquitto）。本文只讲客户端如何接入 broker、订阅、接收并展示消息。
> **单向接收**：客户端只订阅下行，不做任何上行反馈。
> 状态：草案，随客户端落地持续修订。

---

## 1. 接入概览

```
push-server 到点 publish ──▶ Mosquitto broker ──▶ 客户端（订阅下行主题）
```

- 客户端**主动订阅**下行主题，服务端到点把提醒 publish 出来，客户端收到即展示。
- 提醒内容已是**拼好的纯文本**，客户端零解析即可展示。
- 纯单向：客户端只接收、不上行反馈、不维护倒计时；完成 / 推迟等所有操作都在 TaskOps 侧完成。

---

## 2. 连接参数

| 项 | 值 | 说明 |
| --- | --- | --- |
| 协议 | MQTT 3.1.1 / 5.0 | paho / mqtt.js 等任意客户端库 |
| TCP 地址 | `<broker-host>:1883` | 与 push-server 同机部署的 Mosquitto |
| WebSocket 地址 | `ws://<broker-host>:9001` | 浏览器 / 小程序等走 WS |
| 鉴权 | 内网匿名 | 与 Mosquitto 配置一致，**不要暴露公网** |
| Client ID | 自定义唯一 | 同一 ID 重复连接会顶掉旧连接 |
| Keep Alive | 60s | 建议值 |
| Clean Session | `true` | 离线消息靠第 6 节 REST 补拉 |
| QoS | `1` | 至少一次 |
| Retained | `false` | 服务端不留存 |

> `<broker-host>` 为运行 push-server / Mosquitto 的主机；对外访问时用反代域名或内网 IP。

---

## 3. 订阅主题

| 方向 | 主题 | 说明 |
| --- | --- | --- |
| 下行（收） | `{base}/#`（如 `taskops/todo/#`） | 订阅通配符；`base` 默认 `taskops/todo`（服务端 `PUSH_TOPIC` 可改） |

- 下行实际主题形如 `taskops/todo/7`，**最后一段即 `task_id`**（取整，取不到视为野消息丢弃）。
- 身份放主题里，正文保持纯文本可读，普通 MQTT 工具订阅 `taskops/todo/#` 肉眼即见人话。

---

## 4. 接收消息（下行）

payload 为纯文本，格式 `【待办提醒】{title}\n{message}`（无标题时只发正文）：

```
【待办提醒】交电费
主卧电表，户号123456
到期：2026-10-12
```

对应服务端任务字段：

| 字段 | 说明 |
| --- | --- |
| `title` | 待办标题（拼进 payload 首行） |
| `message` | 待办正文 + 到期日，多行纯文本 |
| 主题尾段 | `task_id`，仅用于展示 / 去重，无需回传 |

客户端处理规则：

- 收到即展示，不解析、不拼装。
- 同一 `task_id` 可能来多次：TaskOps 改动排期后的重推是**新提醒**（正常展示）；
  QoS 重传的极偶发重复可忽略，不做去重。
- TaskOps 删除待办 / 关闭提醒后，推送中心会取消该任务，客户端此后不再收到，无需处理。

---

## 5. 交互与展示

```
服务端到点 publish → 客户端收到下行 → 弹窗 / 通知 / 屏显纯文本
```

- 客户端不维护倒计时：排期只服务端算，到点自然会推。
- 客户端不发送任何回执，收到即展示，无需等待 / 重试。

---

## 6. 离线补拉（可选）

`retained=false` 不会补发离线消息。APP 类客户端重连成功后可选地拉一次当前待推送任务：

```
GET /api/tasks?status=pending&server_name=taskops
```

```json
{
  "total": 1,
  "tasks": [
    {"task_id": 7, "title": "交电费", "schedule_at": "2026-10-12T20:30:00+08:00", "status": "pending"}
  ]
}
```

- 把 `schedule_at` 已过（或未来 24h 内）的任务当错过 / 将到提醒展示。
- 只读接口，无需鉴权；桌面通知 / 纯展示类客户端可跳过本节。

---

## 7. 接入示例

### 7.1 Python（paho-mqtt）

```python
import paho.mqtt.client as mqtt

BROKER, PORT = "<broker-host>", 1883
BASE = "taskops/todo"

def on_connect(client, userdata, flags, rc, *args):
    client.subscribe(f"{BASE}/#", qos=1)

def on_message(client, userdata, msg):
    task_id = int(msg.topic.rsplit("/", 1)[-1])  # 主题尾段即 task_id
    text = msg.payload.decode("utf-8")
    print(f"[提醒 #{task_id}]\n{text}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)
client.loop_forever()
```

### 7.2 命令行（调试）

```bash
mosquitto_sub -h <broker-host> -t 'taskops/todo/#' -v
```

### 7.3 WebSocket（mqtt.js）

```js
import mqtt from 'mqtt'
const client = mqtt.connect('ws://<broker-host>:9001')
client.on('connect', () => client.subscribe('taskops/todo/#', { qos: 1 }))
client.on('message', (topic, payload) => {
  const taskId = Number(topic.split('/').pop())
  console.log(taskId, payload.toString())
})
```

---

## 8. 可靠性

- 重连：broker 断线自动重连（指数退避），重连后按第 6 节可选补拉。
- 服务端挂了：下行停；客户端只管展示，不做本地补偿，等服务端恢复（任务全在服务端 `tasks.json`，不丢）。
- 离线消息：`retained=false` 不补发，重连后靠 REST 补拉。

---

## 9. 不同形态建议

- **手机 APP**：常驻 MQTT 连接（心跳 60s）+ 系统通知 + 重连补拉。
- **桌面通知**：短连接或常驻均可，只展示；不做补拉。
- **ESP32 / 简单设备**：订阅通配、串口/屏显 payload。
- **浏览器 / 小程序**：走 WebSocket（9001）+ mqtt.js。

---

## 10. 安全

- 内网使用：broker 匿名（与 Mosquitto 配置一致），不要暴露公网。
- 本节接口均为只读订阅 / 查询，无上行写入，无需鉴权。
