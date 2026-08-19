from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
import paho.mqtt.publish as publish
import asyncio
import logging
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MQTT 推送中心 API", description="MQTT 推送中心的 HTTP 接口，文档由 OpenAPI 自动生成，访问 /api/docs 查看在线版。")

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
