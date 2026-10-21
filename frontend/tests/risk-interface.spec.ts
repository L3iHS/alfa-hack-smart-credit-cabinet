import { test, expect, type Page } from "@playwright/test";

const id = "efbb7d37-1f76-4801-bdab-e417916293d1";
const revision = "bba71ddd-1cb0-4686-9513-a3a228701403";
function risk(probability = 0.1684, extra: Record<string, unknown> = {}) {
  return {
    assessment_id: "risk-original",
    revision_id: revision,
    processing_run_id: "run-current",
    status: "succeeded",
    reason_code: null,
    scorer_kind: "model",
    scorer_version: "logistic-risk-v1",
    feature_schema_version: "risk-features-v1",
    target_event: "loan_90dpd_12m",
    horizon_months: 12,
    data_kind: "synthetic",
    prediction_scope: "requested_terms",
    offer_version: null,
    terms_fingerprint: "requested",
    terms: {
      product_code: "working_capital",
      amount_kopecks: 100000000,
      term_months: 12,
      annual_rate_bps: 2400,
    },
    probability,
    risk_band:
      probability < 0.1 ? "low" : probability < 0.3 ? "elevated" : "high",
    explanation_method: "linear_contributions",
    explanation_scale: "raw_log_odds",
    base_value: -1.5,
    raw_prediction: -1.6,
    contributions: [],
    top_increasing_factors: [
      { feature_name: "debt", label: "Долговая нагрузка", contribution: 0.4 },
    ],
    top_decreasing_factors: [
      { feature_name: "age", label: "Возраст компании", contribution: -0.5 },
    ],
    ...extra,
  };
}
function app() {
  return {
    id,
    product_code: "working_capital",
    version: 7,
    status: "manual_review",
    updated_at: "2026-10-21T10:00:00Z",
    catalog_version: "demo-v1",
    purpose: "Закупка материалов",
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
    available_actions: ["make_offer", "approve", "reject"],
  };
}
function assessment(scores = [risk()], extra: Record<string, unknown> = {}) {
  return {
    application_id: id,
    revision_id: revision,
    risk_assessment: scores[0] || null,
    runs: [
      {
        id: "run-current",
        revision_id: revision,
        status: "succeeded",
        catalog_version: "demo-v1",
        policy_version: "demo-policy-0.3",
        source_version: "synthetic-v1",
        scorer_version: "logistic-risk-v1",
        created_at: "2026-10-21T10:00:00Z",
        error_code: null,
        checks: [],
        calculation: null,
        decision: { internal_reason: "Риск требует рассмотрения сотрудником" },
        risk_assessments: scores,
      },
    ],
    ...extra,
  };
}
async function open(
  page: Page,
  getAssessment: () => unknown,
  getApp = app,
  staff = true,
) {
  await page.goto("/login");
  await page
    .getByLabel("Электронная почта")
    .fill(staff ? "staff@example.test" : "client1@example.test");
  await page
    .getByLabel("Пароль", { exact: true })
    .fill(process.env.DEMO_PASSWORD || "Demo-credit-2026!");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(
    staff ? /\/staff\/applications$/ : /\/applications$/,
  );
  await page.route(`**/api/v1/applications/${id}`, (route) =>
    route.fulfill({ json: getApp() }),
  );
  await page.route(`**/api/v1/applications/${id}/documents`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`**/api/v1/applications/${id}/history?*`, (route) =>
    route.fulfill({ json: { items: [], total: 0, limit: 10, offset: 0 } }),
  );
  await page.route(`**/api/v1/applications/${id}/assessment`, (route) =>
    route.fulfill({ json: getAssessment() }),
  );
  await page.goto(`${staff ? "/staff" : ""}/applications/${id}`);
}
for (const [p, label, display] of [
  [0.070751957, "Низкий риск", "7,08%"],
  [0.1, "Повышенный риск", "10,00%"],
  [0.3, "Высокий риск", "30,00%"],
  [0.09999999999999999, "Низкий риск", "< 10%"],
  [0.29999999999999993, "Повышенный риск", "< 30%"],
] as const) {
  test(`staff risk ${p} preserves category near thresholds`, async ({
    page,
  }) => {
    await open(page, () => assessment([risk(p)]));
    const score = page.locator(".assessment-run .risk-assessment");
    await expect(score).toContainText(label);
    await expect(score).toContainText(display);
    await expect(score).toContainText("Просрочка 90+ дней в первые 12 месяцев");
    await expect(score).toContainText("Синтетические данные");
    await expect(score).toContainText("1 000 000");
    await expect(score).toContainText("12 мес.");
    await expect(score).toContainText("logistic-risk-v1");
    await expect(
      score
        .locator(".risk-factors")
        .getByText("Долговая нагрузка", { exact: true }),
    ).toBeVisible();
    await score.getByText("Численные вклады", { exact: true }).click();
    await expect(score).toContainText("log odds");
    await expect(score).not.toContainText("SHAP");
  });
}
test("empty factors and missing risk never become zero", async ({ page }) => {
  await open(page, () =>
    assessment([
      risk(0.15, { top_increasing_factors: [], top_decreasing_factors: [] }),
    ]),
  );
  await expect(
    page.getByText("Нет повышающих факторов", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Нет снижающих факторов", { exact: true }),
  ).toBeVisible();
});
for (const [state, text] of [
  ["failed", "Техническая ошибка оценки"],
  ["not_applicable", "Оценка неприменима"],
] as const) {
  test(`risk ${state} has no numeric substitute`, async ({ page }) => {
    await open(page, () =>
      assessment([
        risk(0.15, {
          status: state,
          probability: null,
          risk_band: null,
          reason_code: state === "failed" ? "model_unavailable" : "hard_stop",
          top_increasing_factors: [],
          top_decreasing_factors: [],
        }),
      ]),
    );
    await expect(page.locator(".risk-assessment")).toContainText(text);
    await expect(page.locator(".risk-assessment")).not.toContainText("0,00%");
    await expect(
      page.getByRole("checkbox", { name: /Изучена оценка/ }),
    ).toHaveCount(0);
  });
}
test("historical policy and previous revision are labelled separately", async ({
  page,
}) => {
  const old = {
    ...assessment().runs[0],
    id: "old-run",
    revision_id: "old-revision",
    policy_version: "demo-policy-0.2",
    scorer_version: null,
    risk_assessments: [],
  };
  await open(page, () =>
    assessment([], {
      revision_id: "new-revision",
      risk_assessment: null,
      runs: [
        old,
        {
          ...assessment().runs[0],
          status: "pending",
          revision_id: "new-revision",
          risk_assessments: [],
        },
      ],
    }),
  );
  await expect(
    page.getByText("Ожидается расчёт риска", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".assessment-run")
    .first()
    .locator("summary")
    .first()
    .click();
  await expect(
    page.getByText("Историческая политика без ML", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".assessment-run").first()).toContainText(
    "Предыдущая отправка",
  );
});
test("approval needs explicit acknowledgement and resets on application version", async ({
  page,
}) => {
  let current = app();
  await open(
    page,
    () => assessment(),
    () => current,
  );
  const ack = page.getByRole("checkbox", {
    name: "Изучена оценка риска исходных условий",
  });
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Риск рассмотрен");
  let body: Record<string, unknown> | null = null;
  await page.route(`**/api/v1/applications/${id}/decisions`, async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: { version: 8, status: "approved" } });
  });
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Подтвердите");
  expect(body).toBeNull();
  await ack.check();
  await page.getByText("Предложить другие условия", { exact: true }).click();
  await page.getByLabel("Предлагаемая сумма, ₽").fill("900000");
  await expect(ack).not.toBeChecked();
  await ack.check();
  current = { ...current, version: 8 };
  await expect(ack).not.toBeChecked({ timeout: 6000 });
  await ack.check();
  await page
    .getByRole("button", { name: "Одобрить заявку", exact: true })
    .click();
  await expect.poll(() => body?.risk_acknowledged).toBe(true);
});
test("409 refreshes unchanged-version offered risk before confirmation and terms reset it", async ({
  page,
}) => {
  let scores = [risk()];
  await open(page, () => assessment(scores));
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Проверены новые условия");
  await page.getByText("Предложить другие условия", { exact: true }).click();
  await page.getByLabel("Предлагаемая сумма, ₽").fill("900000");
  await page.getByLabel("Предлагаемый срок, месяцев").fill("18");
  const sent: Record<string, unknown>[] = [];
  await page.route(`**/api/v1/applications/${id}/offers`, async (route) => {
    sent.push(route.request().postDataJSON());
    if (sent.length === 1) {
      scores = [
        risk(),
        risk(0.35, {
          assessment_id: "risk-offered",
          prediction_scope: "offered_terms",
          terms_fingerprint: "offer900",
          terms: {
            product_code: "working_capital",
            amount_kopecks: 90000000,
            term_months: 18,
            annual_rate_bps: 2400,
          },
        }),
      ];
      await route.fulfill({
        status: 409,
        json: {
          code: "risk_acknowledgement_required",
          message: "Изучите оценку новых условий",
        },
      });
    } else
      await route.fulfill({ json: { version: 8, status: "counteroffer" } });
  });
  await page
    .getByRole("button", { name: "Отправить предложение", exact: true })
    .click();
  const form = page.locator(".review-form").last();
  await expect(form.locator(".risk-assessment")).toContainText("35,00%");
  await expect(form.locator(".risk-assessment")).toContainText("900 000");
  await expect(form.locator(".risk-assessment")).toContainText("18 мес.");
  await expect(
    page.getByText("Заявка изменилась.", { exact: false }),
  ).toHaveCount(0);
  if (process.env.SCREENSHOT_DIR) {
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `${process.env.SCREENSHOT_DIR}/task-3-offered-${width}.png`,
        fullPage: true,
      });
    }
  }
  const ack = page.getByRole("checkbox", {
    name: "Изучена оценка риска новых условий",
  });
  await ack.check();
  await page.getByLabel("Предлагаемая сумма, ₽").fill("850000");
  await expect(ack).toHaveCount(0);
  await page.getByLabel("Предлагаемая сумма, ₽").fill("900000");
  await expect(ack).not.toBeChecked();
  await ack.check();
  await page
    .getByRole("button", { name: "Отправить предложение", exact: true })
    .click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[0].risk_acknowledged).toBe(false);
  expect(sent[1].risk_acknowledged).toBe(true);
  expect(sent[1].expected_version).toBe(7);
});
test("known model error refreshes failed offered assessment without unknown retry", async ({
  page,
}) => {
  let scores = [risk()];
  await open(page, () => assessment(scores));
  await page
    .getByLabel("Основание решения или предложения")
    .fill("Новые условия");
  await page.getByText("Предложить другие условия", { exact: true }).click();
  await page.getByLabel("Предлагаемая сумма, ₽").fill("900000");
  await page.getByLabel("Предлагаемый срок, месяцев").fill("18");
  await page.route(`**/api/v1/applications/${id}/offers`, async (route) => {
    scores = [
      risk(),
      risk(0.35, {
        assessment_id: "failed-offer",
        prediction_scope: "offered_terms",
        status: "failed",
        probability: null,
        risk_band: null,
        reason_code: "model_unavailable",
        terms: {
          product_code: "working_capital",
          amount_kopecks: 90000000,
          term_months: 18,
          annual_rate_bps: 2400,
        },
      }),
    ];
    await route.fulfill({
      status: 503,
      json: {
        code: "risk_model_unavailable",
        message: "Оценка риска недоступна. Решение не принято",
      },
    });
  });
  await page
    .getByRole("button", { name: "Отправить предложение", exact: true })
    .click();
  await expect(page.locator(".review-form .risk-assessment")).toContainText(
    "Техническая ошибка оценки",
  );
  await expect(
    page.getByRole("button", { name: "Повторить действие", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("Решение не принято");
});
test("client never requests internal assessment or sees risk", async ({
  page,
}) => {
  let reads = 0;
  await open(
    page,
    () => {
      reads++;
      return assessment();
    },
    app,
    false,
  );
  await expect(page.locator(".details-panel")).toBeVisible();
  await expect(page.locator(".risk-assessment")).toHaveCount(0);
  expect(reads).toBe(0);
});
for (const width of [320, 390, 768, 1440]) {
  test(`risk visual keyboard and overflow ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await open(page, () => assessment([risk(0.35)]));
    await expect(page.locator(".risk-assessment").first()).toBeVisible();
    const ack = page.getByRole("checkbox", {
      name: "Изучена оценка риска исходных условий",
    });
    await page.getByLabel("Основание решения или предложения").focus();
    await page.keyboard.press("Tab");
    await expect(ack).toBeFocused();
    await page.keyboard.press("Space");
    await expect(ack).toBeChecked();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    if (process.env.SCREENSHOT_DIR) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `${process.env.SCREENSHOT_DIR}/task-3-risk-${width}.png`,
        fullPage: true,
      });
    }
  });
}
