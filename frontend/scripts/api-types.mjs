import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createClient } from "@hey-api/openapi-ts";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = resolve(frontendRoot, "..", "backend");
const generatedRoot = resolve(frontendRoot, "src", "api", "generated");
const temporaryRoot = resolve(frontendRoot, ".tmp");
const exporter = resolve(backendRoot, "scripts", "export_openapi.py");
const checkOnly = process.argv[2] === "--check";
const args = process.argv.slice(2);

if (args.length > 1 || (args.length === 1 && !checkOnly)) {
  throw new Error("Usage: node scripts/api-types.mjs [--check]");
}

function pythonExecutable() {
  if (process.env.PYTHON) return process.env.PYTHON;

  const venvPython = join(
    backendRoot,
    ".venv",
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  if (existsSync(venvPython)) return venvPython;

  return process.platform === "win32" ? "python" : "python3";
}

function exportOpenApi() {
  const env = { PATH: process.env.PATH ?? "" };
  if (process.platform === "win32") {
    env.SYSTEMROOT = process.env.SystemRoot ?? process.env.SYSTEMROOT ?? "";
  }

  const result = spawnSync(pythonExecutable(), [exporter], {
    cwd: backendRoot,
    encoding: "utf8",
    env,
    maxBuffer: 16 * 1024 * 1024,
  });

  if (result.error) throw result.error;
  if (result.status !== 0) {
    const failure = result.signal
      ? `signal ${result.signal}`
      : `exit code ${result.status}`;
    throw new Error(
      `Local OpenAPI export failed with ${failure}:\n${result.stderr}`,
    );
  }
  return JSON.parse(result.stdout);
}

function readFiles(root) {
  if (!existsSync(root)) return new Map();

  const files = new Map();
  const pending = [root];
  while (pending.length > 0) {
    const directory = pending.pop();
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        pending.push(path);
      } else if (entry.isFile()) {
        files.set(
          relative(root, path),
          readFileSync(path, "utf8").replace(/\r\n/g, "\n"),
        );
      }
    }
  }
  return files;
}

async function generate(output) {
  await createClient({
    input: exportOpenApi(),
    output,
    plugins: ["@hey-api/typescript"],
  });
}

let temporaryOutput;
try {
  let output = generatedRoot;
  if (checkOnly) {
    mkdirSync(temporaryRoot, { recursive: true });
    temporaryOutput = mkdtempSync(join(temporaryRoot, "api-types-"));
    output = temporaryOutput;
  }

  await generate(output);

  if (checkOnly) {
    const committed = readFiles(generatedRoot);
    const current = readFiles(temporaryOutput);
    const changed = [
      ...new Set([...committed.keys(), ...current.keys()]),
    ].filter((path) => committed.get(path) !== current.get(path));

    if (changed.length > 0) {
      throw new Error(
        `Generated API types are out of date: ${changed.join(", ")}. Run npm run generate:api-types and commit the result.`,
      );
    }
    console.log("Generated API types match the local backend OpenAPI schema.");
  }
} finally {
  if (temporaryOutput) {
    rmSync(temporaryOutput, { force: true, recursive: true });
  }
}
