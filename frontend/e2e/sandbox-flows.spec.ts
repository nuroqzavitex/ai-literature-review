import { expect, test } from "@playwright/test";
import { PROJECT_ID, useAnalysisApi, useHypothesisApi } from "./sandbox-test-api";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("litreview_lang", "vi"));
});

test("Sandbox breadcrumb shows the project name with editorial type", async ({ page }) => {
  await useHypothesisApi(page);
  await page.route("**/api/v1/projects", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ items: [{ project_id: PROJECT_ID, name: "Nghiên cứu giấc ngủ" }] }),
  }));

  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=hypothesis`);

  await expect(page.getByRole("link", { name: "Nghiên cứu giấc ngủ" })).toBeVisible();
  await expect(page.locator(".sandbox-current-crumb")).toHaveText("Sandbox");
  await expect(page.locator(".sandbox-current-crumb")).toHaveCSS("font-family", /Source Serif 4/);
});

test("Flow 1: GraphRAG context → hypothesis versions → experiment → review", async ({ page }) => {
  await useHypothesisApi(page);
  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=hypothesis&entrypoint=graphrag_answer&source_resource_id=report-v1`);

  await page.getByLabel("Tên session").fill("GraphRAG hypothesis");
  await page.getByRole("button", { name: "Mở Sandbox" }).click();
  await expect(page).toHaveURL(/mode=hypothesis.*session=ses-hypothesis/);

  await page.getByLabel("Câu hỏi cần khám phá").fill("Method A có cải thiện outcome B không?");
  await page.getByRole("button", { name: "Tạo bản thảo" }).click();
  await expect(page.getByRole("heading", { name: /Graph evidence suggests/ })).toBeVisible();
  await page.getByRole("button", { name: "Tạo bản thảo" }).click();
  await expect(page.getByText("v2", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /v1 Graph evidence/ }).click();
  await page.getByRole("button", { name: "Tạo thiết kế" }).click();
  await expect(page.getByRole("heading", { name: "Test method A against baseline" })).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Phê duyệt" }).click();
  await expect(page.locator(".sandbox-paper-head").getByText("Đã duyệt", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Chuyển sang Phân tích dữ liệu" }).click();
  await expect(page).toHaveURL(/mode=data_analysis.*session=ses-analysis-handoff/);
  await expect(page.getByText("Mục tiêu được chuyển từ giả thuyết")).toBeVisible();
  await expect(page.getByText("Test method A against baseline")).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({ name: "unrelated.csv", mimeType: "text/csv", buffer: Buffer.from("city,temperature\nHanoi,32\n") });
  await expect(page.getByText("MISMATCH_DATASET", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Kiểm tra độ đầy đủ" })).toBeDisabled();
});

test("Flow 3: failed interpretation is regenerated before result approval", async ({ page }) => {
  await useAnalysisApi(page, { interpretationInitiallyUnavailable: true });
  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=data_analysis`);

  await page.locator('input[type="file"]').setInputFiles({ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("fruit name,count sold\napple,1\npear,2\nplum,3\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" })).toBeVisible();
  await page.getByRole("button", { name: "Chạy deterministic profile" }).click();
  await expect(page.getByRole("heading", { name: "Hồ sơ deterministic" })).toBeVisible();

  await page.getByLabel("Câu hỏi nghiên cứu").fill("Describe sales by fruit");
  await page.getByLabel("Cột kết quả").fill("count sold");
  await page.getByLabel("Cột phân nhóm").fill("fruit name");
  await page.getByRole("button", { name: "Kiểm tra độ đầy đủ" }).click();
  await page.getByRole("button", { name: "Sinh plan từ metadata" }).click();
  await expect(page.getByRole("heading", { name: "Descriptive aggregation" })).toBeVisible();

  await page.getByRole("button", { name: "Mở review plan" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Phê duyệt" }).click();
  await page.getByRole("button", { name: "Tạo run" }).click();
  await expect(page.getByRole("heading", { name: "Mã nguồn thực thi" })).toBeVisible();
  await expect(page.getByLabel("Mã Python do AI sinh")).toContainText("from sandbox_sdk import load_dataset");
  await expect(page.locator(".sandbox-run-section > header").getByText("Chờ duyệt kết quả", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Validation: đã vượt qua", { exact: true })).toBeVisible();
  await expect(page.getByText("Chưa thể tải diễn giải. Kết quả đã validation vẫn có thể được duyệt.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tải lại diễn giải" }).click();
  await expect(page.getByRole("heading", { name: "Diễn giải sau validation" })).toBeVisible();
  await expect(page.getByText("-24.635", { exact: true })).toBeVisible();
  await expect(page.getByText("p < 0.001", { exact: true })).toBeVisible();
  await expect(page.getByText("[-26.66, -22.61]", { exact: true })).toBeVisible();
  await expect(page.getByText("/statistical_results/0/effect_size", { exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Xem nguồn trích dẫn 1" }).click();
  await expect(page.getByText("/statistical_results/0/effect_size", { exact: true })).toBeVisible();

  await page.locator(".sandbox-result-review").getByRole("button", { name: "Phê duyệt" }).click();
  await expect(page.getByText("Reproducibility Bundle đã niêm phong")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Tải bundle" }).click();
  await expect((await download).suggestedFilename()).toContain("reproducibility");
});

test("Context Copilot mở form phiên mới thay vì khôi phục phiên thủ công cũ và có thể xóa phiên", async ({ page }) => {
  await page.addInitScript((projectId) => {
    window.localStorage.setItem(`research-sandbox:${projectId}:session:hypothesis`, "ses-hypothesis-old");
  }, PROJECT_ID);
  await useHypothesisApi(page, { seedOldSession: true });
  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=hypothesis&entrypoint=graphrag_answer&source_resource_id=answer-new&source_parent_id=conversation-1&title=Giả%20thuyết%20từ%20Copilot`);

  await expect(page.getByRole("heading", { name: "Mở một không gian thử nghiệm" })).toBeVisible();
  await expect(page.getByLabel("Tên session")).toHaveValue("Giả thuyết từ Copilot");
  await expect(page).not.toHaveURL(/session=ses-hypothesis-old/);

  await page.getByRole("button", { name: "Mở Sandbox" }).click();
  await expect(page).toHaveURL(/session=ses-hypothesis/);
  await expect(page.getByRole("button", { name: "Xóa phiên" })).toBeEnabled();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Xóa phiên" }).click();
  await expect(page.getByText("Đã xóa phiên khỏi danh sách đang làm việc.")).toBeVisible();
  await expect(page).toHaveURL(/session=ses-hypothesis-old/);
});

test("Session phân tích mới không kế thừa tiến trình và kết quả session cũ", async ({ page }) => {
  await useAnalysisApi(page);
  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=data_analysis`);

  await page.locator('input[type="file"]').setInputFiles({ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("fruit name,count sold\napple,1\npear,2\n") });
  await page.getByRole("button", { name: "Chạy deterministic profile" }).click();
  await expect(page.getByRole("heading", { name: "Hồ sơ deterministic" })).toBeVisible();

  await page.getByRole("button", { name: "Phiên mới" }).click();
  await page.getByLabel("Tên session").fill("Phân tích độc lập lần hai");
  await page.getByRole("button", { name: "Mở Sandbox" }).click();

  await expect(page).toHaveURL(/mode=data_analysis.*session=ses-analysis-2/);
  await expect(page.getByText("sales.csv", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bắt đầu bằng dữ liệu đã phân loại" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Hồ sơ deterministic" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Mã nguồn thực thi" })).toHaveCount(0);
});
