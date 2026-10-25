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
  const row = page.locator(`.application-title[href="/staff/applications/${id}"]`);
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
    const first = page.locator(".application-title").first();
    const previous = await first.getAttribute("href");
    await next.click();
    await expect(first).not.toHaveAttribute("href", previous!);
  }
  await row.click();
}
async function confirm(page: Page) {
  await page.locator("#data-confirmed").check();
  await page.locator("#bki-consent").check();
}
test("upload_refresh_keeps_selected_file_names_in_sync", async ({ page }) => {
  await login(page);
  await draft(page, "equipment");
  const financial = page.getByLabel("Файл: Финансовая отчётность", {
    exact: true,
  });
  const invoice = page.getByLabel("Файл: Счёт на оборудование", { exact: true });
  const invoicePicker = page.locator(".document-picker").filter({ has: invoice });
  await financial.setInputFiles({
    name: "financial.png",
    mimeType: "image/png",
    buffer: png,
  });
  await invoice.setInputFiles({
    name: "invoice.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(
    invoicePicker.getByText("invoice.png", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Загрузить: Финансовая отчётность", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Скачать financial.png", exact: true }),
  ).toBeVisible();
  await expect(invoice).toBeEnabled();
  expect(
    await invoice.evaluate((input: HTMLInputElement) => input.files?.length),
  ).toBe(0);
  await expect(
    invoicePicker.getByText("Файл не выбран", { exact: true }),
  ).toBeVisible();
  await upload(page, "Счёт на оборудование");
  await expect(
    page.getByText("Выберите непустой файл", { exact: true }),
  ).toHaveCount(0);
});

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
      "Одобрена",
    );
    await expect(
      page.getByRole("link", { name: "Редактировать", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Заявка отправлена", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Одобрена",
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
      "Одобрена",
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
  await expect(page.locator(".page-heading .status")).toHaveText("Одобрена", {
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


async function submissionEvidence(
  page: Page,
  id: string,
  original: { revision_id: string; processing_run_id: string },
  browser: import("@playwright/test").Browser,
  checkAuthors = false,
) {
  const staffContext = await browser.newContext();
  try {
    const staff = await staffContext.newPage();
    await login(staff, "staff@example.test");
    await staff.goto(`/staff/applications/${id}`);
    const history = await (
      await staff.request.get(`/api/v1/applications/${id}/history?limit=100`)
    ).json();
    expect(
      history.items.filter(
        (event: { event_type: string }) =>
          event.event_type === "application_submitted",
      ),
    ).toHaveLength(1);
    const assessment = await (
      await staff.request.get(`/api/v1/applications/${id}/assessment`)
    ).json();
    expect(assessment.runs).toHaveLength(1);
    expect(assessment.runs[0].id).toBe(original.processing_run_id);
    expect(assessment.runs[0].revision_id).toBe(original.revision_id);
    if (checkAuthors) {
      await expect(staff.locator(".page-heading .status")).toHaveText(
        "На рассмотрении",
      );
      await staff
        .getByLabel("Основание решения или предложения")
        .fill("Проверены уточняющие сведения о компании");
      await staff
        .getByRole("button", { name: "Одобрить заявку", exact: true })
        .click();
      await expect(staff.locator(".page-heading .status")).toHaveText(
        "Одобрена",
      );
      await expect(page.locator(".page-heading .status")).toHaveText(
        "Одобрена",
      );
      for (const [view, otherAuthor] of [
        [page, "Сотрудник банка"],
        [staff, "Клиент компании"],
      ] as const) {
        const signatures = view.locator(".history small");
        await expect(
          signatures.filter({ hasText: /^Вы · версия \d+$/ }).first(),
        ).toBeVisible();
        await expect(
          signatures.filter({ hasText: /^Система · версия \d+$/ }).first(),
        ).toBeVisible();
        await expect(
          signatures
            .filter({ hasText: new RegExp(`^${otherAuthor} · версия \\d+$`) })
            .first(),
        ).toBeVisible();
        await expect(
          signatures.filter({ hasText: /Пользователь|[a-f0-9]{8}/ }),
        ).toHaveCount(0);
        await expect(view.locator(".history time").first()).toHaveAttribute(
          "datetime",
          /.+/,
        );
        if (process.env.SCREENSHOT_DIR)
          await view.screenshot({path: `${process.env.SCREENSHOT_DIR}/history-authors-${view === page ? "client" : "staff"}.png`, fullPage: true});
      }
    }
    await test
      .info()
      .attach("submission-evidence.json", {
        contentType: "application/json",
        body: JSON.stringify({
          application_id: id,
          revision_id: original.revision_id,
          processing_run_id: original.processing_run_id,
          runs: assessment.runs.length,
          submitted_events: history.items.filter(
            (event: { event_type: string }) =>
              event.event_type === "application_submitted",
          ).length,
        }),
      });
  } finally {
    await staffContext.close();
  }
}

test("committed_submit_survives_delayed_response_session_switch_and_has_readable_authors", async ({
  page,
  browser,
}) => {
  await login(page, "demo-d@example.test");
  const id = await draft(page);
  await upload(page);
  await confirm(page);
  const owner = await (await page.request.get("/api/v1/me")).json();
  const storageKey = `credit-submit:${owner.id}:${id}`;
  const commands: {
    key: string | undefined;
    body: string | null;
    path: string;
  }[] = [];
  const results: { revision_id: string; processing_run_id: string }[] = [];
  let committed = false;
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/applications/${id}/submit`, async (route) => {
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postData(),
      path: new URL(route.request().url()).pathname,
    });
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    results.push(await response.json());
    if (commands.length === 1) {
      committed = true;
      await delayed;
    }
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect.poll(() => committed).toBe(true);
  await expect(page.locator(".page-heading .status")).toHaveText(
    "На рассмотрении",
  );
  const original = await page.evaluate(
    (key) => JSON.parse(sessionStorage.getItem(key) || "null"),
    storageKey,
  );
  expect(original.key).toBe(commands[0].key);
  await page.evaluate(() => window.dispatchEvent(new Event("session-expired")));
  await expect(page).toHaveURL(/\/login$/);
  const delivered = page.waitForResponse((response) =>
    response.url().endsWith(`/applications/${id}/submit`),
  );
  release();
  await delivered;
  await page.request.get("/api/v1/health");
  await expect
    .poll(() =>
      page.evaluate(
        (key) => JSON.parse(sessionStorage.getItem(key) || "null"),
        storageKey,
      ),
    )
    .toEqual(original);
  await page.getByLabel("Электронная почта").fill("client2@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await page.goto(`/applications/${id}`);
  await expect(
    page.getByRole("heading", { name: "Заявка не найдена", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить отправку", exact: true }),
  ).toHaveCount(0);
  expect(commands).toHaveLength(1);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "demo-d@example.test");
  await page.goto(`/applications/${id}`);
  await expect(page.locator(".page-heading .status")).toHaveText(
    "На рассмотрении",
  );
  await page
    .getByRole("button", { name: "Повторить отправку", exact: true })
    .click();
  await expect.poll(() => commands.length).toBe(2);
  await expect.poll(() => results.length).toBe(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(results[1]).toEqual(results[0]);
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), storageKey))
    .toBeNull();
  await submissionEvidence(page, id, results[0], browser, true);
});

test("unknown_submit_survives_retry_401_and_reuses_original_submission", async ({
  page,
  browser,
}) => {
  await login(page, "demo-d@example.test");
  const id = await draft(page);
  await upload(page);
  await confirm(page);
  const owner = await (await page.request.get("/api/v1/me")).json();
  const storageKey = `credit-submit:${owner.id}:${id}`;
  const commands: {
    key: string | undefined;
    body: string | null;
    path: string;
  }[] = [];
  const results: { revision_id: string; processing_run_id: string }[] = [];
  await page.route(`**/api/v1/applications/${id}/submit`, async (route) => {
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postData(),
      path: new URL(route.request().url()).pathname,
    });
    if (commands.length === 2) {
      await route.fulfill({
        status: 401,
        json: { code: "session_expired", message: "Войдите снова" },
      });
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    results.push(await response.json());
    if (commands.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(page.locator(".page-heading .status")).toHaveText(
    "На рассмотрении",
  );
  await page
    .getByRole("button", { name: "Повторить отправку", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("demo-d@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
  await page
    .getByRole("button", { name: "Повторить отправку", exact: true })
    .click();
  await expect.poll(() => commands.length).toBe(3);
  await expect.poll(() => results.length).toBe(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(commands[2]).toEqual(commands[0]);
  expect(results[1]).toEqual(results[0]);
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), storageKey))
    .toBeNull();
  await submissionEvidence(page, id, results[0], browser);
});
