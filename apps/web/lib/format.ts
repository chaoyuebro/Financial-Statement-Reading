// 数值格式化工具（金额单位换算 / 百分比），前端指标卡与摘要复用。

/** 将「元」格式化为 亿元 / 万元 / 元（保留 2 位小数，中文千分位）。 */
export function formatCny(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e8) {
    return `${sign}${(abs / 1e8).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 亿元`;
  }
  if (abs >= 1e4) {
    return `${sign}${(abs / 1e4).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 万元`;
  }
  return `${sign}${abs.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元`;
}

/** 同比/环比百分比展示，null 显示「—」。 */
export function formatPercent(v: number | null): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

/** 将数据库内部指标范围枚举转换为面向用户的中文。 */
export function formatValueScope(scope: string): string {
  const labels: Record<string, string> = {
    year_to_date: '年初至报告期末累计',
    single_period: '本期单期',
  };
  return labels[scope] ?? scope;
}
