import { expect, test } from "@playwright/test";

const id = "12345678-1234-4234-8234-123456789abc";
const second = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = { workflowId: id, revision: "saved-revision-1", createdAt: "2025-01-02T03:04:05Z" };
const canonicalJson = '{"revision":"saved-revision-1","text":"<script>inert</script>"}';

test("browses fixture metadata at each viewport using keyboard", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [{ workflowId: id }], nextCursor: null } });
    } else if (url.pathname === `/api/v1/workflows/${id}/revisions`) {
      await route.fulfill({ json: { data: [revision], nextCursor: null } });
    } else if (url.pathname === `/api/v1/workflows/${id}/revision` && url.searchParams.get("revision") === revision.revision) {
      await route.fulfill({ json: { workflowId: id, revision: revision.revision, canonicalJson, sha256: "a".repeat(64) } });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/#workflows");
    const button = page.getByRole("button", { name: id });
    await expect(button).toBeVisible();
    await button.focus();
    await page.keyboard.press("Enter");
    const inspect = page.getByRole("button", { name: "Inspect saved-revision-1" });
    await expect(inspect).toBeVisible();
    await inspect.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Exact canonical JSON")).toHaveText(canonicalJson);
    await expect(page.getByText("a".repeat(64))).toBeVisible();
    await expect(page.getByText(/immutable, read-only/i)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`workflows-${width}.png`), fullPage: true });
  }
  expect(errors).toEqual([]);
});

test("supports bounded cursors and removes data on denied access, then retries", async ({ page }, testInfo) => {
  let denied = true;
  const ids = Array.from({ length: 50 }, (_, index) => ({
    workflowId: `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`,
  }));
  const queries: string[] = [];
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    queries.push(url.search);
    if (url.pathname === "/api/v1/workflows") {
      await route.fulfill({ json: url.searchParams.has("cursor")
        ? { data: [{ workflowId: second }], nextCursor: null }
        : { data: ids, nextCursor: "next_page" } });
    } else if (url.pathname === `/api/v1/workflows/${second}/revisions`) {
      await route.fulfill(denied ? { status: 403 } : { json: { data: [], nextCursor: null } });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
  await page.goto("/#workflows");
  await page.getByRole("button", { name: "Next workflows" }).click();
  await expect(page.getByRole("heading", { name: "Workflow IDs" })).toBeFocused();
  await page.getByRole("button", { name: second }).click();
  await expect(page.getByRole("alert")).toContainText("Access");
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeFocused();
  await expect(page.getByText(second)).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("workflows-forbidden.png"), fullPage: true });
  denied = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next workflows" })).toBeVisible();
  await page.getByRole("button", { name: "Next workflows" }).click();
  await page.getByRole("button", { name: second }).click();
  await expect(page.getByText("No saved revisions are available for this workflow.")).toBeVisible();
  expect(queries.every((query) => new URLSearchParams(query).get("limit") === "50")).toBe(true);
  expect(queries.some((query) => new URLSearchParams(query).get("cursor") === "next_page")).toBe(true);
});

test("shows loading, service error, retry, and empty states", async ({ page }, testInfo) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let failing = true;
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    if (failing) {
      await pending;
      await route.fulfill({ status: 503 });
    } else {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    }
  });
  await page.goto("/#workflows");
  await expect(page.getByRole("status")).toContainText("Loading workflows");
  await page.screenshot({ path: testInfo.outputPath("workflows-loading.png"), fullPage: true });
  release();
  await expect(page.getByRole("alert")).toContainText("503");
  await page.screenshot({ path: testInfo.outputPath("workflows-error.png"), fullPage: true });
  failing = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("No saved workflows are available.")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("workflows-empty.png"), fullPage: true });
});

test("inspects special revision IDs and handles detail failure and retry", async ({ page }, testInfo) => {
    const special = "../雪?x=1&z=+";
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let attempts = 0;
    const observed: string[] = [];
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/workflows") {
        await route.fulfill({ json: { data: [{ workflowId: id }], nextCursor: null } });
      } else if (url.pathname.endsWith("/revisions")) {
        await route.fulfill({ json: { data: [{ ...revision, revision: special }], nextCursor: null } });
      } else if (url.pathname.endsWith("/revision")) {
        observed.push(url.searchParams.get("revision") ?? "");
        attempts++;
        if (attempts === 1) {
          await pending;
          await route.fulfill({ status: 503 });
        } else {
          await route.fulfill({ json: { workflowId: id, revision: special, canonicalJson, sha256: "b".repeat(64) } });
        }
      } else await route.fulfill({ status: 404 });
    });
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto("/#workflows");
    await page.getByRole("button", { name: id }).click();
    await page.getByRole("button", { name: `Inspect ${special}` }).click();
    await expect(page.getByRole("status")).toContainText("Loading saved revision");
    await page.screenshot({ path: testInfo.outputPath("inspector-loading.png"), fullPage: true });
    release();
    await expect(page.getByRole("alert")).toContainText("503");
    await page.screenshot({ path: testInfo.outputPath("inspector-error.png"), fullPage: true });
    await page.getByRole("button", { name: "Retry revision" }).click();
    await expect(page.getByRole("heading", { name: "Revision inspector" })).toBeFocused();
    await expect(page.getByLabel("Exact canonical JSON")).toHaveText(canonicalJson);
    expect(observed).toEqual([special, special]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("inspector-special.png"), fullPage: true });
});

test("keeps a maximum-length Unicode revision usable on a narrow viewport", async ({ page }) => {
      const longRevision = "😀".repeat(128);
      await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/v1/workflows") {
          await route.fulfill({ json: { data: [{ workflowId: id }], nextCursor: null } });
        } else if (url.pathname.endsWith("/revisions")) {
          await route.fulfill({ json: { data: [{ ...revision, revision: longRevision }], nextCursor: null } });
        } else {
          expect(url.searchParams.get("revision")).toBe(longRevision);
          await route.fulfill({ json: { workflowId: id, revision: longRevision, canonicalJson, sha256: "a".repeat(64) } });
        }
      });
      await page.setViewportSize({ width: 320, height: 900 });
      await page.goto("/#workflows");
      await page.getByRole("button", { name: id }).click();
      await page.getByRole("button", { name: `Inspect ${longRevision}` }).click();
      await expect(page.getByLabel("Exact canonical JSON")).toHaveText(canonicalJson);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
