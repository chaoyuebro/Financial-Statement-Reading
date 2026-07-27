#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/srv/financial-reader}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "缺少 $APP_DIR/.env，停止部署。" >&2
  exit 1
fi

proxy_args=()
if ss -lnt | grep -q '127.0.0.1:7897'; then
  proxy_args=(
    --build-arg HTTP_PROXY=http://127.0.0.1:7897
    --build-arg HTTPS_PROXY=http://127.0.0.1:7897
    --build-arg NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16
  )
fi

# Ubuntu仓库版Docker暂未附带buildx；使用宿主网络的传统构建器，
# 让npm/pip能够稳定使用服务器本机代理。
export DOCKER_BUILDKIT=0
docker build --network host "${proxy_args[@]}" -f Dockerfile.web -t infra-web:latest .
docker build --network host "${proxy_args[@]}" -f Dockerfile.worker -t infra-worker:latest .

docker compose -f infra/docker-compose.yml --env-file .env up -d --no-build

echo
docker compose -f infra/docker-compose.yml --env-file .env ps
echo
curl --fail --silent --show-error --max-time 20 \
  --output /dev/null http://127.0.0.1:3001/
echo "部署验证通过。"
