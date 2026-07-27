// 共享契约（TS 侧）。Python 侧在 apps/worker 维护镜像，保持字段/语义一致。
// 来源：《技术方案文档》§4 数据模型 / §7.2 列表 API / §7.5 搜索。

/** 报告类型 */
export type DisclosureType = 'annual' | 'halfyear' | 'quarterly' | 'prospectus';

/** 交易所 */
export type Exchange = 'sh' | 'sz' | 'bse';

/** 报告级状态机（见 §5，对齐 reports.status 状态链）
 * pending→downloaded→parsed→embedded→metrics_done→ready / failed
 * 含进行态别名(downloading/parsing/embedding/extracting)以兼容过渡展示。 */
export type DisclosureStatus =
  | 'pending'
  | 'downloading'
  | 'downloaded'
  | 'parsing'
  | 'parsed'
  | 'embedding'
  | 'embedded'
  | 'extracting'
  | 'metrics_done'
  | 'ready'
  | 'failed'
  | 'withdrawn';

/** 数据源（归并后主源） */
export type DataSource = 'cninfo' | 'eastmoney';

/** 列表项（首页 / 列表页使用） */
export interface DisclosureListItem {
  id: string; // reports.id（内部 UUID，全系统引用锚点）
  companyCode: string; // '600519'
  companyName: string;
  type: DisclosureType;
  reportPeriod: string; // '2023' | '2023Q1' | '2023H1'
  disclosureDate: string; // ISO date (YYYY-MM-DD)
  status: DisclosureStatus;
  primarySource: DataSource;
}

/** 列表查询参数（§7.2） */
export interface ListQuery {
  type?: DisclosureType;
  exchange?: Exchange;
  q?: string; // 名称 / 代码 模糊
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
}

/** 列表响应（§7.2） */
export interface ListResponse {
  items: DisclosureListItem[];
  total: number;
  hasMore: boolean;
}

/** 目录项（parser 产出 / 反推兜底，§8.2 / §7.2 detail） */
export interface TocItem {
  title: string; // 章节标题
  page: number; // 页码（pdf.js 稳定映射, 预研#3）
  level?: number; // 层级（1=章, 2=节…）
}

/** 报告详情（§7.2 GET /api/disclosures/[id]） */
export interface DisclosureDetail extends DisclosureListItem {
  toc: TocItem[];
  metricsCached: boolean; // 指标卡是否已预计算
}

export const TYPE_LABELS: Record<DisclosureType, string> = {
  annual: '年报',
  halfyear: '半年报',
  quarterly: '季报',
  prospectus: '招股书',
};

export const EXCHANGE_LABELS: Record<Exchange, string> = {
  sh: '上交所',
  sz: '深交所',
  bse: '北交所',
};

export const STATUS_LABELS: Record<DisclosureStatus, string> = {
  pending: '待处理',
  downloading: '下载中',
  downloaded: '已下载',
  parsing: '解析中',
  parsed: '已解析',
  embedding: '向量化中',
  embedded: '已向量化',
  extracting: '抽取中',
  metrics_done: '指标已抽取',
  ready: '已就绪',
  failed: '失败',
  withdrawn: '已撤回',
};

/** 代码归一化：去除 .SH / .SZ / .BJ 后缀，转大写（§7.5） */
export function normalizeStockCode(raw: string): string {
  return raw.trim().toUpperCase().replace(/\.(SH|SZ|BJ)$/, '');
}

// ---------------------------------------------------------------------------
// AI 核心契约（§6.5 / §7.3 / §8.2）—— Web BFF 与 Worker 共享，字段语义一致
// ---------------------------------------------------------------------------

/** 指标卡（metrics 表映射，§6.5）。三项：营收 / 归母净利润 / 经营活动现金流 */
export interface MetricRow {
  name: 'revenue' | 'net_profit_attr' | 'op_cash_flow';
  label: string; // 中文名（营业收入 / 归属于上市公司股东的净利润 / 经营活动产生的现金流量净额）
  value: number; // 数值（元）
  unit: string; // 元
  caliber: string; // 口径：合并 / 归母
  valueScope: string; // 口径范围：year_to_date（累计）
  yoy: number | null; // 同比 %（主表同页含上年同期时计算，否则 null）
  qoq: number | null; // 环比 %（MVP 季报不展示，恒 null）
  page: number | null; // 引用页码（pdf.js 稳定映射）
  confidence: number; // 抽取置信度
}

/** 引用（§7.3 / §8.2）：定位到具体页 + 片段文本，供前端跳页 + 高亮 */
export interface Citation {
  page: number;
  text: string; // 命中的片段文本（与检索集合一致，引用二次校验用）
  score?: number; // 检索相关性（可选）
}

/** 摘要要点（§7.3 一键摘要） */
export interface SummaryPoint {
  text: string;
  citations: Citation[];
}

/** 摘要响应 */
export interface SummaryResponse {
  reportId: string;
  points: SummaryPoint[];
  generatedAt: string; // ISO 时间
  model: string | null; // 大模型名（未接入为 null）
  fromMetrics: boolean; // 是否由预计算指标派生（MVP 恒 true）
}

/** 问答消息 */
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
}

/** 问答响应（§7.3 RAG） */
export interface ChatResponse {
  reportId: string;
  answer: string;
  citations: Citation[]; // 二次校验后保留的引用（均在检索集合内）
  model: string | null;
  fallback: boolean; // 无 LLM 时的抽取式降级
}

/** 指标中文短标签（与 worker metrics.py METRICS 对齐，用于前端展示与引用文本） */
export const METRIC_LABELS: Record<MetricRow['name'], string> = {
  revenue: '营业收入',
  net_profit_attr: '归属于上市公司股东的净利润',
  op_cash_flow: '经营活动产生的现金流量净额',
};
