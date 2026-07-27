// 提示注入防护（§7.3 安全护栏 1）+ 引用二次校验（§7.3 安全护栏 2）。
// 思路：模型输入前的检索片段先做 sanitizeChunk，再喂给 LLM；LLM 输出后再次校验引用。

import { sanitizeChunk, revalidateCitations, type RetrievedChunk } from './core';
import type { Citation } from '@fr/shared';

/** 过滤检索片段：剥离控制字符与指令性文本，统一为干净上下文。 */
export function sanitizeChunks(chunks: RetrievedChunk[]): RetrievedChunk[] {
  return chunks.map((c) => ({ ...c, text: sanitizeChunk(c.text) })).filter((c) => c.text.length > 0);
}

/**
 * 对模型产出的引用做二次校验：仅保留 (page,text) 命中检索片段集合的引用。
 * 模型可能产出虚假的页码/片段，本护栏强制只保留真实命中的引用。
 */
export function filterCitations(
  citations: Citation[],
  retrieved: RetrievedChunk[],
): Citation[] {
  const { kept } = revalidateCitations(citations, retrieved);
  return kept;
}

/** 构造 RAG 上下文（prompt 中的 system 引用块）。限制长度防止超 token。 */
export function buildRagContext(
  chunks: RetrievedChunk[],
  maxChars = 6000,
): string {
  const lines: string[] = [];
  let used = 0;
  for (const c of chunks) {
    const snippet = c.text.length > 800 ? c.text.slice(0, 800) + '…' : c.text;
    const line = `[page=${c.page}] ${snippet}`;
    if (used + line.length > maxChars) break;
    lines.push(line);
    used += line.length;
  }
  return lines.join('\n');
}