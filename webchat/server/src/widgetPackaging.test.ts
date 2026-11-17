import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execute = promisify(execFile);
const source = fileURLToPath(new URL("../../../devTools/package_teams_widget.mjs", import.meta.url));

async function fixture(t: TestContext) {
  const root = await mkdtemp(path.join(os.tmpdir(), "aistro-package-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const script = path.join(root, "devTools/package_teams_widget.mjs");
  const assets = path.join(root, "webchat/client/dist/teams-widget/v1");
  await mkdir(path.dirname(script), { recursive: true });
  await mkdir(assets, { recursive: true });
  await copyFile(source, script);
  for (const name of ["widget.js", "widget.css", "viewer-licenses.txt"]) {
    await writeFile(path.join(assets, name), "fixture");
  }
  await writeFile(path.join(assets, ".env"), "DO_NOT_PUBLISH");
  return { root, script, output: path.join(root, "site") };
}

test("pending bot packaging publishes no credentials and leaves CORS closed", async t => {
  const files = await fixture(t);
  await execute(process.execPath, [files.script, "--pending-bot", files.output]);
  const config = JSON.parse(await readFile(path.join(files.output, "staticwebapp.config.json"), "utf8"));
  assert.equal(config.globalHeaders["Access-Control-Allow-Origin"], undefined);
  assert.deepEqual((await readdir(path.join(files.output, "teams-widget/v1"))).sort(),
    ["viewer-licenses.txt", "widget.css", "widget.js"]);
});

test("activation preserves the exact full-MRI Teams renderer origin", async t => {
  const files = await fixture(t);
  await execute(process.execPath, [
    files.script, "27d67f5b-b7cc-4935-b979-0fdb47ccf365", files.output,
  ]);
  const config = JSON.parse(await readFile(path.join(files.output, "staticwebapp.config.json"), "utf8"));
  assert.equal(config.globalHeaders["Access-Control-Allow-Origin"],
    "https://ecf78bca578133f43cc5a936854c832d.widget-renderer.usercontent.microsoft");
});
