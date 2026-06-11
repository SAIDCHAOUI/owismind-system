import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],

  base: '/plugins/owismind/resource/owismind-app/',

  build: {
    outDir: '../resource/owismind-app',
    emptyOutDir: true,
  },
})