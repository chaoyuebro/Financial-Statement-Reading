#!/usr/bin/env bash
# Worker 容器启动脚本：同时拉起「内部入队 HTTP 端点」与「RQ Worker」。
# - enqueue_server 监听 0.0.0.0:8000（仅 docker 内网可达，供 web BFF 调用）；
# - rq worker 在前台运行（exec 接收信号），处理下载/解析/向量化/抽取管线。
# PYTHONPATH=/app/apps/worker 使扁平 import(config/db/...) 与 RQ 任务 pipeline.run_stage 均可解析。
set -euo pipefail

cd /app/apps/worker
export PYTHONPATH="/app/apps/worker:${PYTHONPATH:-}"

echo "[run_worker] starting enqueue_server on ${ENQUEUE_HOST:-0.0.0.0}:${ENQUEUE_PORT:-8000}"
python enqueue_server.py &
ENQUEUE_PID=$!

# enqueue_server 退出则随容器退出（保持单一前台进程语义）
trap 'kill "$ENQUEUE_PID" 2>/dev/null || true' EXIT INT TERM

echo "[run_worker] starting rq worker (queue=${RQ_QUEUE:-default})"
exec rq worker "${RQ_QUEUE:-default}" --url redis://redis:6379/0
