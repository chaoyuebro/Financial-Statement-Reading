// AI 纯逻辑核心（无外部运行时依赖，可 node --experimental-strip-types 单测）。
// 移植自 worker/retrieval.py 的 BM25 / RRF 思路 + §7.3 引用二次校验 / 提示注入防护。

export interface RetrievedChunk {
  page: number;
  seq?: number;
  text: string;
  score?: number;
}

// 粗分词：CJK 单字 + 英文/数字词（与 worker retrieval.py 一致）
const TOKEN_RE = /[一-鿿]|[A-Za-z0-9]+/g;

export function tokenize(text: string): string[] {
  return text.toLowerCase().match(TOKEN_RE) ?? [];
}

/** BM25 打分（对齐 worker retrieval.bm25_scores）。返回与 corpus 等长的分数数组。 */
export function bm25Scores(corpus: { text: string }[], query: string): number[] {
  const qTok = tokenize(query);
  const n = corpus.length;
  if (n === 0 || qTok.length === 0) return new Array(n).fill(0);

  const df: Record<string, number> = {};
  for (const c of corpus) {
    const toks = new Set(tokenize(c.text));
    for (const t of qTok) if (toks.has(t)) df[t] = (df[t] ?? 0) + 1;
  }
  const idf: Record<string, number> = {};
  for (const t of qTok) {
    idf[t] = Math.log((n - (df[t] ?? 0) + 0.5) / ((df[t] ?? 0) + 0.5) + 1);
  }
  const k1 = 1.5;
  const b = 0.75;
  const lens = corpus.map((c) => tokenize(c.text).length);
  const avg = lens.reduce((a, x) => a + x, 0) / n;

  return corpus.map((c, i) => {
    const toks = tokenize(c.text);
    const tf: Record<string, number> = {};
    for (const t of toks) tf[t] = (tf[t] ?? 0) + 1;
    let score = 0;
    for (const t of qTok) {
      const f = tf[t];
      if (!f) continue;
      const denom = f + k1 * (1 - b + (b * lens[i]) / Math.max(avg, 1));
      score += (idf[t] ?? 0) * ((f * (k1 + 1)) / denom);
    }
    return score;
  });
}

export function buildRetrievalKey(page: number, text: string): string {
  return `${page}::${text}`;
}

const FINANCIAL_PHRASES = [
  ['营业收入', '营收'],
  ['归属于上市公司股东的净利润', '归母净利润'],
  ['经营活动产生的现金流量净额', '经营现金流'],
] as const;

/** 对指标类问题增加完整短语命中奖励，避免单字 BM25 把零散命中的正文排在主表前。 */
export function financialPhraseBoost(text: string, query: string): number {
  let score = 0;
  for (const aliases of FINANCIAL_PHRASES) {
    if (!aliases.some((term) => query.includes(term))) continue;
    if (aliases.some((term) => text.includes(term))) score += 20;
  }
  return score;
}

/**
 * 引用二次校验（§7.3 安全护栏 2）：仅保留 (page,text) 命中检索片段集合的引用。
 * 返回 (kept, dropped)。模型产出的引用若不在检索集合内一律丢弃。
 */
export function revalidateCitations(
  citations: { page: number; text: string }[],
  retrieved: RetrievedChunk[],
): { kept: { page: number; text: string }[]; dropped: { page: number; text: string }[] } {
  const allowed = new Set(retrieved.map((c) => buildRetrievalKey(c.page, c.text)));
  const kept: { page: number; text: string }[] = [];
  const dropped: { page: number; text: string }[] = [];
  for (const cit of citations) {
    if (allowed.has(buildRetrievalKey(cit.page, cit.text))) kept.push(cit);
    else dropped.push(cit);
  }
  return { kept, dropped };
}

// 提示注入防护（§7.3）：剥离检索片段中的控制字符与明显指令性文本，降低数据投毒风险。
const INJECTION_PATTERNS = [
  /ignore (?:all |any |the )?(?:previous|above|prior) (?:instructions|prompt)s?/gi,
  /disregard (?:the )?(?:above|previous) (?:instructions|prompt)/gi,
  /you are now\b/gi,
  /system prompt/gi,
  /\bassistant\s*:/gi,
  /<\s*(?:system|assistant|user)\s*>/gi,
];

export function sanitizeChunk(text: string): string {
  // 去控制字符（保留换行 \n / 制表 \t / 回车 \r），再剥离指令性文本，压缩多余空白
  let t = text.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, ' ');
  for (const re of INJECTION_PATTERNS) t = t.replace(re, '');
  return t.replace(/\s{2,}/g, ' ').trim();
}

/** 清理模型回答时保留 Markdown 所需换行，仅压缩行内空白。 */
export function normalizeAnswerMarkdown(text: string): string {
  return text
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
