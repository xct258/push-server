from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from contextlib import asynccontextmanager
import paho.mqtt.publish as publish
from paho.mqtt import client as mqtt_client
import asyncio
import logging
import json
import os
import re
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建任务库→起上行订阅→起反馈消费→起精确唤醒调度；关闭：全停。

    调试：订阅起不来（broker 没跑）服务照常起，REST 反馈仍可用，看启动日志确认。
    """
    global _scheduler_wake
    if not os.path.exists(TASKS_PATH):
        save_tasks(_empty_tasks())
    wake = asyncio.Event()
    _scheduler_wake = wake
    fb_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    subscriber = start_feedback_subscriber(loop, fb_queue)
    consumer = asyncio.create_task(feedback_consumer_loop(fb_queue))
    sched = asyncio.create_task(task_scheduler_loop(wake))
    try:
        yield
    finally:
        for t in (consumer, sched):
            t.cancel()
        try:
            await asyncio.gather(consumer, sched, return_exceptions=True)
        except Exception:
            pass
        if subscriber is not None:
            try:
                subscriber.loop_stop()
                subscriber.disconnect()
            except Exception:
                pass
        _scheduler_wake = None


app = FastAPI(title="MQTT 推送中心 API", description="MQTT 推送中心的 HTTP 接口，文档由 OpenAPI 自动生成，访问 /api/docs 查看在线版。", lifespan=lifespan)

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
                    tips = {"push_to_mqtt": "控制是否推送 MQTT，只能传入 true 或 false（不要加引号）", "server_name": "来源服务器名称", "mode": '可选 "append"（持续）或 "overwrite"（覆盖）', "msg_type": '固定为 "markdown"'}
                    field_hint = f"，字段 '{fname}'（{tips.get(fname, '值格式有误')}）" if fname in tips else f"，字段 '{fname}' 的值有误"
                else:
                    field_hint = ""
            except Exception:
                field_hint = ""
            msg = f"JSON 格式错误（字符 {pos}{field_hint}）"
        elif "push_to_mqtt" in field:
            msg = f"字段 'push_to_mqtt'（控制是否推送 MQTT）只允许传入 true 或 false，不要加引号或传其他值"
        elif "mode" in field:
            msg = '字段 "mode" 可选 "append"（持续记录）或 "overwrite"（覆盖记录）'
        elif "msg_type" in field:
            msg = '字段 "msg_type" 固定为 "markdown"'
        elif e["type"] == "missing":
            tips = {"push_to_mqtt": "（控制是否推送 MQTT）", "server_name": "（来源服务器名称）", "mode": '（可选 "append"/"overwrite"）'}
            msg = f"缺少必填字段 '{field}'{tips.get(field, '')}"
        errors.append({"field": field, "message": msg})
    return JSONResponse(status_code=422, content={"code": 422, "errors": errors})

@app.get("/", summary="前端页面")
async def serve_frontend():
    return FileResponse(os.path.join(BASE_DIR, "static/index.html"))

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

# ---- 定时任务（TaskOps 双向同步）配置，全走环境变量 ----
TASKOPS_BASE_URL = os.environ.get("TASKOPS_BASE_URL", "http://127.0.0.1:8481").rstrip("/")
TASKOPS_TOKEN = os.environ.get("TASKOPS_TOKEN", "")
PUSH_SERVER_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
PUSH_TOPIC_DEFAULT = os.environ.get("PUSH_TOPIC", "taskops/todo")
FEEDBACK_TOPIC = os.environ.get("FEEDBACK_TOPIC", "taskops/feedback")
TASK_RESYNC_INTERVAL = int(os.environ.get("TASK_RESYNC_INTERVAL", "300"))  # 兜底重载秒数
TASK_MIN_WAIT = 5  # 唤醒重算后最小休眠（防失败任务空转）
CALLBACK_MAX_RETRY = 10
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


def downlink_text(t: dict) -> str:
    """下行纯文本：【待办提醒】标题 + 正文；无标题只发正文。"""
    title = (t.get("title") or "").strip()
    message = (t.get("message") or "").strip()
    if title:
        return f"【待办提醒】{title}\n{message}" if message else f"【待办提醒】{title}"
    return message


def task_view(t: dict) -> dict:
    """接口返回的任务视图（存什么返什么，不加工）。"""
    return {
        "task_id": t.get("task_id"),
        "server_name": t.get("server_name"),
        "client_ref": t.get("client_ref"),
        "topic": t.get("topic"),
        "title": t.get("title"),
        "message": t.get("message"),
        "schedule_at": t.get("schedule_at"),
        "recurring": bool(t.get("recurring")),
        "status": t.get("status"),
        "callback": t.get("callback", "none"),
        "retry": int(t.get("retry", 0)),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
    }

class PushRequest(BaseModel):
    server_name: str = Field(description="来源服务器名称，记录保存到 push_records/{server_name}.json")
    topic: str = Field(description="MQTT 主题")
    message: str = Field(description="消息内容（markdown 格式）")
    push_to_mqtt: bool = Field(description="是否推送到 MQTT，只允许 true 或 false")
    msg_type: str = Field("markdown", description='消息类型，固定为 "markdown"')
    mode: str = Field("append", description='记录模式："append" 持续记录 或 "overwrite" 覆盖同名主题')

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
            raise ValueError('只能传入 "append"（持续记录）或 "overwrite"（覆盖记录）')
        return v

class RePushRequest(BaseModel):
    server_name: str = Field(description="来源服务器名称")
    id: int = Field(description="记录 ID（可从 /records 获取）")


class TaskCreate(BaseModel):
    server_name: str = Field(description="来源服务名，如 taskops")
    client_ref: str = Field(description="调用方唯一标识，如 todo-123；同 server 下重复推送=更新")
    topic: str = Field(default="", description="下行 MQTT 主题，空则用 PUSH_TOPIC 默认")
    title: str = Field(default="", description="任务标题")
    message: str = Field(description="消息内容（markdown）")
    schedule_at: datetime = Field(description="推送时刻，ISO，如 2026-10-12T20:30:00+08:00")
    recurring: bool = Field(default=False, description="是否循环任务（仅标记，下一期由调用方重建）")

    @field_validator("client_ref")
    @classmethod
    def check_ref(cls, v):
        if not str(v or "").strip():
            raise ValueError("client_ref 不能为空")
        return str(v).strip()


class TaskUpdate(BaseModel):
    topic: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    schedule_at: Optional[datetime] = Field(default=None)
    recurring: Optional[bool] = Field(default=None)


class FeedbackIn(BaseModel):
    action: str = Field(description='反馈动作：done（完成）、snooze（推迟）或 cancelled（取消）')
    snooze_minutes: int = Field(default=60, description="推迟分钟数，仅 snooze 有效")

    @field_validator("action")
    @classmethod
    def check_action(cls, v):
        if v not in ("done", "snooze", "cancelled"):
            raise ValueError('action 只能是 "done"、"snooze" 或 "cancelled"')
        return v

    @field_validator("snooze_minutes")
    @classmethod
    def check_minutes(cls, v):
        if int(v) < 1:
            raise ValueError("snooze_minutes 必须 >= 1")
        return int(v)

# ---------------------------------------------------------------------------
# 定时任务核心：下行推送 / 反馈处理 / 回调 / 精确唤醒调度 / 上行订阅
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


def _ref_to_todo_id(client_ref: str) -> Optional[int]:
    """client_ref 约定 todo-{id}，解析出 TaskOps 待办 id；不符合返回 None（跳过回调）。

    调试：回调没触发先看任务的 client_ref 长什么样：GET /api/tasks。
    """
    m = re.match(r"^todo-(\d+)$", str(client_ref or "").strip())
    return int(m.group(1)) if m else None


def _callback_http(method: str, url: str, body: Optional[dict]) -> dict:
    """同步回调（urllib，跑在 to_thread 里）；非 2xx 抛错触发重试。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if TASKOPS_TOKEN:
        headers["X-Callback-Token"] = TASKOPS_TOKEN
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as res:
        code, text = res.status, res.read().decode("utf-8") or "{}"
    if not (200 <= code < 300):
        raise RuntimeError(f"callback HTTP {code}: {text[:200]}")
    try:
        return json.loads(text)
    except Exception:
        return {}


