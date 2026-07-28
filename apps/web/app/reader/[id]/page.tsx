import { notFound } from 'next/navigation';
import { getDisclosureDetail } from '@/lib/disclosures';
import { ReaderPage } from '@/components/reader/ReaderPage';

// 阅读页（§7.1 / §8.1）：SSR 取报告详情 + toc，交客户端三栏组件渲染
export const dynamic = 'force-dynamic';

function safeReturnTo(value: string | string[] | undefined): string {
  if (typeof value !== 'string') return '/';
  if (value === '/' || (value.startsWith('/?') && !value.startsWith('//'))) {
    return value;
  }
  return '/';
}

export default async function ReaderRoute({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams: { returnTo?: string | string[] };
}) {
  const detail = await getDisclosureDetail(params.id);
  if (!detail) notFound();

  // 开发期用本地 fixture 验证渲染/Range/跳页；生产走真实代理（§7.4）。
  // 通过服务端 FR_PDF_DEV_FIXTURE 显式开启（值为 public/fixtures 下的文件名）。
  // 仅动态 SSR 读取，不暴露给客户端；生产不设置即走真实上游。
  // URL 带 devFixture 便于识别这是开发回退，而非真实代理。
  const devFixture =
    process.env.NODE_ENV !== 'production' ? process.env.FR_PDF_DEV_FIXTURE : undefined;
  const pdfUrl = devFixture
    ? `/api/disclosures/${params.id}/pdf?devFixture=${encodeURIComponent(devFixture)}`
    : `/api/disclosures/${params.id}/pdf`;

  return (
    <ReaderPage
      detail={detail}
      pdfUrl={pdfUrl}
      returnTo={safeReturnTo(searchParams.returnTo)}
    />
  );
}
