#!/bin/bash
# ============================================================
# 启动前的准备：每次启动容器都执行（docker restart 也会执行）
#   - 把镜像里的应用代码/前端产物同步到数据目录 /data
#   - 生成 mosquitto 配置（端口来自环境变量）
#   - 保留 /data/push_records、/data/tasks.json 等运行数据
# ============================================================
set -euo pipefail

# 日志模块（构建时下载到 /opt/startup/log.sh）
. "$(dirname "${BASH_SOURCE[0]}")/log.sh"

SRC_DIR=/opt/push-server
DATA_DIR=/data
MQTT_WS_PORT=${MQTT_WS_PORT:-9001}

mkdir -p "$DATA_DIR/push_records"

# 应用代码每次启动都同步，避免旧挂载卷继续运行旧版本
cp "$SRC_DIR/main.py" "$DATA_DIR/"
cp "$SRC_DIR/auth.py" "$DATA_DIR/"
cp "$SRC_DIR/api-docs.html" "$DATA_DIR/"

# 前端是构建产物（文件名带哈希，每次构建都变）：清空重铺
rm -rf "$DATA_DIR/static"
mkdir -p "$DATA_DIR/static"
cp -r "$SRC_DIR/frontend/." "$DATA_DIR/static/"

# mosquitto 配置每次按环境变量重写，改端口后重启即生效
cat > "$DATA_DIR/mosquitto.conf" << CONF
listener 1883 127.0.0.1
allow_anonymous true
listener ${MQTT_WS_PORT} 0.0.0.0
protocol websockets
allow_anonymous true
CONF

log info "应用文件已同步到 ${DATA_DIR}；MQTT WS 端口 ${MQTT_WS_PORT}"
