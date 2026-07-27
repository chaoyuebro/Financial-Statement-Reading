#!/usr/bin/env bash
#
# W3 联调冒烟（W3-1~W3-4）
#   首页 SSR / 列表 / 详情+TOC / PDF 代理(200+Accept-Ranges) / PDF Range(206) / 解析触发(GET/POST)
#
# 前置：本地 docker compose 已起（Postgres / Redis / MinIO / web / worker）。
# 用法：
#   BASE_URL=http://localhost:3000 REPORT_ID=<uuid> bash scripts/smoke_w3.sh
#   BASE_URL=http://localhost:3000 USE_DEV_FIXTURE=1 bash scripts/smoke_w3.sh   # 假 PDF 验证（需服务端 FR_ALLOW_DEV_FIXTURE=1）
#
# 退出码：关键步骤(1-6)全过为 0，否则 1。第 7 步(parse POST)为软断言（200/502/409 均记 SOFT，非阻断）。

set -u

BASE_URL="${BASE_URL:-http://localhost:3000}"
REPORT_ID="${REPORT_ID:-}"
USE_DEV_FIXTURE="${USE_DEV_FIXTURE:-0}"
DEV_FIXTURE="${DEV_FIXTURE:-sample-report.pdf}"

PASS=0
FAIL=0
SOFT=0

JQ_OK=1
command -v jq >/dev/null 2>&1 || JQ_OK=0

BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

# 单状态断言：name expect_code path [curl-args...]
step() {
  local name="$1" expect="$2" path="$3"; shift 3
  local hdrs code
  hdrs="$(curl -s -D - -o "$BODY_FILE" "$@" "${BASE_URL}${path}" 2>/dev/null)"
  code="$(printf '%s' "$hdrs" | head -n 1 | grep -oE '[0-9]{3}' | head -n 1)"
  if [ "$code" = "$expect" ]; then
    echo "PASS  $name  [$code]  $path"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name  [got $code, want $expect]  $path"
    FAIL=$((FAIL + 1))
  fi
}

# 多状态软断言：name "200,502,409" path [curl-args...]
step_any() {
  local name="$1" expects="$2" path="$3"; shift 3
  local hdrs code
  hdrs="$(curl -s -D - -o "$BODY_FILE" "$@" "${BASE_URL}${path}" 2>/dev/null)"
  code="$(printf '%s' "$hdrs" | head -n 1 | grep -oE '[0-9]{3}' | head -n 1)"
  if printf '%s' "$expects" | tr ',' '\n' | grep -qx "$code"; then
    echo "PASS  $name  [$code]  $path"
    PASS=$((PASS + 1))
  else
    echo "SOFT  $name  [got $code, accept $expects]  $path"
    SOFT=$((SOFT + 1))
  fi
}

hdr() {
  echo
  echo "=== $1 ==="
}

hdr "W3 联调冒烟 @ $BASE_URL"
echo "USE_DEV_FIXTURE=$USE_DEV_FIXTURE  REPORT_ID=${REPORT_ID:-<auto from list>}"

# 1) 首页 SSR（W3-1 骨架）
hdr "W3-1 阅读页骨架"
step "首页 SSR 200" 200 "/"

# 2) 列表 API（并尝试取首个 report id）
hdr "列表 + 详情"
step "列表 API 200" 200 "/api/disclosures"
if [ -z "$REPORT_ID" ] && [ "$JQ_OK" = "1" ]; then
  REPORT_ID="$(jq -r '.items[0].id // empty' "$BODY_FILE" 2>/dev/null)"
  echo "  auto REPORT_ID=$REPORT_ID"
fi
if [ -z "$REPORT_ID" ]; then
  echo "WARN  未提供 REPORT_ID 且无法从列表取得，后续依赖步骤跳过"
fi

if [ -n "$REPORT_ID" ]; then
  # 3) 详情 + TOC（W3-3 数据来源）
  step "详情 API 200" 200 "/api/disclosures/${REPORT_ID}"
  if [ "$JQ_OK" = "1" ]; then
    toc_len="$(jq -r '.toc | length // 0' "$BODY_FILE" 2>/dev/null)"
    echo "  toc 条目数=$toc_len"
  fi

  # 4) PDF 代理（无 Range → 200 + Accept-Ranges）（W3-2）
  hdr "W3-2 Range 代理"
  pdf_q=""
  if [ "$USE_DEV_FIXTURE" = "1" ]; then pdf_q="?devFixture=${DEV_FIXTURE}"; fi
  step "PDF 代理 200" 200 "/api/disclosures/${REPORT_ID}/pdf${pdf_q}"
  ar="$(curl -s -D - -o /dev/null "${BASE_URL}/api/disclosures/${REPORT_ID}/pdf${pdf_q}" 2>/dev/null | grep -i '^accept-ranges:' | tr -d '\r')"
  if [ -n "$ar" ]; then echo "PASS  Accept-Ranges 头存在 ($ar)"; PASS=$((PASS + 1)); else echo "FAIL  Accept-Ranges 头缺失"; FAIL=$((FAIL + 1)); fi

  # 5) PDF Range → 206
  step "PDF Range 206" 206 "/api/disclosures/${REPORT_ID}/pdf${pdf_q}" -H "Range: bytes=0-99"

  # 6) 解析状态 GET（W3-4 触发前置）
  hdr "W3-4 解析触发"
  step "解析状态 GET 200" 200 "/api/disclosures/${REPORT_ID}/parse"
  if [ "$JQ_OK" = "1" ]; then
    can="$(jq -r '.canParse // false' "$BODY_FILE" 2>/dev/null)"
    st="$(jq -r '.status // empty' "$BODY_FILE" 2>/dev/null)"
    echo "  status=$st canParse=$can"
  fi

  # 7) 解析触发 POST（软：worker 起=200 / 未起=502 / 不可解析=409）
  step_any "解析触发 POST" "200,502,409" "/api/disclosures/${REPORT_ID}/parse" \
    -X POST -H "Content-Type: application/json" -d '{}'
fi

hdr "汇总"
echo "PASS=$PASS  FAIL=$FAIL  SOFT=$SOFT"
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: OK（关键步骤全过；SOFT 项为环境相关，非阻断）"
  exit 0
else
  echo "RESULT: FAIL（存在关键步骤失败，需排查）"
  exit 1
fi
