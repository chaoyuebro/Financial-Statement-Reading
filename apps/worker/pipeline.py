"""状态机 + RQ 入队 / 分发（技术方案 §5 / §5.1 / §5.2）。

- guard_can_parse：临时报告(report_period_unknown)与已撤回(is_withdrawn)禁止启动解析（§6.1.3）。
- enqueue_stage：幂等创建 parse_jobs（ON CONFLICT DO NOTHING）+ RQ 入队；
  幂等键 job_id = '{report_id}_{stage}'，RQ 侧同样以该 id 投递防重。
- run_stage：RQ 任务入口。认领租约 → 守卫 → 分发(download/parse/embed/metrics) →
  成功则推进报告状态（transient→completed）并级联入队下一阶段；
  失败则标记 failed 并置报告 failed。
- embed / metrics 阶段属 W5–6（见 metrics.py / embed.py）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import config
import db

try:
    from redis import Redis
    from rq import Queue
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    _RQ_AVAILABLE = True
except Exception:  # pragma: no cover — 入队仅在 worker 运行时需要
    _RQ_AVAILABLE = False

# 阶段进行态（租约认领时写入 reports.status，供前端渐进展示）
TRANSITION_STATUS = {
    "download": "downloading",
    "parse": "parsing",
    "embed": "embedding",
    "metrics": "extracting",
}

PROGRESS_START = {
    "download": (3, "正在下载 PDF"),
    "parse": (25, "正在读取 PDF 页面"),
    "embed": (78, "正在建立问答索引"),
    "metrics": (92, "正在抽取关键指标"),
}
PROGRESS_DONE = {
    "download": (20, "PDF 下载完成"),
    "parse": (75, "全文解析完成"),
    "embed": (90, "问答索引建立完成"),
    "metrics": (100, "报告解析完成"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def guard_can_parse(report_id: str) -> None:
    """守卫：临时报告 / 已撤回 不得进入解析管线（§6.1.3）。"""
    meta = db.report_meta(report_id)
    if meta is None:
        raise RuntimeError(f"报告不存在: {report_id}")
    if meta.get("report_period_unknown"):
        raise RuntimeError(f"临时报告(报告期未知)禁止解析: {report_id}")
    if meta.get("is_withdrawn"):
        raise RuntimeError(f"已撤回报告禁止解析: {report_id}")


def _make_queue() -> "Queue":
    if not _RQ_AVAILABLE:
        raise RuntimeError("RQ/Redis 未安装，无法入队")
    conn = Redis.from_url(config.REDIS_URL)
    return Queue(connection=conn)


def enqueue_stage(
    report_id: str,
    stage: str,
    source: str | None = None,
    payload: dict | None = None,
) -> tuple[str, bool]:
    """幂等入队某阶段。返回 (job_id, created)。

    - 先守卫（失败直接抛，不建任务）。
    - db.ensure_parse_job 幂等建行；仅新建成功才向 RQ 投递，避免重复任务。
    - RQ 任务以 job_id 作为去重键，并通过 kwargs 传递 source/payload。
    """
    guard_can_parse(report_id)
    if stage not in config.STAGES:
        raise ValueError(f"未知阶段: {stage}")
    if source is None:
        source = db.primary_source_for(report_id)
        if not source:
            raise RuntimeError(f"无主源可绑定: {report_id}")

    job_id, created = db.ensure_parse_job(report_id, stage, source, payload)
    if created:
        q = _make_queue()
        q.enqueue_call(
            "pipeline.run_stage",
            args=(report_id, stage),
            kwargs={"source": source, "payload": payload or {}},
            job_id=job_id,
            timeout=config.JOB_TIMEOUTS.get(stage, 300),
        )
    return job_id, created


def restart_pipeline(
    report_id: str,
    source: str | None = None,
    payload: dict | None = None,
) -> tuple[str, bool]:
    """安全重置已结束任务，并从 download 阶段重新执行完整管线。"""
    guard_can_parse(report_id)
    q = _make_queue()
    db.reset_parse_pipeline(report_id)
    for stage in config.STAGES:
        job_id = f"{report_id}_{stage}"
        try:
            Job.fetch(job_id, connection=q.connection).delete()
        except NoSuchJobError:
            pass
    return enqueue_stage(report_id, "download", source=source, payload=payload)


def run_stage(
    report_id: str,
    stage: str,
    source: str | None = None,
    payload: dict | None = None,
) -> dict:
    """RQ 任务入口：执行单阶段并推进状态机。"""
    payload = payload or {}
    job_id = f"{report_id}_{stage}"

    # 双重守卫
    try:
        guard_can_parse(report_id)
    except RuntimeError as e:
        db.update_parse_job(job_id, "failed", error=str(e))
        db.set_report_status(report_id, "failed")
        raise

    if source is None:
        job = db.get_parse_job(job_id)
        source = db.primary_source_for(report_id) or (job.get("source") if job else None)
    if not source:
        raise RuntimeError(f"无法确定源: {report_id}:{stage}")

    # 认领租约 + 写入进行态
    lease_token = uuid.uuid4().hex
    lease_expires = _now() + timedelta(seconds=config.JOB_TIMEOUTS.get(stage, 300))
    start_progress, start_message = PROGRESS_START.get(stage, (0, "正在处理"))
    db.update_parse_job(
        job_id,
        "running",
        lease_token=lease_token,
        lease_expires_at=lease_expires,
        progress=start_progress,
        progress_message=start_message,
    )
    db.set_report_status(report_id, TRANSITION_STATUS.get(stage, "parsing"))

    try:
        if stage == "download":
            result = _run_download(report_id, source, payload)
            # 把实际落盘的源 / 路径传给下游 parse
            payload = {**payload, "pdf_path": result["pdf_path"], "source": result["source"]}
        elif stage == "parse":
            result = _run_parse(report_id, source, payload)
        elif stage == "embed":
            result = _run_embed(report_id, source, payload)
        elif stage == "metrics":
            result = _run_metrics(report_id, source, payload)
        else:
            raise ValueError(f"未知阶段: {stage}")
    except Exception as e:  # noqa: BLE001
        db.update_parse_job(
            job_id,
            "failed",
            error=str(e)[:2000],
            attempts_incr=1,
            progress_message=f"{start_message}失败",
        )
        db.set_report_status(report_id, "failed")
        raise

    # 成功：done + 报告级完成态
    done_progress, done_message = PROGRESS_DONE.get(stage, (100, "处理完成"))
    db.update_parse_job(
        job_id,
        "done",
        attempts_incr=1,
        progress=done_progress,
        progress_message=done_message,
    )
    db.set_report_status(report_id, config.STATUS_AFTER[stage])

    # 级联入队下一阶段（download → parse；parse → embed 属 W5–6）
    next_stage = config.NEXT_STAGE.get(stage)
    if next_stage:
        next_source = payload.get("source") or source
        enqueue_stage(report_id, next_stage, source=next_source, payload=payload)
    return result


def _run_download(report_id: str, source: str, payload: dict) -> dict:
    import download

    return download.run_download(report_id, source, payload)


def _run_parse(report_id: str, source: str, payload: dict) -> dict:
    import parse

    job_id = f"{report_id}_parse"

    def on_progress(done: int, total: int) -> None:
        percent = 25 + round((done / max(1, total)) * 45)
        db.update_parse_job(
            job_id,
            "running",
            progress=percent,
            progress_message=f"正在解析 PDF：第 {done}/{total} 页",
        )

    return parse.run_parse(report_id, source, payload, progress_callback=on_progress)


def _run_embed(report_id: str, source: str, payload: dict) -> dict:
    import embed

    job_id = f"{report_id}_embed"

    def on_progress(done: int, total: int) -> None:
        percent = 78 + round((done / max(1, total)) * 11)
        db.update_parse_job(
            job_id,
            "running",
            progress=percent,
            progress_message=f"正在建立问答索引：{done}/{total} 个片段",
        )

    return embed.run_embed(report_id, source, payload, progress_callback=on_progress)


def _run_metrics(report_id: str, source: str, payload: dict) -> dict:
    import metrics

    return metrics.run_metrics(report_id, source, payload)
