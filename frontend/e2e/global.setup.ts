import { clerk, clerkSetup } from "@clerk/testing/playwright";
import { test as setup, expect } from "@playwright/test";
import path from "node:path";

setup.describe.configure({ mode: "serial" });

setup("configure Clerk testing token", async () => {
  if (!process.env.CLERK_PUBLISHABLE_KEY || !process.env.CLERK_SECRET_KEY) {
    throw new Error("E2E requires CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY from a Clerk development instance.");
  }
  await clerkSetup();
});

setup("authenticate Clerk test account", async ({ page }) => {
  const emailAddress = process.env.E2E_CLERK_USER_EMAIL;
  if (!emailAddress) throw new Error("E2E requires E2E_CLERK_USER_EMAIL (prefer a +clerk_test address).");
  await page.goto("/");
  await clerk.signIn({ page, emailAddress });
  await page.goto("/dashboard");
  await expect(page).not.toHaveURL(/\/auth(?:\?|$)/);
  await page.context().storageState({ path: path.join(process.cwd(), "playwright/.clerk/user.json") });
});
