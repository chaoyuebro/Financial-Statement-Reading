import { test } from 'node:test';
import assert from 'node:assert/strict';

import { financialPhraseBoost } from './core.ts';

test('financialPhraseBoost 优先完整财务指标短语', () => {
  const query = '营业收入和归母净利润分别是多少';
  const mainTable =
    '营业收入 168,838,102,514.79 归属于上市公司股东的净利润 82,320,067,101.68';
  const scattered = '公司分析了营业收入变化';
  assert.equal(financialPhraseBoost(mainTable, query), 40);
  assert.equal(financialPhraseBoost(scattered, query), 20);
});

test('financialPhraseBoost 不给无关问题加权', () => {
  assert.equal(financialPhraseBoost('营业收入 100 元', '公司有哪些风险'), 0);
});
