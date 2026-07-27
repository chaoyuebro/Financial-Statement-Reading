import { test } from 'node:test';
import assert from 'node:assert/strict';

import { chatComplete, type LlmConfig } from './client.ts';

test('chatComplete 支持 MiniMax Anthropic 兼容响应', async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = '';
  let requestHeaders: HeadersInit | undefined;
  let requestBody: Record<string, unknown> = {};

  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestHeaders = init?.headers;
    requestBody = JSON.parse(String(init?.body));
    return Response.json({
      id: 'msg_test',
      model: 'MiniMax-M3',
      content: [{ type: 'text', text: '测试回答 [page=6] 主表' }],
      usage: { input_tokens: 10, output_tokens: 8 },
    });
  };

  try {
    const cfg: LlmConfig = {
      apiBase: 'https://api.minimaxi.com/anthropic',
      apiKey: 'test-key',
      model: 'MiniMax-M3',
      style: 'anthropic',
      maxRetries: 0,
    };
    const result = await chatComplete(cfg, '系统提示', '用户问题');
    const headers = new Headers(requestHeaders);
    assert.equal(requestUrl, 'https://api.minimaxi.com/anthropic/v1/messages');
    assert.equal(headers.get('x-api-key'), 'test-key');
    assert.equal(headers.get('anthropic-version'), '2023-06-01');
    assert.equal(requestBody.model, 'MiniMax-M3');
    assert.equal(requestBody.system, '系统提示');
    assert.equal(result.model, 'MiniMax-M3');
    assert.equal(result.choices[0].message.content, '测试回答 [page=6] 主表');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
