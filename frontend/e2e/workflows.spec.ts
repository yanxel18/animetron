import { expect, test } from "@playwright/test";

const id = "12345678-1234-4234-8234-123456789abc";
const second = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = { workflowId: id, revision: "saved-revision-1", createdAt: "2025-01-02T03:04:05Z" };
const canonicalJson = '{"revision":"saved-revision-1","text":"<script>inert</script>"}';

test("shows sample validation metadata on request at a narrow viewport", async ({ page }) => {
  let writes = 0;
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") writes += 1;
    if (path === "/api/v1/workflows/node-types") {
      await route.fulfill({ json: { scope: "sample-validation", nodes: [
        { type: "sample.constant", inputs: [], outputs: [{ name: "text", type: "text", required: false }], configSchema: { type: "object", properties: { text: { type: "string" } } } },
      ] } });
    } else if (path === `/api/v1/workflows/${id}/draft`) {
      await route.fulfill({ json: { workflowId: id, version: 1, document: '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[]}' } });
    } else {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    }
  });
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/#workflows");
  await page.getByRole("button", { name: "Load sample node types" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "sample.constant" })).toBeVisible();
  await expect(page.getByLabel("Configuration schema for sample.constant")).toContainText('"type": "object"');
  await page.getByLabel("Workflow ID", { exact: true }).fill(id);
  await page.getByRole("button", { name: "Load draft" }).click();
  await page.getByLabel("Sample node type", { exact: true }).selectOption("sample.constant");
  await page.getByRole("button", { name: "Insert sample node" }).focus();
  await page.keyboard.press("Enter");
  const text = await page.getByLabel("Workflow draft JSON").inputValue();
  const inserted = JSON.parse(text).nodes;
  expect(inserted).toHaveLength(1);
  expect(inserted[0].id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(inserted[0]).toMatchObject({ type: "sample.constant", config: {} });
  await expect(page.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  expect(writes).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("recovers an uncertain empty draft creation and loads the same ID", async ({ page }, testInfo) => {
  let attempts = 0;
  let createdId = "";
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (path === "/api/v1/auth/session") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (path === `/api/v1/workflows/${createdId}/draft` && request.method() === "PUT") {
      expect(request.postDataJSON()).toEqual({ document: "", expectedVersion: null });
      attempts++;
      if (attempts === 1) await route.fulfill({ status: 503 });
      else await route.fulfill({ json: { workflowId: createdId, document: "", version: 1 } });
    } else if (path === `/api/v1/workflows/${createdId}/draft` && request.method() === "GET") {
      if (attempts === 1) await route.fulfill({ status: 404 });
      else await route.fulfill({ json: { workflowId: createdId, document: "", version: 1 } });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/#workflows");
  await page.getByRole("button", { name: "Generate workflow ID" }).click();
  createdId = await page.getByLabel("New workflow ID").inputValue();
  expect(createdId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  await page.getByRole("button", { name: "Create empty draft" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText(/may have been created/i);
  await page.reload();
  await expect(page.getByLabel("New workflow ID")).toHaveValue(createdId);
  await expect(page.getByRole("button", { name: "Generate workflow ID" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Create empty draft" })).toBeDisabled();
  await page.getByRole("button", { name: "Check draft creation" }).click();
  await expect(page.getByRole("alert")).toContainText(/not found.*same id/i);
  await page.getByRole("button", { name: "Create empty draft" }).click();
  await expect(page.getByText(/empty draft created/i)).toContainText(createdId);
  await page.reload();
  await expect(page.getByLabel("New workflow ID")).toHaveValue(createdId);
  await page.getByRole("button", { name: "Check draft creation" }).click();
  await expect(page.getByText(/draft found/i)).toContainText(createdId);
  await page.getByRole("button", { name: "I recorded this ID" }).click();
  await page.getByLabel("Workflow ID", { exact: true }).fill(createdId);
  await page.getByRole("button", { name: "Load draft" }).click();
  await expect(page.getByLabel("Workflow draft JSON")).toHaveValue("");
  await page.getByRole("button", { name: "Initialize empty draft" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Workflow draft JSON")).toBeFocused();
  await expect(page.getByLabel("Workflow draft JSON")).toHaveValue(/"schemaVersion": 1/);
  await expect(page.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  await page.getByLabel("Node JSON").fill('{"id":"first","type":"sample.constant","config":{"text":"hello"}}');
  await page.getByRole("button", { name: "Add node" }).click();
  await expect(page.getByRole("list", { name: "Workflow node order" })).toContainText("first");
  await expect(page.getByRole("status").filter({ hasText: "Node added locally" })).toBeVisible();
  expect(attempts).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("draft-creation-375.png"), fullPage: true });
});

test("coordinates draft creation across two tabs", async ({ page, context }) => {
  let attempts = 0;
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await context.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (path === "/api/v1/auth/session") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (request.method() === "PUT" && path === `/api/v1/workflows/${id}/draft`) {
      attempts++;
      await held;
      await route.fulfill({ json: { workflowId: id, document: "", version: 1 } });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
  const other = await context.newPage();
  try {
    await page.goto("/#workflows");
    await other.goto("/#workflows");
    await page.getByLabel("New workflow ID").fill(id);
    await other.getByLabel("New workflow ID").fill(second);
    await page.getByRole("button", { name: "Create empty draft" }).click();
    await expect.poll(() => attempts).toBe(1);
    await other.getByRole("button", { name: "Create empty draft" }).click();
    await expect(other.getByRole("alert")).toContainText(/another draft creation.*in progress/i);
    expect(attempts).toBe(1);
    await expect(other.getByLabel("New workflow ID")).toHaveValue(id);
    await expect(other.getByLabel("New workflow ID")).toBeDisabled();
    release();
    await expect(page.getByText(/empty draft created/i)).toContainText(id);
    expect(attempts).toBe(1);
  } finally {
    release();
    await other.close();
  }
});

test("saves an edited draft before validation and revision creation with keyboard controls", async ({ page }, testInfo) => {
  const requests: string[] = [];
  const errors: string[] = [];
  const editedDocument = '{"revision":"saved-revision-2"}';
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (path === "/api/v1/auth/session") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (request.method() === "PUT" && path.endsWith("/draft")) {
      requests.push(`${request.method()}:${path}:${request.postData()}`);
      await route.fulfill({ json: { workflowId: id, version: 4, document: editedDocument } });
    } else if (request.method() === "GET" && path.endsWith("/draft")) {
      await route.fulfill({ json: { workflowId: id, version: 3, document: '{"revision":"saved-revision-1"}' } });
    } else if (request.method() === "POST") {
      requests.push(`${request.method()}:${path}:${request.postData()}`);
      await route.fulfill({ json: path.endsWith("/validations")
        ? { workflowId: id, draftVersion: 4, isValid: true, issues: [] }
        : { workflowId: id, revision: "saved-revision-2", canonicalJson: editedDocument, sha256: "a".repeat(64) } });
    } else await route.fulfill({ status: 404 });
  });
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/#workflows");
  await page.getByRole("textbox", { name: "Workflow ID", exact: true }).fill(id);
  await page.getByRole("textbox", { name: "Workflow ID", exact: true }).press("Enter");
  await expect(page.getByLabel("Workflow draft JSON")).toHaveValue('{"revision":"saved-revision-1"}');
  await page.getByLabel("Workflow draft JSON").fill(editedDocument);
  await expect(page.getByText(/unsaved changes/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  await page.getByRole("button", { name: "Save draft" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Draft saved as version 4.")).toBeVisible();
  await page.getByRole("button", { name: "Validate saved draft" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Draft is valid for version 4.")).toBeVisible();
  await page.getByRole("button", { name: "Create immutable revision" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Revision saved:/)).toBeVisible();
  expect(requests).toEqual([
    `PUT:/api/v1/workflows/${id}/draft:${JSON.stringify({ document: editedDocument, expectedVersion: 3 })}`,
    `POST:/api/v1/workflows/${id}/validations:{"expectedVersion":4}`,
    `POST:/api/v1/workflows/${id}/revisions:{"expectedVersion":4}`,
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("draft-revision-320.png"), fullPage: true });
});

test("reorders saved-draft nodes with pointer controls at responsive widths", async ({ page }, testInfo) => {
  const workflow = {
    schemaVersion: 1,
    revision: "r1",
    nodes: [
      { id: "node-a", type: "sample.constant", config: { value: "A", options: [1, 2] } },
      { id: "node-b", type: "sample.constant", config: { value: "B" } },
    ],
    edges: [{
      id: "edge-a-b", source: "node-a", sourcePort: "value",
      target: "node-b", targetPort: "value",
    }],
  };
  const workflowDocument = JSON.stringify(workflow).replace('"value":"A"', '"value":9007199254740993');
  const expectedDocument = JSON.stringify({
    ...workflow,
    nodes: [workflow.nodes[1], workflow.nodes[0]],
  }).replace('"value":"A"', '"value":9007199254740993');
  const restoredDocument = workflowDocument;
  const savedDocuments: string[] = [];
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (path === "/api/v1/auth/session") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (request.method() === "GET" && path.endsWith("/draft")) {
      await route.fulfill({ json: { workflowId: id, version: 3, document: workflowDocument } });
    } else if (request.method() === "PUT" && path.endsWith("/draft")) {
      const body = request.postDataJSON() as { document: string; expectedVersion: number };
      expect(body.expectedVersion).toBe(3);
      savedDocuments.push(body.document);
      await route.fulfill({ json: { workflowId: id, version: 4, document: body.document } });
    } else {
      await route.fulfill({ status: 404 });
    }
  });

  for (const [index, width] of [375, 768, 1024, 1440].entries()) {
    await page.setViewportSize({ width, height: 900 });
    if (index === 0) await page.goto("/#workflows");
    else await page.reload();
    await page.getByRole("textbox", { name: "Workflow ID", exact: true }).fill(id);
    await page.getByRole("button", { name: "Load draft" }).click();
    await expect(page.getByRole("list", { name: "Workflow node order" })).toContainText("node-a");
    await page.getByRole("button", { name: "Move node-b up" }).click();
    await expect(page.getByText("Moved node-b to position 1 of 2.")).toBeVisible();
    await expect(page.getByLabel("Workflow draft JSON")).toHaveValue(expectedDocument);
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText("Draft saved as version 4.")).toBeVisible();
    await page.getByRole("button", { name: "Move node-b down" }).click();
    await expect(page.getByLabel("Workflow draft JSON")).toHaveValue(restoredDocument);
    await expect(page.getByRole("button", { name: "Move node-b down" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Move node-b up" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`workflow-node-order-${width}.png`), fullPage: true });
  }
  expect(savedDocuments).toEqual(Array(4).fill(expectedDocument));
});

test("restores an uncertain revision attempt after reload without retrying it", async ({ page }) => {
  let revisionAttempts = 0;
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/workflows") {
      await route.fulfill({ json: { data: [], nextCursor: null } });
    } else if (path === "/api/v1/auth/session") {
      await route.fulfill({ json: { role: "owner", csrfToken: "fixture-csrf" } });
    } else if (path.endsWith("/draft")) {
      await route.fulfill({ json: { workflowId: id, version: 3, document: '{"revision":"saved-revision-1"}' } });
    } else if (request.method() === "POST" && path.endsWith("/validations")) {
      await route.fulfill({ json: { workflowId: id, draftVersion: 3, isValid: true, issues: [] } });
    } else if (request.method() === "POST" && path.endsWith("/revisions")) {
      revisionAttempts++;
      await route.fulfill({ status: 503 });
    } else await route.fulfill({ status: 404 });
  });

  await page.goto("/#workflows");
  await page.getByRole("textbox", { name: "Workflow ID", exact: true }).fill(id);
  await page.getByRole("button", { name: "Load draft" }).click();
  await page.getByRole("button", { name: "Validate saved draft" }).click();
  await page.getByRole("button", { name: "Create immutable revision" }).click();
  await expect(page.getByRole("alert")).toContainText(/revision may have been created/i);
  expect(revisionAttempts).toBe(1);

  await page.reload();
  await expect(page.getByRole("textbox", { name: "Workflow ID", exact: true })).toHaveValue(id);
  await expect(page.getByRole("alert")).toContainText(/previous revision attempt/i);
  await expect(page.getByRole("button", { name: "Reload saved draft" })).toBeEnabled();
  expect(revisionAttempts).toBe(1);

  await page.getByRole("button", { name: "Reload saved draft" }).click();
  await expect(page.getByLabel("Workflow draft JSON")).toHaveValue('{"revision":"saved-revision-1"}');
  await expect(page.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
  expect(revisionAttempts).toBe(1);
});

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
