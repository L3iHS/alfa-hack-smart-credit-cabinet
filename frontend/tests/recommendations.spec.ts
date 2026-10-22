import { test, expect } from "@playwright/test";

const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";

test("recommendation panel applies an equipment offer to the form", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#email").fill("demo-a@example.test");
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/applications$/);

  await page.goto("/applications/new");
  const panel = page.locator(".recommendation-panel");
  await expect(panel).toBeVisible();

  await page.locator("#amount_kopecks").fill("2000000");
  await page.locator("#term_months").fill("24");
  await page.locator("#revenue_kopecks").fill("2400000");
  await page.locator("#operating_expenses_kopecks").fill("300000");
  await page.locator("#existing_debt_payments_kopecks").fill("150000");

  await panel.locator("select").first().selectOption("equipment");
  await panel.locator('input[inputmode="numeric"]').fill("10");
  await panel.locator('.recommendation-checks input[type="checkbox"]').nth(1).check();

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/product-recommendations") &&
      response.request().method() === "POST",
  );
  await panel.locator(".recommendation-actions button.primary").click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.items[0].product_id).toBe("equipment_loan");

  await expect(panel.locator(".recommendation-card").first()).toBeVisible();
  await panel.locator(".recommendation-apply").first().click();

  await expect(page.locator('input[name="product_code"][value="equipment"]')).toBeChecked();
  await expect(page.locator("#amount_kopecks")).toHaveValue("2000000,00");
  await expect(page.locator("#term_months")).toHaveValue("24");
});
