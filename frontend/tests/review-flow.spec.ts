import { test, expect, type Page } from "@playwright/test";
const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";
async function login(page: Page, staff = false, email?: string) {
  await page.goto("/login");
  await page
    .getByLabel("Электронная почта")
    .fill(email || (staff ? "staff@example.test" : "client1@example.test"));
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(
    staff ? /\/staff\/applications$/ : /\/applications$/,
  );
}
const id = "efbb7d37-1f76-4801-bdab-e417916293d1";
function application(status = "manual_review") {
  return {
    id,
    product_code: "working_capital",
    version: 7,
    status,
    updated_at: new Date().toISOString(),
    catalog_version: "demo-v1",
    purpose: "Тест рассмотрения",
    description: null,
    amount_kopecks: 100000000,
    term_months: 12,
    period_start: "2026-07-01",
    period_end: "2026-09-30",
    revenue_kopecks: 300000000,
    operating_expenses_kopecks: 100000000,
    existing_debt_payments_kopecks: 0,
    public_reasons: ["Нужен разбор сотрудника"],
    processing_status: "succeeded",
    information_requests: [],
    offers: [],
    available_actions: [
      "request_information",
      "make_offer",
      "approve",
      "reject",
    ],
  };
}
async function mockDetails(page: Page, get: () => object) {
  await page.route(`**/api/v1/applications/${id}`, (route) =>
    route.fulfill({ json: get() }),
  );
  await page.route(`**/api/v1/applications/${id}/documents`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`**/api/v1/applications/${id}/history?*`, (route) =>
    route.fulfill({ json: { items: [], total: 0, limit: 10, offset: 0 } }),
  );
  await page.route(`**/api/v1/applications/${id}/assessment`, (route) =>
    route.fulfill({
      json: {
        application_id: id,
        revision_id: null,
        runs: [],
        risk_assessment: null,
      },
    }),
  );
}
test("staff_reason_survives_poll_and_unknown_command_reuses_key_and_body", async ({
  page,
}) => {
  await login(page, true);
  let item = application();
  await mockDetails(page, () => item);
  const commands: { key: string | undefined; body: unknown }[] = [];
  await page.route(`**/api/v1/applications/${id}/decisions`, async (route) => {
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    if (commands.length === 1) {
      item = { ...item, status: "approved", version: 8, available_actions: [] };
      await route.abort("failed");
    } else
      await route.fulfill({
        status: 201,
        json: {
          application_id: id,
          version: 8,
          status: "approved",
          revision_id: id,
          decision_id: id,
        },
      });
  });
  await page.goto(`/staff/applications/${id}`);
  await expect(
    page.getByText("Обработка ещё не запускалась", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(
    page.getByText("Укажите основание решения", { exact: true }),
  ).toBeVisible();
  expect(commands).toHaveLength(0);
  const reason = page.getByLabel("Основание решения или предложения");
  await reason.fill("Проверены дополнительные сведения");
  if (process.env.SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.SCREENSHOT_DIR}/review-staff-1366.png`,
      fullPage: true,
    });
  await page.setViewportSize({ width: 320, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(320);
  if (process.env.SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.SCREENSHOT_DIR}/review-staff-320.png`,
      fullPage: true,
    });
  await page.waitForResponse((response) =>
    response.url().endsWith(`/api/v1/applications/${id}`),
  );
  await expect(reason).toHaveValue("Проверены дополнительные сведения");
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Повторить действие", exact: true }),
  ).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: "Повторить действие", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Повторить действие", exact: true }),
  ).toHaveCount(0);
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(commands[0].body).toEqual({
    expected_version: 7,
    outcome: "approved",
    risk_acknowledged: false,
    reason: "Проверены дополнительные сведения",
  });
});

