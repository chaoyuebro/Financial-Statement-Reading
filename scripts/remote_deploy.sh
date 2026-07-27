#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/srv/financial-reader}"
COMMIT="${2:-unknown}"
PAYLOAD_B64="${3:-}"
ARCHIVE="${4:--}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "缺少 $APP_DIR/.env，停止部署。" >&2
  exit 1
fi

payload="$(printf '%s' "$PAYLOAD_B64" | base64 -d)"
mapfile -t changed < <(python3 -c 'import json,sys; print(*json.load(sys.stdin)["changed"], sep="\n")' <<<"$payload")
mapfile -t deleted < <(python3 -c 'import json,sys; print(*json.load(sys.stdin)["deleted"], sep="\n")' <<<"$payload")
full="$(python3 -c 'import json,sys; print("1" if json.load(sys.stdin)["full"] else "0")' <<<"$payload")"

if [[ "$ARCHIVE" != "-" ]]; then
  tar -xzf "$ARCHIVE" -C "$APP_DIR"
  rm -f "$ARCHIVE"
fi
for file in "${deleted[@]}"; do
  [[ -n "$file" ]] && rm -f -- "$APP_DIR/$file"
done

contains_path() {
  local pattern="$1" file
  for file in "${changed[@]}" "${deleted[@]}"; do
    [[ "$file" == $pattern ]] && return 0
  done
  return 1
}

web_changed=0
worker_changed=0
web_deps_changed=0
worker_deps_changed=0
compose_changed=0

if [[ "$full" == "1" ]] || contains_path 'apps/web/*' || contains_path 'packages/shared/*' \
  || contains_path 'Dockerfile.web*' || contains_path 'package.json' || contains_path 'package-lock.json'; then
  web_changed=1
fi
if [[ "$full" == "1" ]] || contains_path 'package.json' || contains_path 'package-lock.json' \
  || contains_path 'apps/web/package.json' || contains_path 'packages/shared/package.json'; then
  web_deps_changed=1
fi
if [[ "$full" == "1" ]] || contains_path 'apps/worker/*' || contains_path 'scripts/sync_cninfo_reports.py' \
  || contains_path 'Dockerfile.worker'; then
  worker_changed=1
fi
if [[ "$full" == "1" ]] || contains_path 'Dockerfile.worker' \
  || contains_path 'apps/worker/requirements*.txt'; then
  worker_deps_changed=1
fi
if [[ "$full" == "1" ]] || contains_path 'infra/docker-compose.yml'; then
  compose_changed=1
fi

proxy_args=()
if ss -lnt | grep -q '127.0.0.1:7897'; then
  proxy_args=(
    --build-arg HTTP_PROXY=http://127.0.0.1:7897
    --build-arg HTTPS_PROXY=http://127.0.0.1:7897
    --build-arg NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16
  )
fi

# 当前 Ubuntu Docker 未安装 buildx；增量镜像直接继承现有生产镜像，
# 即使使用传统构建器也不会执行 npm ci。
export DOCKER_BUILDKIT=0

if [[ "$web_changed" == "1" ]]; then
  if [[ "$web_deps_changed" == "1" ]] || ! docker image inspect infra-web:latest >/dev/null 2>&1; then
    echo "[Web] 依赖清单有变化，执行包含 npm ci 的完整构建。"
    docker build --network host "${proxy_args[@]}" -f Dockerfile.web -t infra-web:latest .
  else
    echo "[Web] 依赖未变化，复用现有 node_modules，跳过 npm ci。"
    docker build --network host "${proxy_args[@]}" \
      --build-arg BASE_IMAGE=infra-web:latest \
      -f Dockerfile.web.incremental -t infra-web:latest .
  fi
  docker compose -f infra/docker-compose.yml --env-file .env up -d --no-deps --force-recreate web
fi

if [[ "$worker_changed" == "1" ]]; then
  if [[ "$worker_deps_changed" == "1" ]] || ! docker container inspect fr_worker >/dev/null 2>&1; then
    echo "[Worker] 依赖或镜像配置有变化，执行完整构建。"
    docker build --network host "${proxy_args[@]}" -f Dockerfile.worker -t infra-worker:latest .
    docker compose -f infra/docker-compose.yml --env-file .env up -d --no-deps --force-recreate worker
  else
    echo "[Worker] 仅代码变化，增量复制并重启。"
    docker cp "$APP_DIR/apps/worker/." fr_worker:/app/apps/worker/
    if [[ -f "$APP_DIR/scripts/sync_cninfo_reports.py" ]]; then
      docker exec fr_worker mkdir -p /app/scripts
      docker cp "$APP_DIR/scripts/sync_cninfo_reports.py" fr_worker:/app/scripts/sync_cninfo_reports.py
    fi
    if [[ -f "$APP_DIR/scripts/backfill_cninfo_catalog.py" ]]; then
      docker exec fr_worker mkdir -p /app/scripts
      docker cp "$APP_DIR/scripts/backfill_cninfo_catalog.py" fr_worker:/app/scripts/backfill_cninfo_catalog.py
    fi
    docker restart fr_worker >/dev/null
  fi
fi

if [[ "$compose_changed" == "1" ]]; then
  docker compose -f infra/docker-compose.yml --env-file .env up -d --no-build
fi

docker compose -f infra/docker-compose.yml --env-file .env ps

healthy=0
for _ in {1..20}; do
  if curl --fail --silent --max-time 5 --output /dev/null http://127.0.0.1:3001/; then
    healthy=1
    break
  fi
  sleep 2
done
if [[ "$healthy" != "1" ]]; then
  echo "Web 服务在 40 秒内未就绪。" >&2
  exit 1
fi

printf '%s\n' "$COMMIT" > .deploy_commit
echo "增量部署验证通过，提交：$COMMIT"
