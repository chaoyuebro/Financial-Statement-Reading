"""RQ Worker 入口（技术方案 §5.1）。

任务引用：worker.pipeline.run_stage（RQ 按此字符串导入，故本包须以顶层名 `worker` 导入）。

运行：
    export PYTHONPATH=/repo/apps/worker
    python -m worker.worker
或更简单： rq worker  （同样需 PYTHONPATH 指向 apps/worker）
"""
from __future__ import annotations

import config
from redis import Redis
from rq import Connection, Worker


def main() -> None:
    conn = Redis.from_url(config.REDIS_URL)
    with Connection(conn):
        worker = Worker(Worker.all_queues())
        print("[worker] 启动，监听默认队列")
        worker.work()


if __name__ == "__main__":
    main()
