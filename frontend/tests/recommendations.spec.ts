import { test, expect } from "@playwright/test";

const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";

test("recommendation panel applies an equipment offer to the form", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#email").fill("demo-a@example.test");
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);

  await page.goto("/applications/new");
  const panel = page.locator(".recommendation-panel");
  await expect(panel).toBeVisible();

  await page.locator("#amount_kopecks").fill("2000000");
  await page.locator("#term_months").fill("24");
  await page.locator("#revenue_kopecks").fill("9000000");
  await page.locator("#operating_expenses_kopecks").fill("3000000");
  await page.locator("#existing_debt_payments_kopecks").fill("0");
  await page.locator("#period_start").fill("2026-01");
  await page.locator("#period_end").fill("2026-03");

  await panel.getByRole("combobox", { name: "Что планируете финансировать" }).click();
  await panel.getByRole("option", { name: "Покупка оборудования" }).click();

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/product-recommendations") &&
      response.request().method() === "POST",
  );
  await panel.locator(".recommendation-actions button.primary").click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.items[0].product_code).toBe("equipment");
  expect(body.items[0].recommended_amount_kopecks).toBe(200000000);

  await expect(panel.locator(".recommendation-card").first()).toBeVisible();
  await panel.locator(".recommendation-apply").first().click();

  await expect(page.locator('input[name="product_code"][value="equipment"]')).toBeChecked();
  await expect(page.locator("#amount_kopecks")).toHaveValue("2000000,00");
  await expect(page.locator("#term_months")).toHaveValue("24");
  await expect(panel).toContainText("Условия подставлены. Проверьте данные и сохраните черновик");
});