def _mark_callback(task_id: int, callback: str, retry: int) -> None:
    """回写回调状态（save 自带版本号+1 与调度唤醒，无害）。"""
    data = load_tasks()
    t = find_task(data, task_id)
    if not t:
        return
    t["callback"] = callback
    t["retry"] = retry
    t["updated_at"] = _now_str()
    save_tasks(data)


async def do_callback(task_snapshot: dict, action: str, extra: Optional[dict] = None) -> None:
    """反馈回调 TaskOps：done→processed，snooze→snooze；失败退避重试，最多 10 次。

    调试：回调没到先看任务 callback/retry 列，再 curl 直调 TaskOps 接口确认通不通。
    """
    todo_id = _ref_to_todo_id(task_snapshot.get("client_ref"))
    if todo_id is None:
        logger.error(f"任务 #{task_snapshot.get('task_id')} client_ref 不符合 todo-{{id}}，跳过回调")
        _mark_callback(task_snapshot["task_id"], "skipped", 0)
        return
    if action == "done":
        method, url = "PUT", f"{TASKOPS_BASE_URL}/api/todos/{todo_id}/processed"
        body = None
    elif action == "cancelled":
        method, url = "PUT", f"{TASKOPS_BASE_URL}/api/todos/{todo_id}/processed"
        body = {"action": "cancelled", "note": "任务已取消"}
    else:
        method, url = "POST", f"{TASKOPS_BASE_URL}/api/todos/{todo_id}/snooze"
        body = {
            "note": f"客户端推迟{(extra or {}).get('snooze_minutes', 60)}分钟",
            "mqtt_at": task_snapshot.get("schedule_at"),
            "callback_ref": f"push-{task_snapshot['task_id']}-snooze-{task_snapshot.get('schedule_at')}",
        }
    for attempt in range(1, CALLBACK_MAX_RETRY + 1):
        current = find_task(load_tasks(), task_snapshot["task_id"])
        if action != "cancelled" and current and current.get("status") == "cancelled":
            return  # 调用方已取消，停止旧的完成/推迟回调。
        try:
            await asyncio.to_thread(_callback_http, method, url, body)
            logger.info(f"任务 #{task_snapshot.get('task_id')} 回调 TaskOps {action} 成功")
            _mark_callback(task_snapshot["task_id"], "done", attempt - 1)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            current = find_task(load_tasks(), task_snapshot["task_id"])
            if action != "cancelled" and current and current.get("status") == "cancelled":
                return
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                logger.info(f"任务 #{task_snapshot.get('task_id')} 对应待办已不存在，停止回调")
                _mark_callback(task_snapshot["task_id"], "skipped", 0)
                return
            logger.error(f"任务 #{task_snapshot.get('task_id')} 回调失败（第{attempt}次）：{e}")
            _mark_callback(task_snapshot["task_id"], "pending", attempt)
            await asyncio.sleep(min(30 * attempt, 300))
    _mark_callback(task_snapshot["task_id"], "failed", CALLBACK_MAX_RETRY)
    logger.error(f"任务 #{task_snapshot.get('task_id')} 回调达最大重试，需人工对账")


