// LLM 客户端（OpenAI 兼容 chat/completions）+ 抽取式降级。
// 适配 DeepSeek / OpenAI / 任意 chat/completions 端点，通过环境变量切换。

export interface ChatChoice {
  message: { role: string; content: string };
}

export interface ChatResponseRaw {
  choices: ChatChoice[];
  model?: string;
}

export interface LlmConfig {
  apiBase: string; // e.g. https://api.deepseek.com/v1
  apiKey: string;
  model: string;
  style: 'openai' | 'anthropic';
  timeoutMs?: number;
  maxRetries?: number;
}

export function loadLlmConfig(): LlmConfig | null {
  const apiKey = process.env.LLM_API_KEY;
  const apiBase = process.env.LLM_API_BASE ?? 'https://api.deepseek.com/v1';
  const model = process.env.LLM_MODEL ?? 'deepseek-chat';
  const style = process.env.LLM_API_STYLE === 'anthropic' ? 'anthropic' : 'openai';
  if (!apiKey) return null; // 触发降级
  return { apiBase, apiKey, model, style, timeoutMs: 60000, maxRetries: 1 };
}

/** 单次 chat 调用（含轻量指数退避重试）。失败抛异常，调用方决定是否降级。 */
export async function chatComplete(
  cfg: LlmConfig,
  system: string,
  user: string,
): Promise<ChatResponseRaw> {
  const anthropic = cfg.style === 'anthropic';
  const url = anthropic
    ? `${cfg.apiBase.replace(/\/+$/, '')}/v1/messages`
    : `${cfg.apiBase.replace(/\/+$/, '')}/chat/completions`;
  const body = anthropic
    ? {
        model: cfg.model,
        max_tokens: 1200,
        temperature: 0.2,
        system,
        messages: [{ role: 'user', content: [{ type: 'text', text: user }] }],
        thinking: { type: 'disabled' },
      }
    : {
        model: cfg.model,
        temperature: 0.2,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content: user },
        ],
      };
  let attempt = 0;
  const max = cfg.maxRetries ?? 1;
  let lastErr: unknown;
  while (attempt <= max) {
    const ctl = new AbortController();
    const tid = setTimeout(() => ctl.abort(), cfg.timeoutMs ?? 20000);
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(anthropic
            ? { 'x-api-key': cfg.apiKey, 'anthropic-version': '2023-06-01' }
            : { Authorization: `Bearer ${cfg.apiKey}` }),
        },
        body: JSON.stringify(body),
        signal: ctl.signal,
      });
      clearTimeout(tid);
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(`LLM ${res.status}: ${txt.slice(0, 200)}`);
      }
      const payload = (await res.json()) as ChatResponseRaw & {
        content?: { type: string; text?: string }[];
      };
      if (!anthropic) return payload;
      const content =
        payload.content
          ?.filter((block) => block.type === 'text')
          .map((block) => block.text ?? '')
          .join('') ?? '';
      return {
        model: payload.model,
        choices: [{ message: { role: 'assistant', content } }],
      };
    } catch (e) {
      clearTimeout(tid);
      lastErr = e;
      attempt += 1;
      if (attempt > max) break;
      await new Promise((r) => setTimeout(r, 250 * attempt));
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('LLM call failed');
}

/**
 * 抽取式降级：未配置 LLM 或调用失败时，直接拼接 top 1~2 个检索片段作为答案，
 * 并以这些片段本身作为引用。属于 MVP 安全兜底（§7.3 §MVP 降级）。
 */
export function extractiveFallback(
  question: string,
  chunks: { page: number; seq?: number; text: string; score?: number }[],
): { answer: string; citations: { page: number; text: string; score?: number }[] } {
  const top = chunks.slice(0, 2);
  if (top.length === 0) {
    return { answer: `未找到与「${question}」相关的披露内容。`, citations: [] };
  }
  const answer = top.map((c) => c.text.slice(0, 220)).join('\n\n');
  return {
    answer,
    citations: top.map((c) => ({ page: c.page, text: c.text, score: c.score })),
  };
}
