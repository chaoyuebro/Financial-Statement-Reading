import { DisclosureListItem, TYPE_LABELS, STATUS_LABELS } from '@fr/shared';

interface Props {
  item: DisclosureListItem;
  active: boolean;
  tabIndex: number;
  onActivate: () => void;
  onFocus: () => void;
}

// 列表项卡片（可键盘聚焦；点击或回车进入阅读页）。
export function DisclosureCard({ item, active, tabIndex, onActivate, onFocus }: Props) {
  return (
    <button
      data-card-button
      type="button"
      tabIndex={tabIndex}
      onClick={onActivate}
      onFocus={onFocus}
      aria-label={`${item.companyName} ${TYPE_LABELS[item.type]} ${item.reportPeriod}${item.isRevised ? '，更正后' : ''}，披露日期 ${item.disclosureDate}`}
      className={
        'block w-full rounded-lg border px-4 py-3 text-left transition-colors ' +
        (active ? 'border-accent bg-accent-soft' : 'border-line bg-surface hover:bg-surface-muted')
      }
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="font-medium text-ink">{item.companyName}</span>{' '}
          <span className="text-sm text-ink-soft">{item.companyCode}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {item.isRevised && (
            <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
              更正后
            </span>
          )}
          <span className="rounded-full bg-surface-muted px-2.5 py-0.5 text-xs text-ink-soft">
            {TYPE_LABELS[item.type]}
          </span>
        </div>
      </div>
      <div className="mt-1 text-sm text-ink-soft">
        报告期 {item.reportPeriod} · 披露 {item.disclosureDate} · {STATUS_LABELS[item.status]}
      </div>
    </button>
  );
}
