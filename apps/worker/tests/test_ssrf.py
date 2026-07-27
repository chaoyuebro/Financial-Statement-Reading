"""SSRF 安全取数单测（纯标准库，无需网络 / 数据库）。

覆盖 §7.6 关键防护点：
- 域名白名单拒绝
- 私有/环回 IP 拒绝（DNS 解析后校验）
- 重定向重新校验（重定向到非白名单域名被拒）
- 内容校验（非 %PDF 拒绝、正常 PDF 通过）
"""
import sys
import os

# 将 apps/worker 加入路径，使 `import ssrf` 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ssrf


class _FakeSock:
    """预置一段 HTTP 响应字节，recv 依次吐出，末次返回 b''（EOF）。"""

    def __init__(self, payload: bytes):
        self._buf = payload
        self._pos = 0

    def recv(self, n: int) -> bytes:
        if self._pos >= len(self._buf):
            return b""
        chunk = self._buf[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def sendall(self, _data: bytes) -> None:
        return None

    def close(self) -> None:
        return None


def _patch_connect(monkeypatch, payload: bytes):
    """用 FakeSock 替换 _connect，避免真实网络。"""

    def fake_connect(host, port, timeout, scheme):
        return _FakeSock(payload), "203.0.113.9"  # 固定为公网示例 IP

    monkeypatch.setattr(ssrf, "_connect", fake_connect)


def test_whitelist_reject(monkeypatch):
    # 非白名单域名在 _check_host_allowed 阶段即被拒（DNS 都不解析）
    try:
        ssrf.safe_fetch("http://evil.example.com/x.pdf")
        assert False, "应拒绝非白名单域名"
    except ssrf.SSFRFetchError as e:
        assert "白名单" in str(e)


def test_private_ip_reject(monkeypatch):
    # 解析到 127.0.0.1（环回）→ _connect 拒绝
    monkeypatch.setattr(ssrf, "_resolve", lambda host: ["127.0.0.1"])
    try:
        ssrf.safe_fetch("http://static.cninfo.com.cn/x.pdf")
        assert False, "应拒绝内网 IP"
    except ssrf.SSFRFetchError as e:
        assert "内网" in str(e) or "拒绝" in str(e)


def test_success_pdf(monkeypatch):
    payload = (
        b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4x"
    )
    _patch_connect(monkeypatch, payload)
    data = ssrf.safe_fetch("http://static.cninfo.com.cn/r.pdf")
    assert data.startswith(b"%PDF"), "应返回 PDF 字节"
    assert len(data) == 9


def test_non_pdf_rejected(monkeypatch):
    payload = (
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n"
        b"Content-Type: text/html\r\n\r\nHELLO"
    )
    _patch_connect(monkeypatch, payload)
    try:
        ssrf.safe_fetch("http://static.cninfo.com.cn/r.pdf")
        assert False, "非 PDF 应通过内容校验被拒"
    except ssrf.SSFRFetchError as e:
        assert "PDF" in str(e)


def test_redirect_revalidated(monkeypatch):
    # 302 跳转到非白名单域名 → 重新校验被拒
    payload = (
        b"HTTP/1.1 302 Found\r\nLocation: http://evil.example.com/x.pdf\r\n\r\n"
    )
    _patch_connect(monkeypatch, payload)
    try:
        ssrf.safe_fetch("http://static.cninfo.com.cn/r.pdf")
        assert False, "重定向到非白名单应被拒"
    except ssrf.SSFRFetchError as e:
        assert "白名单" in str(e)


def test_redirect_same_host_ok(monkeypatch):
    # 302 跳转到白名单内另一路径 → 允许
    payload = (
        b"HTTP/1.1 302 Found\r\nLocation: http://static.cninfo.com.cn/real.pdf\r\n\r\n"
    )
    _patch_connect(monkeypatch, payload)
    # 第二次 _connect（重定向后）返回真实 PDF
    calls = {"n": 0}

    def fake_connect(host, port, timeout, scheme):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeSock(payload), "203.0.113.9"
        return (
            _FakeSock(
                b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n%PDF-1.4x"
            ),
            "203.0.113.9",
        )

    monkeypatch.setattr(ssrf, "_connect", fake_connect)
    data = ssrf.safe_fetch("http://static.cninfo.com.cn/r.pdf")
    assert data.startswith(b"%PDF")
    assert calls["n"] == 2


def test_is_blocked_ip():
    assert ssrf._is_blocked_ip("127.0.0.1")
    assert ssrf._is_blocked_ip("10.0.0.5")
    assert ssrf._is_blocked_ip("192.168.1.1")
    assert ssrf._is_blocked_ip("172.16.5.5")
    assert ssrf._is_blocked_ip("169.254.0.1")
    # 真实公网地址（非保留/私有）应通过
    assert not ssrf._is_blocked_ip("8.8.8.8")
    assert not ssrf._is_blocked_ip("1.1.1.1")


if __name__ == "__main__":
    import inspect

    class MP:
        """简易 monkeypatch：备份被替换属性，restore 时还原。"""

        def __init__(self):
            self._saved = []

        def setattr(self, mod, name, val):
            self._saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, val)

        def restore(self):
            for mod, name, val in self._saved:
                setattr(mod, name, val)

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in tests:
        mp = MP()
        try:
            if len(inspect.signature(fn).parameters) >= 1:
                fn(mp)
            else:
                fn()
            mp.restore()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            mp.restore()
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
