#!/bin/bash
# ============================================================
# 只执行一次：第一次启动时执行，成功后写标记 /data/.startup-once.done
#   push-server 的运行数据目录由 prepare.sh 每次启动时补齐，
#   这里只做一次性的目录初始化。
# ============================================================
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/log.sh"

mkdir -p /data/push_records
log info "数据目录已初始化"
