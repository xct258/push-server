#!/bin/bash

# ============================================================
# 容器构建初始化脚本
# ============================================================

# GitHub 仓库地址（在构建文件指定即可）
GITHUB_USER=${GITHUB_USER}
GITHUB_REPO=${GITHUB_REPO}

# --------------------------------------------------
# 确保 apt 缓存存在，安装运行依赖工具
# --------------------------------------------------
apt-get install -y --no-install-recommends curl jq wget tar xz-utils

# --------------------------------------------------
# 从 GitHub API 获取 7z 最新版本信息
# 仓库：ip7z/7zip
# 获取 x86_64 和 ARM64 两种架构的下载链接
# --------------------------------------------------
echo "[7z] 正在获取最新版本信息..."
latest_release_7z=$(curl -s --retry 3 --retry-delay 5 https://api.github.com/repos/ip7z/7zip/releases/latest)
version_7z=$(echo "$latest_release_7z" | jq -r '.tag_name')
# x86_64 架构匹配 linux-x64.tar.xz
latest_7z_x64_url=$(echo "$latest_release_7z" | jq -r '.assets[] | select(.name | test("linux-x64.tar.xz")) | .browser_download_url')
# ARM64 架构匹配 linux-arm64.tar.xz
latest_7z_arm64_url=$(echo "$latest_release_7z" | jq -r '.assets[] | select(.name | test("linux-arm64.tar.xz")) | .browser_download_url')
echo "[7z] 最新版本: ${version_7z}"

# --------------------------------------------------
# 检测当前 CPU 架构，下载对应的二进制文件
# uname -m 返回值：
#   x86_64  - Intel/AMD 64位处理器
#   aarch64 - ARM 64位处理器（如树莓派、AWS Graviton）
# --------------------------------------------------
arch=$(uname -m)
echo "当前系统架构: ${arch}"

if [[ $arch == *"x86_64"* ]]; then
    # 下载 x86_64 架构的二进制文件（带重试）
    echo "下载 x86_64 架构的组件..."
    wget --tries=3 -O /root/tmp/7zz.tar.xz "$latest_7z_x64_url"
elif [[ $arch == *"aarch64"* ]]; then
    # 下载 ARM64 架构的二进制文件（带重试）
    echo "下载 ARM64 架构的组件..."
    wget --tries=3 -O /root/tmp/7zz.tar.xz "$latest_7z_arm64_url"
fi

# --------------------------------------------------
# 安装 7z（7-Zip 命令行版本）
# 解压后重命名为 7zz 并移动到 /bin 目录
# --------------------------------------------------
echo "正在安装 7z..."
tar -xf /root/tmp/7zz.tar.xz -C /root/tmp
chmod +x /root/tmp/7zz
mv /root/tmp/7zz /bin/7zz
echo "7z 安装完成"


# 安装容器所需的软件包
apt install -y mosquitto python3-pip
pip3 install fastapi "uvicorn[standard]" paho-mqtt pydantic --break-system-packages

# --------------------------------------------------
# 下载运行时脚本到 /usr/local/bin
# 这些脚本在容器启动时被 start.sh 调用
# --------------------------------------------------
# 下载容器相关脚本（前端改走 Vue 构建产物，见下方 frontend 步骤）
for script in main.py api-docs.html; do
    wget -q --tries=3 -O "/usr/local/bin/${script}" \
        "https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/main/容器相关脚本/${script}"
    chmod +x "/usr/local/bin/${script}"
done

# --------------------------------------------------
# 前端：Vue 3 + Vite 工程在镜像内构建，产物落到 /usr/local/bin/frontend
# --------------------------------------------------
echo "[frontend] 安装 Node.js（Vite 6 需要 Node 18+，按架构下载官方二进制）..."
NODE_VERSION=20.19.2
if [[ $arch == *"x86_64"* ]]; then
    NODE_DIST="node-v${NODE_VERSION}-linux-x64"
elif [[ $arch == *"aarch64"* ]]; then
    NODE_DIST="node-v${NODE_VERSION}-linux-arm64"
else
    echo "不支持的架构：$arch" >&2
    exit 1
fi
wget --tries=3 -O /root/tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_DIST}.tar.xz"
tar -xf /root/tmp/node.tar.xz -C /opt
export PATH="/opt/${NODE_DIST}/bin:$PATH"
node --version && npm --version

echo "[frontend] 下载仓库源码包并构建 前端/..."
wget --tries=3 -O /root/tmp/repo.tar.gz "https://github.com/${GITHUB_USER}/${GITHUB_REPO}/archive/refs/heads/main.tar.gz"
mkdir -p /root/tmp/repo
tar -xzf /root/tmp/repo.tar.gz -C /root/tmp/repo
cd "/root/tmp/repo/${GITHUB_REPO}-main/前端"
npm install --registry=https://registry.npmmirror.com --no-audit --no-fund
npm run build
mkdir -p /usr/local/bin/frontend
cp -r dist/. /usr/local/bin/frontend/
cd /
# 运行时只需要静态产物，Node 工具链移出镜像以保持体积
rm -rf "/opt/${NODE_DIST}" /root/.npm
