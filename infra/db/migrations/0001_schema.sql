-- ============================================================================
-- 0001_schema.sql — 财报/招股书辅助阅读工具 核心数据模型
-- 对齐《技术方案文档.md》§4（v1.0 冻结基线）
-- 运行顺序：本文件由 postgres 容器首次启动自动执行（/docker-entrypoint-initdb.d），
--           或经 migrate 工具手动执行。必须早于任何含 vector / trgm 的表。
-- ============================================================================

-- 扩展（须在含 vector(512) / gin_trgm_ops 的表之前创建）
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector：文档分块向量检索
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- 名称模糊/前缀搜索（PRD F-102）

-- ----------------------------------------------------------------------------
-- 公司（种子 20–50 家，覆盖三交易所）—— 详见 0002_seed_companies.sql
-- ----------------------------------------------------------------------------
CREATE TABLE companies (
  code         TEXT PRIMARY KEY,       -- '600519'
  name         TEXT NOT NULL,          -- 全称, e.g. '贵州茅台酒股份有限公司'
  short_name   TEXT,                   -- 简称, e.g. '茅台'
  former_names TEXT[],                 -- 历史名称(更名前)
  aliases      TEXT[],                 -- 别名/俗称
  pinyin       TEXT,                   -- 全拼(可选, 助搜 'maotai')
  org_id       TEXT,                   -- 巨潮 orgId, e.g. 'gssh0600519'
  exchange     TEXT NOT NULL           -- 'sh'|'sz'|'bse'
);
-- 模糊/前缀搜索索引(PRD F-102: 全称/简称/模糊名称)
CREATE INDEX idx_company_name_trgm  ON companies USING gin (name gin_trgm_ops);
CREATE INDEX idx_company_short_trgm ON companies USING gin (short_name gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 规范报告：用户视角的"一份报告" = 一家公司 + 一个报告期 + 一个报告类型**仅一行**
-- 主键为应用层生成的内部 UUID，不依赖任何数据源 ID → 跨源 ID 永不碰撞
-- ----------------------------------------------------------------------------
CREATE TABLE reports (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 内部报告 ID（对外 API / 全系统引用皆此值）
  company_code      TEXT REFERENCES companies(code),
  type              TEXT NOT NULL,       -- 'annual'|'halfyear'|'quarterly'|'prospectus'
  report_period     TEXT,                -- '2023'|'2023Q1'|'2023H1'
  canonical_key     TEXT UNIQUE,         -- '{company_code}:{type}:{report_period}' — 一份报告一个首页记录
                                         --   (NULL=报告期未定, 进复核, 不参与跨源归并; reports 仅一行/键, 修订版不新建行故不冲突)
  report_period_unknown BOOLEAN NOT NULL DEFAULT false, -- 报告期未确定(临时记录, 进复核队列, 不进正式列表)
  title             TEXT,
  disclosure_date   DATE,
  primary_source    TEXT NOT NULL DEFAULT 'cninfo', -- 归并后主源(默认巨潮); 巨潮失效可切 eastmoney(保持同 id)
  status            TEXT NOT NULL DEFAULT 'pending', -- 见状态机(报告级): pending→downloaded→parsed→embedded→metrics_done→ready / failed
  is_withdrawn      BOOL DEFAULT false,  -- 公告撤回/取消(§5.2)
  created_at        TIMESTAMPTZ DEFAULT now(),
  -- 状态一致性约束: 本系统中 canonical_key 为 NULL 仅发生于报告期未定, 二者必须同步
  -- (若未来出现其他 NULL canonical_key 的原因, 须改为服务层校验并移除本 CHECK)
  CONSTRAINT chk_rep_period_known CHECK (
    (report_period_unknown = true  AND report_period IS NULL AND canonical_key IS NULL)
    OR
    (report_period_unknown = false AND report_period IS NOT NULL AND canonical_key IS NOT NULL)
  )
);
CREATE INDEX idx_rep_list ON reports(disclosure_date DESC, type, company_code);

-- ----------------------------------------------------------------------------
-- 披露来源/版本记录：每个数据源 / 每个版本一行
--   (巨潮/东财 × 原版/修订版/补充版分别保存)
-- 同源天然唯一(复合主键); 经 report_id 归并到同一 reports(一个 report 仅一条首页记录)
-- ★ 修正原"id 直接取官方公告 ID 且全局唯一"假设: 巨潮/东财 ID 可能碰撞, 同报告双源会重复
-- ★ 版本状态(is_current_version)放在 disclosures, 不再放 reports —— 否则"完整修订版=新 reports 行"会与 canonical_key UNIQUE 冲突
-- ----------------------------------------------------------------------------
CREATE TABLE disclosures (
  source                  TEXT NOT NULL CHECK (source IN ('cninfo','eastmoney')),
  source_announcement_id  TEXT NOT NULL,           -- 巨潮 announcementId / 东财 art_code
  report_id               UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  company_code            TEXT REFERENCES companies(code),
  type                    TEXT NOT NULL,
  report_period           TEXT,
  report_period_unknown   BOOL DEFAULT false,       -- 报告期无法确定(进复核队列, 不进正式列表)
  title                   TEXT,
  disclosure_date         DATE,
  pdf_url                 TEXT,                     -- 本源 PDF 下载地址
  adjunct_url             TEXT,                     -- 巨潮 adjunctUrl(拼真实地址用)
  is_primary_source       BOOL NOT NULL DEFAULT false, -- cninfo=true; 东财=false(备用下载地址)
  is_current_version      BOOL DEFAULT false,       -- 当前阅读主版本(同 report_id 下仅一个 true)
  supersedes_source       TEXT,                    -- 被本版本取代的来源(更正/修订链路)
  supersedes_announcement_id TEXT,                 -- 被本版本取代的公告 ID
  cached_pdf              BOOL DEFAULT false,       -- 是否落盘副本(7.3合规开关)
  created_at              TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (source, source_announcement_id)     -- 复合主键: 单源内天然唯一, 杜绝跨源 ID 碰撞
);
CREATE INDEX idx_disc_report ON disclosures(report_id);
-- 部分唯一索引: 同一 report 至多一个主源记录(巨潮优先; 失效切换备用源须在同一事务内翻转)
CREATE UNIQUE INDEX uq_disc_src_primary
  ON disclosures(report_id) WHERE is_primary_source = true;
-- 部分唯一索引: 同一 report 仅一个当前阅读版本(切换版本时须在同一事务内翻转 is_current_version)
CREATE UNIQUE INDEX uq_current_disclosure_version
  ON disclosures(report_id) WHERE is_current_version = true;

-- ----------------------------------------------------------------------------
-- 解析任务（每阶段一行, 支持重试 + 租约 + 去重）
-- 注意: report_id 引用 reports(id) 且**无 ON DELETE CASCADE** ——
--       临时报告(未知期)禁止生成 parse_jobs, 故合并删除临时 reports 时不会有残留任务触发外键冲突
-- ----------------------------------------------------------------------------
CREATE TABLE parse_jobs (
  id               TEXT PRIMARY KEY,
  report_id        UUID NOT NULL REFERENCES reports(id),
  source           TEXT NOT NULL CHECK (source IN ('cninfo','eastmoney')), -- 本次处理所用源(默认主源)
  stage            TEXT NOT NULL,          -- download|parse|embed|metrics
  status           TEXT NOT NULL,          -- pending|running|done|failed
  attempts         INT DEFAULT 0,
  last_error       TEXT,
  payload          JSONB,
  lease_token      TEXT,                   -- 任务租约(防 Worker 崩溃后任务卡 running)
  lease_expires_at TIMESTAMPTZ,            -- 租约过期时间; 过期允许其他 Worker 接管
  UNIQUE (report_id, stage)                -- 评审要求: 同阶段不重复入队
);

-- ----------------------------------------------------------------------------
-- 文档分块（向量检索的检索单元）
-- ----------------------------------------------------------------------------
CREATE TABLE document_chunks (
  id            BIGSERIAL PRIMARY KEY,
  report_id     UUID REFERENCES reports(id),
  version_tag   TEXT NOT NULL,         -- 产生该产物的披露版本 = disclosures 的 'source:source_announcement_id'(修订后重跑, 整批替换为新版本)
  page          INT NOT NULL,          -- ★ 页码(预研#3: 稳定映射)
  seq           INT NOT NULL,
  text          TEXT NOT NULL,
  embedding     vector(512),           -- 维度随嵌入模型; MVP 固定 bge-small-zh(512) 以锁定维度与索引
  meta          JSONB                  -- {section, is_table, ...}
);
CREATE INDEX idx_chunk_rep ON document_chunks(report_id, page);
CREATE INDEX idx_chunk_vec  ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);

-- ----------------------------------------------------------------------------
-- 关键指标卡片（预研#4: 三项首版）
-- ----------------------------------------------------------------------------
CREATE TABLE metrics (
  id            BIGSERIAL PRIMARY KEY,
  report_id     UUID REFERENCES reports(id),
  version_tag   TEXT NOT NULL,         -- 产生该指标卡的披露版本(同 document_chunks, 修订后重跑重新生成)
  name          TEXT NOT NULL,         -- 'revenue'|'net_profit_attr'|'op_cash_flow'
  source_value  NUMERIC,               -- 原始抽取值(通常为年初至报告期末累计)
  value         NUMERIC,               -- 对外展示值(=source_value 或派生值)
  derived_value NUMERIC,               -- 派生值(如单季=累计差), 无则为 NULL
  calculation_formula TEXT,            -- 派生公式, e.g. 'q3_cum - h1_cum'
  is_derived    BOOLEAN DEFAULT false, -- 是否为跨期计算结果
  period_type   TEXT,                  -- 'annual'|'h1'|'q1'|'q3' (报告期类型)
  value_scope   TEXT,                  -- 'year_to_date'|'single_period'
  unit          TEXT DEFAULT '元',
  yoy           NUMERIC,               -- 同比%(需跨期, MVP 仅在可用时计算)
  qoq           NUMERIC,               -- 环比%(MVP 季报不展示, 见 6.5)
  page          INT,                   -- 出处页码
  caliber       TEXT,                  -- '合并'|'母公司'|'归母'
  confidence    NUMERIC
);

-- ----------------------------------------------------------------------------
-- 对话（匿名: 仅会话内, localStorage 也可; 登录后云同步）
-- ----------------------------------------------------------------------------
CREATE TABLE chat_sessions (
  id            TEXT PRIMARY KEY,
  report_id     UUID REFERENCES reports(id),
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE chat_messages (
  id            BIGSERIAL PRIMARY KEY,
  session_id    TEXT REFERENCES chat_sessions(id),
  role          TEXT NOT NULL,         -- 'user'|'assistant'
  content       TEXT,
  citations     JSONB                  -- [{page, text}] 预研#5: 强制引用
);
