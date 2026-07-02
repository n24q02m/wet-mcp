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
 *   2. wrangler.jsonc         - committed reference config. Used as a fallback; its
 *      <YOUR_ACCOUNT_ID>/<YOUR_PUBLIC_URL>/<YOUR_WORKER_DOMAIN> placeholders are
 *      substituted at deploy time.
 *
 * The committed file is never mutated: substitution happens into a temp config.
 * <YOUR_ACCOUNT_ID> -> $CLOUDFLARE_ACCOUNT_ID, and (when the <YOUR_PUBLIC_URL>
 * placeholder is present) <YOUR_PUBLIC_URL> -> $PUBLIC_URL plus the
 * <YOUR_WORKER_DOMAIN> custom-domain route pattern -> the host of $PUBLIC_URL. On
 * the deploy.jsonc path these are no-ops (it carries real values). Image, secrets,
 * and resource IDs are otherwise left untouched.
 *
 * Env (export before running; any secret manager works):
 *   CLOUDFLARE_API_TOKEN   - required. CF API token with Workers + Containers edit.
 *   CLOUDFLARE_ACCOUNT_ID  - required. Substituted for the <YOUR_ACCOUNT_ID>
 *                            placeholder in the image ref.
 *   PUBLIC_URL             - required only on the wrangler.jsonc fallback path,
 *                            where it fills the <YOUR_PUBLIC_URL> placeholder and
 *                            the <YOUR_WORKER_DOMAIN> route pattern (its host).
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
let substituted = original.split(PLACEHOLDER).join(accountId);
if (substituted.includes(PLACEHOLDER)) {
  console.error(`Failed to substitute ${PLACEHOLDER} in ${sourceConfig}.`);
  process.exit(1);
}

// The committed reference wrangler.jsonc keeps the PUBLIC_URL + custom-domain
// route as placeholders so a forker fills their own domain. Substitute them from
// $PUBLIC_URL (the route pattern is its host); only required when the placeholder
// is present, so the wrangler.deploy.jsonc path (real values) is a no-op and the
// live deploy gains no new env requirement.
const PUBLIC_URL_PLACEHOLDER = "<YOUR_PUBLIC_URL>";
if (substituted.includes(PUBLIC_URL_PLACEHOLDER)) {
  const publicUrl = process.env.PUBLIC_URL;
  if (!publicUrl) {
    console.error("PUBLIC_URL is not set (base wrangler.jsonc uses <YOUR_PUBLIC_URL>).");
    process.exit(1);
  }
  substituted = substituted.split(PUBLIC_URL_PLACEHOLDER).join(publicUrl);
  substituted = substituted.split("<YOUR_WORKER_DOMAIN>").join(new URL(publicUrl).host);
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
    process.exit(0);
  }
  const result = spawnSync(cmd, args, { stdio: "inherit", shell: true });
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(tmpConfig, { force: true });
  rmSync(tmpDir, { recursive: true, force: true });
}
