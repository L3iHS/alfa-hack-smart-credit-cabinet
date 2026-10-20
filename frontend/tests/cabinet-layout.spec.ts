import { test, expect, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

async function login(page: Page, email = "client1@example.test") {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.DEMO_PASSWORD || "Demo-credit-2026!");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/);
}

async function draft(page: Page, product: string) {
  const { csrf_token } = await (await page.request.get("/api/v1/auth/csrf")).json();
  const response = await page.request.post("/api/v1/applications", {
    headers: { "X-CSRF-Token": csrf_token },
    data: { product_code: product },
  });
  expect(response.status()).toBe(201);
  return (await response.json()).id as string;
}

async function geometry(page: Page) {
  return page.evaluate(() => {
    const bounds = (selector: string) => {
      const { x, y, width, height, right } = document.querySelector(selector)!.getBoundingClientRect();
      return { x, y, width, height, right };
    };
    return { topbar: bounds(".topbar"), panel: bounds("main .panel"), viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth };
  });
}

for (const width of [1366, 1440, 320, 390]) {
  test(`compact_cabinet_geometry_${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width > 700 ? 768 : 844 });
    await login(page);
    const id = await draft(page, "working_capital");
    const folder = process.env.SCREENSHOT_DIR || "test-results/layout";
    await mkdir(folder, { recursive: true });
    await page.goto(`/applications/${id}`);
    await expect(page.locator(".details-panel")).toBeVisible();
    const details = await geometry(page);
    await page.screenshot({ path: `${folder}/layout-details-${width}.png`, fullPage: true });
    await page.goto(`/applications/${id}/edit`);
    await expect(page.getByRole("heading", { name: "Выбор продукта" })).toBeVisible();
    const form = await geometry(page);
    await page.screenshot({ path: `${folder}/layout-form-${width}.png`, fullPage: true });
    await writeFile(`${folder}/geometry-${width}.json`, JSON.stringify({ details, form }, null, 2));
    for (const value of [details, form]) {
      expect(value.scrollWidth).toBeLessThanOrEqual(width);
      expect(value.topbar.right).toBeLessThanOrEqual(width);
      if (width > 700) {
        expect(value.panel.y).toBeLessThanOrEqual(210);
        expect(value.topbar.height).toBeGreaterThanOrEqual(64);
        expect(value.topbar.height).toBeLessThanOrEqual(72);
      }
    }
    const save = page.getByRole("button", { name: "Сохранить черновик" });
    await save.scrollIntoViewIfNeeded();
    const saveBox = await save.boundingBox();
    expect(saveBox!.x).toBeGreaterThanOrEqual(0);
    expect(saveBox!.x + saveBox!.width).toBeLessThanOrEqual(width);
    if (width > 700) {
      const area = await page.locator(".save-area").boundingBox();
      expect(Math.abs(saveBox!.x + saveBox!.width - area!.x - area!.width)).toBeLessThan(1);
    }
  });
}

test("header_navigation_actions_and_both_products", async ({ page }) => {
  await login(page);
  await expect(page.locator(".topbar .back-link")).toHaveCount(0);
  await page.getByRole("link", { name: "Новая заявка" }).first().click();
  await expect(page.locator(".topbar .back-link")).toHaveAttribute("href", "/applications");
  await page.locator(".topbar .back-link").click();
  await expect(page).toHaveURL(/\/applications$/);
  for (const product of ["working_capital", "equipment"]) {
    const id = await draft(page, product);
    await page.goto(`/applications/${id}`);
    const edit = page.locator(".details-panel .section-top").getByRole("link", { name: "Редактировать", exact: true });
    await expect(edit).toHaveClass(/secondary/);
    await expect(page.locator("main .back-link")).toHaveCount(0);
    await expect(page.locator(".topbar .back-link")).toHaveAttribute("href", "/applications");
    await edit.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/applications/${id}/edit$`));
    await expect(page.locator(".topbar .back-link")).toHaveAttribute("href", `/applications/${id}`);
    await page.locator(".topbar .back-link").focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
    await expect(page.getByText("PDF, PNG, JPEG · до 10 МБ", { exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "staff@example.test");
  await expect(page.locator(".topbar .back-link")).toHaveCount(0);
  await page.goto("/staff/applications/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: "Заявка не найдена" })).toBeVisible();
  await expect(page.locator(".topbar .back-link")).toHaveAttribute("href", "/staff/applications");
  await page.locator(".topbar .back-link").click();
  await expect(page).toHaveURL(/\/staff\/applications$/);
});

test("staff_long_name_and_header_controls_fit_320", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await login(page, "staff@example.test");
  const displayName = "Александра Константинопольская-Долгорукова, старший кредитный специалист";
  await page.route("**/api/v1/me", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), display_name: displayName } });
  });
  await page.reload();
  await expect(page.locator(".company-name")).toContainText(displayName);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  for (const selector of [".account-menu", ".company-name", ".logout"]) {
    const bounds = await page.locator(selector).boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  }
  const folder = process.env.SCREENSHOT_DIR || "test-results/layout";
  await mkdir(folder, { recursive: true });
  await page.screenshot({ path: `${folder}/staff-long-name-320.png`, fullPage: true });
});
