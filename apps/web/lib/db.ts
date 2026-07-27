import { Pool } from 'pg';

// 直连 Postgres 的连接池单例（BFF 阶段不接 Worker/RQ，直接读库）。
// 优先读 DATABASE_URL（Docker 容器内注入为 postgresql://fr:fr_dev_pw@postgres:5432/fr）；
// 本地 host 验证时通过 .env.local 提供 DATABASE_URL=postgresql://fr:fr_dev_pw@localhost:5432/fr。

const globalForPg = globalThis as unknown as { __frPgPool?: Pool };

function buildConnectionString(): string {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;
  const user = process.env.POSTGRES_USER ?? 'fr';
  const password = process.env.POSTGRES_PASSWORD ?? 'fr_dev_pw';
  const host = process.env.POSTGRES_HOST ?? 'localhost';
  const port = process.env.POSTGRES_PORT ?? '5432';
  const db = process.env.POSTGRES_DB ?? 'fr';
  return `postgresql://${user}:${password}@${host}:${port}/${db}`;
}

export const pgPool: Pool =
  globalForPg.__frPgPool ?? new Pool({ connectionString: buildConnectionString() });

if (process.env.NODE_ENV !== 'production') globalForPg.__frPgPool = pgPool;

/** 类型化参数化查询（占位符 $1/$2/...）。失败抛出原始错误供上层记录。
 *  不对 T 加索引签名约束（postgres 行类型天然没有），由调用方负责窄化。
 */
export async function dbQuery<T = Record<string, unknown>>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  const res = await pgPool.query(sql, params as unknown[]);
  return res.rows as T[];
}
