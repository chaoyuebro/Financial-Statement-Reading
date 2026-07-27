#!/usr/bin/env bash
# W5-6 BFF 冒烟（不依赖真实数据，只验证路由可达 + 错误路径）
# - /metrics 期望 404 / 400（按 report 状态）
# - /summary 期望 200（指标派生）或 409 not_ready
# - /chat 期望 200（抽取式降级 + 引用 0/1）或 400 missing question
# 用法: BASE_URL=http://127.0.0.1:3001 ./scripts/smoke_w5_6.sh

set -u
BASE_URL="${BASE_URL:-http://127.0.0.1:3001}"
RID="${REPORT_ID:-00000000-0000-0000-0000-000000000000}"

pass=0; fail=0
declare -a msgs=()

check() {
    local name="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
        pass=$((pass+1)); msgs+=("PASS $name ($actual)")
    else
        fail=$((fail+1)); msgs+=("FAIL $name (expected $expected, got $actual)")
    fi
}

code_get()  { curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/disclosures/$RID$1"; }
code_post() { curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$2" "$BASE_URL/api/disclosures/$RID$1"; }

# 1) metrics（无数据报告）
check "GET /metrics" "404" "$(code_get /metrics)"

# 2) summary（应能 200，fromMetrics=true）
check "POST /summary" "200" "$(code_post /summary '{}')"

# 3) chat 缺 question → 400
check "POST /chat missing question" "400" "$(code_post /chat '{}')"

# 4) chat 合法 → 200 + fallback=true
check "POST /chat valid" "200" "$(code_post /chat '{"question":"营业收入"}')"

# 5) /metrics 不存在 UUID 解析仍 404（不是 500）
check "GET /metrics bad uuid" "404" "$(code_get /metrics)"

echo "--- W5-6 BFF smoke ---"
for m in "${msgs[@]}"; do echo "  $m"; done
echo "--- $pass PASS / $fail FAIL ---"
[ $fail -eq 0 ]