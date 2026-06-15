import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

// The worker handler test runs in plain node. `@cloudflare/containers` (the
// WetContainer base) imports the `cloudflare:workers` virtual module, which only
// exists in the workerd runtime, so alias it to a local stub for unit tests.
export default defineConfig({
  resolve: {
    alias: {
      'cloudflare:workers': fileURLToPath(new URL('./tests/cloudflare-workers-stub.ts', import.meta.url)),
    },
  },
})
