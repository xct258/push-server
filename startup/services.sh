#!/bin/bash
# ============================================================
# push-server 的服务声明
#   由 template/supervisor.sh 统一启动/停止/记录日志
# ============================================================

SERVICE_NAMES=(mqtt api)
SERVICE_STOP_TIMEOUT=([mqtt]=5 [api]=15)

start_mqtt() {
    run_service mqtt mosquitto -c /data/mosquitto.conf
}
stop_mqtt() { :; }

start_api() {
    run_service api uvicorn main:app \
        --app-dir /data \
        --host 0.0.0.0 \
        --port "${UVICORN_PORT:-8383}"
}
stop_api() { :; }