async def apply_feedback(task_id: int, action: str, snooze_minutes: int = 60) -> dict:
    """反馈统一入口（MQTT 上行与 REST 共用）：改状态 + 落盘 + 起回调任务。

    返回 {"code":200,...} 或 {"code":404/400,...}，调用方自行映射（REST 抛错 / MQTT 记日志）。
    调试：反馈没生效先 GET /api/tasks 看 status 列。
    """
    data = load_tasks()
    t = find_task(data, task_id)
    if not t:
        return {"code": 404, "detail": f"任务 #{task_id} 不存在"}
    if t.get("status") in TERMINAL_STATUS:
        return {"code": 200, "task_id": task_id, "status": t["status"], "detail": "任务已终态，忽略"}
    if action == "done":
        t["status"] = "done"
    elif action == "cancelled":
        t["status"] = "cancelled"
    elif action == "snooze":
        minutes = max(int(snooze_minutes or 60), 1)
        try:
            base = parse_schedule_at(t.get("schedule_at"))
        except ValueError:
            base = _now_shanghai()
        t["schedule_at"] = (base + timedelta(minutes=minutes)).isoformat()
        t["status"] = "pending"
    else:
        return {"code": 400, "detail": 'action 只能是 "done"、"snooze" 或 "cancelled"'}
    t["callback"] = "none"
    t["retry"] = 0
    t["updated_at"] = _now_str()
    snapshot = dict(t)
    save_tasks(data)  # 版本号+1 并唤醒调度（snooze 后重算 delay）
    asyncio.create_task(do_callback(snapshot, action, {"snooze_minutes": snooze_minutes}))
    logger.info(f"任务 #{task_id} 反馈 {action} 已受理，状态={t['status']}")
    return {"code": 200, "task_id": task_id, "status": t["status"], "schedule_at": t.get("schedule_at")}


