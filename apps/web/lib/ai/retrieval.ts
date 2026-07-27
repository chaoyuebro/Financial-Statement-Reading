// 检索抽象：Worker /internal/retrieve 为主路径，Postgres lexical BM25 为本地降级。
// 同时导出纯函数 lexicalSearch（用 lib/ai/core BM25）以便 BFF 在 worker 不可达时仍能跑通。

import { bm25Scores, financialPhraseBoost, type RetrievedChunk } from './core';
import { dbQuery } from '../db';

export interface RetrieveParams {
  reportId: string;
  question: string;
  topK?: number;
}

export interface RetrieveResult {
  chunks: RetrievedChunk[];
  source: 'worker-vector' | 'lexical' | 'empty';
  error?: string;
}

/**
 * 主路径：调用 worker /internal/retrieve。
 * 通过 WEB_INTERNAL_ENQUEUE_URL + WORKER_API_TOKEN（在 BFF 路由内读取 env）。
 */
export async function callWorkerRetrieve(
  endpoint: string,
  token: string,
  params: RetrieveParams,
): Promise<RetrieveResult> {
  const res = await fetch(`${endpoint.replace(/\/+$/, '')}/internal/retrieve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ report_id: params.reportId, question: params.question, top_k: params.topK ?? 8 }),
    // BFF 内部调用，给 worker 充足时间
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) {
    return { chunks: [], source: 'empty', error: `worker ${res.status}` };
  }
  const data = (await res.json()) as { chunks?: RetrievedChunk[]; error?: string };
  return { chunks: data.chunks ?? [], source: 'worker-vector', error: data.error };
}

/**
 * 本地降级：直接从 Postgres document_chunks 表读全文，在内存里跑 BM25。
 * 适用于 worker 不可达或 chunks 未向量化的情况。MVP 兜底，性能足以支撑小规模 chunks（<1k）。
 */
export async function lexicalSearch(params: RetrieveParams): Promise<RetrieveResult> {
  const topK = params.topK ?? 8;
  const rows = await dbQuery<{ page: number; seq: number; text: string }>(
    `SELECT page, seq, text FROM document_chunks WHERE report_id = $1 ORDER BY seq ASC LIMIT 2000`,
    [params.reportId],
  );
  if (rows.length === 0) return { chunks: [], source: 'empty' };
  const corpus = rows.map((r) => ({ page: r.page, seq: r.seq, text: r.text }));
  const scores = bm25Scores(corpus, params.question);
  const ranked = corpus
    .map((c, i) => ({
      ...c,
      score: scores[i] + financialPhraseBoost(c.text, params.question),
    }))
    .filter((c) => c.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);
  return { chunks: ranked, source: 'lexical' };
}
