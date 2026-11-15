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
  await expect(page.getByRole("heading", { name: "No run is loaded" })).toBeVisible();
  await expect(page.getByText("Backend not checked")).toBeVisible();
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
  await expect(page.getByRole("button", { name: "Runs" })).toBeDisabled();

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
