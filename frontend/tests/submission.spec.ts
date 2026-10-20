import { test, expect, type Page } from "@playwright/test";
const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC",
  "base64",
);
async function login(page: Page, email = "client1@example.test") {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(
    email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/,
  );
}
async function draft(page: Page, product = "working_capital", complete = true) {
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const response = await page.request.post("/api/v1/applications", {
    headers: { "X-CSRF-Token": token },
    data: {
      product_code: product,
      ...(complete
        ? {
            purpose: `Закупка для проверки отправки ${Date.now()}`,
            amount_kopecks: 100000000,
            term_months: 12,
            period_start: "2025-01-01",
            period_end: "2025-03-31",
            revenue_kopecks: 300000000,
            operating_expenses_kopecks: 100000000,
            existing_debt_payments_kopecks: 0,
          }
        : {}),
    },
  });
  expect(response.status()).toBe(201);
  const value = await response.json();
  await page.goto(`/applications/${value.id}`);
  return value.id as string;
}
async function upload(page: Page, label = "Финансовая отчётность") {
  const previousCount = await page
    .getByRole("button", { name: "Скачать report.png" })
    .count();
  const picker = page.locator(".document-picker").filter({
    has: page.getByLabel(`Файл: ${label}`, { exact: true }),
  });
  await page
    .getByLabel(`Файл: ${label}`, { exact: true })
    .setInputFiles({ name: "report.png", mimeType: "image/png", buffer: png });
  await expect(picker.getByText("report.png", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: `Загрузить: ${label}`, exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Скачать report.png" }),
  ).toHaveCount(previousCount + 1);
  await expect(
    page.getByRole("button", { name: `Загрузить: ${label}`, exact: true }),
  ).toBeEnabled();
  await expect(picker.getByText("Файл не выбран", { exact: true })).toBeVisible();
}
async function openQueuedApplication(page: Page, id: string) {
  const row = page.getByRole("link").filter({ hasText: id.slice(0, 8) });
  const next = page.getByRole("button", { name: "Далее", exact: true });
  while (!(await row.isVisible())) {
    await expect
      .poll(
        async () =>
          (await row.isVisible()) ||
          ((await next.isVisible()) && (await next.isEnabled())),
      )
      .toBe(true);
    if (await row.isVisible()) break;
    const first = page.locator(".application-row small").first();
    const previous = await first.innerText();
    await next.click();
    await expect(first).not.toHaveText(previous);
  }
  await row.click();
}
async function confirm(page: Page) {
  await page.locator("#data-confirmed").check();
  await page.locator("#bki-consent").check();
}
for (const product of ["working_capital", "equipment"]) {
  test(`submits_${product}_and_staff_reads_same_application`, async ({
    page,
    browser,
  }) => {
    if (product === "equipment")
      await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    const id = await draft(page, product);
    await upload(page);
    if (product === "equipment") await upload(page, "Счёт на оборудование");
    await confirm(page);
    const staffContext = await browser.newContext();
    const staff = await staffContext.newPage();
    await login(staff, "staff@example.test");
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    if (process.env.SCREENSHOT_DIR)
      await page.screenshot({
        path: `${process.env.SCREENSHOT_DIR}/submission-${product}.png`,
        fullPage: true,
      });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Отправить заявку", exact: true })
      .click();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    await expect(
      page.getByRole("link", { name: "Редактировать", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Заявка отправлена", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Скачать report.png" })
      .first()
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("report.png");
    const { readFile } = await import("node:fs/promises");
    expect(await readFile((await download.path())!)).toEqual(png);
    await page.goto(`/applications/${id}/edit`);
    await expect(
      page.getByRole("heading", { name: "Редактирование недоступно" }),
    ).toBeVisible();
    await openQueuedApplication(staff, id);
    await expect(staff).toHaveURL(new RegExp(`/staff/applications/${id}$`));
    await expect(staff.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    await expect(
      staff.getByRole("button", { name: /Загрузить|Удалить|Отправить/ }),
    ).toHaveCount(0);
    await staffContext.close();
  });
}
test("incomplete_application_displays_errors_and_document_can_be_deleted", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page, "working_capital", false);
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(page.locator(".submission-errors")).toBeVisible();
  expect(
    (await (await page.request.get(`/api/v1/applications/${id}`)).json())
      .status,
  ).toBe("draft");
  await upload(page);
  await page.getByRole("button", { name: "Удалить report.png" }).click();
  await expect(
    page.getByRole("button", { name: "Скачать report.png" }),
  ).toHaveCount(0);
});
test("lost_submit_response_reuses_key_and_body", async ({ page }) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  await confirm(page);
  const commands: { key: string | undefined; body: string | null }[] = [];
  let intercepted = false;
  await page.route(`**/api/v1/applications/${id}/submit`, async (route) => {
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postData(),
    });
    if (!intercepted) {
      intercepted = true;
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      await route.abort("failed");
    } else await route.continue();
  });
  // На время повтора подавляем опрос: результат отправки проверяет повтор команды.
  await page.route(`**/api/v1/applications/${id}`, async (route) => {
    if (intercepted) await route.abort("failed");
    else await route.continue();
  });
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Повторить отправку" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить отправку" }).click();
  await expect(page.locator(".page-heading .status")).toHaveText("Отправлена");
  expect(commands).toHaveLength(2);
  expect(commands[0].key).toMatch(/^[a-f0-9-]{36}$/);
  expect(commands[1]).toEqual(commands[0]);
  const history = await (
    await page.request.get(`/api/v1/applications/${id}/history`)
  ).json();
  expect(
    history.items.filter(
      (event: { event_type: string }) =>
        event.event_type === "application_submitted",
    ),
  ).toHaveLength(1);
});
test("upload_rejects_changed_account_and_other_company_cannot_download", async ({
  page,
  context,
  browser,
}) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  const document = (
    await (
      await page.request.get(`/api/v1/applications/${id}/documents`)
    ).json()
  ).items[0];
  const fileUrl = `/api/v1/applications/${id}/documents/${document.id}`;
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await login(other, "client2@example.test");
  expect((await other.request.get(fileUrl!)).status()).toBe(404);
  await otherContext.close();
  const tab = await context.newPage();
  await tab.goto("/applications");
  await tab.getByRole("button", { name: "Выйти" }).click();
  await expect(tab).toHaveURL(/\/login$/);
  await login(tab, "client2@example.test");
  await page
    .getByLabel("Файл: Финансовая отчётность", { exact: true })
    .setInputFiles({ name: "private.png", mimeType: "image/png", buffer: png });
  await page
    .getByRole("button", { name: "Загрузить: Финансовая отчётность" })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await tab.close();
});

