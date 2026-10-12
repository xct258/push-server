#!/bin/bash

DRIVE_DIR=/rec
SRC_DIR=/usr/local/bin

MQTT_WS_PORT=${MQTT_WS_PORT:-9001}
UVICORN_PORT=${UVICORN_PORT:-8383}

# 每次启动都同步镜像中的应用代码，避免旧挂载卷继续运行旧版本。
cp "$SRC_DIR/main.py" "$DRIVE_DIR/"
mkdir -p "$DRIVE_DIR/static"
cp "$SRC_DIR/index.html" "$DRIVE_DIR/static/"
cp "$SRC_DIR/api-docs.html" "$DRIVE_DIR/static/"

# 配置 mosquitto（仅首次创建）
if [ ! -f $SRC_DIR/mosquitto.conf ]; then
    cat > $SRC_DIR/mosquitto.conf << CONF
listener 1883 127.0.0.1
allow_anonymous true
listener $MQTT_WS_PORT 0.0.0.0
protocol websockets
allow_anonymous true
CONF
fi

# 启动 mosquitto
mosquitto -c $SRC_DIR/mosquitto.conf -d

# 启动 uvicorn
nohup uvicorn main:app --app-dir "$DRIVE_DIR" --host 0.0.0.0 --port $UVICORN_PORT > /dev/null 2>&1 &

# 保持容器运行
tail -f /dev/null
