#!/bin/bash

DRIVE_DIR=/rec
SRC_DIR=/usr/local/bin

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
    cat > $SRC_DIR/mosquitto.conf << CONF
listener 1883 127.0.0.1
allow_anonymous true
listener 9001 0.0.0.0
protocol websockets
allow_anonymous true
CONF
fi

# 启动 mosquitto
mosquitto -c $SRC_DIR/mosquitto.conf -d

# 启动 uvicorn
nohup uvicorn main:app --app-dir "$DRIVE_DIR" --host 0.0.0.0 --port 8383 > /dev/null 2>&1 &

# 保持容器运行
tail -f /dev/null
