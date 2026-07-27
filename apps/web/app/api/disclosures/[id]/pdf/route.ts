import { NextRequest } from 'next/server';
import { pgPool } from '@/lib/db';
import dns from 'node:dns/promises';
import fs from 'node:fs';
import path from 'node:path';
import { Readable } from 'node:stream';
import { Client as MinioClient } from 'minio';

// PDF 流式代理（§7.4）—— 支持 Range（pdf.js 按页懒加载依赖此能力）
// 源选择(主源→备用源) + SSRF 防护(域名白名单/禁内网/限大小) + 206 分片 + 对象存储签名URL优先
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const MAX_BYTES = 100 * 1024 * 1024; // §7.6 单次下载上限 100MB
const FETCH_TIMEOUT_MS = 60_000;

// 允许的上游域名白名单（§7.6）—— 仅这些域可被代理，其余一律拒绝
const ALLOWED_HOSTS = (process.env.FR_PDF_ALLOWED_HOSTS || 'static.cninfo.com.cn,pdf.dfcfw.com')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

function isPrivateIp(ip: string): boolean {
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && !ip.includes(':')) return false;
  if (ip.startsWith('::1') || ip === '0:0:0:0:0:0:0:1') return true;
  const p = ip.split('.').map(Number);
  if (p.length !== 4 || p.some((n) => Number.isNaN(n))) return false;
  return (
    p[0] === 10 ||
    p[0] === 127 ||
    p[0] === 169 || // 169.254.x.x 链路本地
    (p[0] === 172 && p[1] >= 16 && p[1] <= 31) ||
    (p[0] === 192 && p[1] === 168) ||
    (p[0] === 100 && p[1] >= 64 && p[1] <= 127) // CGNAT
  );
}

