import { expect, test } from "@playwright/test";

const viewports = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 900 },
  { width: 1440, height: 1000 },
];

function luminance(color: string) {
  const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  if (!channels || channels.length !== 3) {
    throw new Error(`Unexpected computed color: ${color}`);
  }
  const linear = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!
  );
}

function contrastRatio(foreground: string, background: string) {
  const values = [luminance(foreground), luminance(background)].sort(
    (first, second) => second - first,
  );
  return (values[0]! + 0.05) / (values[1]! + 0.05);
}

test("keeps the workspace usable at the required viewport widths", async ({
  page,
}, testInfo) => {
  await page.goto("/");

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(
      page.getByRole("main", { name: "Creator workspace" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Workflow canvas" }),
    ).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
      workspaceWidth: document.querySelector("main")?.getBoundingClientRect()
        .width,
    }));
    expect(
      dimensions.contentWidth,
      `horizontal overflow at ${viewport.width}px: ${JSON.stringify(dimensions)}`,
    ).toBeLessThanOrEqual(dimensions.viewportWidth);

    await page.screenshot({
      path: testInfo.outputPath(`studio-${viewport.width}.png`),
      fullPage: true,
    });
  }
});

test("measures rendered text and control contrast from computed browser colors", async ({
  page,
}) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const pairs = await page.evaluate(() => {
    const measure = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing contrast sample: ${selector}`);
      const style = getComputedStyle(element);
      return {
        selector,
        foreground: style.color,
        background: style.backgroundColor,
      };
    };
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement)) {
      throw new Error("Keyboard focus did not reach a visible workspace control");
    }
    const focusStyle = getComputedStyle(focused);
    return [
      measure("body"),
      measure(".availability-note"),
      measure(".button--secondary"),
      measure(".button--primary"),
      measure(".navigation-link--current"),
      {
        selector: "keyboard focus ring on Studio navigation",
        foreground: focusStyle.outlineColor,
        background: focusStyle.backgroundColor,
      },
    ];
  });
  const results = pairs.map((pair) => ({
    ...pair,
    ratio: Number(contrastRatio(pair.foreground, pair.background).toFixed(2)),
  }));
  console.info("Computed contrast measurements:", JSON.stringify(results));

  for (const result of results) {
    expect(
      result.ratio,
      `${result.selector}: ${result.foreground} on ${result.background}`,
    ).toBeGreaterThanOrEqual(
      result.selector.startsWith("keyboard focus ring") ? 3 : 4.5,
    );
  }
});

test("exposes real disabled states and navigable landmarks", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("navigation", { name: "Studio sections" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Studio" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Models" })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run workflow" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run workflow" }),
  ).toHaveAccessibleDescription(/not implemented in P7-01/i);
  await expect(
    page.getByRole("heading", { name: "No workflow is loaded" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Runs" })).toBeVisible();
  await expect(page.getByText("Backend not checked")).toBeVisible();
});

test("renders the metadata-only review queue without overflow at every target width", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.route("**/api/v1/reviews?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            id: "3e3f44c7-f1ae-4c62-9afd-8146ddb19179",
            runId: "3986b877-6311-4193-9a9e-30788e8c8787",
            artifactRevision: "revision-7",
            artifactSha256: "a".repeat(64),
            captionSha256: "b".repeat(64),
            destinations: [{ provider: "facebook", accountId: "page-42" }],
            expiresAt: "2026-11-16T12:00:00Z",
            createdAt: "2026-11-15T12:00:00Z",
            state: "AWAITING_DECISION",
            stateChangedAt: "2026-11-15T12:30:00Z",
            deliveryErrorCode: null,
          },
        ],
        nextCursor: null,
      }),
    }),
  );
  await page.goto("/#review");

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(
      page.getByRole("main", { name: "Review workspace" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Review queue", level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Studio", level: 1 }),
    ).toHaveCount(0);
    await expect(page.getByText("facebook · page-42")).toBeVisible();
    await expect(
      page.getByText(/exact media and caption can be reviewed/i),
    ).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(
      dimensions.contentWidth,
      `horizontal overflow at ${viewport.width}px: ${JSON.stringify(dimensions)}`,
    ).toBeLessThanOrEqual(dimensions.viewportWidth);
  }

  await expect(
    page.getByRole("button", { name: /approve|reject/i }),
  ).toHaveCount(0);
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to workspace" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#review-queue-title$/);
  await expect(
    page.getByRole("heading", { name: "Review queue", level: 1 }),
  ).toBeFocused();
  expect(browserErrors).toEqual([]);
});

test("renders persisted run history across target widths", async ({ page }, testInfo) => {
  const runId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.route(`**/api/v1/runs/${runId}**`, (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname.endsWith("/events")
      ? {
          data: [{
            runId,
            sequence: 1,
            state: "SUCCEEDED",
            message: "Run completed",
            occurredAt: "2026-11-15T12:00:00Z",
          }],
          nextAfterSequence: 1,
          hasMore: false,
        }
      : { runId, state: "SUCCEEDED", lastSequence: 1 };
    return route.fulfill({ status: 200, json: body });
  });

  await page.goto("/#runs");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to workspace" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Run monitor" })).toBeFocused();
  await page.getByLabel("Run ID").fill(runId);
  await page.getByRole("button", { name: "Open run" }).click();
  await expect(page.getByText("Run completed")).toBeVisible();
  await expect(page.getByText("Run finished")).toBeVisible();

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(page.getByRole("heading", { name: "Run monitor" })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({
      path: testInfo.outputPath(`runs-${viewport.width}.png`),
      fullPage: true,
    });
  }
  await expect(page.getByRole("button", { name: /start|cancel run/i })).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});

test("renders saved schedules across target widths without automatic updates", async ({ page }, testInfo) => {
  const browserErrors: string[] = [];
  const methods: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.route("**/api/v1/schedules?*", (route) => {
    methods.push(route.request().method());
    return route.fulfill({
      status: 200,
      json: {
        data: [{
          id: "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53",
          workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
          revision: "revision-1",
          expression: "0 9 * * *",
          timeZone: "Asia/Tokyo",
          enabled: true,
          nextDueAt: "2026-11-16T00:00:00Z",
          overlapPolicy: "skip",
          missedRunPolicy: "skip",
          version: 1,
          createdAt: "2026-11-15T00:00:00Z",
          updatedAt: "2026-11-15T00:00:00Z",
        }],
        nextCursor: null,
      },
    });
  });

  await page.goto("/#schedules");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to workspace" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#schedule-list-title$/);
  await expect(page.getByRole("heading", { name: "Schedules" })).toBeFocused();
  await expect(page.getByText("0 9 * * *")).toBeVisible();
  await expect(page.getByText(/dispatch is not implemented/i)).toBeVisible();

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(page.getByRole("main", { name: "Schedules workspace" })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({
      path: testInfo.outputPath(`schedules-${viewport.width}.png`),
      fullPage: true,
    });
  }
  await expect(page.getByRole("button", { name: "Create schedule" })).toHaveAttribute("aria-expanded", "false");
  expect(methods.length).toBeGreaterThan(0);
  expect(methods.every((method) => method === "GET")).toBe(true);
  expect(browserErrors).toEqual([]);
});

test("pauses a saved schedule using its version", async ({ page }, testInfo) => {
  const id = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
  const schedule = {
    id, workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
    revision: "revision-1", expression: "0 9 * * *", timeZone: "Asia/Tokyo",
    enabled: true, nextDueAt: "2026-11-16T00:00:00Z", overlapPolicy: "skip",
    missedRunPolicy: "skip", version: 1, createdAt: "2026-11-15T00:00:00Z",
    updatedAt: "2026-11-15T00:00:00Z",
  };
  let updates = 0;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/schedules" && request.method() === "GET") {
      return route.fulfill({ json: { data: [schedule], nextCursor: null } });
    }
    if (pathname === "/api/v1/auth/session" && request.method() === "GET") {
      return route.fulfill({ json: { role: "owner", csrfToken: "test-csrf" } });
    }
    if (pathname === `/api/v1/schedules/${id}` && request.method() === "PUT") {
      updates += 1;
      expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
      expect(request.postDataJSON()).toEqual({
        workflowId: schedule.workflowId, revision: schedule.revision,
        expression: schedule.expression, timeZone: schedule.timeZone, enabled: false,
        overlapPolicy: "skip", missedRunPolicy: "skip", expectedVersion: 1,
      });
      return route.fulfill({ json: { ...schedule, enabled: false, nextDueAt: null, version: 2 } });
    }
    throw new Error(`Unexpected API request: ${request.method()} ${pathname}`);
  });
  await page.goto("/#schedules");
  const button = page.getByRole("button", { name: `Pause schedule ${id}` });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Paused", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: `Resume schedule ${id}` })).toBeVisible();
  await expect(page.getByText(/scheduler dispatch is not implemented/i)).toBeVisible();
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({ path: testInfo.outputPath(`pause-${viewport.width}.png`), fullPage: true });
  }
  expect(updates).toBe(1);
  expect(errors).toEqual([]);
});

for (const focusTarget of ["schedule", "navigation"] as const) {
  test(`recovers from a delayed schedule conflict with focus on ${focusTarget}`, async ({ page }) => {
    const id = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
    const schedule = {
      id, workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
      revision: "revision-1", expression: "0 9 * * *", timeZone: "Asia/Tokyo",
      enabled: true, nextDueAt: "2026-11-16T00:00:00Z", overlapPolicy: "skip",
      missedRunPolicy: "skip", version: 1, createdAt: "2026-11-15T00:00:00Z",
      updatedAt: "2026-11-15T00:00:00Z",
    };
    let updates = 0;
    let reads = 0;
    let releaseResponse!: () => void;
    let notifyRequest!: () => void;
    const requestArrived = new Promise<void>((resolve) => { notifyRequest = resolve; });
    const responseReleased = new Promise<void>((resolve) => { releaseResponse = resolve; });
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === "/api/v1/schedules" && request.method() === "GET") {
        reads += 1;
        await route.fulfill({ json: { data: [schedule], nextCursor: null } });
      } else if (pathname === "/api/v1/auth/session" && request.method() === "GET") {
        await route.fulfill({ json: { role: "owner", csrfToken: "test-csrf" } });
      } else if (pathname === `/api/v1/schedules/${id}` && request.method() === "PUT") {
        updates += 1;
        notifyRequest();
        await responseReleased;
        await route.fulfill({ status: 409, json: {} });
      } else {
        throw new Error(`Unexpected API request: ${request.method()} ${pathname}`);
      }
    });

    await page.goto("/#schedules");
    const pause = page.getByRole("button", { name: `Pause schedule ${id}` });
    await pause.click();
    await requestArrived;
    const focus = focusTarget === "schedule"
      ? page.getByRole("button", { name: `Preview next five for schedule ${id}` })
      : page.getByRole("link", { name: "Studio" });
    await focus.focus();
    await expect(focus).toBeFocused();
    releaseResponse();
    const refresh = page.getByRole("button", { name: "Refresh schedules" });
    await expect(page.getByRole("alert")).toContainText(/refresh schedules/i);
    await expect(focusTarget === "schedule" ? refresh : focus).toBeFocused();
    expect(updates).toBe(1);
    const previousReads = reads;
    await refresh.click();
    await expect(page.getByRole("button", { name: `Pause schedule ${id}` })).toBeVisible();
    expect(reads).toBeGreaterThan(previousReads);
    expect(updates).toBe(1);
  });
}

test("previews saved schedule times without starting a run", async ({ page }, testInfo) => {
  const id = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    requests.push(`${request.method()} ${pathname}`);
    if (pathname === "/api/v1/schedules") {
      return route.fulfill({ json: { data: [{
        id, workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
        revision: "revision-1", expression: "0 9 * * *", timeZone: "Asia/Tokyo",
        enabled: false, nextDueAt: null, overlapPolicy: "skip", missedRunPolicy: "skip",
        version: 1, createdAt: "2026-11-15T00:00:00Z", updatedAt: "2026-11-15T00:00:00Z",
      }], nextCursor: null } });
    }
    if (pathname === "/api/v1/auth/session") {
      return route.fulfill({ json: { role: "owner", csrfToken: "test-csrf" } });
    }
    if (pathname === `/api/v1/schedules/${id}/previews`) {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
      expect(request.postData()).toBe("{}");
      return route.fulfill({ json: {
        occurrences: Array.from({ length: 5 }, (_, index) => ({
          localTime: `2026-11-${16 + index}T09:00:00+09:00`,
          dueAt: `2026-11-${16 + index}T00:00:00Z`,
          slotKey: `Asia/Tokyo:2026-11-${16 + index}T09:00`,
        })),
      } });
    }
    throw new Error(`Unexpected API request: ${pathname}`);
  });

  await page.goto("/#schedules");
  const button = page.getByRole("button", { name: `Preview next five for schedule ${id}` });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("2026-11-16T09:00:00+09:00")).toBeVisible();
  await expect(page.getByText(/even for paused schedules/i)).toBeVisible();
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({ path: testInfo.outputPath(`preview-${viewport.width}.png`), fullPage: true });
  }
  expect(requests.filter((request) => request === "GET /api/v1/schedules").length).toBeGreaterThan(0);
  expect(requests.filter((request) => request !== "GET /api/v1/schedules")).toEqual([
    "GET /api/v1/auth/session",
    `POST /api/v1/schedules/${id}/previews`,
  ]);
  expect(errors).toEqual([]);
});

test("starts keyboard navigation at the skip link and moves focus to the workspace", async ({
  page,
}) => {
  await page.goto("/");
  await page.keyboard.press("Tab");

  const skipLink = page.getByRole("link", { name: "Skip to workspace" });
  await expect(skipLink).toBeFocused();
  const focusStyle = await skipLink.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(focusStyle.outlineStyle).toBe("solid");
  expect(focusStyle.outlineWidth).not.toBe("0px");

  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#workspace$/);
  await expect(
    page.getByRole("main", { name: "Creator workspace" }),
  ).toBeFocused();
});

test("opens and closes the mobile navigation without enabling unavailable screens", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");

  const openButton = page.getByRole("button", { name: "Open navigation" });
  await expect(openButton).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(openButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("navigation", { name: "Studio sections" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Runs" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Library" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Models" })).toBeDisabled();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Studio" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toHaveAttribute("aria-expanded", "false");
  await expect(openButton).toBeFocused();
  await expect(
    page.getByRole("navigation", { name: "Studio sections" }),
  ).toBeHidden();

  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("navigation", { name: "Studio sections" }),
  ).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toHaveAttribute("aria-expanded", "false");
});

test("honors reduced motion and remains usable at a 200 percent effective viewport", async ({
  browser,
}, testInfo) => {
  const zoomContext = await browser.newContext({
    viewport: { width: 720, height: 900 },
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
  });
  try {
    const zoomPage = await zoomContext.newPage();
    await zoomPage.goto("/");
    const transition = await zoomPage
      .getByRole("button", { name: "Validate" })
      .evaluate((element) => getComputedStyle(element).transitionDuration);
    expect(Number.parseFloat(transition)).toBeLessThan(0.001);

    const zoomState = await zoomPage.evaluate(() => ({
      devicePixelRatio: window.devicePixelRatio,
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    console.info(
      "200% effective viewport rendering:",
      JSON.stringify(zoomState),
    );
    expect(zoomState.devicePixelRatio).toBe(2);
    expect(zoomState.viewportWidth).toBe(720);
    expect(zoomState.contentWidth).toBeLessThanOrEqual(
      zoomState.viewportWidth,
    );
    await expect(
      zoomPage.getByRole("heading", { name: "Studio", level: 1 }),
    ).toBeVisible();
    await zoomPage.screenshot({
      path: testInfo.outputPath("studio-effective-200-percent.png"),
      fullPage: true,
    });
  } finally {
    await zoomContext.close();
  }
});

test("looks up owner-only artifact metadata without listing or previewing bytes", async ({
  page,
}, testInfo) => {
  const artifactId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
  const requests: { method: string; pathname: string }[] = [];
  const browserErrors: string[] = [];
  let lookups = 0;
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("status of 403 (Forbidden)")
    ) {
      browserErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/artifacts/")) {
      requests.push({ method: request.method(), pathname: url.pathname });
    }
  });
  await page.route(`**/api/v1/artifacts/${artifactId}`, async (route) => {
    lookups += 1;
    if (lookups === 1) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: artifactId,
          ownerId: "owner-1",
          revision: "revision-7",
          sha256: "a".repeat(64),
          byteSize: 1_024,
          mediaType: "image/png",
        }),
      });
      return;
    }
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "forbidden" }),
    });
  });

  await page.goto("/#library");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to workspace" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#artifact-library-title$/);
  await expect(page.getByRole("heading", { name: "Library" })).toBeFocused();
  await page.getByLabel("Artifact ID").fill(artifactId);
  await page.getByRole("button", { name: "Look up metadata" }).click();
  await expect(
    page.getByRole("heading", { name: "Artifact metadata" }),
  ).toBeVisible();
  await expect(page.getByText("owner-1")).toBeVisible();
  await expect(
    page.getByText(/does not list artifacts or preview bytes/i),
  ).toBeVisible();
  await expect(page.locator("img, video, audio")).toHaveCount(0);

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const dimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(
      dimensions.contentWidth,
      `horizontal overflow at ${viewport.width}px: ${JSON.stringify(dimensions)}`,
    ).toBeLessThanOrEqual(dimensions.viewportWidth);
    await page.screenshot({
      path: testInfo.outputPath(`library-${viewport.width}.png`),
      fullPage: true,
    });
  }

  await page.getByRole("button", { name: "Look up metadata" }).click();
  await expect(page.getByRole("alert")).toContainText(
    /owner access is required/i,
  );
  await expect(
    page.getByRole("heading", { name: "Artifact metadata" }),
  ).toHaveCount(0);
  await expect(page.getByText("owner-1")).toHaveCount(0);
  expect(requests).toEqual([
    { method: "GET", pathname: `/api/v1/artifacts/${artifactId}` },
    { method: "GET", pathname: `/api/v1/artifacts/${artifactId}` },
  ]);
  expect(browserErrors).toEqual([]);
});

test("keeps the Library accessible at a 200 percent effective viewport with reduced motion", async ({
  browser,
}, testInfo) => {
  const artifactId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
  const context = await browser.newContext({
    viewport: { width: 720, height: 900 },
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
  });
  let releaseLookup!: () => void;
  let signalLookupStarted!: () => void;
  const lookupStarted = new Promise<void>((resolve) => {
    signalLookupStarted = resolve;
  });
  const lookupReleased = new Promise<void>((resolve) => {
    releaseLookup = resolve;
  });

  try {
    const page = await context.newPage();
    const browserErrors: string[] = [];
    page.on("console", (message) => {
      if (
        (message.type() === "error" || message.type() === "warning") &&
        !message.text().includes("status of 403 (Forbidden)")
      ) {
        browserErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));
    let lookups = 0;
    await page.route(`**/api/v1/artifacts/${artifactId}`, async (route) => {
      lookups += 1;
      if (lookups === 1) {
        signalLookupStarted();
        await lookupReleased;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: artifactId,
            ownerId: "owner-1",
            revision: "revision-7",
            sha256: "a".repeat(64),
            byteSize: 1_024,
            mediaType: "image/png",
          }),
        });
        return;
      }

      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "forbidden" }),
      });
    });

    await page.goto("/#library");
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Skip to workspace" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    const library = page.getByRole("region", { name: "Library" });
    await expect(page.getByRole("heading", { name: "Library" })).toBeFocused();
    await expect(page.getByLabel("Artifact ID")).toBeVisible();

    const transition = await page
      .getByRole("button", { name: "Look up metadata" })
      .evaluate((element) => getComputedStyle(element).transitionDuration);
    expect(Number.parseFloat(transition)).toBeLessThan(0.001);

    await page.getByLabel("Artifact ID").fill(artifactId);
    await page.getByRole("button", { name: "Look up metadata" }).click();
    await lookupStarted;
    await expect(page.getByRole("status")).toContainText(
      "Looking up artifact metadata...",
    );
    await expect(library).toHaveAttribute("aria-busy", "true");
    await expect(
      page.getByRole("button", { name: "Looking up..." }),
    ).toBeDisabled();
    releaseLookup();

    await expect(
      page.getByRole("heading", { name: "Artifact metadata" }),
    ).toBeVisible();
    await expect(library).toHaveAttribute("aria-busy", "false");
    const metadataDimensions = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(
      metadataDimensions.contentWidth,
      `horizontal overflow while showing metadata: ${JSON.stringify(metadataDimensions)}`,
    ).toBeLessThanOrEqual(metadataDimensions.viewportWidth);
    await page.screenshot({
      path: testInfo.outputPath("library-effective-200-percent-metadata.png"),
      fullPage: true,
    });

    await page.getByRole("button", { name: "Look up metadata" }).click();
    const alert = page.getByRole("alert");
    await expect(alert).toContainText(/owner access is required/i);
    await expect(alert).toBeFocused();
    await expect(
      page.getByRole("heading", { name: "Artifact metadata" }),
    ).toHaveCount(0);

    const dimensions = await page.evaluate(() => ({
      devicePixelRatio: window.devicePixelRatio,
      viewportWidth: document.documentElement.clientWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.devicePixelRatio).toBe(2);
    expect(dimensions.viewportWidth).toBe(720);
    expect(
      dimensions.contentWidth,
      `horizontal overflow at the 200 percent effective viewport: ${JSON.stringify(dimensions)}`,
    ).toBeLessThanOrEqual(dimensions.viewportWidth);
    expect(browserErrors).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath("library-effective-200-percent.png"),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
