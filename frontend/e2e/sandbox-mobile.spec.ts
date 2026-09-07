import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { PROJECT_ID, useHypothesisApi } from "./sandbox-test-api";

test("Sandbox mobile has no critical accessibility violations or undersized controls", async ({ page }) => {
  await useHypothesisApi(page);
  await page.addInitScript(() => window.localStorage.setItem("litreview_lang", "en"));
  await page.goto(`/projects/${PROJECT_ID}/sandbox?mode=hypothesis`);
  await expect(page.getByRole("heading", { name: "Open an experiment workspace" })).toBeVisible();

  const results = await new AxeBuilder({ page }).include(".sandbox-shell").analyze();
  expect(results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);

  const undersized = await page.locator(".sandbox-shell button:visible, .sandbox-shell select:visible, .sandbox-shell a:visible").evaluateAll((elements) => elements.flatMap((element) => {
    const box = element.getBoundingClientRect();
    return box.width < 44 || box.height < 44 ? [{ tag: element.tagName, text: element.textContent?.trim(), width: box.width, height: box.height }] : [];
  }));
  expect(undersized).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
