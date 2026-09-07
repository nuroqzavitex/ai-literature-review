import { Suspense } from "react";
import Workspace from "../_components/Workspace";

export default function WorkspacePage() {
  return <Suspense fallback={<main className="mock-loading">Đang mở không gian làm việc…</main>}><Workspace /></Suspense>;
}
