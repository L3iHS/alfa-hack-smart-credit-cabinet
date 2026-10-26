import { test, expect, type Page, type Route } from "@playwright/test";
import type { Application, DealOutput, ProductCode } from "../src/api/types";

// Фикстуры проверяют только контракт интерфейса: переходы сервера и банковские операции не проверяются.
const id = "00000000-0000-4000-8000-000000000061";
const owner = "deal-ui-owner";
const time = "2026-10-26T10:00:00Z";
const products = [
  ["working_capital", "Оборотный кредит", "credit"], ["equipment", "Кредит на оборудование", "credit"],
  ["investment", "Инвестиционный кредит", "credit"], ["overdraft", "Овердрафт", "limit"],
  ["credit_line", "Кредитная линия", "limit"], ["tender_guarantee", "Тендерная гарантия", "guarantee"],
] as const;
function snapshot(code: ProductCode = "working_capital", status: DealOutput["status"] = "prepared"): DealOutput {
  const product = products.find(([value]) => value === code)!;
  const kind = product[2] === "credit" ? "annuity" : product[2] === "limit" ? "revolving" : "guarantee";
  return {
    id, reference: "СД-000061", product_code: code, product_name: product[1], completion_kind: product[2], status,
    amount_kopecks: 87654321, term_months: 18, created_at: time,
    confirmed_at: status === "confirmed" || status === "completed" ? time : null,
    completed_at: status === "completed" ? time : null, cancelled_at: status === "cancelled" ? time : null,
    cancel_reason: status === "cancelled" ? "Потребность изменилась" : null,
    available_actions: [],
    payment_terms: { payment_kind: kind, amount_kopecks: 87654321, term_months: 18, annual_rate_bps: kind === "guarantee" ? null : 2400, annual_commission_bps: 300,
      monthly_payment_kopecks: kind === "guarantee" ? null : 6000000, upfront_fee_kopecks: 123456,
      principal_due_at_end_kopecks: kind === "revolving" ? 87654321 : 0, last_payment_kopecks: 6000000,
      total_payment_kopecks: 108000000, total_cost_kopecks: 20345679, assessment_monthly_burden_kopecks: kind === "guarantee" ? null : 6000000,
      contingent_liability_kopecks: kind === "guarantee" ? 87654321 : 0, assumptions: [] },
  };
}
function application(deal: DealOutput | null = snapshot()): Application {
  return { id, display_number: "КЗ-000061", version: 8, status: "approved", product_code: deal?.product_code || "working_capital", catalog_version: "fixture",
    amount_kopecks: 100000000, term_months: 12, purpose: "Исходный запрос", description: null,
    period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null,
    project_description: null, tender_number: null, beneficiary_name: null, updated_at: time, processing_status: "succeeded",
    public_reasons: ["Одобрено по сохранённым условиям"], information_requests: [], offers: [], available_actions: [], deal };
}
async function fixture(page: Page, item: Application, staff = false, command?: (route: Route) => Promise<void>) {
  const state = { item, reads: 0, failRead: false };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path.startsWith(`/applications/${id}/deal/`) && route.request().method() === "POST" && command) return command(route);
    if (path === `/applications/${id}`) {
      state.reads++;
      if (state.failRead) return route.fulfill({ status: 503, json: { message: "Не удалось обновить" } });
      return route.fulfill({ json: state.item });
    }
    const routes: Record<string, unknown> = {
      "/me": { id: owner, role: staff ? "staff" : "client", company_id: "company", display_name: "Тест" },
      "/company": { id: "company", name: "ООО «UI contract»", inn: "7701234567", industry: "Тест", registered_at: "2020-01-01" },
      "/auth/csrf": { csrf_token: "fixture", user_id: owner },
      "/products": { catalog_version: "fixture", items: products.map(([code, name, kind]) => ({ code, name, payment_kind: kind === "credit" ? "annuity" : kind === "limit" ? "revolving" : "guarantee", required_document_types: [], required_application_fields: [] })) },
      "/applications": { items: [state.item], total: 1, limit: 20, offset: 0 },
      [`/applications/${id}/documents`]: { items: [] },
      [`/applications/${id}/assessment`]: { application_id: id, revision_id: null, risk_assessment: null, runs: [] },
      [`/applications/${id}/history`]: { items: ["deal_prepared", "deal_confirmed", "deal_completed", "deal_cancelled"].map((event_type, index) => ({ id: String(index), event_type, actor_type: "user", actor_id: index === 1 ? owner : "another", application_version: index + 8, created_at: time })), total: 4, limit: 10, offset: 0 },
      "/submission-policy": { consent_version: "fixture", data_confirmation_text: "Подтверждаю", bki_consent_text: "Согласен", accepted_content_types: [], max_file_size_bytes: 100000 },
    };
    return route.fulfill({ status: path in routes ? 200 : 503, json: routes[path] ?? { message: "UI fixture: endpoint unavailable" } });
  });
  return state;
}
const detail = (staff = false) => `${staff ? "/staff" : ""}/applications/${id}`;
const panel = (page: Page) => page.getByRole("region", { name: "Оформление сделки", exact: true });

