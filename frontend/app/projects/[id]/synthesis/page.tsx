import { Suspense } from "react";
import ProjectSynthesis from "../../../_components/ProjectSynthesis";

export default async function SynthesisPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={<main className="mock-loading">Đang tải bài tổng hợp…</main>}>
      <ProjectSynthesis projectId={id} />
    </Suspense>
  );
}
