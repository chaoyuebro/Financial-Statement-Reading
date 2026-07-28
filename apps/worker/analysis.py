"""触发 Web 内部深度分析接口，并将结果缓存到 PostgreSQL。"""
from __future__ import annotations

import httpx

import config


def run_analysis(report_id: str) -> dict:
    url = (
        f"{config.WEB_APP_URL.rstrip('/')}/api/disclosures/"
        f"{report_id}/summary?refresh=1"
    )
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {config.WORKER_API_TOKEN}"},
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "analysis_cached": True,
        "points": len(payload.get("points") or []),
        "model": payload.get("model"),
    }
