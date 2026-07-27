-- ============================================================================
-- fixtures_dev.sql — 开发期验证数据（W2 BFF 联调用，NOT 自动执行）
-- 不放在 migrations/ 下，故不会被 compose 的 initdb.d 自动跑；仅手动灌入运行库。
-- 真实数据由 Worker 管线（W3+）抓取写入，本文件仅用于本地联调。
-- ============================================================================

-- 报告（reports）：一份报告一行；canonical_key 全局唯一
INSERT INTO reports (id, company_code, type, report_period, canonical_key, report_period_unknown, title, disclosure_date, primary_source, status) VALUES
  ('a1111111-1111-1111-1111-111111111111', '600519', 'annual',    '2023',    '600519:annual:2023',    false, '贵州茅台 2023 年年度报告',             '2024-03-20', 'cninfo', 'ready'),
  ('a2222222-2222-2222-2222-222222222222', '600519', 'halfyear', '2023H1',  '600519:halfyear:2023H1', false, '贵州茅台 2023 年半年度报告',           '2023-08-08', 'cninfo', 'ready'),
  ('a3333333-3333-3333-3333-333333333333', '600519', 'quarterly','2023Q1',  '600519:quarterly:2023Q1', false, '贵州茅台 2023 年第一季度报告',         '2023-04-25', 'cninfo', 'ready'),
  ('a4444444-4444-4444-4444-444444444444', '601318', 'annual',    '2023',    '601318:annual:2023',    false, '中国平安 2023 年年度报告',             '2024-03-22', 'cninfo', 'ready'),
  ('a5555555-5555-5555-5555-555555555555', '000001', 'annual',    '2023',    '000001:annual:2023',    false, '平安银行 2023 年年度报告',             '2024-03-15', 'cninfo', 'ready'),
  ('a6666666-6666-6666-6666-666666666666', '300750', 'annual',    '2023',    '300750:annual:2023',    false, '宁德时代 2023 年年度报告',             '2024-03-16', 'cninfo', 'ready'),
  ('a7777777-7777-7777-7777-777777777777', '300750', 'quarterly','2023Q3',  '300750:quarterly:2023Q3', false, '宁德时代 2023 年第三季度报告',         '2023-10-20', 'cninfo', 'ready'),
  ('a8888888-8888-8888-8888-888888888888', '002594', 'annual',    '2023',    '002594:annual:2023',    false, '比亚迪 2023 年年度报告',               '2024-03-27', 'cninfo', 'ready'),
  ('a9999999-9999-9999-9999-999999999999', '835185', 'annual',    '2023',    '835185:annual:2023',    false, '贝特瑞 2023 年年度报告',               '2024-04-10', 'cninfo', 'ready'),
  ('abbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '600519', 'annual',    '2022',    '600519:annual:2022',    false, '贵州茅台 2022 年年度报告',             '2023-03-30', 'cninfo', 'ready')
ON CONFLICT (canonical_key) DO NOTHING;

-- 披露来源记录（disclosures）：复合主键 (source, source_announcement_id)；巨潮主源
-- 注意：disclosures 已无 canonical_key 冗余列（经 report_id 关联 reports）
INSERT INTO disclosures (source, source_announcement_id, report_id, company_code, type, report_period, report_period_unknown, title, disclosure_date, pdf_url, is_primary_source) VALUES
  ('cninfo', 'cn-600519-2023-an','a1111111-1111-1111-1111-111111111111', '600519', 'annual',    '2023',   false, '贵州茅台 2023 年年度报告', '2024-03-20', 'http://static.cninfo.com.cn/maotai2023.pdf', true),
  ('cninfo', 'cn-600519-2023-h1','a2222222-2222-2222-2222-222222222222', '600519', 'halfyear', '2023H1', false, '贵州茅台 2023 年半年度报告', '2023-08-08', 'http://static.cninfo.com.cn/maotai2023h1.pdf', true),
  ('cninfo', 'cn-600519-2023-q1','a3333333-3333-3333-3333-333333333333', '600519', 'quarterly','2023Q1', false, '贵州茅台 2023 年第一季度报告', '2023-04-25', 'http://static.cninfo.com.cn/maotai2023q1.pdf', true),
  ('cninfo', 'cn-601318-2023-an','a4444444-4444-4444-4444-444444444444', '601318', 'annual',    '2023',   false, '中国平安 2023 年年度报告', '2024-03-22', 'http://static.cninfo.com.cn/pingan2023.pdf', true),
  ('cninfo', 'cn-000001-2023-an','a5555555-5555-5555-5555-555555555555', '000001', 'annual',    '2023',   false, '平安银行 2023 年年度报告', '2024-03-15', 'http://static.cninfo.com.cn/pinganbank2023.pdf', true),
  ('cninfo', 'cn-300750-2023-an','a6666666-6666-6666-6666-666666666666', '300750', 'annual',    '2023',   false, '宁德时代 2023 年年度报告', '2024-03-16', 'http://static.cninfo.com.cn/catl2023.pdf', true),
  ('cninfo', 'cn-300750-2023-q3','a7777777-7777-7777-7777-777777777777', '300750', 'quarterly','2023Q3', false, '宁德时代 2023 年第三季度报告', '2023-10-20', 'http://static.cninfo.com.cn/catl2023q3.pdf', true),
  ('cninfo', 'cn-002594-2023-an','a8888888-8888-8888-8888-888888888888', '002594', 'annual',    '2023',   false, '比亚迪 2023 年年度报告', '2024-03-27', 'http://static.cninfo.com.cn/byd2023.pdf', true),
  ('cninfo', 'cn-835185-2023-an','a9999999-9999-9999-9999-999999999999', '835185', 'annual',    '2023',   false, '贝特瑞 2023 年年度报告', '2024-04-10', 'http://static.cninfo.com.cn/btl2023.pdf', true),
  ('cninfo', 'cn-600519-2022-an','abbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '600519', 'annual',    '2022',   false, '贵州茅台 2022 年年度报告', '2023-03-30', 'http://static.cninfo.com.cn/maotai2022.pdf', true)
ON CONFLICT (source, source_announcement_id) DO NOTHING;
