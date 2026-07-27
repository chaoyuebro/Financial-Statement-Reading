-- ============================================================================
-- 0003_disclosure_toc.sql — W3 阅读页所需目录列
-- 对齐《技术方案文档.md》§7.2（detail 契约返回 toc:[{title,page}]）。
-- parser 写入 disclosures.toc（书签 / 反推兜底），BFF 读取后供 TOC 面板跳页。
-- IF NOT EXISTS 保证重复执行（如本地手动 ALTER 后重跑）不报错。
-- ============================================================================

ALTER TABLE disclosures ADD COLUMN IF NOT EXISTS toc JSONB;

COMMENT ON COLUMN disclosures.toc IS
  '目录(JSONB 数组: [{title,page,level?}]), parser 产出, 供阅读页 TOC 跳页与引用定位';
