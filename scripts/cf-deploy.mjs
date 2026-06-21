#!/usr/bin/env node
/**
 * Live Cloudflare Worker + Container deploy (config-only by default).
 *
 * Companion to the "cf:dryrun" package.json script. Where cf:dryrun validates the
 * bundle with `wrangler deploy --dry-run`, this ships it for real with
 * `wrangler deploy`, applying the committed cost config (instance_type, sleepAfter,
 * max_instances) to the live Worker + Container without rebuilding the image.
 *
 * Config resolution (real CF resource IDs are never committed):
 *   1. wrangler.deploy.jsonc  - GITIGNORED deploy-time copy carrying the REAL
 *      account/KV/D1/Vectorize IDs. Preferred when present (this is the live
 *      deploy path; the committed wrangler.jsonc keeps placeholder resource IDs).
 *   2. wrangler.jsonc         - committed config. Used as a fallback; its
 *      <YOUR_ACCOUNT_ID> image-ref placeholder is substituted at deploy time.
 *
 * In both cases the literal <YOUR_ACCOUNT_ID> placeholder (if any) is replaced
 * with $CLOUDFLARE_ACCOUNT_ID into a temp config, so the committed file is never
 * mutated. Image, secrets, and resource IDs are otherwise left untouched.
 *
 * Env (export before running; any secret manager works):
 *   CLOUDFLARE_API_TOKEN   - required. CF API token with Workers + Containers edit.
 *   CLOUDFLARE_ACCOUNT_ID  - required. Substituted for the <YOUR_ACCOUNT_ID>
 *                            placeholder in the image ref.
 *
 * Usage:
 *   export CLOUDFLARE_API_TOKEN=...      # however you store secrets
 *   export CLOUDFLARE_ACCOUNT_ID=...
 *   npm run cf:deploy                    # or: bun run cf:deploy
 *   npm run cf:deploy -- --dry-run       # print the resolved plan, run nothing
 *
 * The maintainer injects the token via skret, e.g. (Git Bash):
 *   CLOUDFLARE_API_TOKEN=$(MSYS_NO_PATHCONV=1 skret env -e prod \
 *     --path=/n24q02m/dev --format=dotenv | sed -n 's/^CF_DEV_TOKEN=//p') \
 *   CLOUDFLARE_ACCOUNT_ID=<account-id> npm run cf:deploy
 */

import { existsSync, readFileSync, writeFileSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

const PLACEHOLDER = "<YOUR_ACCOUNT_ID>";
const dryRun = process.argv.includes("--dry-run");

const token = process.env.CLOUDFLARE_API_TOKEN;
const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
if (!token) {
  console.error("CLOUDFLARE_API_TOKEN is not set. Export it (e.g. from skret) first.");
  process.exit(1);
}
if (!accountId) {
  console.error("CLOUDFLARE_ACCOUNT_ID is not set. Export the CF account id first.");
  process.exit(1);
}

// Prefer the gitignored deploy config with real resource IDs; fall back to the
// committed config (placeholder resource IDs) so the script is usable standalone.
const sourceConfig = existsSync("wrangler.deploy.jsonc")
  ? "wrangler.deploy.jsonc"
  : "wrangler.jsonc";
console.log(`cf:deploy using config: ${sourceConfig}`);

const original = readFileSync(sourceConfig, "utf8");
const substituted = original.split(PLACEHOLDER).join(accountId);
if (substituted.includes(PLACEHOLDER)) {
  console.error(`Failed to substitute ${PLACEHOLDER} in ${sourceConfig}.`);
  process.exit(1);
}

// Write the substituted config to a temp file so the committed/gitignored source
// is never mutated. wrangler resolves relative paths (main, migrations_dir)
// against the config file's directory, so keep the temp file in the repo root.
const tmpDir = mkdtempSync(join(tmpdir(), "wet-cf-deploy-"));
const tmpConfig = join(process.cwd(), `.wrangler-deploy-${process.pid}.jsonc`);
writeFileSync(tmpConfig, substituted, "utf8");

const cmd = "wrangler";
const args = ["deploy", "--config", tmpConfig];
console.log(`$ ${cmd} ${args.join(" ")}`);

try {
  if (dryRun) {
    console.log("(--dry-run) resolved config written; not invoking wrangler deploy.");
    console.log(substituted);
    process.exit(0);
  }
  const result = spawnSync(cmd, args, { stdio: "inherit", shell: true });
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(tmpConfig, { force: true });
  rmSync(tmpDir, { recursive: true, force: true });
}