/** SSRF 防护：协议 + 域名白名单 + DNS 解析后禁内网（先解析再校验, 重定向后重新校验） */
async function isAllowedUrl(urlStr: string): Promise<boolean> {
  let u: URL;
  try {
    u = new URL(urlStr);
  } catch {
    return false;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
  if (!ALLOWED_HOSTS.includes(u.hostname)) return false;
  try {
    const { address } = await dns.lookup(u.hostname);
    if (isPrivateIp(address)) return false;
  } catch {
    return false; // 解析失败直接拒绝
  }
  return true;
}

/** 取该报告的 PDF 源 URL 列表：优先当前版本/主源，其次备用源（跨源归并, 保持同一 report_id） */
async function resolvePdfSources(id: string): Promise<string[]> {
  const res = await pgPool.query<{ pdf_url: string }>(
    `SELECT pdf_url FROM disclosures
     WHERE report_id = $1 AND pdf_url IS NOT NULL
     ORDER BY (is_current_version = true) DESC, (is_primary_source = true) DESC, created_at ASC`,
    [id],
  );
  return res.rows.map((r) => r.pdf_url).filter(Boolean);
}

async function resolveCachedObject(id: string): Promise<string | null> {
  const res = await pgPool.query<{ source: string; source_announcement_id: string }>(
    `SELECT source, source_announcement_id FROM disclosures
     WHERE report_id = $1
     ORDER BY (is_current_version = true) DESC, (is_primary_source = true) DESC, created_at ASC
     LIMIT 1`,
    [id],
  );
  const row = res.rows[0];
  return row ? `${id}/${row.source}:${row.source_announcement_id}.pdf` : null;
}

async function streamCachedPdf(id: string, req: NextRequest): Promise<Response | null> {
  const endpoint = process.env.MINIO_ENDPOINT;
  const accessKey = process.env.MINIO_ACCESS_KEY;
  const secretKey = process.env.MINIO_SECRET_KEY;
  if (!endpoint || !accessKey || !secretKey) return null;

  const objectName = await resolveCachedObject(id);
  if (!objectName) return null;
  const [host, portText] = endpoint.split(':');
  const client = new MinioClient({
    endPoint: host,
    port: Number(portText || (process.env.MINIO_SECURE === 'true' ? 443 : 80)),
    useSSL: process.env.MINIO_SECURE === 'true',
    accessKey,
    secretKey,
  });
  const bucket = process.env.MINIO_BUCKET || 'fr-pdf';
  try {
    const stat = await client.statObject(bucket, objectName);
    const total = stat.size;
    const range = req.headers.get('range');
    const m = range ? /bytes=(\d*)-(\d*)/.exec(range) : null;
    let start = 0;
    let end = total - 1;
    if (m) {
      start = m[1] ? parseInt(m[1], 10) : 0;
      end = m[2] ? Math.min(parseInt(m[2], 10), total - 1) : total - 1;
      if (start > end || start >= total) {
        return new Response('Range Not Satisfiable', {
          status: 416,
          headers: { 'Content-Range': `bytes */${total}` },
        });
      }
    }
    const length = end - start + 1;
    const stream = m
      ? await client.getPartialObject(bucket, objectName, start, length)
      : await client.getObject(bucket, objectName);
    const headers: Record<string, string> = {
      'Content-Type': 'application/pdf',
      'Accept-Ranges': 'bytes',
      'Content-Length': String(length),
      'Cache-Control': 'private, max-age=300',
    };
    if (m) headers['Content-Range'] = `bytes ${start}-${end}/${total}`;
    return new Response(Readable.toWeb(stream) as unknown as BodyInit, {
      status: m ? 206 : 200,
      headers,
    });
  } catch {
    return null;
  }
}

/** 安全上游拉取：重定向手动跟随并重新校验；非 PDF / 4xx 返回 null 以便回退备用源 */
async function safeFetch(
  url: string,
  range: string | null,
  depth: number,
): Promise<Response | null> {
  if (depth > 3) return null;
  try {
    const upstream = await fetch(url, {
      headers: range ? { Range: range } : {},
      redirect: 'manual',
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    // 3xx：抽取 Location 重新校验后递归一次
    if (upstream.status >= 300 && upstream.status < 400) {
      const loc = upstream.headers.get('location');
      if (loc) {
        const abs = new URL(loc, url).toString();
        if (await isAllowedUrl(abs)) return safeFetch(abs, range, depth + 1);
      }
      return null;
    }
    if (upstream.status === 404 || upstream.status === 403) return null; // 主源失败 → 试备用源
    if (!upstream.ok) return null;
    const ct = upstream.headers.get('content-type') || '';
    if (!ct.includes('pdf')) return null; // §7.6 非 PDF 直接丢弃
    const cl = Number(upstream.headers.get('content-length') || '0');
    if (cl > MAX_BYTES) return null; // §7.6 资源上限

    const headers = new Headers();
    headers.set('Content-Type', 'application/pdf');
    headers.set('Accept-Ranges', 'bytes');
    headers.set('Cache-Control', 'private, max-age=300');
    if (upstream.headers.get('content-range'))
      headers.set('Content-Range', upstream.headers.get('content-range')!);
    if (upstream.headers.get('content-length'))
      headers.set('Content-Length', upstream.headers.get('content-length')!);
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return null;
  }
}

/** 开发期本地 fixture 回退：便于无外网环境下验证 Range / 渲染 / 跳页（生产不启用） */
function streamLocalFixture(name: string, req: NextRequest): Response {
  const safe = path.basename(name); // 防路径穿越
  const file = path.join(process.cwd(), 'public', 'fixtures', safe);
  if (!fs.existsSync(file)) return new Response('fixture not found', { status: 404 });
  const total = fs.statSync(file).size;
  const range = req.headers.get('range');
  const streamToWeb = (s: fs.ReadStream) => Readable.toWeb(s) as unknown as BodyInit;

  const m = range ? /bytes=(\d*)-(\d*)/.exec(range) : null;
  if (m) {
    let start = m[1] ? parseInt(m[1], 10) : 0;
    let end = m[2] ? parseInt(m[2], 10) : total - 1;
    if (start > end || start >= total) {
      return new Response('Range Not Satisfiable', {
        status: 416,
        headers: { 'Content-Range': `bytes */${total}` },
      });
    }
    end = Math.min(end, total - 1);
    const s = fs.createReadStream(file, { start, end });
    return new Response(streamToWeb(s), {
      status: 206,
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Range': `bytes ${start}-${end}/${total}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': String(end - start + 1),
        'Cache-Control': 'no-store',
      },
    });
  }
  const s = fs.createReadStream(file);
  return new Response(streamToWeb(s), {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Accept-Ranges': 'bytes',
      'Content-Length': String(total),
      'Cache-Control': 'no-store',
    },
  });
}

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const devFixture = req.nextUrl.searchParams.get('devFixture');
  const asDownload = req.nextUrl.searchParams.get('download') === '1';
  const finalize = (response: Response): Response => {
    if (!asDownload) return response;
    const headers = new Headers(response.headers);
    headers.set('Content-Disposition', `attachment; filename="report-${params.id}.pdf"`);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  };

  // 开发/测试模式：用本地 fixture 验证 Range/渲染/跳页。
  // 须显式开启 FR_ALLOW_DEV_FIXTURE=1（默认关闭，生产绝不暴露 fixture 回退）
  if (
    process.env.NODE_ENV !== 'production' &&
    devFixture &&
    process.env.FR_ALLOW_DEV_FIXTURE === '1'
  ) {
    return finalize(streamLocalFixture(devFixture, req));
  }

  const cached = await streamCachedPdf(params.id, req);
  if (cached) return finalize(cached);

  const sources = await resolvePdfSources(params.id);
  if (!sources.length) return new Response('not found', { status: 404 });

  const range = req.headers.get('range');
  for (const url of sources) {
    if (!(await isAllowedUrl(url))) continue; // SSRF：非法源跳过
    const r = await safeFetch(url, range, 0);
    if (r) return finalize(r);
  }
  return new Response('PDF unavailable', { status: 502 });
}