test("offer_compare_and_stale_conflict_preserve_form", async ({ page }) => {
  await login(page);
  const item = {
    ...application("counteroffer"),
    available_actions: ["accept_offer", "decline_offer"],
    offers: [
      {
        id,
        version: 1,
        revision_id: id,
        application_version: 7,
        status: "active",
        product_code: "working_capital",
        amount_kopecks: 90000000,
        term_months: 18,
        monthly_payment_kopecks: 6500000,
        total_payment_kopecks: 117000000,
        annual_rate_bps: 2400,
        payment_terms: {
          payment_kind: "annuity", amount_kopecks: 90000000, term_months: 18,
          annual_rate_bps: 2400, annual_commission_bps: 0,
          monthly_payment_kopecks: 6500000, upfront_fee_kopecks: 0,
          principal_due_at_end_kopecks: 0, last_payment_kopecks: 6500000,
          total_payment_kopecks: 117000000, total_cost_kopecks: 27000000,
          assessment_monthly_burden_kopecks: 6500000,
          contingent_liability_kopecks: 0, assumptions: [],
        },
        reason: "Допустимая нагрузка",
        created_at: new Date().toISOString(),
      },
    ],
  };
  await mockDetails(page, () => item);
  let body: unknown;
  await page.route(`**/api/v1/offers/${id}/accept`, (route) => {
    body = route.request().postDataJSON();
    return route.fulfill({
      status: 409,
      json: { code: "version_conflict", message: "Версия заявки изменилась" },
    });
  });
  await page.goto(`/applications/${id}`);
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(page.getByRole("table")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(320);
  if (process.env.SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.SCREENSHOT_DIR}/review-offer-320.png`,
      fullPage: true,
    });
  await expect(
    page.getByRole("cell", { name: "900 000 ₽", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Принять условия", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Загрузить актуальное состояние",
      exact: true,
    }),
  ).toBeVisible();
  expect(body).toEqual({ expected_version: 7, offer_version: 1 });
  await expect(
    page.getByRole("button", { name: "Принять условия", exact: true }),
  ).toBeDisabled();
});

test("information_response_is_explicit_and_keeps_message_while_polling", async ({
  page,
}) => {
  await login(page);
  const item = {
    ...application("needs_info"),
    available_actions: ["edit_draft", "upload_document", "respond_information"],
    information_requests: [
      {
        id,
        revision_id: id,
        application_version: 7,
        status: "open",
        message: "Уточните выручку",
        requested_fields: ["revenue_kopecks"],
        requested_document_types: [],
        created_at: new Date().toISOString(),
        response_message: null,
        responded_by: null,
        responded_at: null,
        response_revision_id: null,
      },
    ],
  };
  await mockDetails(page, () => item);
  const commands: unknown[] = [];
  await page.route(
    `**/api/v1/applications/${id}/information-responses`,
    async (route) => {
      commands.push(route.request().postDataJSON());
      await route.fulfill({
        status: 422,
        json: {
          code: "validation_error",
          message: "Подтвердите данные",
          field_errors: { data_confirmed: "Нужно подтверждение" },
        },
      });
    },
  );
  await page.goto(`/applications/${id}`);
  await expect(
    page.getByText("Уточните выручку", { exact: true }),
  ).toBeVisible();
  const message = page.getByLabel("Сообщение к ответу");
  await message.fill("Выручка уточнена по отчётности");
  await page.waitForResponse((response) =>
    response.url().endsWith(`/api/v1/applications/${id}`),
  );
  expect(commands).toHaveLength(0);
  await expect(message).toHaveValue("Выручка уточнена по отчётности");
  await page
    .getByRole("button", { name: "Отправить ответ", exact: true })
    .click();
  await expect(
    page.getByText("Подтвердите данные", { exact: true }),
  ).toBeVisible();
  expect(commands).toEqual([
    {
      expected_version: 7,
      request_id: id,
      message: "Выручка уточнена по отчётности",
      data_confirmed: false,
      bki_consent: false,
      consent_version: "demo-consent-v1",
    },
  ]);
  await expect(message).toHaveValue("Выручка уточнена по отчётности");
});

test("staff_input_recovers_after_401_only_for_same_owner", async ({ page }) => {
  await login(page, true);
  await mockDetails(page, () => application());
  let commands = 0;
  await page.route(`**/api/v1/applications/${id}/decisions`, async (route) => {
    commands++;
    await route.fulfill({
      status: 401,
      json: { code: "session_expired", message: "Войдите снова" },
    });
  });
  await page.goto(`/staff/applications/${id}`);
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Основание, сохранённое до истечения сессии");
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("staff@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/staff/applications/${id}$`));
  await expect(
    page.getByLabel("Основание решения или предложения"),
  ).toHaveValue("Основание, сохранённое до истечения сессии");
  expect(commands).toBe(1);
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("client1@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await expect(
    page.getByLabel("Основание решения или предложения"),
  ).toHaveCount(0);
  expect(commands).toBe(2);
});

