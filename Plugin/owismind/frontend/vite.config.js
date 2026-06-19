import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The asset base embeds the DSS plugin id. It is env-driven so a coexisting DEV
// plugin can build with a distinct id without forking this config. Default stays
// 'owismind', so the prod build is byte-compatible with before this change.
const PLUGIN_ID = process.env.OWI_PLUGIN_ID || 'owismind'

export default defineConfig({
  plugins: [vue()],

  base: '/plugins/' + PLUGIN_ID + '/resource/owismind-app/',

  build: {
    outDir: '../resource/owismind-app',
    emptyOutDir: true,
  },
})