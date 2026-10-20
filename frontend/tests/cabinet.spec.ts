import { test, expect, type Page } from "@playwright/test";
const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";
async function login(page: Page, email = "client1@example.test") {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(
    email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/,
  );
}
async function createDraft(page: Page) {
  await page.getByRole("link", { name: "Новая заявка" }).first().click();
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
  return page.url().split("/").at(-1)!;
}
async function csrf(page: Page) {
  return (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
}

test("client_saves_and_reopens_draft", async ({ page }) => {
  await login(page);
  const id = await createDraft(page);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Оборотный кредит" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await page.getByLabel("Цель финансирования").fill("Сезонная закупка муки");
  await page.getByLabel("Сумма кредита, ₽").fill("500000,01");
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
  await page.reload();
  await expect(
    page.getByText("Сезонная закупка муки", { exact: true }),
  ).toBeVisible();
  const saved = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(saved.amount_kopecks).toBe(50000001);
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
});
test("other_client_cannot_open_draft", async ({ page, browser }) => {
  await login(page);
  const id = await createDraft(page);
  const context = await browser.newContext();
  const other = await context.newPage();
  await login(other, "client2@example.test");
  await other.goto(`/applications/${id}`);
  await expect(
    other.getByRole("heading", { name: "Заявка не найдена" }),
  ).toBeVisible();
  await context.close();
});
test("staff_queue_does_not_include_drafts", async ({ page }) => {
  await login(page);
  const id = await createDraft(page);
  await page.route("**/api/v1/auth/logout", async (route) => {
    // Задержка сети воспроизводит уход со страницы до завершения выхода.
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.continue();
  });
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "staff@example.test");
  await expect(
    page.getByRole("heading", { name: "Заявки на рассмотрение", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".application-row").filter({ hasText: id.slice(0, 8) }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Новая заявка" })).toHaveCount(0);
});
test("staff_navigation_fits_narrow_viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await login(page, "staff@example.test");
  await expect(
    page.getByRole("link", { name: "Заявки на рассмотрение", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("expired_session_returns_to_login", async ({ page }) => {
  await login(page);
  const id = await createDraft(page);
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await page
    .getByLabel("Цель финансирования")
    .fill("Ввод до завершения сессии");
  const response = await page.request.post("/api/v1/auth/logout", {
    headers: { "X-CSRF-Token": await csrf(page) },
  });
  expect(response.status()).toBe(204);
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("client1@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/applications/${id}/edit$`));
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Ввод до завершения сессии",
  );
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(
    page.getByText("Ввод до завершения сессии", { exact: true }),
  ).toBeVisible();
});
test("stale_edit_preserves_input", async ({ page }) => {
  await login(page);
  const id = await createDraft(page);
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await page
    .getByLabel("Цель финансирования")
    .fill("Мои несохранённые изменения");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  const response = await page.request.patch(`/api/v1/applications/${id}`, {
    headers: { "X-CSRF-Token": await csrf(page) },
    data: {
      expected_version: current.version,
      purpose: "Сохранено в другой вкладке",
    },
  });
  expect(response.status()).toBe(200);
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(
    page.getByText("Заявка изменилась в другой вкладке", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Мои несохранённые изменения",
  );
  const unchanged = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(unchanged.purpose).toBe("Сохранено в другой вкладке");
  await page.getByRole("button", { name: "Загрузить новую версию" }).click();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Сохранено в другой вкладке",
  );
});

test("fresh_login_does_not_claim_expiry", async ({ page }) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Вход в кабинет" }),
  ).toBeVisible();
  await expect(page.getByText(/Сессия завершилась/)).toHaveCount(0);
});

test("money_boundaries_product_validation_and_months", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Новая заявка" }).first().click();
  await page.getByLabel("Сумма кредита, ₽").fill("0,001");
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page.getByLabel("Сумма кредита, ₽")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await page.getByLabel("Сумма кредита, ₽").fill("500000,01");
  await page.getByLabel("Выручка за период, ₽").fill("90071992547409,92");
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page.getByLabel("Выручка за период, ₽")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await page.getByLabel("Выручка за период, ₽").fill("90071992547409,91");
  await page.getByLabel("Операционные расходы за период, ₽").fill("12345,67");
  await page.getByLabel("Платежи по кредитам за период, ₽").fill("0");
  await page.getByLabel("Начало периода").fill("2025-01");
  await page.getByLabel("Конец периода").fill("2025-03");
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
  const id = page.url().split("/").at(-1);
  const saved = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(saved.revenue_kopecks).toBe(Number.MAX_SAFE_INTEGER);
  expect(saved.operating_expenses_kopecks).toBe(1234567);
  expect(saved.existing_debt_payments_kopecks).toBe(0);
  expect(saved.period_start).toBe("2025-01-01");
  expect(saved.period_end).toBe("2025-03-31");
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await expect(page.getByLabel("Выручка за период, ₽")).toHaveValue(
    "90071992547409,91",
  );
});

test("expired_draft_is_not_restored_for_another_user", async ({ page }) => {
  await login(page);
  await createDraft(page);
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await page.getByLabel("Цель финансирования").fill("Ввод первой компании");
  await page.request.post("/api/v1/auth/logout", {
    headers: { "X-CSRF-Token": await csrf(page) },
  });
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("client2@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await page.getByRole("link", { name: "Новая заявка" }).first().click();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue("");
});

test("network_failure_can_be_retried_and_period_error_is_associated", async ({
  page,
  context,
}) => {
  await login(page);
  await context.setOffline(true);
  await page.getByRole("link", { name: "Новая заявка" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Не удалось загрузить данные" }),
  ).toBeVisible();
  await context.setOffline(false);
  await page.getByRole("button", { name: "Повторить" }).click();
  await page.getByLabel("Начало периода").fill("2099-01");
  await page.getByLabel("Конец периода").fill("2099-02");
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page.getByLabel("Конец периода")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.locator("#period_end-error")).not.toBeEmpty();
  await expect(page.getByLabel("Конец периода")).toHaveAttribute(
    "aria-describedby",
    /period_end-error/,
  );
  await expect(page.getByLabel("Конец периода")).toHaveValue("2099-02");
});

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`responsive_keyboard_and_screenshots_${viewport.width}`, async ({
    page,
  }) => {
    const { mkdir } = await import("node:fs/promises");
    const screenshotDir =
      process.env.SCREENSHOT_DIR || "test-results/screenshots";
    await mkdir(screenshotDir, { recursive: true });
    await page.setViewportSize(viewport);
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: "Вход в кабинет" }),
    ).toBeVisible();
    await page.screenshot({
      path: `${screenshotDir}/login-${viewport.width}.png`,
      fullPage: true,
    });
    await login(page);
    await page.screenshot({
      path: `${screenshotDir}/list-${viewport.width}.png`,
    });
    await page.getByRole("link", { name: "Новая заявка" }).first().click();
    await page.getByLabel("Сумма кредита, ₽").fill("650000,01");
    await page.getByLabel("Срок кредита, месяцев").fill("12");
    await page
      .getByLabel("Цель финансирования")
      .fill("Закупка сырья для пекарни");
    await page.getByLabel("Сумма кредита, ₽").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Срок кредита, месяцев")).toBeFocused();
    const focus = await page
      .getByLabel("Срок кредита, месяцев")
      .evaluate((element) => ({
        width: getComputedStyle(element).outlineWidth,
        style: getComputedStyle(element).outlineStyle,
      }));
    expect(focus.style).not.toBe("none");
    expect(parseFloat(focus.width)).toBeGreaterThanOrEqual(2);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${screenshotDir}/form-${viewport.width}.png`,
    });
    await page.screenshot({
      path: `${screenshotDir}/form-full-${viewport.width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    await page.screenshot({
      path: `${screenshotDir}/details-${viewport.width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("button", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await login(page, "staff@example.test");
    await expect(
      page.getByRole("heading", {
        name: "Заявки на рассмотрение",
        exact: true,
      }),
    ).toBeVisible();
    await page.screenshot({
      path: `${screenshotDir}/staff-${viewport.width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

for (const mode of [
  "empty",
  "inflight",
  "cached-network",
  "cached-503",
] as const) {
  test(`csrf_account_switch_blocks_draft_${mode}`, async ({
    page,
    context,
  }) => {
    await login(page);
    await page.getByRole("link", { name: "Новая заявка" }).first().click();
    if (mode === "empty" || mode === "inflight") await page.reload();
    const marker = `Не передавать другой компании ${mode} ${Date.now()}`;
    await page.getByLabel("Цель финансирования").fill(marker);
    const other = await context.newPage();
    const mutations: number[] = [];
    page.on("response", (response) => {
      if (
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/v1/applications"
      )
        mutations.push(response.status());
    });
    let release = () => {};
    let entered = () => {};
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    if (mode === "inflight") {
      await page.route(
        "**/api/v1/auth/csrf",
        async (route) => {
          const response = await route.fetch();
          entered();
          await gate;
          await route.fulfill({ response });
        },
        { times: 1 },
      );
      await page.getByRole("button", { name: "Сохранить черновик" }).click();
      await started;
    }
    await other.goto("/applications");
    await other.getByRole("button", { name: "Выйти" }).click();
    await expect(other).toHaveURL(/\/login$/);
    await login(other, "client2@example.test");
    const before = await (
      await other.request.get("/api/v1/applications?limit=100")
    ).json();
    let injected = 0;
    if (mode.startsWith("cached")) {
      await page.route(
        /\/api\/v1\/(me|auth\/csrf)$/,
        async (route) => {
          injected++;
          if (mode === "cached-network") await route.abort("failed");
          else
            await route.fulfill({
              status: 503,
              contentType: "application/json",
              body: JSON.stringify({
                code: "database_unavailable",
                message: "Сервис временно недоступен",
              }),
            });
        },
        { times: 1 },
      );
    }
    if (mode === "inflight") release();
    else await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page).toHaveURL(/\/login$/);
    const after = await (
      await other.request.get("/api/v1/applications?limit=100")
    ).json();
    expect(after.total).toBe(before.total);
    expect(
      after.items.some((item: { purpose: string }) => item.purpose === marker),
    ).toBe(false);
    expect(mutations).toEqual(mode === "empty" ? [] : [403]);
    if (mode.startsWith("cached")) expect(injected).toBe(1);
    await page.getByLabel("Электронная почта").fill("client1@example.test");
    await page.getByLabel("Пароль", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Войти", exact: true }).click();
    await expect(page).toHaveURL(/\/applications\/new$/);
    await expect(page.getByLabel("Цель финансирования")).toHaveValue(marker);
    await other.close();
  });
}

test("conflict_reload_failure_is_visible_and_retry_preserves_input", async ({
  page,
  context,
}) => {
  await login(page);
  const id = await createDraft(page);
  await page.getByRole("link", { name: "Продолжить заполнение" }).click();
  await page
    .getByLabel("Цель финансирования")
    .fill("Несохранённый ввод при конфликте");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  await page.request.patch(`/api/v1/applications/${id}`, {
    headers: { "X-CSRF-Token": await csrf(page) },
    data: {
      expected_version: current.version,
      purpose: "Новая серверная версия",
    },
  });
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(
    page.getByText("Заявка изменилась в другой вкладке", { exact: true }),
  ).toBeVisible();
  await context.setOffline(true);
  await page.getByRole("button", { name: "Загрузить новую версию" }).click();
  await expect(
    page.getByText(
      "Нет связи с сервером. Проверьте подключение и повторите попытку",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Несохранённый ввод при конфликте",
  );
  if (process.env.SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.SCREENSHOT_DIR}/conflict-reload-error.png`,
    });
  await context.setOffline(false);
  await page.getByRole("button", { name: "Загрузить новую версию" }).click();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Новая серверная версия",
  );
});
