#!/bin/bash
# ============================================================
# 服务管理脚本：mosquitto + uvicorn
#   两个进程任意一个退出，容器都会结束并由 restart 策略拉起。
#   docker stop / 更新重启时由 stop_service 一起停掉。
# ============================================================
set -euo pipefail

# 日志模块（构建时下载到 /opt/startup/log.sh）
. "$(dirname "${BASH_SOURCE[0]}")/log.sh"

SERVICE_LOG=${SERVICE_LOG:-/data/logs/service/service.log}
SERVICE_LOG_KEEP_DAYS=${SERVICE_LOG_KEEP_DAYS:-15}
SERVICE_PORT=${SERVICE_PORT:-${UVICORN_PORT:-8383}}
SERVICE_PASSWORD=${SERVICE_PASSWORD:-${APP_PASSWORD:-}}
mkdir -p "$(dirname "$SERVICE_LOG")"

rotate_service_log() {
    local archive
    [ -s "$SERVICE_LOG" ] || return 0

    archive="${SERVICE_LOG}-$(date -d yesterday '+%Y-%m-%d')"
    cp "$SERVICE_LOG" "$archive" && : > "$SERVICE_LOG"

    ls -1t -- "${SERVICE_LOG}"-* 2>/dev/null \
        | tail -n +"$(( SERVICE_LOG_KEEP_DAYS + 1 ))" \
        | xargs -r rm -f --
}

sleep_until_midnight() {
    local now target
    now=$(date +%s)
    target=$(date -d "tomorrow 00:00" +%s 2>/dev/null || echo 0)
    if [ "$target" -gt "$now" ]; then
        sleep "$(( target - now ))"
    else
        sleep 86400
    fi
}

log_rotate_loop() {
    while :; do
        sleep_until_midnight
        rotate_service_log
    done
}

print_start_info() {
    log -f success "服务已启动（PID ${svc_pid}）"
    [ -z "${SERVICE_PORT:-}" ] || log -f info "访问端口: ${SERVICE_PORT}"
    [ -z "${SERVICE_PASSWORD:-}" ] || log -f info "密码: ${SERVICE_PASSWORD}"
    log -f info "MQTT 端口: 1883（本机）/ ${MQTT_WS_PORT:-9001}（WebSocket）"
}

svc_pid=""
mqtt_pid=""
mqtt_watch_pid=""

start_service() {
    mosquitto -c /data/mosquitto.conf >> "$SERVICE_LOG" 2>&1 &
    mqtt_pid=$!

    uvicorn main:app \
        --app-dir /data \
        --host 0.0.0.0 \
        --port "${UVICORN_PORT:-8383}" \
        >> "$SERVICE_LOG" 2>&1 &
    svc_pid=$!

    # mosquitto 退出时结束 uvicorn，让 main.sh 跟着退出并由 Docker 重启容器
    (
        while kill -0 "$mqtt_pid" 2>/dev/null; do
            sleep 2
        done
        kill -TERM "$svc_pid" 2>/dev/null || true
    ) >> "$SERVICE_LOG" 2>&1 &
    mqtt_watch_pid=$!
}

stop_service() {
    [ -z "${mqtt_watch_pid:-}" ] || kill -TERM "$mqtt_watch_pid" 2>/dev/null || true
    [ -z "${svc_pid:-}" ] || kill -TERM "$svc_pid" 2>/dev/null || true
    [ -z "${mqtt_pid:-}" ] || kill -TERM "$mqtt_pid" 2>/dev/null || true
    [ -z "${mqtt_watch_pid:-}" ] || wait "$mqtt_watch_pid" 2>/dev/null || true
    [ -z "${svc_pid:-}" ] || wait "$svc_pid" 2>/dev/null || true
    [ -z "${mqtt_pid:-}" ] || wait "$mqtt_pid" 2>/dev/null || true
}

log_rotate_loop &
restart_requested=0
first_start=1
trap 'restart_requested=1; stop_service' USR1
trap 'stop_service; exit 143' TERM INT

while :; do
    restart_requested=0
    start_service
    if [ -z "$svc_pid" ]; then
        log -f error "start_service 没有设置 svc_pid"
        exit 1
    fi

    if [ "$first_start" -eq 1 ]; then
        print_start_info
        first_start=0
    else
        log info "服务已重启（PID ${svc_pid}）"
    fi

    code=0
    wait "$svc_pid" 2>/dev/null || code=$?

    if [ "$restart_requested" -eq 1 ]; then
        log -f success "重启服务（应用更新）"
        continue
    fi

    if [ "$code" -ne 0 ]; then
        log -f error "服务异常退出（exit ${code}），容器结束"
    else
        log info "服务已退出（exit 0），容器结束"
    fi
    exit "$code"
done
