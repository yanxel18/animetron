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

test("renders read-only schedules across target widths", async ({ page }, testInfo) => {
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
  await expect(page.getByRole("button", { name: /create|edit|pause|resume/i })).toHaveCount(0);
  expect(methods.length).toBeGreaterThan(0);
  expect(methods.every((method) => method === "GET")).toBe(true);
  expect(browserErrors).toEqual([]);
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
  await expect(page.getByRole("button", { name: "Library" })).toBeDisabled();

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
