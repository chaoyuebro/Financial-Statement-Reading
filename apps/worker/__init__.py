"""财报阅读 Worker 包（Python 解析 / 抽取管线）。

以 `worker` 包名导入：将 apps/worker 加入 PYTHONPATH 后
`import worker.config` / `import worker.pipeline` 即可。
RQ 跨进程任务引用路径为 `worker.pipeline.run_stage`。
"""
