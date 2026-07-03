#!/bin/bash

DRIVE_DIR=/rec
SRC_DIR=/usr/local/bin
MQTT_WS_PORT=${MQTT_WS_PORT:-9001}
UVICORN_PORT=${UVICORN_PORT:-8383}

# 如果挂载卷为空，从镜像复制应用文件
if [ ! -f "$DRIVE_DIR/main.py" ]; then
    cp "$SRC_DIR/main.py" "$DRIVE_DIR/"
fi
mkdir -p "$DRIVE_DIR/static"
if [ ! -f "$DRIVE_DIR/static/index.html" ]; then
    cp "$SRC_DIR/index.html" "$DRIVE_DIR/static/"
fi

# 配置 mosquitto（仅首次创建）
if [ ! -f /etc/mosquitto/mosquitto.conf ]; then
    cat > /etc/mosquitto/mosquitto.conf << CONF
listener 1883 127.0.0.1
allow_anonymous true
listener $MQTT_WS_PORT 0.0.0.0
protocol websockets
allow_anonymous true
CONF
fi

# 启动 mosquitto
mosquitto -c /etc/mosquitto/mosquitto.conf -d

# 启动 uvicorn
nohup uvicorn /rec/main:app --host 0.0.0.0 --port $UVICORN_PORT > /dev/null 2>&1 &

# 保持容器运行
tail -f /dev/null
