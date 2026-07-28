"""Worker 运行时配置（环境变量驱动，所有默认值对齐技术方案 §5 / §7.6）。

运行方式：将 apps/worker 加入 PYTHONPATH 后，本包以顶层名 `worker` 导入：
    export PYTHONPATH=/repo/apps/worker
    python -m worker.enqueue_server     # 内部入队端点
    python -m worker.worker             # rq worker（或直接 rq worker）
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [v.strip() for v in raw.split(",") if v.strip()]


# ---- 基础设施连接 ----
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fr:fr_dev_pw@localhost:5432/fr")

# MinIO（§7.4：优先对象存储签名 URL；未配置时 PDF 落本地缓存降级）
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "fr-pdf")
MINIO_PRESIGNED_TTL = int(os.getenv("MINIO_PRESIGNED_TTL", "3600"))
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

# ---- 内部入队端点（§5.1：仅监听 127.0.0.1 / 容器内网，Bearer 鉴权）----
WORKER_API_TOKEN = os.getenv("WORKER_API_TOKEN", "dev-worker-token-change-me")
ENQUEUE_HOST = os.getenv("ENQUEUE_HOST", "127.0.0.1")
ENQUEUE_PORT = int(os.getenv("ENQUEUE_PORT", "8000"))

# ---- SSRF 防护（§7.6）----
# 域名白名单：仅允许巨潮 / 东财 / 已配置对象存储域名
ALLOWED_PDF_HOSTS = _env_list(
    "FR_PDF_ALLOWED_HOSTS", "static.cninfo.com.cn,pdf.dfcfw.com"
)
DOWNLOAD_MAX_BYTES = int(os.getenv("DOWNLOAD_MAX_BYTES", "104857600"))  # 100MB
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "60"))
MAX_REDIRECTS = int(os.getenv("MAX_REDIRECTS", "3"))

# ---- 状态机（§5：pending→downloaded→parsed→embedded→metrics_done→ready）----
STAGES = ["download", "parse", "embed", "metrics"]
NEXT_STAGE = {"download": "parse", "parse": "embed", "embed": "metrics", "metrics": None}
# 各阶段完成后的报告级状态（对齐 reports.status 状态链 §5 / 0001_schema.sql）
# pending→downloaded→parsed→embedded→metrics_done→ready / failed
STATUS_AFTER = {
    "download": "downloaded",
    "parse": "parsed",
    "embed": "embedded",
    "metrics": "metrics_done",
}
# RQ 单任务超时（秒）
JOB_TIMEOUTS = {"download": 60, "parse": 300, "embed": 600, "metrics": 120}
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))

# 本地 PDF 缓存目录（MinIO 未配置时的降级落盘点；仅开发验证用）
PDF_CACHE_DIR = os.getenv(
    "PDF_CACHE_DIR", os.path.join(os.path.dirname(__file__), ".pdf_cache")
)

# ---- 嵌入模型（§6.4：MVP 固定 bge-small-zh，512 维，与 document_chunks.embedding 一致）----
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
EMBEDDING_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "/models/fastembed")
# P1 可切换不同维度模型——必须为该模型新建独立向量列与索引（§6.4），不得混用同一列

# ---- 关键指标大模型复核（规则抽取后、写库前）----
LLM_API_STYLE = os.getenv("LLM_API_STYLE", "")
LLM_API_BASE = os.getenv("LLM_API_BASE", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
METRICS_LLM_REVIEW = os.getenv("METRICS_LLM_REVIEW", "true").lower() in (
    "1",
    "true",
    "yes",
)
