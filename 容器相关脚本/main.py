from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator
import paho.mqtt.publish as publish
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

app = FastAPI(title="MQTT 推送中心 API")

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

@app.get("/")
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
    server_name: str
    topic: str
    message: str
    push_to_mqtt: bool
    msg_type: str = "markdown"
    mode: str = "append"

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
    server_name: str
    id: int

@app.post("/api/push")
async def push_to_phone(request: PushRequest):
    name = request.server_name
    records = load_server(name)

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
            "msg_type": request.msg_type,
            "mode": "append",
            "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        }
        records.append(record)

        while len(records) > MAX_RECORDS_PER_SERVER:
            records.pop(0)

    save_server(name, records)

    if request.push_to_mqtt:
        try:
            publish.single(
                topic=request.topic,
                payload=request.message.encode('utf-8'),
                qos=1,
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
            )
            logger.info(f"成功推送消息到主题 [{request.topic}]: {request.message}")
        except Exception as e:
            logger.error(f"推送失败: {str(e)}")

    detail = "消息已投递至 MQTT" if request.push_to_mqtt else "消息已保存，未推送至 MQTT"
    return {"code": 200, "record_id": record["id"], "detail": detail}

@app.post("/api/repush")
async def repush(request: RePushRequest):
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
        logger.info(f"重新推送消息到主题 [{target['topic']}]: {target['message']}")
        return {"code": 200, "detail": "消息已重新推送"}
    except Exception as e:
        logger.error(f"重新推送失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新推送失败: {str(e)}")

@app.get("/records")
async def get_history(
    server_name: Optional[str] = Query(None, description="按服务器筛选"),
    topic: Optional[str] = Query(None, description="按主题筛选"),
    limit: int = Query(100, ge=1, le=500, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    records = all_records_flat()

    if server_name:
        records = [r for r in records if r.get("server_name") == server_name]
    if topic:
        records = [r for r in records if topic.lower() in r.get("topic", "").lower()]

    records.sort(key=lambda r: r["created_at"], reverse=True)
    total = len(records)
    page = records[offset:offset + limit]

    return {"total": total, "offset": offset, "limit": limit, "records": page}

@app.get("/api/health")
async def health_check():
    return {"status": "running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8383)
