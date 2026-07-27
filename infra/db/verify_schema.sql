-- verify_schema.sql — W1-3 运行验收：迁移与种子落库检查
-- 用法: docker exec -i fr_postgres psql -U fr -d fr -f /dev/stdin < infra/db/verify_schema.sql
-- 或挂载后: docker exec fr_postgres psql -U fr -d fr -f /docker-entrypoint-initdb.d/../verify_schema.sql

\echo '=== 1. public 表清单 ==='
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;

\echo '=== 2. 关键唯一索引/部分索引 ==='
SELECT indexname, tablename
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'uq_disc_src_primary',
    'uq_current_disclosure_version',
    'uq_rep_canonical',
    'companies_pinyin_trgm',
    'idx_chunk_vec',
    'idx_disc_report'
  )
ORDER BY tablename, indexname;

\echo '=== 3. reports 一致性 CHECK 约束 ==='
SELECT conname, pg_get_constraintdef(oid) AS def
FROM pg_constraint
WHERE conrelid = 'reports'::regclass AND contype = 'c';

\echo '=== 4. 启用扩展 ==='
SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname;

\echo '=== 5. 种子公司数量与样本 ==='
SELECT count(*) AS company_count FROM companies;
SELECT code, name, exchange FROM companies ORDER BY code LIMIT 8;

\echo '=== 6. companies 搜索辅助列抽样 ==='
SELECT code, name, short_name, pinyin, aliases
FROM companies
WHERE code IN ('600519', '000001', '300750')
ORDER BY code;