test.describe("UI contract (mocked API): deal completion", () => {
  test("client explicitly confirms exact snapshot; pending response survives reload with one retry", async ({ page }) => {
    const item = application(); item.deal!.available_actions = ["confirm_deal", "cancel_deal"];
    const commands: { key?: string; body: unknown }[] = [];
    const state = await fixture(page, item, false, async route => {
      commands.push({ key: route.request().headers()["idempotency-key"], body: route.request().postDataJSON() });
      state.item = { ...item, version: 9, deal: { ...item.deal!, status: "confirmed", available_actions: ["cancel_deal"] } };
      if (commands.length === 1) return route.abort("failed");
      return route.fulfill({ json: state.item });
    });
    await page.goto(detail());
    await expect(page.locator(".details-main > :first-child")).toHaveClass(/deal-panel/);
    await expect(panel(page)).toContainText("876 543,21 ₽");
    await expect(panel(page)).toContainText("18 мес.");
    await expect(panel(page).getByText("Всего к выплате", { exact: true })).not.toBeVisible();
    const confirm = panel(page).getByRole("button", { name: "Подтвердить условия", exact: true });
    await expect(confirm).toBeDisabled();
    await panel(page).getByRole("checkbox").check(); await confirm.click();
    await expect(page.getByRole("button", { name: "Повторить действие", exact: true })).toHaveCount(1);
    await page.reload();
    await page.getByRole("button", { name: "Повторить действие", exact: true }).click();
    await expect.poll(() => commands.length).toBe(2);
    expect(commands[1]).toEqual(commands[0]);
    expect(commands[0].body).toEqual({ expected_version: 8, terms_confirmed: true });
    expect(commands[0].key).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page.getByRole("button", { name: "Повторить действие", exact: true })).toHaveCount(0);
    await expect(panel(page)).toContainText("Сотрудник завершит оформление");
    await expect(page.getByRole("heading", { name: "Следующий шаг", exact: true })).toHaveCount(0);
  });

  test("staff prepares and completes only after client confirmation", async ({ page }) => {
    const item = application(null); item.available_actions = ["prepare_deal"];
    const paths: string[] = [];
    const state = await fixture(page, item, true, async route => {
      paths.push(new URL(route.request().url()).pathname);
      const complete = paths.at(-1)!.endsWith("complete");
      state.item = { ...item, version: complete ? 11 : 9, available_actions: [], deal: { ...snapshot("working_capital", complete ? "completed" : "prepared"), available_actions: complete ? [] : ["cancel_deal"] } };
      return route.fulfill({ json: state.item });
    });
    await page.goto(detail(true));
    await panel(page).getByRole("button", { name: "Подготовить оформление", exact: true }).click();
    await expect(panel(page)).toContainText("Клиент должен подтвердить условия");
    await expect(panel(page).getByRole("button", { name: "Завершить оформление", exact: true })).toHaveCount(0);
    state.item = { ...state.item, version: 10, deal: { ...state.item.deal!, status: "confirmed", available_actions: ["complete_deal", "cancel_deal"] } };
    await page.reload();
    await panel(page).getByRole("button", { name: "Завершить оформление", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Кредит выдан");
    await dialog.getByRole("button", { name: "Завершить оформление", exact: true }).click();
    await expect(panel(page)).toContainText("Кредит выдан");
    await expect(panel(page).getByRole("button", { name: "Отменить оформление", exact: true })).toHaveCount(0);
    expect(paths).toHaveLength(2);
    await expect(page.locator(".page-heading .status")).toHaveText("Одобрена");
  });

  for (const staff of [false, true]) test(`cancel requires reason, refreshes conflict and keeps input (${staff})`, async ({ page }) => {
    const item = application(); item.deal!.available_actions = ["cancel_deal"];
    let calls = 0;
    const state = await fixture(page, item, staff, async route => {
      calls++;
      if (calls === 1) { state.item = { ...item, version: 9 }; return route.fulfill({ status: 409, json: { code: "version_conflict", message: "Версия изменилась" } }); }
      expect(route.request().postDataJSON()).toEqual({ expected_version: 9, reason: "Планы изменились" });
      state.item = { ...item, version: 10, deal: { ...item.deal!, status: "cancelled", cancel_reason: "Планы изменились", available_actions: [] } };
      return route.fulfill({ json: state.item });
    });
    await page.goto(detail(staff));
    const trigger = panel(page).getByRole("button", { name: "Отменить оформление", exact: true });
    await trigger.click(); await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
    await trigger.click();
    const dialog = page.getByRole("dialog"); const reason = dialog.getByRole("textbox", { name: "Причина отмены", exact: true });
    const cancel = dialog.getByRole("button", { name: "Отменить оформление", exact: true });
    await reason.fill("   "); await cancel.click(); expect(calls).toBe(0);
    await reason.fill("Планы изменились"); await cancel.click();
    await expect(dialog.getByRole("button", { name: "Загрузить актуальное состояние" })).toBeVisible();
    await expect(cancel).toBeDisabled();
    await dialog.getByRole("button", { name: "Загрузить актуальное состояние" }).click();
    await expect(reason).toHaveValue("Планы изменились"); await cancel.click();
    await expect(dialog).not.toBeVisible();
    await expect(panel(page)).toContainText("Планы изменились");
    await expect(panel(page)).toContainText("Оформление отменено");
  });

  for (const [code, , kind] of products) test(`snapshot and terminal labels ${code}`, async ({ page }) => {
    const item = application(snapshot(code, "completed"));
    await fixture(page, item);
    await page.goto(detail());
    const final = kind === "credit" ? "Кредит выдан" : kind === "limit" ? "Лимит открыт" : "Гарантия выпущена";
    await expect(panel(page)).toContainText(final);
    await expect(panel(page)).toContainText(kind === "credit" ? "Сумма кредита" : kind === "limit" ? "Лимит" : "Сумма гарантии");
    await expect(panel(page)).toContainText("876 543,21 ₽");
    await expect(panel(page).getByRole("checkbox")).toHaveCount(0);
    await page.goto("/applications");
    await expect(page.locator(".application-row")).toContainText("Одобрена");
    await expect(page.locator(".application-row")).toContainText(final);
  });

  test("download retrieves server Markdown and reports download errors", async ({ page }) => {
    await fixture(page, application()); let calls = 0;
    await page.route(`**/api/v1/applications/${id}/deal/document`, route => {
      calls++;
      return calls === 1 ? route.fulfill({ status: 503, json: { message: "Документ временно недоступен" } }) : route.fulfill({ contentType: "text/markdown", body: "# Условия сделки\n876 543,21 ₽\nДемонстрационное оформление" });
    });
    await page.goto(detail());
    const button = panel(page).getByRole("button", { name: "Скачать условия в Markdown", exact: true });
    await button.click(); await expect(panel(page)).toContainText("Документ временно недоступен");
    const downloading = page.waitForEvent("download"); await button.click();
    const download = await downloading;
    expect(download.suggestedFilename()).toMatch(/\.md$/);
    const stream = await download.createReadStream(); let text = ""; for await (const chunk of stream!) text += chunk.toString();
    expect(text).toContain("876 543,21 ₽"); expect(text).toContain("Демонстрационное оформление");
  });

  test("old review pending remains the only repeat action after approved", async ({ page }) => {
    const item = application(null); item.available_actions = ["prepare_deal"];
    const state = await fixture(page, item, true);
    let repeated: unknown;
    await page.route(`**/api/v1/applications/${id}/decisions`, route => {
      repeated = route.request().postDataJSON();
      return route.fulfill({ json: { application_id: id, status: "approved", version: state.item.version } });
    });
    await page.addInitScript(({ owner, id }) => sessionStorage.setItem(`credit-command:v1:${owner}:${id}`, JSON.stringify({ key: "00000000-0000-4000-8000-000000000062", path: `/applications/${id}/decisions`, body: { expected_version: 7, outcome: "approved", reason: "Проверено" } })), { owner, id });
    await page.goto(detail(true));
    await expect(page.getByRole("button", { name: "Повторить действие", exact: true })).toHaveCount(1);
    await expect(panel(page).getByRole("button", { name: "Подготовить оформление", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Повторить действие", exact: true }).click();
    await expect(panel(page).getByRole("button", { name: "Подготовить оформление", exact: true })).toBeEnabled();
    expect(repeated).toEqual({ expected_version: 7, outcome: "approved", reason: "Проверено" });
  });

  test("saved command with failed or stale GET only refreshes; it never submits a new POST", async ({ page }) => {
    const item = application(); item.deal!.available_actions = ["confirm_deal", "cancel_deal"];
    let calls = 0;
    const state = await fixture(page, item, false, async route => {
      calls++; state.failRead = true;
      return route.fulfill({ json: { ...item, version: 9, deal: { ...item.deal!, status: "confirmed" } } });
    });
    await page.goto(detail());
    await panel(page).getByRole("checkbox").check();
    await panel(page).getByRole("button", { name: "Подтвердить условия", exact: true }).click();
    await expect(panel(page)).toContainText("Действие сохранено");
    await expect(panel(page).getByRole("button", { name: "Подтвердить условия", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Повторить действие", exact: true })).toHaveCount(0);
    state.failRead = false; // Отставший ответ чтения с версией 8 после успешного POST с версией 9.
    await panel(page).getByRole("button", { name: "Загрузить актуальное состояние" }).click();
    await expect(panel(page)).toContainText("Сервер ещё обновляет сведения");
    await expect(panel(page).getByRole("button", { name: "Отменить оформление", exact: true })).toBeDisabled();
    state.item = { ...item, version: 9, deal: { ...item.deal!, status: "confirmed", available_actions: ["cancel_deal"] } };
    await panel(page).getByRole("button", { name: "Загрузить актуальное состояние" }).click();
    await expect(panel(page)).toContainText("Сотрудник завершит оформление");
    expect(calls).toBe(1);
  });

  test("role fences and acknowledgement follow fresh version", async ({ page }) => {
    const item = application(); item.deal!.available_actions = ["confirm_deal", "cancel_deal"];
    const state = await fixture(page, item);
    await page.goto(detail()); await panel(page).getByRole("checkbox").check();
    const reads = state.reads; state.item = { ...item, version: 9 };
    await expect.poll(() => state.reads).toBeGreaterThan(reads);
    await expect(panel(page).getByRole("checkbox")).not.toBeChecked();
    await expect(panel(page).getByRole("button", { name: "Подготовить оформление", exact: true })).toHaveCount(0);
    await expect(panel(page).getByRole("button", { name: "Завершить оформление", exact: true })).toHaveCount(0);
    for (const label of ["Условия сделки подготовлены", "Условия подтверждены клиентом", "Оформление завершено", "Оформление отменено"]) await expect(page.locator(".history")).toContainText(label);
  });

  for (const staff of [false, true]) test(`terminal cancel shows no mutation and list retains decision (${staff})`, async ({ page }) => {
    await fixture(page, application(snapshot("tender_guarantee", "cancelled")), staff);
    await page.goto(detail(staff));
    await expect(panel(page)).toContainText("Потребность изменилась");
    await expect(panel(page).getByRole("button", { name: /Подготовить оформление|Подтвердить условия|Завершить оформление|Отменить оформление/ })).toHaveCount(0);
    await page.goto(staff ? "/staff/applications" : "/applications");
    await expect(page.locator(".application-row")).toContainText("Одобрена");
    await expect(page.locator(".application-row")).toContainText("Оформление отменено");
  });

  for (const width of [320, 390, 1366]) test(`compact card, dialog and screenshot ${width}`, async ({ page }, info) => {
    const item = application(); item.deal!.available_actions = ["confirm_deal", "cancel_deal"];
    await fixture(page, item); await page.setViewportSize({ width, height: 900 }); await page.goto(detail());
    await expect(panel(page)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const cta = await panel(page).getByRole("button", { name: "Подтвердить условия", exact: true }).boundingBox();
    expect(cta!.y + cta!.height).toBeLessThan(900);
    await page.screenshot({ path: info.outputPath(`mocked-deal-prepared-${width}.png`), fullPage: true });
    await panel(page).getByRole("button", { name: "Отменить оформление", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`mocked-deal-cancel-dialog-${width}.png`), fullPage: true });
  });
});
