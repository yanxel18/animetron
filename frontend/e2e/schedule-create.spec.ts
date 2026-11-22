import { expect, test } from "@playwright/test";

const workflowId = "3986b877-6311-4193-9a9e-30788e8c8787";
const revision = "saved-revision-1";
const scheduleId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
const schedule = {
  id: scheduleId,
  workflowId,
  revision,
  expression: "0 9 * * *",
  timeZone: "Asia/Tokyo",
  enabled: false,
  nextDueAt: null,
  overlapPolicy: "skip",
  missedRunPolicy: "skip",
  version: 1,
  createdAt: "2026-11-15T00:00:00Z",
  updatedAt: "2026-11-15T00:00:00Z",
};
const viewports = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 900 },
  { width: 1440, height: 1000 },
];

test("creates the owner form from persisted choices and fits the target widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(`${request.method()} ${url.pathname}`);
    if (url.pathname === "/api/v1/schedules" && request.method() === "GET") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (url.pathname === "/api/v1/workflows" && request.method() === "GET") {
      await route.fulfill({ json: { data: [{ workflowId }], nextCursor: null } });
    } else if (url.pathname === `/api/v1/workflows/${workflowId}/revisions`) {
      await route.fulfill({
        json: { data: [{ workflowId, revision, createdAt: "2026-11-15T00:00:00Z" }], nextCursor: null },
      });
    } else {
      await route.fulfill({ status: 404, json: { error: "Unexpected fixture request" } });
    }
  });

  await page.goto("/#schedules");
  await page.getByRole("button", { name: "Create schedule" }).click();
  await page.getByLabel("Workflow ID").selectOption(workflowId);
  await page.getByLabel("Saved revision").selectOption(revision);
  await page.getByLabel("Five-field cron expression").fill("0 9 * * *");
  await page.getByLabel("IANA time zone").fill("Asia/Tokyo");
  for (const label of ["Workflow ID", "Saved revision", "Five-field cron expression", "IANA time zone"]) {
    const contrast = await page.getByLabel(label).evaluate((element) => {
      const surface = element.closest(".schedule-create");
      if (!surface) throw new Error("Missing schedule surface");
      const luminance = (color: string) => {
        const channels = color.match(/\d+/g)?.slice(0, 3).map(Number);
        if (!channels || channels.length !== 3) throw new Error(`Unexpected color: ${color}`);
        const values = channels.map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * values[0]! + 0.7152 * values[1]! + 0.0722 * values[2]!;
      };
      const values = [luminance(getComputedStyle(element).borderTopColor), luminance(getComputedStyle(surface).backgroundColor)].sort((a, b) => b - a);
      return (values[0]! + 0.05) / (values[1]! + 0.05);
    });
    expect(contrast, label).toBeGreaterThanOrEqual(3);
  }
  await expect(page.getByText(/dispatch is not implemented/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Create schedule" })).toBeVisible();

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(page.getByLabel("Workflow ID")).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({
      path: testInfo.outputPath(`schedule-create-${viewport.width}.png`),
      fullPage: true,
    });
  }
  expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
  expect(errors).toEqual([]);
});

test("keeps an unknown create blocked after reload and does not reconcile by list matching", async ({ page }) => {
  let postCount = 0;
  let scheduleReads = 0;
  const requestDetails: Array<{ origin: string | undefined; csrf: string | undefined; body: string | null }> = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/schedules" && request.method() === "GET") {
      scheduleReads += 1;
      await route.fulfill({ json: { data: [schedule], nextCursor: null } });
    } else if (url.pathname === "/api/v1/workflows" && request.method() === "GET") {
      await route.fulfill({ json: { data: [{ workflowId }], nextCursor: null } });
    } else if (url.pathname === `/api/v1/workflows/${workflowId}/revisions`) {
      await route.fulfill({
        json: { data: [{ workflowId, revision, createdAt: "2026-11-15T00:00:00Z" }], nextCursor: null },
      });
    } else if (url.pathname === "/api/v1/auth/session" && request.method() === "GET") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (url.pathname === "/api/v1/schedules" && request.method() === "POST") {
      postCount += 1;
      requestDetails.push({
        origin: request.headers().origin,
        csrf: request.headers()["x-csrf-token"],
        body: request.postData(),
      });
      if (postCount === 1) {
        await route.fulfill({ status: 503, json: { error: "fixture unavailable" } });
      } else {
        const body = JSON.parse(request.postData() ?? "{}") as typeof schedule;
        await route.fulfill({
          status: 201,
          json: {
            ...schedule,
            id: "00000000-0000-4000-8000-000000000001",
            workflowId: body.workflowId,
            revision: body.revision,
            expression: body.expression,
            timeZone: body.timeZone,
            enabled: body.enabled,
            nextDueAt: null,
          },
        });
      }
    } else {
      await route.fulfill({ status: 404, json: { error: "Unexpected fixture request" } });
    }
  });

  await page.goto("/#schedules");
  await page.getByRole("button", { name: "Create schedule" }).click();
  await page.getByLabel("Workflow ID").selectOption(workflowId);
  await page.getByLabel("Saved revision").selectOption(revision);
  await page.getByLabel("Five-field cron expression").fill("0 9 * * *");
  await page.getByLabel("IANA time zone").fill("Asia/Tokyo");
  await page.getByRole("button", { name: "Create schedule" }).click();
  await expect(page.getByRole("heading", { name: "Schedule outcome uncertain" })).toBeVisible();
  await expect(page.getByText(/could create a duplicate/i).first()).toBeVisible();
  expect(postCount).toBe(1);

  await page.reload();
  await expect(page.getByText(scheduleId)).toBeVisible();
  await page.getByRole("button", { name: "Create schedule" }).click();
  await expect(page.getByText(/a previous creation may have succeeded/i)).toBeVisible();
  await expect(page.getByText(/matching descriptor.*cannot prove/i)).toBeVisible();
  await page.getByLabel("Workflow ID").selectOption(workflowId);
  await page.getByLabel("Saved revision").selectOption(revision);
  await page.getByLabel("Five-field cron expression").fill("0 9 * * *");
  await page.getByLabel("IANA time zone").fill("Asia/Tokyo");
  const start = page.getByRole("button", { name: "Start a new attempt" });
  await expect(start).toBeDisabled();
  await page.getByRole("button", { name: "Refresh schedules" }).click();
  await expect.poll(() => scheduleReads).toBeGreaterThan(1);
  await expect(start).toBeDisabled();
  expect(postCount).toBe(1);

  await page.getByLabel(/I understand the prior attempt may have succeeded/i).check();
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByText(/earlier uncertain attempt remains unresolved/i)).toBeVisible();
  expect(postCount).toBe(2);
  expect(requestDetails[0]).toMatchObject({
    origin: "http://127.0.0.1:4173",
    csrf: "fixture-csrf",
    body: JSON.stringify({
      workflowId,
      revision,
      expression: "0 9 * * *",
      timeZone: "Asia/Tokyo",
      enabled: false,
      overlapPolicy: "skip",
      missedRunPolicy: "skip",
    }),
  });

  await page.reload();
  await expect(page.getByRole("button", { name: "Create schedule" })).toBeVisible();
  await page.getByRole("button", { name: "Create schedule" }).click();
  await expect(page.getByText(/a previous creation may have succeeded/i)).toBeVisible();
  expect(postCount).toBe(2);
});