async def task_scheduler_loop(wake: asyncio.Event) -> None:
    """精确唤醒调度：算最早任务 delay 睡到点；任务变更打断重算；兜底定时重载。

    顺序保证：先 clear 再 load（save 都是先落盘后置位，变更不会丢，见 save_tasks）。
    调试：推送延迟先看 delay；失败任务按 TASK_MIN_WAIT 节奏重试，broker 挂了会刷屏日志。
    """
    logger.info(
        f"定时任务调度启动：兜底{TASK_RESYNC_INTERVAL}s，下行默认[{PUSH_TOPIC_DEFAULT}]，上行[{FEEDBACK_TOPIC}]"
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


async def feedback_consumer_loop(queue: asyncio.Queue) -> None:
    """上行反馈消费：MQTT 线程只管投递队列，处理全在事件循环里（与 REST 同一入口）。"""
    while True:
        obj = await queue.get()
        try:
            task_id = int(obj.get("task_id"))
            action = str(obj.get("action"))
            minutes = int(obj.get("snooze_minutes", 60))
        except Exception:
            logger.error(f"上行反馈格式非法，已丢弃：{obj}")
            continue
        try:
            res = await apply_feedback(task_id, action, minutes)
            if res.get("code") != 200:
                logger.error(f"上行反馈处理失败：{res}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"上行反馈处理异常：{e}")


def start_feedback_subscriber(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """常驻订阅上行主题；连不上 broker 返回 None（服务照常起，REST 反馈仍可用）。

    调试：订阅没消息先旁路确认客户端发出去了：mosquitto_sub -t '<FEEDBACK_TOPIC>'。
    """
    try:
        try:
            c = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
        except Exception:
            c = mqtt_client.Client()  # paho 1.x 兼容
    except Exception as e:
        logger.error(f"MQTT 订阅客户端创建失败：{e}")
        return None

    def on_connect(client, userdata, flags, rc, *args):
        if rc == 0:
            client.subscribe(FEEDBACK_TOPIC, qos=1)
            logger.info(f"已订阅上行反馈主题 [{FEEDBACK_TOPIC}]")
        else:
            logger.error(f"MQTT 连接被拒 rc={rc}")

    def on_disconnect(client, userdata, flags, rc, *args):
        logger.error(f"MQTT 订阅断开 rc={rc}，自动重连中")

    def on_message(client, userdata, msg):
        try:
            obj = json.loads(msg.payload.decode("utf-8") or "{}")
        except Exception:
            logger.error(f"上行消息非 JSON，已丢弃：{msg.payload[:100]!r}")
            return
        if isinstance(obj, dict) and "task_id" in obj and "action" in obj:
            loop.call_soon_threadsafe(queue.put_nowait, obj)
        else:
            logger.error(f"上行反馈缺字段，已丢弃：{obj}")

    c.on_connect = on_connect
    c.on_disconnect = on_disconnect
    c.on_message = on_message
    try:
        c.reconnect_delay_set(min_delay=5, max_delay=60)
    except Exception:
        pass
    try:
        c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        logger.error(f"MQTT broker 连不上（{MQTT_BROKER}:{MQTT_PORT}）：{e}，订阅未启动")
        return None
    c.loop_start()
    return c


def _check_push_token(request: Request) -> None:
    """写接口鉴权：PUSH_SERVER_TOKEN 为空=不设防；否则必须带对 X-Push-Token。"""
    if PUSH_SERVER_TOKEN and request.headers.get("X-Push-Token") != PUSH_SERVER_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/api/push", summary="推送消息")
async def push_to_phone(request: PushRequest):
    """推送消息：保存记录，可选推送到 MQTT（push_to_mqtt=true 时）"""
    name = request.server_name
    records = load_server(name)

    if request.push_to_mqtt:
        try:
            publish.single(
                topic=request.topic,
                payload=request.message.encode('utf-8'),
                qos=1,
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
            )
            push_result = "success"
            logger.info(f"成功推送消息到主题 [{request.topic}]: {request.message}")
        except Exception as e:
            push_result = "failed"
            logger.error(f"推送失败: {str(e)}")
    else:
        push_result = "skipped"

    if request.mode == "overwrite":
        existing = None
        for r in records:
            if r["topic"] == request.topic:
                existing = r
                break
        if existing:
            record = {
                "id": existing["id"],
                "server_name": name,
                "topic": request.topic,
                "message": request.message,
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
                "topic": request.topic,
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
            "topic": request.topic,
            "message": request.message,
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
    return {"code": 200, "record_id": record["id"], "detail": detail}

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
        publish.single(
            topic=target["topic"],
            payload=target["message"].encode("utf-8"),
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
        if body.topic:
            t["topic"] = body.topic
        if body.title is not None:
            t["title"] = body.title
        if body.message is not None:
            t["message"] = body.message
        t["schedule_at"] = when.isoformat()
        t["recurring"] = bool(body.recurring)
        t["status"] = "pending"
        t["callback"] = "none"
        t["retry"] = 0
        t["updated_at"] = _now_str()
        action = "updated"
    else:
        data["seq"] = int(data.get("seq", 0)) + 1
        t = {
            "task_id": data["seq"],
            "server_name": body.server_name,
            "client_ref": body.client_ref,
            "topic": body.topic or PUSH_TOPIC_DEFAULT,
            "title": body.title or "",
            "message": body.message,
            "schedule_at": when.isoformat(),
            "recurring": bool(body.recurring),
            "status": "pending",
            "callback": "none",
            "retry": 0,
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
        t["callback"] = "none"
        t["retry"] = 0
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
        task_changed = False
        if t.get("status") not in TERMINAL_STATUS:
            t["status"] = "cancelled"
            n += 1
            task_changed = True
        if t.get("callback") in ("pending", "failed") or t.get("retry", 0):
            t["callback"] = "none"
            t["retry"] = 0
            task_changed = True
        if task_changed:
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


@app.post("/api/task/{task_id}/feedback", summary="任务反馈（REST 备用，与 MQTT 上行同一入口）")
async def feedback_task(task_id: int, body: FeedbackIn, request: Request):
    """MQTT 客户端发不了上行主题时走这里；处理逻辑与上行订阅完全一致。

    调试：done 后 TaskOps 没变看任务 callback 列；snooze 后看 schedule_at 是否顺延。
    """
    _check_push_token(request)
    res = await apply_feedback(task_id, body.action, body.snooze_minutes)
    if res.get("code") == 404:
        raise HTTPException(status_code=404, detail=res.get("detail"))
    if res.get("code") == 400:
        raise HTTPException(status_code=400, detail=res.get("detail"))
    return res


@app.get("/api/health", summary="健康检查")
async def health_check():
    """健康检查：返回 {"status":"running"}"""
    return {"status": "running"}

@app.get("/api/docs", include_in_schema=False)
async def api_docs_page():
    """在线 API 文档页面（自动生成，无需手工维护）"""
    return FileResponse(os.path.join(BASE_DIR, "static/api-docs.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8383)
