"""SSRF 安全 HTTP 取数（技术方案 §7.6）。

防护点：
- 域名白名单：仅允许 config.ALLOWED_PDF_HOSTS 中的主机。
- 禁止内网：先解析 DNS 拿到全部 IP，逐个拒绝环回/私有/链路本地/保留/组播/未指定地址；
  仅当至少一个 IP 安全时才连接。
- 手动重定向重校验：遇到 3xx 时，对新 Location 重新走「白名单 + DNS + 内网校验」，
  不允许重定向到非白名单域名（重定向上限 ≤ MAX_REDIRECTS）。
- 资源限制：单次响应最大字节（DOWNLOAD_MAX_BYTES）、超时（DOWNLOAD_TIMEOUT）。
- 内容校验：响应头 Content-Type 明显为 HTML 时拒绝（错误页）；文件头必须为 %PDF。

实现采用标准库 http.client 级别的手动连接（对解析出的 IP 建连、Host 头保留原域名，
以支持 SNI / 虚拟主机），不依赖 requests，保持 Worker 依赖精简。
"""
from __future__ import annotations

import ipaddress
import socket
import ssl
import urllib.parse

import config


class SSFRFetchError(Exception):
    """SSRF 校验或下载约束被违反时抛出。"""


# ---------------------------------------------------------------------------
# IP / 域名校验
# ---------------------------------------------------------------------------
def _is_blocked_ip(ip: str) -> bool:
    """判断 IP 是否应被拒绝（内网 / 环回 / 保留 / 组播 / 未指定）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # 无法解析为合法 IP 即阻断
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    """返回 host 的全部 A/AAAA 解析结果（去重 IP 列表）。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSFRFetchError(f"DNS 解析失败: {host} ({e})")
    ips = {info[4][0] for info in infos}
    if not ips:
        raise SSFRFetchError(f"无可用 IP: {host}")
    return list(ips)


def _check_host_allowed(host: str, allowed: list[str]) -> None:
    lowered = {h.lower() for h in allowed}
    if host.lower() not in lowered:
        raise SSFRFetchError(f"域名不在白名单: {host}")


def _connect(host: str, port: int, timeout: int, scheme: str):
    """解析 DNS、逐个校验 IP 非内网，连接第一个安全 IP。返回 (socket, ip)。"""
    ips = _resolve(host)
    last_err: Exception | None = None
    for ip in ips:
        if _is_blocked_ip(ip):
            last_err = SSFRFetchError(f"拒绝内网/保留 IP: {ip} (host={host})")
            continue
        try:
            sock = socket.create_connection((ip, port), timeout=timeout)
        except OSError as e:
            last_err = e
            continue
        if scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        return sock, ip
    raise SSFRFetchError(f"无法建立安全连接: {host} ({last_err})")


# ---------------------------------------------------------------------------
# 响应读取（支持 Content-Length 与 chunked）
# ---------------------------------------------------------------------------
class _SockReader:
    """在 socket 上做有上限的缓冲读取，避免 zip-bomb / 无限读取。"""

    def __init__(self, sock: socket.socket, max_bytes: int):
        self.sock = sock
        self.buf = bytearray()
        self.max_bytes = max_bytes

    def _fill(self) -> bool:
        chunk = self.sock.recv(65536)
        if not chunk:
            return False
        self.buf += chunk
        if len(self.buf) > self.max_bytes:
            raise SSFRFetchError(f"响应超过大小上限 {self.max_bytes} 字节")
        return True

    def read_until(self, sep: bytes) -> bytes | None:
        while sep not in self.buf:
            if not self._fill():
                return None
        idx = self.buf.find(sep)
        data = bytes(self.buf[:idx])
        del self.buf[: idx + len(sep)]
        return data

    def read_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            if not self._fill():
                raise SSFRFetchError("连接提前关闭（数据不足）")
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data

    def read_to_eof(self) -> bytes:
        while True:
            if not self._fill():
                break
        return bytes(self.buf)


