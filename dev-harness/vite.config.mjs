// OWIsMind dev harness - a STANDALONE Vite config that serves the plugin's Vue
// frontend locally against a mock DSS backend, for visual work with real eyes
// (screenshots, Playwright) without any DSS instance.
//
// Guarantees:
//   - The plugin source (frontend/, python-lib/, resource/) is NEVER modified.
//     This config only points Vite's root AT the frontend and injects the DSS
//     `getWebAppBackendUrl` shim into the served HTML at request time.
//   - No dependency is installed: vite and @vitejs/plugin-vue are resolved from
//     the frontend's own node_modules via createRequire.
//   - The Vite cache is kept inside dev-harness/.vite-cache (git-ignored), so
//     nothing is written under the plugin tree.
//
// Run (from the repo root):
//   OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/node_modules/.bin/vite \
//     --config dev-harness/vite.config.mjs

import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { createRequire } from 'node:module'
import { createMockApi } from './mock/api.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const FRONTEND = resolve(HERE, '../OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend')

export default async function config() {
  // Resolve the frontend's own plugin-vue (never a separate install).
  const require = createRequire(resolve(FRONTEND, 'package.json'))
  const vueModule = await import(pathToFileURL(require.resolve('@vitejs/plugin-vue')).href)
  const vue = vueModule.default

  const owiMockBackend = {
    name: 'owi-mock-backend',
    // DSS injects getWebAppBackendUrl globally in the webapp page; the harness
    // injects an identity shim so services/backend.js resolves same-origin URLs
    // that land on the mock middleware below. Injected at serve time only - the
    // frontend's index.html on disk stays untouched.
    transformIndexHtml() {
      return [
        {
          tag: 'script',
          injectTo: 'head-prepend',
          children: 'window.getWebAppBackendUrl = function (path) { return path }',
        },
      ]
    },
    configureServer(server) {
      server.middlewares.use(createMockApi())
    },
  }

  return {
    root: FRONTEND,
    base: '/',
    cacheDir: resolve(HERE, '.vite-cache'),
    plugins: [vue(), owiMockBackend],
    server: {
      port: 5199,
      strictPort: true,
      host: '127.0.0.1',
      open: false,
    },
  }
}
