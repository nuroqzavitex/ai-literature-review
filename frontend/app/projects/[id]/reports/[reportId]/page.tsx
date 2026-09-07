import { Suspense } from "react";
import ReportReader from "../../../../_components/ReportReader";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ id: string; reportId: string }>;
}) {
  const { id, reportId } = await params;
  return (
    <Suspense fallback={<main className="mock-loading">Đang tải báo cáo…</main>}>
      <ReportReader projectId={id} reportId={reportId} />
    </Suspense>
  );
}