def _parse_status_and_headers(header_blob: bytes) -> tuple[int, dict]:
    lines = header_blob.split(b"\r\n")
    status_line = lines[0].decode("latin-1")
    parts = status_line.split(" ", 2)
    if len(parts) < 2:
        raise SSFRFetchError(f"非法状态行: {status_line!r}")
    status = int(parts[1])
    headers: dict[str, str] = {}
    for ln in lines[1:]:
        if b":" not in ln:
            continue
        k, _, v = ln.partition(b":")
        headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    return status, headers


def _read_body(reader: _SockReader, status: int, headers: dict) -> bytes:
    te = headers.get("transfer-encoding", "").lower()
    if te == "chunked":
        body = bytearray()
        while True:
            line = reader.read_until(b"\r\n")
            if line is None:
                raise SSFRFetchError("chunked 分块大小行缺失")
            size = int(line.split(b";")[0].strip(), 16)
            if size == 0:
                reader.read_exact(2)  # 消费尾部 CRLF
                break
            body += reader.read_exact(size)
            reader.read_exact(2)  # 分块后的 CRLF
        return bytes(body)
    cl = headers.get("content-length")
    if cl is not None:
        target = int(cl)
        # read_exact 会先消费 reader.buf，再从 socket 补足；不能预先复制 buf，
        # 否则响应头之后已缓冲的 PDF 开头会被拼接两次并损坏文件。
        return reader.read_exact(target)
    # 无 Content-Length 也无 chunked：读到 EOF
    return reader.read_to_eof()


# ---------------------------------------------------------------------------
# 内容校验
# ---------------------------------------------------------------------------
def _validate_pdf(body: bytes, content_type: str | None) -> None:
    if not body.startswith(b"%PDF"):
        raise SSFRFetchError("文件头非 %PDF，疑似非 PDF 内容")
    ct = (content_type or "").lower()
    if ct and "text/html" in ct:
        raise SSFRFetchError(f"Content-Type 为 HTML（可能是错误页）: {ct}")


# ---------------------------------------------------------------------------
# 对外主函数
# ---------------------------------------------------------------------------
def safe_fetch(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: int | None = None,
    max_redirects: int | None = None,
    allowed_hosts: list[str] | None = None,
    require_pdf: bool = True,
) -> bytes:
    """SSRF 安全抓取字节内容。

    参数取自 config 默认值；allowed_hosts 用于覆盖白名单（测试用）。
    返回响应体字节；非 200 / 超限 / 非白名单 / 内网 / 非 PDF 均抛 SSFRFetchError。
    """
    max_bytes = max_bytes if max_bytes is not None else config.DOWNLOAD_MAX_BYTES
    timeout = timeout if timeout is not None else config.DOWNLOAD_TIMEOUT
    max_redirects = max_redirects if max_redirects is not None else config.MAX_REDIRECTS
    allowed_hosts = allowed_hosts if allowed_hosts is not None else config.ALLOWED_PDF_HOSTS

    redirects = 0
    while True:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise SSFRFetchError(f"不支持的协议: {parsed.scheme}")
        host = parsed.hostname
        if not host:
            raise SSFRFetchError(f"无效 URL（无 host）: {url}")
        _check_host_allowed(host, allowed_hosts)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock, _ip = _connect(host, port, timeout, parsed.scheme)
        try:
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: FR-Worker/1.0\r\n"
                "Accept: application/pdf,*/*\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            sock.sendall(req.encode("utf-8"))
            reader = _SockReader(sock, max_bytes)
            header_blob = reader.read_until(b"\r\n\r\n")
            if header_blob is None:
                raise SSFRFetchError("响应头读取失败（连接关闭）")
            status, headers = _parse_status_and_headers(header_blob)

            if 300 <= status < 400 and "location" in headers:
                redirects += 1
                if redirects > max_redirects:
                    raise SSFRFetchError(f"重定向次数超限(>{max_redirects})")
                url = urllib.parse.urljoin(url, headers["location"])
                continue
            if status != 200:
                raise SSFRFetchError(f"HTTP {status} for {url}")

            # 响应体必须在 socket 关闭前完整读取；旧实现先 close 再读取，
            # 对真实远程 PDF 会稳定触发 Bad file descriptor。
            body = _read_body(reader, status, headers)
        finally:
            sock.close()

        if require_pdf:
            _validate_pdf(body, headers.get("content-type"))
        return body
