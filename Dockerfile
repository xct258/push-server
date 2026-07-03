# 使用 Debian 作为基础镜像
FROM debian

# --------------------------------------------------
# GITHUB_USER - GitHub 用户名
# GITHUB_REPO - GitHub 仓库名
# 用于构建时从 GitHub 下载 init-components.sh 等脚本
# --------------------------------------------------
ARG GITHUB_USER=xct258
ARG GITHUB_REPO=push-server

# 将构建参数传递为环境变量，供 init-components.sh 等脚本使用
ENV GITHUB_USER=${GITHUB_USER}
ENV GITHUB_REPO=${GITHUB_REPO}

# --------------------------------------------------
# 设置中文语言环境和时区
# LANG=zh_CN.UTF-8     - 中文 UTF-8 编码
# TZ=Asia/Shanghai     - 中国标准时间（东八区）
# --------------------------------------------------
RUN apt-get update && apt-get install -y locales tzdata \
    # 生成中文 locale（zh_CN.UTF-8）
    && localedef -i zh_CN -c -f UTF-8 -A /usr/share/locale/locale.alias zh_CN.UTF-8

# 设置环境变量为中文
ENV LANG=zh_CN.UTF-8
# 设置时区为上海
ENV TZ=Asia/Shanghai

# --------------------------------------------------
# 安装构建依赖并执行初始化脚本
# --------------------------------------------------
RUN apt install -y wget \
    # 创建临时目录（用于存放下载的脚本）
    && mkdir -p /root/tmp \
    # 从 GitHub 下载 init-components.sh
    && wget -O /root/tmp/init-components.sh https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/main/容器构建脚本/init-components.sh \
    && chmod +x /root/tmp/init-components.sh \
    # 执行初始化脚本（安装所有组件）
    && /root/tmp/init-components.sh \
    # 清理临时目录（减少镜像体积）
    && rm -rf /root/tmp \
    # 下载容器入口脚本到 /usr/local/bin
    && wget -O /usr/local/bin/start.sh https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/main/容器构建脚本/start.sh \
    && chmod +x /usr/local/bin/start.sh \
    && rm -rf /var/lib/apt/lists/*
# --------------------------------------------------
# 设置容器启动时执行的入口脚本
# --------------------------------------------------
ENTRYPOINT ["/usr/local/bin/start.sh"]
