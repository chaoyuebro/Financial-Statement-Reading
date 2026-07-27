import { pgPool } from './db';
import {
  DisclosureListItem,
  DisclosureType,
  DisclosureDetail,
  Exchange,
  ListResponse,
  TocItem,
  normalizeStockCode,
} from '@fr/shared';

const VALID_TYPES: DisclosureType[] = ['annual', 'halfyear', 'quarterly', 'prospectus'];
const VALID_EXCHANGES: Exchange[] = ['sh', 'sz', 'bse'];

export interface ListQueryParams {
  type?: DisclosureType;
  exchange?: Exchange;
  q?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
}

/**
 * 列表查询（§7.2 BFF 契约 + §7.5 搜索设计）。
 * - 仅返回正式报告：report_period_unknown=false 且 is_withdrawn=false
 * - q 支持：代码归一化精确匹配 + 名称/简称/拼音/曾用名/别名(前缀 + trgm 相似度)，按优先级排序
 * - type/exchange/dateRange 过滤，分页返回 {items,total,hasMore}
 */
export async function listDisclosures(params: ListQueryParams): Promise<ListResponse> {
  const page = Math.max(1, Math.floor(params.page ?? 1));
  const pageSize = Math.min(100, Math.max(1, Math.floor(params.pageSize ?? 20)));
  const offset = (page - 1) * pageSize;

  const where: string[] = ['r.report_period_unknown = false', 'r.is_withdrawn = false'];
  const values: unknown[] = [];
  let v = 1;

  if (params.type && VALID_TYPES.includes(params.type)) {
    where.push(`r.type = $${v++}`);
    values.push(params.type);
  }
  if (params.exchange && VALID_EXCHANGES.includes(params.exchange)) {
    where.push(`c.exchange = $${v++}`);
    values.push(params.exchange);
  }
  if (params.dateFrom) {
    where.push(`r.disclosure_date >= $${v++}`);
    values.push(params.dateFrom);
  }
  if (params.dateTo) {
    where.push(`r.disclosure_date <= $${v++}`);
    values.push(params.dateTo);
  }

  const q = params.q?.trim();
  let orderBy = 'r.disclosure_time DESC NULLS LAST, r.disclosure_date DESC, r.id DESC';

  if (q) {
    const qCode = normalizeStockCode(q); // 去除 .SH/.SZ/.BJ 后缀
    const qText = q;
    const codeIdx = v++; // $${codeIdx} = 归一化代码
    const textIdx = v++; // $${textIdx} = 原始查询文本
    values.push(qCode, qText);

    // 仅匹配与 q 相关的行（代码 / 名称前缀 / 简称前缀 / 拼音前缀 / 曾用名别名数组 / trgm 相似度）
    where.push(
      `(c.code = $${codeIdx} ` +
        `OR c.name ILIKE ($${textIdx} || '%') ` +
        `OR c.short_name ILIKE ($${textIdx} || '%') ` +
        `OR coalesce(c.pinyin,'') ILIKE ($${textIdx} || '%') ` +
        `OR c.former_names && ARRAY[$${textIdx}] ` +
        `OR c.aliases && ARRAY[$${textIdx}] ` +
        `OR similarity(c.name, $${textIdx}) > 0.2 ` +
        `OR similarity(c.short_name, $${textIdx}) > 0.2)`,
    );
    // 相关性打分（越小越优先）：代码精确 > 名称精确 > 简称精确 > 前缀 > 模糊
    const relevance =
      `CASE ` +
      `WHEN c.code = $${codeIdx} THEN 0 ` +
      `WHEN c.name = $${textIdx} THEN 1 ` +
      `WHEN c.short_name = $${textIdx} THEN 2 ` +
      `WHEN c.name ILIKE ($${textIdx} || '%') OR c.short_name ILIKE ($${textIdx} || '%') THEN 3 ` +
      `ELSE 4 END`;
    const sim = `GREATEST(similarity(c.name, $${textIdx}), similarity(c.short_name, $${textIdx}))`;
    orderBy = `${relevance} ASC, ${sim} DESC, r.disclosure_time DESC NULLS LAST, r.disclosure_date DESC, r.id DESC`;
  }

  // 分页参数放到最后
  const limitIdx = v++;
  const offsetIdx = v++;
  values.push(pageSize, offset);

  const whereSql = where.join(' AND ');

  const countSql = `
    SELECT count(*)::int AS total
    FROM reports r
    JOIN companies c ON c.code = r.company_code
    WHERE ${whereSql}
  `;
  // 列表（camelCase 别名直接映射 DisclosureListItem）；分页用最后两个值，去掉它们即为 count 的实参
  const countValues = values.slice(0, values.length - 2);

  const itemsSql = `
    SELECT
      r.id            AS "id",
      c.name          AS "companyName",
      c.code          AS "companyCode",
      r.type          AS "type",
      r.report_period AS "reportPeriod",
      to_char(r.disclosure_date, 'YYYY-MM-DD') AS "disclosureDate",
      r.status        AS "status",
      r.primary_source AS "primarySource"
    FROM reports r
    JOIN companies c ON c.code = r.company_code
    WHERE ${whereSql}
    ORDER BY ${orderBy}
    LIMIT $${limitIdx} OFFSET $${offsetIdx}
  `;

  const [countRes, itemsRes] = await Promise.all([
    pgPool.query(countSql, countValues),
    pgPool.query(itemsSql, values),
  ]);

  const total = countRes.rows[0]?.total ?? 0;
  const items = itemsRes.rows as DisclosureListItem[];

  return { items, total, hasMore: offset + items.length < total };
}

/**
 * 报告详情（§7.2 GET /api/disclosures/[id]）。
 * - 取 reports + companies 基础字段
 * - toc 取当前阅读版本(is_current_version=true)的 disclosures.toc；无则退主源(is_primary_source)
 */
export async function getDisclosureDetail(id: string): Promise<DisclosureDetail | null> {
  const detailSql = `
    SELECT
      r.id            AS "id",
      c.name          AS "companyName",
      c.code          AS "companyCode",
      r.type          AS "type",
      r.report_period AS "reportPeriod",
      to_char(r.disclosure_date, 'YYYY-MM-DD') AS "disclosureDate",
      r.status        AS "status",
      r.primary_source AS "primarySource",
      COALESCE(
        (SELECT d.toc FROM disclosures d WHERE d.report_id = r.id AND d.is_current_version = true LIMIT 1),
        (SELECT d.toc FROM disclosures d WHERE d.report_id = r.id AND d.is_primary_source = true LIMIT 1),
        '[]'::jsonb
      ) AS "toc"
    FROM reports r
    JOIN companies c ON c.code = r.company_code
    WHERE r.id = $1
  `;
  const res = await pgPool.query(detailSql, [id]);
  const row = res.rows[0] as (DisclosureListItem & { toc: TocItem[] }) | undefined;
  if (!row) return null;
  return { ...row, metricsCached: false };
}