test("changed_account_cannot_send_staff_command_or_receive_staff_input", async ({
  page,
  context,
}) => {
  await login(page, true);
  await mockDetails(page, () => application());
  await page.goto(`/staff/applications/${id}`);
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Внутренний ввод сотрудника");
  let commands = 0;
  await page.route(`**/api/v1/applications/${id}/decisions`, async (route) => {
    commands++;
    await route.abort("failed");
  });
  const otherTab = await context.newPage();
  await otherTab.goto("/staff/applications");
  await otherTab.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(otherTab).toHaveURL(/\/login$/);
  await login(otherTab);
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  expect(commands).toBe(0);
  await page.getByLabel("Электронная почта").fill("client1@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await expect(
    page.getByLabel("Основание решения или предложения"),
  ).toHaveCount(0);
  await otherTab.close();
});

for (const staff of [false, true]) {
  test(`answered_information_is_readable_for_${staff ? "staff" : "client"}`, async ({
    page,
  }) => {
    await login(page, staff);
    const user = await (await page.request.get("/api/v1/me")).json();
    const item = {
      ...application("approved"),
      available_actions: [],
      information_requests: [
        {
          id,
          revision_id: id,
          application_version: 5,
          status: "answered",
          message: "Нужна актуальная отчётность",
          requested_fields: ["revenue_kopecks"],
          requested_document_types: ["financial_statement"],
          created_at: "2026-10-20T10:00:00Z",
          response_message: "Предоставлены дополнения и актуальная отчётность",
          responded_by: staff
            ? "55f1bcef-c6b3-4d28-ae1c-6cd51f7ef78f"
            : user.id,
          responded_at: "2026-10-20T11:00:00Z",
          response_revision_id: id,
        },
      ],
    };
    await mockDetails(page, () => item);
    await page.goto(`${staff ? "/staff" : ""}/applications/${id}`);
    await page.getByText("Отправленные ответы", { exact: true }).click();
    await expect(
      page.getByText("Нужна актуальная отчётность", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Предоставлены дополнения и актуальная отчётность", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText(staff ? /Клиент компании ·/ : /Вы ·/),
    ).toBeVisible();
    const displayedTime = new Date("2026-10-20T11:00:00Z").toLocaleString(
      "ru-RU",
      {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      },
    );
    await expect(page.locator(".answered-requests")).toContainText(
      displayedTime,
    );
    await expect(
      page.getByText("55f1bcef-c6b3-4d28-ae1c-6cd51f7ef78f", { exact: true }),
    ).toHaveCount(0);
  });
}

test("real_information_working_copy_and_extra_document_wait_for_explicit_response", async ({
  page,
  browser,
}) => {
  await login(page, false, "demo-d@example.test");
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const now = new Date();
  const start = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 3, 1),
  )
    .toISOString()
    .slice(0, 10);
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 0))
    .toISOString()
    .slice(0, 10);
  const created = await page.request.post("/api/v1/applications", {
    headers: { "X-CSRF-Token": token },
    data: {
      product_code: "working_capital",
      purpose: "Проверка дополнений",
      amount_kopecks: 50000000,
      term_months: 12,
      period_start: start,
      period_end: end,
      revenue_kopecks: 120000000,
      operating_expenses_kopecks: 90000000,
      existing_debt_payments_kopecks: 3000000,
    },
  });
  expect(created.status()).toBe(201);
  const draft = await created.json();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC",
    "base64",
  );
  const attached = await page.request.post(
    `/api/v1/applications/${draft.id}/documents?document_type=financial_statement&expected_version=${draft.version}&filename=original.png`,
    {
      headers: { "X-CSRF-Token": token, "Content-Type": "image/png" },
      data: png,
    },
  );
  expect(attached.status()).toBe(201);
  const uploaded = await attached.json();
  const sent = await page.request.post(
    `/api/v1/applications/${draft.id}/submit`,
    {
      headers: {
        "X-CSRF-Token": token,
        "Idempotency-Key": crypto.randomUUID(),
      },
      data: {
        expected_version: uploaded.application_version,
        data_confirmed: true,
        bki_consent: true,
        consent_version: "demo-consent-v1",
      },
    },
  );
  expect(sent.status()).toBe(202);
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/v1/applications/${draft.id}`)
          ).json()
        ).status,
    )
    .toBe("manual_review");
  const staffContext = await browser.newContext();
  try {
    const staff = await staffContext.newPage();
    await login(staff, true);
    await staff.goto(`/staff/applications/${draft.id}`);
    await expect(
      staff.locator(".assessment-run .risk-assessment").first(),
    ).toBeVisible();
    await expect(
      staff.getByText("Коэффициент покрытия", { exact: true }),
    ).toBeVisible();
    await staff.getByText("Запросить уточнения", { exact: true }).click();
    await staff
      .getByLabel("Сообщение клиенту")
      .fill("Нужна актуальная выручка и финансовая отчётность");
    await staff.getByRole("checkbox", { name: "Выручка", exact: true }).check();
    await staff
      .getByRole("checkbox", { name: "Финансовая отчётность", exact: true })
      .check();
    await staff
      .getByRole("button", { name: "Отправить запрос", exact: true })
      .click();
    await expect(staff.locator(".page-heading .status")).toHaveText(
      "Нужны уточнения",
    );
    await page.goto(`/applications/${draft.id}`);
    await expect(
      page.getByRole("button", { name: "Удалить original.png", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("link", { name: "Дополнить сведения", exact: true })
      .click();
    await expect(page.getByRole("radio").first()).toBeDisabled();
    await page
      .getByLabel("Выручка за период, ₽", { exact: true })
      .fill("1300000");
    await page
      .getByRole("button", { name: "Сохранить дополнения", exact: true })
      .click();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Нужны уточнения",
    );
    expect(
      (
        await (
          await page.request.get(`/api/v1/applications/${draft.id}`)
        ).json()
      ).revenue_kopecks,
    ).toBe(130000000);
    await page
      .getByLabel("Файл: Финансовая отчётность", { exact: true })
      .setInputFiles({ name: "extra.png", mimeType: "image/png", buffer: png });
    await page
      .getByRole("button", {
        name: "Загрузить: Финансовая отчётность",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("button", { name: "Скачать extra.png", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Нужны уточнения",
    );
    await expect(
      page.getByRole("button", { name: "Удалить extra.png", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Удалить original.png", exact: true }),
    ).toHaveCount(0);
    await page
      .getByLabel("Сообщение к ответу")
      .fill("Уточнил выручку и приложил актуальную отчётность");
    await page.locator(".review-panel .consent-list input").nth(0).check();
    await page.locator(".review-panel .consent-list input").nth(1).check();
    await page
      .getByRole("button", { name: "Отправить ответ", exact: true })
      .click();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "На рассмотрении сотрудника",
      { timeout: 10000 },
    );
    await page.getByText("Отправленные ответы", { exact: true }).click();
    await expect(
      page.getByText("Уточнил выручку и приложил актуальную отчётность", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Удалить extra.png", exact: true }),
    ).toHaveCount(0);
    await expect(staff.locator(".page-heading .status")).toHaveText(
      "На рассмотрении сотрудника",
      { timeout: 10000 },
    );
    await staff.getByText("Отправленные ответы", { exact: true }).click();
    await expect(
      staff.getByText("Уточнил выручку и приложил актуальную отчётность", {
        exact: true,
      }),
    ).toBeVisible();
  } finally {
    await staffContext.close();
  }
});

async function preparedReview(page: Page) {
  await login(page, false, "demo-d@example.test");
  const { csrf_token } = await (
    await page.request.get("/api/v1/auth/csrf")
  ).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const now = new Date();
  const created = await page.request.post("/api/v1/applications", {
    headers,
    data: {
      product_code: "working_capital",
      purpose: "Проверка сохранности команды",
      amount_kopecks: 50000000,
      term_months: 12,
      period_start: new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 3, 1),
      )
        .toISOString()
        .slice(0, 10),
      period_end: new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 0))
        .toISOString()
        .slice(0, 10),
      revenue_kopecks: 120000000,
      operating_expenses_kopecks: 90000000,
      existing_debt_payments_kopecks: 3000000,
    },
  });
  expect(created.status()).toBe(201);
  const item = await created.json();
  const attached = await page.request.post(
    `/api/v1/applications/${item.id}/documents?document_type=financial_statement&expected_version=${item.version}&filename=session.png`,
    {
      headers: { ...headers, "Content-Type": "image/png" },
      data: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC",
        "base64",
      ),
    },
  );
  expect(attached.status()).toBe(201);
  const uploaded = await attached.json();
  const sent = await page.request.post(
    `/api/v1/applications/${item.id}/submit`,
    {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        expected_version: uploaded.application_version,
        data_confirmed: true,
        bki_consent: true,
        consent_version: "demo-consent-v1",
      },
    },
  );
  expect(sent.status()).toBe(202);
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/v1/applications/${item.id}`)
          ).json()
        ).status,
    )
    .toBe("manual_review");
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, true);
  const owner = await (await page.request.get("/api/v1/me")).json();
  await page.goto(`/staff/applications/${item.id}`);
  await page.getByRole("checkbox", { name: "Изучена оценка риска исходных условий", exact: true }).check();
  return {
    id: item.id as string,
    storageKey: `credit-command:v1:${owner.id}:${item.id}`,
  };
}

