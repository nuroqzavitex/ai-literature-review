import { redirect } from "next/navigation";

export default async function LoadingProject({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // Workspace tự tải và hiển thị trạng thái research của project này.
  redirect(`/workspace?project=${id}`);
}
