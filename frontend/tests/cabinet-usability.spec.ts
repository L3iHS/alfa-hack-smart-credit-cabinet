import { test, expect, type Page } from "@playwright/test";

const id = "00000000-0000-4000-8000-000000000051";
const product = { code: "working_capital", name: "Оборотный кредит", payment_kind: "annuity", min_amount_kopecks: 10000000, max_amount_kopecks: 500000000, min_term_months: 3, max_term_months: 36, annual_rate_bps: 2400, annual_commission_bps: null, upfront_fee_bps: 0, purpose_description: "Для закупки материалов", required_document_types: ["financial_statement"], required_application_fields: [] };
const application = { id, display_number: "КЗ-000051", version: 1, status: "draft", updated_at: "2026-10-25T10:00:00Z", catalog_version: "demo-v2", product_code: product.code, amount_kopecks: 100000000, term_months: 12, purpose: "Закупка материалов", description: null, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, information_requests: [], offers: [], public_reasons: [], processing_status: null, available_actions: ["edit_draft", "upload_document", "submit"] };

async function cabinet(page: Page, staff = false) {
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const response: Record<string, unknown> = {
      "/me": { id: "layout-user", role: staff ? "staff" : "client", display_name: "Анна", email: "layout@example.test" },
      "/company": { id: "layout-company", name: "ООО «Тестовая компания»", inn: "7701234567", industry: "Производство", registered_at: "2020-01-01" },
      "/products": { catalog_version: "demo-v2", items: [product, ...[["equipment", "Кредит на оборудование"], ["overdraft", "Овердрафт"], ["credit_line", "Кредитная линия"], ["investment", "Инвестиционный кредит"], ["tender_guarantee", "Тендерная гарантия"]].map(([code, name]) => ({ ...product, code, name }))] },
      "/applications": { items: [{ ...application, status: staff ? "manual_review" : "draft" }], total: 1, offset: 0, limit: 20 },
      [`/applications/${id}`]: { ...application, status: staff ? "manual_review" : "draft", available_actions: staff ? [] : application.available_actions },
      [`/applications/${id}/documents`]: { items: [] },
      [`/applications/${id}/history`]: { items: [], total: 0, offset: 0, limit: 10 },
      [`/applications/${id}/assessment`]: { application_id: id, revision_id: "revision-1", risk_assessment: null, runs: [{ id: "run-1", revision_id: "revision-1", status: "succeeded", created_at: "2026-10-25T10:00:00Z", catalog_version: "demo-v2", policy_version: "demo-policy-0.4", source_version: "synthetic-v1", scorer_version: null, error_code: null, checks: [{ id: "registry", kind: "registry", data: { registered_at: "2020-01-01", liquidated: false } }, { id: "bki", kind: "bki", data: { overdue_days: 0 } }], risk_assessments: [], calculation: null, decision: { internal_reason: "Требуется рассмотрение сотрудником" } }] },
      "/submission-policy": { consent_version: "test", data_confirmation_text: "Подтверждаю", bki_consent_text: "Согласен", accepted_content_types: ["application/pdf"], max_file_size_bytes: 10485760 },
      "/product-recommendations/options": { purposes: [] },
      "/auth/csrf": { csrf_token: "layout", user_id: "layout-user" },
    };
    return route.fulfill({ status: path in response ? 200 : 503, json: response[path] ?? { message: "Недоступно" } });
  });
}

for (const width of [1366, 390]) for (const staff of [false, true]) test(`compact shell, linked name and copy ${width} ${staff}`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await cabinet(page, staff);
  await page.goto(staff ? "/staff/applications" : "/applications");
  await expect(page.locator(".topbar")).toHaveCount(0);
  if (width < 700) await page.getByRole("button", { name: "Аккаунт", exact: true }).click();
  await expect(page.locator(".sidebar .account-menu")).toBeVisible();
  const copy = page.getByRole("button", { name: "Скопировать номер КЗ-000051" });
  await copy.click();
  await expect(page.getByRole("status").filter({ hasText: "Номер скопирован" })).toBeVisible();
  const feedback = await page.locator(".copy-feedback").boundingBox();
  const row = await page.locator(".application-row").boundingBox();
  expect(feedback!.y + feedback!.height).toBeLessThanOrEqual(row!.y + row!.height);
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("КЗ-000051");
  await expect(page).toHaveURL(staff ? /\/staff\/applications$/ : /\/applications$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`list-${width}-${staff}.png`), fullPage: true });
  await page.getByRole("link", { name: "Оборотный кредит", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Оборотный кредит");
  await expect(page.locator(".application-number")).toContainText("КЗ-000051");
  await expect(page.locator(".page-heading .back-link")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`details-${width}-${staff}.png`), fullPage: true });
});

test("copy failure gives feedback and preserves navigation", async ({ page }) => {
  await cabinet(page);
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) } }));
  await page.goto("/applications");
  await page.getByRole("button", { name: "Скопировать номер КЗ-000051" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Не удалось скопировать" })).toBeVisible();
  await page.getByRole("link", { name: "Оборотный кредит", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${id}$`));
});

for (const width of [1366, 390]) test(`intake first, optional selection and no duplicate company ${width}`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await cabinet(page);
  let recommendationRequests = 0;
  page.on("request", request => { if (request.method() === "POST" && request.url().includes("product-recommendations")) recommendationRequests++; });
  await page.goto(`/applications/${id}/edit`);
  await expect(page.locator(".form-main > :first-child")).toHaveClass(/intake-panel/);
  await expect(page.locator(".company-summary")).toHaveCount(0);
  const help = page.locator(".product-selection-help");
  await expect(help).not.toHaveAttribute("open", "");
  await help.getByText("Помочь выбрать", { exact: true }).click();
  await expect(help.locator(".recommendation-panel")).toBeVisible();
  await expect(page.locator(".recommendation-panel")).toHaveCount(1);
  await expect(help).toContainText("сумму и срок");
  expect(recommendationRequests).toBe(0);
  await expect(page.getByRole("link", { name: "К заявке", exact: true })).toHaveAttribute("href", `/applications/${id}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`form-${width}.png`), fullPage: true });
});

test("assessment explains result before details and keeps versions collapsed", async ({ page }) => {
  await cabinet(page, true);
  await page.goto(`/staff/applications/${id}`);
  const assessment = page.locator(".assessment-panel");
  await expect(assessment).toContainText("Требуется рассмотрение сотрудником");
  await expect(assessment).toContainText("Кредитная история");
  const technical = assessment.locator(".assessment-technical");
  await expect(technical).not.toHaveAttribute("open", "");
  await expect(technical.getByText("demo-policy-0.4", { exact: false })).toBeHidden();
  await technical.getByText("Технические сведения", { exact: true }).click();
  await expect(technical).toContainText("demo-policy-0.4");
});
