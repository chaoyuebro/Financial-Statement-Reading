"""内部入队 / 检索 HTTP 端点（技术方案 §5.1 / §7.3）。

仅监听 127.0.0.1 / 容器内网，Bearer 鉴权；供 Web BFF 调用。

POST /internal/enqueue
  body: {"report_id": "<uuid>", "stage"?: "download"|"parse"|..., "source"?: "...", "payload"?: {...}}
  - stage 缺省为 "download"（从下载阶段启动完整管线）
  - 返回 {"job_id": "<report_id>_<stage>", "created": bool}

POST /internal/retrieve
  body: {"report_id": "<uuid>", "question": "...", "top_k"?: 8}
  - 向量检索（pgvector）+ 可选 BM25 RRF 重排，返回 top chunks
  - 返回 {"chunks": [{"page":int,"seq":int,"text":str,"score":float}]}

运行：
    export PYTHONPATH=/repo/apps/worker
    python -m worker.enqueue_server
"""
from __future__ import annotations

import json

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import db  # noqa: F401 — 随包初始化（连接池懒加载）
import pipeline


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization", "") == f"Bearer {config.WORKER_API_TOKEN}"

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path not in ("/internal/enqueue", "/internal/retrieve"):
            self._send(404, {"error": "not found"})
            return
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            data = self._read_json()
        except Exception as e:  # noqa: BLE001
            self._send(400, {"error": f"bad json: {e}"})
            return

        if path == "/internal/enqueue":
            self._handle_enqueue(data)
        else:
            self._handle_retrieve(data)

    def _handle_enqueue(self, data: dict) -> None:
        report_id = data.get("report_id")
        if not report_id:
            self._send(400, {"error": "report_id required"})
            return
        stage = data.get("stage") or "download"
        try:
            job_id, created = pipeline.enqueue_stage(
                report_id, stage, source=data.get("source"), payload=data.get("payload")
            )
        except Exception as e:  # noqa: BLE001
            self._send(409, {"error": str(e)})
            return
        self._send(200, {"job_id": job_id, "created": created})

    def _handle_retrieve(self, data: dict) -> None:
        report_id = data.get("report_id")
        question = (data.get("question") or "").strip()
        if not report_id or not question:
            self._send(400, {"error": "report_id and question required"})
            return
        top_k = int(data.get("top_k") or 8)
        # 延迟导入：避免无 torch 时也强制加载 embed 模块（仅 retrieve 路径需要）
        from retrieval import retrieve

        try:
            chunks = retrieve(report_id, question, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            self._send(200, {"chunks": [], "error": str(e)})
            return
        self._send(
            200,
            {
                "chunks": [
                    {"page": c["page"], "seq": c["seq"], "text": c["text"], "score": c["score"]}
                    for c in chunks
                ]
            },
        )

    def log_message(self, *args) -> None:  # 静默默认访问日志
        pass


def main() -> None:
    server = ThreadingHTTPServer((config.ENQUEUE_HOST, config.ENQUEUE_PORT), _Handler)
    print(f"[enqueue] listening on {config.ENQUEUE_HOST}:{config.ENQUEUE_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