test("equipment_needs_invoice_and_open_card_polls_submission", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page, "equipment");
  await upload(page);
  await confirm(page);
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(page.locator(".submission-errors")).toContainText("Документы");
  await upload(page, "Счёт на оборудование");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const policy = await (
    await page.request.get("/api/v1/submission-policy")
  ).json();
  const result = await page.request.post(`/api/v1/applications/${id}/submit`, {
    headers: { "X-CSRF-Token": token, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_version: current.version,
      data_confirmed: true,
      bki_consent: true,
      consent_version: policy.consent_version,
    },
  });
  expect(result.status()).toBe(202);
  await expect(page.locator(".page-heading .status")).toHaveText("Отправлена", {
    timeout: 8000,
  });
  await expect(
    page.getByRole("link", { name: "Редактировать", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Заявка отправлена", { exact: true }),
  ).toBeVisible();
});

test("stale_editor_locks_after_reloading_submitted_application", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  await page.getByRole("link", { name: "Редактировать", exact: true }).click();
  await page
    .getByLabel("Цель финансирования")
    .fill("Несохранённое изменение после отправки");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const policy = await (
    await page.request.get("/api/v1/submission-policy")
  ).json();
  const result = await page.request.post(`/api/v1/applications/${id}/submit`, {
    headers: { "X-CSRF-Token": token, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_version: current.version,
      data_confirmed: true,
      bki_consent: true,
      consent_version: policy.consent_version,
    },
  });
  expect(result.status()).toBe(202);
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Несохранённое изменение после отправки",
  );
  await page
    .getByRole("button", { name: "Загрузить новую версию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Редактирование недоступно" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Сохранить черновик" }),
  ).toHaveCount(0);
});

for (const failure of ["404", "503", "network"] as const) {
  test(`download_${failure}_stays_in_card_and_can_be_retried`, async ({
    page,
  }) => {
    await login(page);
    const id = await draft(page);
    await upload(page);
    const document = (
      await (
        await page.request.get(`/api/v1/applications/${id}/documents`)
      ).json()
    ).items[0];
    await page.route(
      `**/api/v1/applications/${id}/documents/${document.id}`,
      async (route) => {
        if (failure === "network") await route.abort("failed");
        else
          await route.fulfill({
            status: Number(failure),
            contentType: "application/json",
            body: JSON.stringify({
              code: failure === "404" ? "document_not_found" : "unavailable",
              message:
                failure === "404"
                  ? "Документ не найден"
                  : "Сервис временно недоступен",
            }),
          });
      },
      { times: 1 },
    );
    await page.getByLabel("Скачать report.png", { exact: true }).click();
    await expect(page.locator(".download-error")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Повторить скачивание" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("report.png");
    const { readFile } = await import("node:fs/promises");
    expect(await readFile((await download.path())!)).toEqual(png);
    await expect(page.locator(".download-error")).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
  });
}
test("download_401_returns_to_login_instead_of_api_document", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  const document = (
    await (
      await page.request.get(`/api/v1/applications/${id}/documents`)
    ).json()
  ).items[0];
  await page.route(
    `**/api/v1/applications/${id}/documents/${document.id}`,
    (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          code: "authentication_required",
          message: "Войдите в кабинет",
        }),
      }),
    { times: 1 },
  );
  await page.getByLabel("Скачать report.png", { exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("heading", { name: "Вход в кабинет" }),
  ).toBeVisible();
});
