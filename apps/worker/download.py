"""下载阶段（技术方案 §6.1）。

职责：
- 按 disclosures 顺序执行：主源（reports.primary_source 绑定的 source）优先，
  失败回退到同 report_id 的备用源。
- SSRF 安全抓取（ssrf.safe_fetch），落本地缓存（MinIO 已配置时同步上传）。
- 若实际下载成功的源与报告当前主源不一致，在同一事务内翻转 is_primary_source
  （保持 report_id 不变，仅实际来源切换，§6.1.2 第 5 步）。
- 开发/验证便捷通道：payload 含 local_pdf_path（绝对路径）时跳过网络直读本地文件。

返回 dict：{pdf_path, source, version_tag, size}
"""
from __future__ import annotations

import os

import config
import db
import ssrf


def _cache_path(report_id: str, version_tag: str) -> str:
    os.makedirs(config.PDF_CACHE_DIR, exist_ok=True)
    safe = version_tag.replace(":", "_").replace("/", "_")
    return os.path.join(config.PDF_CACHE_DIR, f"{report_id}_{safe}.pdf")


def _store(pdf_bytes: bytes, report_id: str, version_tag: str) -> tuple[str, bool]:
    """落本地缓存；MinIO 已配置则同步上传。返回（本地路径, 是否已持久化到 MinIO）。"""
    path = _cache_path(report_id, version_tag)
    with open(path, "wb") as f:
        f.write(pdf_bytes)

    persisted = False
    if config.MINIO_ENDPOINT:
        try:
            from minio import Minio

            client = Minio(
                config.MINIO_ENDPOINT,
                access_key=config.MINIO_ACCESS_KEY,
                secret_key=config.MINIO_SECRET_KEY,
                secure=config.MINIO_SECURE,
            )
            import io

            client.put_object(
                config.MINIO_BUCKET,
                f"{report_id}/{version_tag}.pdf",
                data=io.BytesIO(pdf_bytes),
                length=len(pdf_bytes),
            )
            persisted = True
        except Exception as e:  # 降级：本地已存
            print(f"[warn] MinIO 上传失败（已落本地）: {e}")
    return path, persisted


def _read_local(path: str) -> bytes:
    if not os.path.isabs(path) or not os.path.isfile(path):
        raise RuntimeError(f"local_pdf_path 无效: {path}")
    with open(path, "rb") as f:
        return f.read()


def run_download(report_id: str, source: str, payload: dict | None = None) -> dict:
    """执行下载阶段。payload 可携带 local_pdf_path 用于开发验证。"""
    payload = payload or {}
    local_path = payload.get("local_pdf_path")

    sources = db.pdf_sources_for(report_id)
    if not sources:
        raise RuntimeError(f"无披露源: {report_id}")

    # 绑定源优先，其余按 disclosures 顺序回退
    order = [s for s in sources if s["source"] == source] + [
        s for s in sources if s["source"] != source
    ]

    last_err: Exception | None = None
    for s in order:
        src = s["source"]
        version_tag = db.version_tag_for(report_id, src)
        try:
            if local_path:
                data = _read_local(local_path)
            else:
                data = ssrf.safe_fetch(s["pdf_url"])
        except Exception as e:  # noqa: BLE001 — 任何失败都尝试下一个源
            last_err = e
            print(f"[warn] 源 {src} 下载失败: {e}")
            continue

        pdf_path, persisted = _store(data, report_id, version_tag)
        if persisted:
            db.mark_pdf_cached(report_id, src, s["source_announcement_id"])

        # 实际下载源与当前主源不一致 → 翻转（同一报告，仅来源切换）
        meta = db.report_meta(report_id)
        if meta and meta.get("primary_source") != src:
            db.switch_primary_source(report_id, src)

        # 阶段自标记终态（状态机：download → downloaded）；pipeline 再设同值幂等
        db.set_report_status(report_id, config.STATUS_AFTER["download"])
        return {
            "pdf_path": pdf_path,
            "source": src,
            "version_tag": version_tag,
            "size": len(data),
        }

    raise RuntimeError(f"所有源下载失败: {report_id} (last={last_err})")