test("committed_delayed_command_survives_local_session_changed_and_owner_switch", async ({
  page,
}) => {
  const item = await preparedReview(page);
  const commands: {
    key: string | undefined;
    body: string | null;
    path: string;
  }[] = [];
  let committed = false;
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/v1/applications/${item.id}/decisions`,
    async (route) => {
      commands.push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postData(),
        path: new URL(route.request().url()).pathname,
      });
      if (commands.length === 1) {
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        committed = true;
        await delayed;
        await route.fulfill({ response });
      } else await route.continue();
    },
  );
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Согласовано после проверки данных");
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect.poll(() => committed).toBe(true);
  const original = await page.evaluate(
    (key) => JSON.parse(sessionStorage.getItem(key) || "null"),
    item.storageKey,
  );
  await page.evaluate(() => window.dispatchEvent(new Event("session-expired")));
  await expect(page).toHaveURL(/\/login$/);
  const delivered = page.waitForResponse((response) =>
    response.url().endsWith(`/applications/${item.id}/decisions`),
  );
  release();
  await delivered;
  // Следующий сетевой цикл даёт обработчику позднего ответа завершиться.
  await page.request.get("/api/v1/health");
  await expect
    .poll(() =>
      page.evaluate(
        (key) => JSON.parse(sessionStorage.getItem(key) || "null"),
        item.storageKey,
      ),
    )
    .toEqual(original);
  await page.getByLabel("Электронная почта").fill("client1@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/applications$/);
  await expect(
    page.getByRole("button", { name: "Повторить действие", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Основание решения или предложения"),
  ).toHaveCount(0);
  expect(commands).toHaveLength(1);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, true);
  await page.goto(`/staff/applications/${item.id}`);
  await page
    .getByRole("button", { name: "Повторить действие", exact: true })
    .click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1]).toEqual(commands[0]);
  await expect
    .poll(() =>
      page.evaluate((key) => sessionStorage.getItem(key), item.storageKey),
    )
    .toBeNull();
  expect(
    (await (await page.request.get(`/api/v1/applications/${item.id}`)).json())
      .status,
  ).toBe("approved");
});

test("unknown_command_survives_retry_401_until_same_owner_retries_exact_body", async ({
  page,
}) => {
  const item = await preparedReview(page);
  const commands: {
    key: string | undefined;
    body: string | null;
    path: string;
  }[] = [];
  await page.route(
    `**/api/v1/applications/${item.id}/decisions`,
    async (route) => {
      commands.push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postData(),
        path: new URL(route.request().url()).pathname,
      });
      if (commands.length === 1) {
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        await route.abort("failed");
      } else if (commands.length === 2)
        await route.fulfill({
          status: 401,
          json: { code: "session_expired", message: "Войдите снова" },
        });
      else await route.continue();
    },
  );
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Проверенные сведения позволяют одобрить");
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Повторить действие", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Электронная почта").fill("staff@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/staff/applications/${item.id}$`));
  await page
    .getByRole("button", { name: "Повторить действие", exact: true })
    .click();
  await expect.poll(() => commands.length).toBe(3);
  expect(commands[1]).toEqual(commands[0]);
  expect(commands[2]).toEqual(commands[0]);
  await expect
    .poll(() =>
      page.evaluate((key) => sessionStorage.getItem(key), item.storageKey),
    )
    .toBeNull();
});
