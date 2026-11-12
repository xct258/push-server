from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from contextlib import asynccontextmanager
import auth
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import asyncio
import logging
import json
import os
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建任务库→起精确唤醒调度→订阅客户端在线状态；关闭：全部停止。

    push-server 对业务消息仍是单向的；唯一额外订阅是客户端保活用的
    `$presence/clients/#`，只用于管理页展示，不参与业务下发。
    """
    global _scheduler_wake, _presence_tracker
    if not os.path.exists(TASKS_PATH):
        save_tasks(_empty_tasks())
    wake = asyncio.Event()
    _scheduler_wake = wake
    sched = asyncio.create_task(task_scheduler_loop(wake))
    _presence_tracker = PresenceTracker()
    _presence_tracker.start()
    try:
        yield
    finally:
        if _presence_tracker:
            _presence_tracker.stop()
        sched.cancel()
        try:
            await asyncio.gather(sched, return_exceptions=True)
        except Exception:
            pass
        _scheduler_wake = None
        _presence_tracker = None


app = FastAPI(title="MQTT 推送中心 API", description="MQTT 推送中心的 HTTP 接口，文档由 OpenAPI 自动生成，访问 /api/docs 查看在线版。", lifespan=lifespan)

# 统一登录（SSO）：会话由 auth-server 签发和校验，未登录接口返回 401。
app.add_middleware(auth.AuthMiddleware)
app.include_router(auth.router)

event_clients: set = set()

def broadcast(event: dict):
    for queue in list(event_clients):
        try:
            if queue.empty():
                queue.put_nowait(event)
        except Exception:
            event_clients.discard(queue)

@app.get("/api/events", summary="SSE 事件流")
async def event_stream(request: Request):
    """SSE 事件流：新消息推送后实时收到 {"type":"new","total":N}，15 秒心跳保活"""
    queue = asyncio.Queue()
    event_clients.add(queue)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            event_clients.discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = []
    for e in exc.errors():
        field = ".".join(str(x) for x in e["loc"][1:])
        msg = e["msg"]
        if e["type"] == "json_invalid":
            pos = e["loc"][-1] if len(e["loc"]) > 1 else 0
            try:
                raw = await request.body()
                text = raw.decode("utf-8", errors="replace")
                before = text[:pos]
                fields = re.findall(r'"([^"]+)"\s*:', before)
                if fields:
                    fname = fields[-1]
                    tips = {"push_to_mqtt": "控制是否推送 MQTT，只能传入 true 或 false（不要加引号）", "server_name": "来源服务器名称", "title": "消息标题（必填）", "status": '必填，只能是 "ok" / "warn" / "error" / "info"', "mode": '可选 "append"（持续）或 "overwrite"（覆盖）', "msg_type": '固定为 "markdown"'}
                    field_hint = f"，字段 '{fname}'（{tips.get(fname, '值格式有误')}）" if fname in tips else f"，字段 '{fname}' 的值有误"
                else:
                    field_hint = ""
            except Exception:
                field_hint = ""
            msg = f"JSON 格式错误（字符 {pos}{field_hint}）"
        elif "push_to_mqtt" in field:
            msg = f"字段 'push_to_mqtt'（控制是否推送 MQTT）只允许传入 true 或 false，不要加引号或传其他值"
        elif "status" in field:
            if e["type"] == "missing":
                msg = '缺少必填字段 "status"，只能是 "ok" / "warn" / "error" / "info"'
            else:
                msg = '字段 "status" 只能是 "ok" / "warn" / "error" / "info"'
        elif "title" in field:
            if e["type"] == "missing":
                msg = '缺少必填字段 "title"（消息标题）'
            else:
                msg = '字段 "title" 不能为空'
        elif "mode" in field:
            msg = '字段 "mode" 可选 "append"（持续记录）或 "overwrite"（覆盖同一 server_name + topic + title 的记录）'
        elif "msg_type" in field:
            msg = '字段 "msg_type" 固定为 "markdown"'
        elif e["type"] == "missing":
            tips = {"push_to_mqtt": "（控制是否推送 MQTT）", "server_name": "（来源服务器名称）", "title": "（消息标题）", "status": "（必填：ok / warn / error / info）", "mode": '（可选 "append"/"overwrite"）'}
            msg = f"缺少必填字段 '{field}'{tips.get(field, '')}"
        errors.append({"field": field, "message": msg})
    return JSONResponse(status_code=422, content={"code": 422, "errors": errors})

def web_file(name: str) -> str:
    """网页文件路径：容器里在 static/ 下（start.sh 铺设），开发布局与 main.py 同级；取存在的那个。

    调试：访问 / 报 500 就是两个位置都没有该文件。
    """
    in_static = os.path.join(BASE_DIR, "static", name)
    return in_static if os.path.exists(in_static) else os.path.join(BASE_DIR, name)


# 前端构建产物目录（Vue 工程），按优先级取第一个存在的：
#   1. 容器布局：/data/static（prepare.sh 把 dist 拷贝进来）
#   2. 开发布局：仓库内 前端/dist（本地 npm run build 后直接使用）
# 都没有时回退到与 main.py 同级的单文件 index.html（旧版）。
FRONTEND_DIST = None
for _cand in (
    os.path.join(BASE_DIR, "static"),
    os.path.join(BASE_DIR, "..", "前端", "dist"),
):
    if os.path.exists(os.path.join(_cand, "index.html")):
        FRONTEND_DIST = _cand
        break


@app.get("/", summary="前端页面")
async def serve_frontend():
    if FRONTEND_DIST:
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
    return FileResponse(web_file("index.html"))


# Vue 构建产物的静态资源（/assets/*），指向 dist/assets
if FRONTEND_DIST and os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="frontend-assets",
    )

# 站点图标（Vue 工程 public/ 下的顶层文件）
if FRONTEND_DIST and os.path.exists(os.path.join(FRONTEND_DIST, "favicon.svg")):

    @app.get("/favicon.svg", include_in_schema=False)
    async def serve_favicon():
        return FileResponse(os.path.join(FRONTEND_DIST, "favicon.svg"), media_type="image/svg+xml")

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

# 客户端在线状态：客户端连接后向 `$presence/clients/{client_id}` 发布 retained JSON，
# 断开时由 MQTT Will（LWT）改写为 online=false；每 30s 左右刷新一次 last_seen。
# `$` 开头的主题不会被 `#` 通配符匹配，因此不会干扰业务订阅。
PRESENCE_TOPIC = "$presence/clients"
PRESENCE_TTL_SECONDS = int(os.environ.get("PRESENCE_TTL_SECONDS", "180"))

# 下行消息分类：决定客户端卡片布局，也决定 push-server 拼哪一种 payload。
# 以后新增类型时在这里追加值，并补对应的 downlink 模板。
MESSAGE_CATEGORY_SERVICE = "service"
MESSAGE_CATEGORY_TODO = "todo"
MESSAGE_CATEGORIES = (MESSAGE_CATEGORY_SERVICE, MESSAGE_CATEGORY_TODO)


def normalize_message_category(value) -> str:
    category = str(value or "").strip().lower()
    if category not in MESSAGE_CATEGORIES:
        allowed = " / ".join(f'"{item}"' for item in MESSAGE_CATEGORIES)
        raise ValueError(f"仅支持 {allowed}")
    return category


def presence_suffix(client_id: str) -> str:
    """从 `{自定义前缀}_{固定随机后缀}` 中取最后一段作为设备标识。"""
    client_id = (client_id or "").strip()
    if "_" not in client_id:
        return client_id
    suffix = client_id.rsplit("_", 1)[-1]
    return suffix or client_id


def parse_presence_ts(value) -> float:
    """解析客户端 payload 里的 ISO 时间戳；解析失败返回 0（不参与新旧比较）。

    只比较客户端自己生成的两个时间戳（心跳 vs 迟到的 Will），不使用服务端时钟，
    因此客户端时钟有偏差也不影响「谁更新」的判断。
    """
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


class PresenceTracker:
    """后台订阅客户端在线状态，供管理页查询。"""

    def __init__(self, topic: str = PRESENCE_TOPIC, ttl_seconds: int = PRESENCE_TTL_SECONDS):
        self.topic = topic.rstrip("/")
        self.ttl_seconds = max(10, ttl_seconds)
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._client = None

    def start(self) -> None:
        try:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"push-server-presence-{os.getpid()}",
                    protocol=mqtt.MQTTv311,
                )
            except AttributeError:
                # paho-mqtt 1.x
                client = mqtt.Client(
                    client_id=f"push-server-presence-{os.getpid()}",
                    protocol=mqtt.MQTTv311,
                )
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_start()
            self._client = client
            logger.info("客户端在线状态订阅已启动：%s/#", self.topic)
        except Exception as exc:
            logger.error("客户端在线状态订阅启动失败：%s", exc)

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if client.is_connected():
                client.disconnect()
        except Exception:
            pass
        try:
            client.loop_stop()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        failure = getattr(reason_code, "is_failure", None)
        if failure is True or (failure is None and reason_code != 0):
            logger.warning("客户端在线状态订阅连接失败：%s", reason_code)
            return
        client.subscribe(f"{self.topic}/#", qos=1)

    def _on_disconnect(self, client, userdata, *args):
        logger.warning("客户端在线状态订阅连接断开，等待自动重连")

    def _on_message(self, client, userdata, msg):
        prefix = f"{self.topic}/"
        if not msg.topic.startswith(prefix):
            return
        topic_client_id = msg.topic[len(prefix):].strip("/")

        # 删除 retained 消息时 broker 会发一个空 payload，此时应移除客户端，
        # 而不是按默认值重新标记为在线。
        # 注意：切换自定义前缀时后端会主动清掉旧主题的 retained，这个空消息也会
        # 回到订阅端；只有当前记录仍指向同一个 topic 时才删除，否则会把刚更新的
        # 新主题记录一起删掉。
        if not msg.payload:
            self.remove_if_topic(presence_suffix(topic_client_id), msg.topic)
            return

        try:
            parsed = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            logger.warning("忽略无法解析的在线状态：%s", msg.topic)
            return
        if not isinstance(parsed, dict) or "online" not in parsed:
            logger.warning("忽略字段不完整的在线状态：%s", msg.topic)
            return

        client_id = str(parsed.get("client_id") or topic_client_id)
        if not client_id:
            return

        # 开发期不兼容旧格式：只接受带 suffix 字段的新 payload，
        # 或 client_id 为 `{前缀}_{后缀}` 的新格式。
        if "suffix" not in parsed and "_" not in client_id:
            logger.info("忽略旧版在线状态：%s", client_id)
            return

        self.ingest(
            client_id,
            suffix=str(parsed.get("suffix") or presence_suffix(client_id)),
            presence_topic=msg.topic,
            subscribe_topic=str(parsed.get("topic") or ""),
            online=bool(parsed.get("online")),
            platform=str(parsed.get("platform") or ""),
            name=str(parsed.get("name") or ""),
            version=str(parsed.get("version") or ""),
            client_ts=parse_presence_ts(parsed.get("ts")),
        )

    def remove(self, suffix: str) -> None:
        with self._lock:
            self._items.pop(suffix, None)

    def remove_if_topic(self, suffix: str, presence_topic: str) -> None:
        with self._lock:
            item = self._items.get(suffix)
            if item is not None and item.get("presence_topic") == presence_topic:
                self._items.pop(suffix, None)

    def delete(self, suffix: str) -> Optional[dict]:
        """删除离线记录，并清掉 broker 上的 retained 消息，避免服务重启后又回来。"""
        with self._lock:
            item = self._items.pop(suffix, None)
        if item is None:
            return None

        presence_topic = item.get("presence_topic")
        if presence_topic:
            self._clear_retained(presence_topic)
        return item

    def _clear_retained(self, topic: str) -> None:
        """删除 retained 消息（空 payload + retain=true）。"""
        client = self._client
        try:
            if client is not None and client.is_connected():
                client.publish(topic, payload=b"", qos=1, retain=True)
            else:
                publish.single(
                    topic,
                    payload=b"",
                    qos=1,
                    retain=True,
                    hostname=MQTT_BROKER,
                    port=MQTT_PORT,
                )
        except Exception as exc:
            logger.warning("清理客户端 retained 消息失败：%s", exc)

    def ingest(
        self,
        client_id: str,
        *,
        online: bool,
        suffix: str = "",
        presence_topic: str = "",
        subscribe_topic: str = "",
        platform: str = "",
        name: str = "",
        version: str = "",
        client_ts: float = 0.0,
    ) -> None:
        now = time.time()
        suffix = suffix or presence_suffix(client_id)
        old_topic = None
        with self._lock:
            previous = self._items.get(suffix, {})

            # MQTT Will 的 payload 是在连接建立时生成的，里面的 ts 是「连接开始时间」，
            # 不一定是断线时间。重连后旧连接的 Will 可能迟到，把刚上线的新状态覆盖成离线。
            # 这里用客户端自己的 ts 做新旧比较：比已记录状态更旧的「离线」消息直接丢弃。
            # 正常停止时客户端会重新生成 payload（ts=当前时间），不会被误丢。
            previous_client_ts = float(previous.get("client_ts", 0) or 0)
            if (not online and client_ts > 0 and previous_client_ts > 0
                    and client_ts <= previous_client_ts):
                logger.info(
                    "忽略迟到的离线状态（Will）：%s（ts=%s <= %s）",
                    client_id,
                    client_ts,
                    previous_client_ts,
                )
                return

            if (presence_topic and previous.get("presence_topic")
                    and previous["presence_topic"] != presence_topic):
                # 自定义前缀变了：清掉旧主题的 retained 在线状态
                old_topic = previous["presence_topic"]
            previous_online = bool(previous.get("online"))
            previous_last_seen = float(previous.get("last_seen_ts", 0))
            previous_fresh = bool(previous) and (now - previous_last_seen <= self.ttl_seconds)
            previous_effective_online = previous_online and previous_fresh

            status_changed_ts = previous.get("status_changed_ts")
            if status_changed_ts is None or previous_effective_online != online:
                status_changed_ts = now

            item = {
                "client_id": client_id,
                "suffix": suffix,
                "presence_topic": presence_topic or previous.get("presence_topic", ""),
                "topic": subscribe_topic or previous.get("topic", ""),
                "online": online,
                # 离线 Will 可能只带 online=false，保留上一次上报的展示信息
                "platform": platform or previous.get("platform", ""),
                "name": name or previous.get("name", ""),
                "version": version or previous.get("version", ""),
                "last_seen": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
                "last_seen_ts": now,
                "status_changed_ts": status_changed_ts,
                # 只用于丢弃迟到的 Will，不对外暴露
                "client_ts": max(client_ts, previous_client_ts),
            }
            self._items[suffix] = item

        if old_topic:
            self._clear_retained(old_topic)

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self._lock:
            items = [dict(item) for item in self._items.values()]

        for item in items:
            last_seen_ts = float(item.get("last_seen_ts", 0))
            stored_online = bool(item.get("online"))
            fresh = now - last_seen_ts <= self.ttl_seconds
            item["online"] = stored_online and fresh

            # 如果是 TTL 判定离线，状态变化时间按“最后一次心跳 + TTL”计算；
            # 否则使用真正收到上线/离线事件的时间。
            status_changed_ts = float(item.get("status_changed_ts", last_seen_ts))
            if stored_online and not fresh:
                status_changed_ts = last_seen_ts + self.ttl_seconds

            item["last_seen_epoch"] = int(last_seen_ts)
            item["status_changed_epoch"] = int(status_changed_ts)
            item["status_changed"] = datetime.fromtimestamp(
                status_changed_ts, ZoneInfo("Asia/Shanghai")
            ).strftime("%Y-%m-%d %H:%M:%S")
            item.pop("last_seen_ts", None)
            item.pop("status_changed_ts", None)
            item.pop("presence_topic", None)
            item.pop("client_ts", None)

        items.sort(key=lambda item: (not item["online"], item["suffix"].lower()))
        return items


_presence_tracker: Optional[PresenceTracker] = None

# ---- 定时任务（TaskOps 单向推送）配置，全走环境变量 ----
PUSH_SERVER_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
PUSH_TOPIC_DEFAULT = os.environ.get("PUSH_TOPIC", "taskops/todo")
TASK_RESYNC_INTERVAL = int(os.environ.get("TASK_RESYNC_INTERVAL", "300"))  # 兜底重载秒数
TASK_MIN_WAIT = 5  # 唤醒重算后最小休眠（防失败任务空转）
TERMINAL_STATUS = ("done", "cancelled")

DATA_DIR = os.path.join(BASE_DIR, "push_records")
MAX_RECORDS_PER_SERVER = 100

def server_path(name):
    return os.path.join(DATA_DIR, f"{name}.json")

def load_server(name):
    path = server_path(name)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_server(name, records):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(server_path(name), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def all_records_flat():
    if not os.path.isdir(DATA_DIR):
        return []
    result = []
    for fname in os.listdir(DATA_DIR):
        if fname.endswith(".json"):
            path = os.path.join(DATA_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    result.extend(json.load(f))
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# 定时任务存储（tasks.json，与 records 分开：records 按 server 封顶 100 条会被挤掉）
# 格式：{"seq": 自增task_id, "version": 变更版本号, "tasks": [ {...}, ... ]}
# 并发：单 worker，文件操作快；threading 锁保底（订阅线程只投递队列，不碰文件）。
# 调试：cat tasks.json | python3 -m json.tool；版本号每次写 +1，供调度循环用。
# ---------------------------------------------------------------------------
TASKS_PATH = os.path.join(BASE_DIR, "tasks.json")
tasks_lock = threading.Lock()

# 调度唤醒事件（lifespan 里创建；API 改完任务后置位，循环被打断重算）。
_scheduler_wake: "asyncio.Event | None" = None


def _now_shanghai() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _now_str() -> str:
    return _now_shanghai().strftime("%Y-%m-%d %H:%M:%S")


def _empty_tasks() -> dict:
    return {"seq": 0, "version": 0, "tasks": []}


def load_tasks() -> dict:
    """读任务库；文件不存在/损坏视为空（损坏记日志，不炸服务）。"""
    with tasks_lock:
        if not os.path.exists(TASKS_PATH):
            return _empty_tasks()
        try:
            with open(TASKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                return _empty_tasks()
            data.setdefault("seq", 0)
            data.setdefault("version", 0)
            return data
        except Exception as e:
            logger.error(f"tasks.json 读取失败，视为空：{e}")
            return _empty_tasks()


def save_tasks(data: dict) -> None:
    """写任务库（先写临时文件再替换，防写一半崩）：版本号 +1 并唤醒调度。

    约定：先落盘再置位，调度循环按“先 clear 再 load”顺序，保证变更不丢（见 task_scheduler_loop）。
    """
    with tasks_lock:
        data["version"] = int(data.get("version", 0)) + 1
        tmp = TASKS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, TASKS_PATH)
    _wake_scheduler()


def _wake_scheduler() -> None:
    """唤醒调度循环重算（服务未启动时是空操作）。"""
    if _scheduler_wake is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.call_soon_threadsafe(_scheduler_wake.set)


def parse_schedule_at(raw) -> datetime:
    """定时时刻统一解析：datetime 直接用，字符串走 ISO；无时区视为上海时间。

    失败抛 ValueError，调用方转 400。调试：客户端传的时间一律带 +08:00 最稳。
    """
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw or "").strip().replace("Z", "+00:00")
        if not text:
            raise ValueError("empty schedule_at")
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            raise ValueError(f"invalid schedule_at: {raw!r}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return dt.astimezone(ZoneInfo("Asia/Shanghai"))


def find_task(data: dict, task_id: int) -> Optional[dict]:
    for t in data["tasks"]:
        if t.get("task_id") == task_id:
            return t
    return None


def find_task_by_ref(data: dict, server_name: str, client_ref: str) -> Optional[dict]:
    for t in data["tasks"]:
        if t.get("server_name") == server_name and t.get("client_ref") == client_ref:
            return t
    return None


def downlink_topic(t: dict) -> str:
    """下行主题：base + /{task_id}，身份放主题里，payload 保持纯文本可读。

    客户端订阅 `base/#`，取主题最后一段即 task_id。调试：收不到先看主题拼对没。
    """
    base = (t.get("topic") or PUSH_TOPIC_DEFAULT).rstrip("/")
    return f"{base}/{t['task_id']}"


TODO_MARKER = "【待办提醒】"
SERVICE_MARKER = "【服务通知】"
SERVICE_FIELD = "【服务】"
STATUS_FIELD = "【状态】"


def _one_line(value) -> str:
    """头字段必须单行，防止调用方传进来的换行破坏协议。"""
    return " ".join(str(value or "").splitlines()).strip()


def infer_message_category(record: dict, default: str = MESSAGE_CATEGORY_SERVICE) -> str:
    """新记录直接读 category；旧记录按 payload 是否含待办前缀推断。"""
    category = str(record.get("category") or "").strip().lower()
    if category in MESSAGE_CATEGORIES:
        return category
    message = str(record.get("message") or "")
    if message.startswith(TODO_MARKER):
        return MESSAGE_CATEGORY_TODO
    return default


def build_downlink_text(record: dict, default_category: str = MESSAGE_CATEGORY_SERVICE) -> str:
    """按 category 生成下行纯文本。

    - todo：保持原格式 `【待办提醒】{title}\\n{message}`；
    - service：`【服务通知】{server_name}` + `【服务】{title}` + `【状态】{status}` + 空行 + 正文。
    """
    category = infer_message_category(record, default=default_category)
    title = _one_line(record.get("title"))
    message = str(record.get("message") or "").strip("\n")

    if category == MESSAGE_CATEGORY_TODO:
        # 兼容调用方已经把 marker 拼进 message 的情况，避免双前缀
        if message.startswith(TODO_MARKER):
            return message
        if title:
            return f"{TODO_MARKER}{title}\n{message}" if message else f"{TODO_MARKER}{title}"
        return message

    # service
    if message.startswith(SERVICE_MARKER):
        return message
    lines = [f"{SERVICE_MARKER}{_one_line(record.get('server_name'))}"]
    if title:
        lines.append(f"{SERVICE_FIELD}{title}")
    status = _one_line(record.get("status"))
    if status:
        lines.append(f"{STATUS_FIELD}{status}")
    return "\n".join(lines) + "\n\n" + message


def downlink_text(t: dict) -> str:
    """定时任务按分类拼下行文本；旧任务没有 category 时按待办处理。

    任务里的 status 是 pending/sent/cancelled 的任务状态，不是消息状态，
    不能写进服务通知的 `【状态】` 头。
    """
    record = dict(t)
    record.pop("status", None)
    return build_downlink_text(record, default_category=MESSAGE_CATEGORY_TODO)


def task_view(t: dict) -> dict:
    """接口返回的任务视图（存什么返什么，不加工）。"""
    return {
        "task_id": t.get("task_id"),
        "server_name": t.get("server_name"),
        "category": t.get("category") or MESSAGE_CATEGORY_TODO,
        "client_ref": t.get("client_ref"),
        "topic": t.get("topic"),
        "title": t.get("title"),
        "message": t.get("message"),
        "schedule_at": t.get("schedule_at"),
        "recurring": bool(t.get("recurring")),
        "status": t.get("status"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
    }

class PushRequest(BaseModel):
    server_name: str = Field(description="来源服务器名称，记录保存到 push_records/{server_name}.json")
    category: str = Field(description='消息分类（必填）："service" 服务通知 / "todo" 待办提醒')
    topic: str = Field(description="MQTT 主题")
    title: str = Field(description="消息标题（必填）")
    message: str = Field(description="消息内容（markdown 格式）")
    status: str = Field(description='消息状态（必填）："ok" / "warn" / "error" / "info"')
    push_to_mqtt: bool = Field(description="是否推送到 MQTT，只允许 true 或 false")
    msg_type: str = Field("markdown", description='消息类型，固定为 "markdown"')
    mode: str = Field("append", description='记录模式："append" 持续记录 或 "overwrite" 覆盖同一 server_name + topic + title 的记录')

    @field_validator("category")
    @classmethod
    def check_category(cls, v):
        return normalize_message_category(v)

    @field_validator("title")
    @classmethod
    def check_title(cls, v):
        value = str(v or "").strip()
        if not value:
            raise ValueError("标题不能为空")
        return value

    @field_validator("status")
    @classmethod
    def check_status(cls, v):
        value = str(v or "").strip().lower()
        if value not in ("ok", "warn", "error", "info"):
            raise ValueError('仅支持 "ok" / "warn" / "error" / "info"')
        return value

    @field_validator("push_to_mqtt", mode="before")
    @classmethod
    def check_bool_only(cls, v):
        if not isinstance(v, bool):
            raise ValueError("只允许 true 或 false，不要加引号或传其他值")
        return v

    @field_validator("msg_type")
    @classmethod
    def check_msg_type(cls, v):
        if v != "markdown":
            raise ValueError('仅支持 "markdown" 类型')
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v):
        if v not in ("append", "overwrite"):
            raise ValueError('只能传入 "append"（持续记录）或 "overwrite"（覆盖同一 server_name + topic + title 的记录）')
        return v

class RePushRequest(BaseModel):
    server_name: str = Field(description="来源服务器名称")
    id: int = Field(description="记录 ID（可从 /records 获取）")


class TaskCreate(BaseModel):
    server_name: str = Field(description="来源服务名，如 taskops")
    category: str = Field(description='消息分类（必填）："service" 服务通知 / "todo" 待办提醒')
    client_ref: str = Field(description="调用方唯一标识，如 todo-123；同 server 下重复推送=更新")
    topic: str = Field(default="", description="下行 MQTT 主题，空则用 PUSH_TOPIC 默认")
    title: str = Field(default="", description="任务标题")
    message: str = Field(description="消息内容（markdown）")
    schedule_at: datetime = Field(description="推送时刻，ISO，如 2026-10-12T20:30:00+08:00")
    recurring: bool = Field(default=False, description="是否循环任务（仅标记，下一期由调用方重建）")

    @field_validator("category")
    @classmethod
    def check_category(cls, v):
        return normalize_message_category(v)

    @field_validator("client_ref")
    @classmethod
    def check_ref(cls, v):
        if not str(v or "").strip():
            raise ValueError("client_ref 不能为空")
        return str(v).strip()


class TaskUpdate(BaseModel):
    category: Optional[str] = Field(default=None)
    topic: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    schedule_at: Optional[datetime] = Field(default=None)
    recurring: Optional[bool] = Field(default=None)

    @field_validator("category")
    @classmethod
    def check_category(cls, v):
        if v is None:
            return None
        return normalize_message_category(v)


# ---------------------------------------------------------------------------
# 定时任务核心：下行推送 / 精确唤醒调度（纯单向，无反馈 / 无回调）
# ---------------------------------------------------------------------------

async def publish_task_downlink(t: dict) -> bool:
    """到点 publish 下行纯文本到 {base}/{task_id}；成功 True，异常记日志 False（保持 pending 下轮再推）。

    调试：客户端没收到先旁路监听确认：mosquitto_sub -h 127.0.0.1 -t '<base>/#'。
    """
    topic = downlink_topic(t)
    try:
        await asyncio.to_thread(
            publish.single,
            topic=topic,
            payload=downlink_text(t).encode("utf-8"),
            qos=1,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
        )
    except Exception as e:
        logger.error(f"任务 #{t.get('task_id')} 下行失败（{topic}）：{e}")
        return False
    logger.info(f"任务 #{t.get('task_id')} 已推送至 [{topic}]")
    return True


async def task_scheduler_loop(wake: asyncio.Event) -> None:
    """精确唤醒调度：算最早任务 delay 睡到点；任务变更打断重算；兜底定时重载。

    顺序保证：先 clear 再 load（save 都是先落盘后置位，变更不会丢，见 save_tasks）。
    调试：推送延迟先看 delay；失败任务按 TASK_MIN_WAIT 节奏重试，broker 挂了会刷屏日志。
    """
    logger.info(
        f"定时任务调度启动：兜底{TASK_RESYNC_INTERVAL}s，下行默认[{PUSH_TOPIC_DEFAULT}]"
    )
    while True:
        wake.clear()
        try:
            data = load_tasks()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"任务库加载失败，本轮跳过：{e}")
            await asyncio.sleep(TASK_MIN_WAIT)
            continue
        now = _now_shanghai()
        due, earliest = [], None
        for t in data["tasks"]:
            if t.get("status") != "pending":
                continue
            try:
                when = parse_schedule_at(t.get("schedule_at"))
            except ValueError:
                logger.error(f"任务 #{t.get('task_id')} schedule_at 非法，跳过")
                continue
            if when <= now:
                due.append(t)
            elif earliest is None or when < earliest:
                earliest = when
        changed = False
        for t in due:
            if await publish_task_downlink(t):
                t["status"] = "sent"
                t["updated_at"] = _now_str()
                changed = True
        if changed:
            save_tasks(data)
            continue  # 落盘后直接重算（save 已唤醒，下一轮顶部 clear 掉）
        timeout = float(TASK_RESYNC_INTERVAL) if earliest is None else min(
            max((earliest - _now_shanghai()).total_seconds(), float(TASK_MIN_WAIT)),
            float(TASK_RESYNC_INTERVAL),
        )
        try:
            await asyncio.wait_for(wake.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass


def _check_push_token(request: Request) -> None:
    """写接口鉴权：PUSH_SERVER_TOKEN 为空=不设防；否则必须带对 X-Push-Token。"""
    if PUSH_SERVER_TOKEN and request.headers.get("X-Push-Token") != PUSH_SERVER_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/api/push", summary="推送消息")
async def push_to_phone(request: PushRequest):
    """推送消息：保存记录，可选推送到 MQTT（push_to_mqtt=true 时）"""
    name = request.server_name
    records = load_server(name)

    downlink = build_downlink_text({
        "category": request.category,
        "server_name": name,
        "title": request.title,
        "message": request.message,
        "status": request.status,
    })

    if request.push_to_mqtt:
        try:
            publish.single(
                topic=request.topic,
                payload=downlink.encode('utf-8'),
                qos=1,
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
            )
            push_result = "success"
            logger.info(f"成功推送消息到主题 [{request.topic}]（{request.category}）")
        except Exception as e:
            push_result = "failed"
            logger.error(f"推送失败: {str(e)}")
    else:
        push_result = "skipped"

    if request.mode == "overwrite":
        existing = None
        for r in records:
            if (r["topic"] == request.topic
                    and (r.get("title") or "") == request.title
                    and infer_message_category(r) == request.category):
                existing = r
                break
        if existing:
            record = {
                "id": existing["id"],
                "server_name": name,
                "category": request.category,
                "topic": request.topic,
                "title": request.title,
                "message": request.message,
                "status": request.status,
                "push_to_mqtt": request.push_to_mqtt,
                "push_result": push_result,
                "msg_type": request.msg_type,
                "mode": "overwrite",
                "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
            }
            records[records.index(existing)] = record
        else:
            record = {
                "id": len(records) + 1,
                "server_name": name,
                "category": request.category,
                "topic": request.topic,
                "title": request.title,
                "message": request.message,
                "push_to_mqtt": request.push_to_mqtt,
                "push_result": push_result,
                "msg_type": request.msg_type,
                "mode": "overwrite",
                "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
            }
            records.append(record)
    else:
        record = {
            "id": len(records) + 1,
            "server_name": name,
            "category": request.category,
            "topic": request.topic,
            "title": request.title,
            "message": request.message,
            "status": request.status,
            "push_to_mqtt": request.push_to_mqtt,
            "push_result": push_result,
            "msg_type": request.msg_type,
            "mode": "append",
            "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        }
        records.append(record)

        while len(records) > MAX_RECORDS_PER_SERVER:
            records.pop(0)

    save_server(name, records)
    broadcast({"type": "new", "total": len(all_records_flat())})

    detail = "消息已投递至 MQTT" if request.push_to_mqtt else "消息已保存，未推送至 MQTT"
    return {"code": 200, "record_id": record["id"], "status": request.status, "detail": detail}

@app.post("/api/repush", summary="重新推送")
async def repush(request: RePushRequest):
    """重新推送：将已保存的记录重新推送到 MQTT，成功后记录状态更新为 success"""
    records = load_server(request.server_name)
    target = None
    for r in records:
        if r["id"] == request.id:
            target = r
            break
    if not target:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        downlink = build_downlink_text(target)
        publish.single(
            topic=target["topic"],
            payload=downlink.encode("utf-8"),
            qos=1,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
        )
        target["push_result"] = "success"
        save_server(request.server_name, records)
        logger.info(f"重新推送消息到主题 [{target['topic']}]: {target['message']}")
        return {"code": 200, "detail": "消息已重新推送"}
    except Exception as e:
        logger.error(f"重新推送失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新推送失败: {str(e)}")

@app.get("/records", summary="查询推送记录")
async def get_history(
    server_name: Optional[str] = Query(None, description="按服务器名称精确筛选"),
    topic: Optional[str] = Query(None, description="按主题模糊筛选（不区分大小写）"),
    limit: int = Query(100, ge=1, le=500, description="返回条数，最大 500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页"),
):
    """查询推送记录：支持按服务器/主题筛选与分页，按创建时间倒序"""
    records = all_records_flat()

    if server_name:
        records = [r for r in records if r.get("server_name") == server_name]
    if topic:
        records = [r for r in records if topic.lower() in r.get("topic", "").lower()]

    records.sort(key=lambda r: r["created_at"], reverse=True)
    total = len(records)
    page = records[offset:offset + limit]

    return {"total": total, "offset": offset, "limit": limit, "records": page}

@app.post("/api/task", summary="创建/更新定时任务")
async def upsert_task(body: TaskCreate, request: Request):
    """按 (server_name, client_ref) 幂等：存在则更新，不存在则创建；一律回到 pending 待推。

    调试：重复建任务先查 client_ref 是否变了；时间不触发看 schedule_at 是否带时区。
    """
    _check_push_token(request)
    try:
        when = parse_schedule_at(body.schedule_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule_at format")
    data = load_tasks()
    t = find_task_by_ref(data, body.server_name, body.client_ref)
    if t:
        t["category"] = body.category
        if body.topic:
            t["topic"] = body.topic
        if body.title is not None:
            t["title"] = body.title
        if body.message is not None:
            t["message"] = body.message
        t["schedule_at"] = when.isoformat()
        t["recurring"] = bool(body.recurring)
        t["status"] = "pending"
        t["updated_at"] = _now_str()
        action = "updated"
    else:
        data["seq"] = int(data.get("seq", 0)) + 1
        t = {
            "task_id": data["seq"],
            "server_name": body.server_name,
            "category": body.category,
            "client_ref": body.client_ref,
            "topic": body.topic or PUSH_TOPIC_DEFAULT,
            "title": body.title or "",
            "message": body.message,
            "schedule_at": when.isoformat(),
            "recurring": bool(body.recurring),
            "status": "pending",
            "created_at": _now_str(),
            "updated_at": _now_str(),
        }
        data["tasks"].append(t)
        action = "created"
    save_tasks(data)
    logger.info(f"定时任务 #{t['task_id']} {action}：{body.server_name}/{body.client_ref} @ {t['schedule_at']}")
    return {"code": 200, "task_id": t["task_id"], "action": action, "task": task_view(t)}


@app.put("/api/task/{task_id}", summary="更新定时任务")
async def update_task(task_id: int, body: TaskUpdate, request: Request):
    """按 id 更新；终态任务被改视为重新排期（回 pending）。

    调试：改完没触发看 status 列是否真回 pending。
    """
    _check_push_token(request)
    data = load_tasks()
    t = find_task(data, task_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"任务 #{task_id} 不存在")
    if body.category is not None:
        t["category"] = body.category
    if body.topic:
        t["topic"] = body.topic
    if body.title is not None:
        t["title"] = body.title
    if body.message is not None:
        t["message"] = body.message
    if body.schedule_at is not None:
        try:
            t["schedule_at"] = parse_schedule_at(body.schedule_at).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid schedule_at format")
    if body.recurring is not None:
        t["recurring"] = bool(body.recurring)
    if t.get("status") in TERMINAL_STATUS:
        t["status"] = "pending"
    t["updated_at"] = _now_str()
    save_tasks(data)
    return {"code": 200, "task_id": task_id, "task": task_view(t)}


@app.delete("/api/task/ref/{client_ref}", summary="按调用方标识取消任务")
async def cancel_task_by_ref(
    client_ref: str,
    request: Request,
    server_name: Optional[str] = Query(None, description="同 client_ref 多服务复用时限定服务"),
):
    """调用方同步取消：非终态任务标 cancelled，不反向回调调用方。

    调试：取消完还推，先查 status 列，再查是不是 client_ref 写错了。
    """
    _check_push_token(request)
    data = load_tasks()
    n = 0
    changed = False
    for t in data["tasks"]:
        if t.get("client_ref") != client_ref:
            continue
        if server_name and t.get("server_name") != server_name:
            continue
        if t.get("status") not in TERMINAL_STATUS:
            t["status"] = "cancelled"
            n += 1
            t["updated_at"] = _now_str()
            changed = True
    if changed:
        save_tasks(data)
    return {"code": 200, "cancelled": n}


@app.get("/api/tasks", summary="查询定时任务")
async def list_tasks(
    server_name: Optional[str] = Query(None, description="按服务筛选"),
    status: Optional[str] = Query(None, description="按状态筛选：pending/sent/done/cancelled"),
    limit: int = Query(100, ge=1, le=500, description="返回条数，最大 500"),
):
    """查任务（对账/调试）：默认倒序，status 拼错会返回空列表，先对状态机。"""
    data = load_tasks()
    tasks = data["tasks"]
    if server_name:
        tasks = [t for t in tasks if t.get("server_name") == server_name]
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    tasks = sorted(tasks, key=lambda t: t.get("task_id", 0), reverse=True)[:limit]
    return {"total": len(tasks), "tasks": [task_view(t) for t in tasks]}


@app.get("/api/clients", summary="查询已连接的客户端")
async def list_clients(online: Optional[bool] = Query(None, description="只看在线 / 离线客户端")):
    """客户端在线状态：客户端通过 `$presence/clients/{client_id}` 上报，后端订阅汇总。

    返回的 `online` 同时参考客户端最后一次心跳和服务端 TTL，避免客户端异常退出后
    一直显示在线；离线记录会保留在内存中，直到服务重启。
    """
    tracker = _presence_tracker
    clients = tracker.snapshot() if tracker else []
    online_count = sum(1 for c in clients if c["online"])
    if online is not None:
        clients = [c for c in clients if c["online"] is online]
    return {
        "total": len(clients),
        "online": online_count,
        "clients": clients,
        "topic": PRESENCE_TOPIC,
        "ttl_seconds": PRESENCE_TTL_SECONDS,
    }


@app.delete("/api/clients/{suffix}", summary="删除离线客户端记录")
async def delete_client(suffix: str):
    """删除离线客户端记录：只清当前展示，不拉黑设备；设备下次上线会重新出现。"""
    tracker = _presence_tracker
    item = next((c for c in tracker.snapshot() if c["suffix"] == suffix), None) if tracker else None
    if item is None:
        raise HTTPException(status_code=404, detail="客户端不存在")
    if item["online"]:
        raise HTTPException(status_code=409, detail="在线客户端不能删除，请等待其离线")

    tracker.delete(suffix)
    logger.info("已删除离线客户端：%s（%s）", item.get("client_id"), suffix)
    return {"code": 200, "deleted": suffix}


@app.get("/api/health", summary="健康检查")
async def health_check():
    """健康检查：返回 {"status":"running"}"""
    return {"status": "running"}

@app.get("/api/docs", include_in_schema=False)
async def api_docs_page():
    """在线 API 文档页面（自动生成，无需手工维护）"""
    return FileResponse(web_file("api-docs.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8383)
