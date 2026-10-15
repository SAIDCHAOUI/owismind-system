// Minimal Playwright driver for the OWIsMind dev harness: navigate the locally
// served webapp, act on it and take screenshots, WITHOUT installing anything.
// It reuses playwright-core from the npx cache (already present because the
// Playwright MCP server ran from it) and the bundled Chromium build from
// ~/Library/Caches/ms-playwright - explicit executablePath, no registry lookup.
//
// Usage:  node dev-harness/tools/browse.mjs <steps.json>
//
// steps.json = { "viewport": {"width":1440,"height":900}, "steps": [
//   {"goto": "http://127.0.0.1:5199/"},
//   {"theme": "dark"},                      // sets body[data-theme] + localStorage
//   {"wait": 1500},                          // ms
//   {"waitText": "OWIsMind"},               // wait until visible text appears
//   {"type": {"selector": "textarea", "text": "...", "enter": true}},
//   {"click": "css selector"},
//   {"eval": "js expression"},
//   {"shot": "out/home.png"},                // relative to dev-harness/tools
//   {"shotFull": "out/full.png"}             // full-page screenshot
// ] }
//
// Console errors are printed at the end so visual checks also catch JS breakage.

import { createRequire } from 'node:module'
import { readFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)

// playwright-core from the npx cache (stable build first). If these hashes ever
// vanish (npx cache eviction), re-run any @playwright/mcp command to repopulate,
// or point PW_CORE at another copy - still no install performed here.
const PW_CORE_CANDIDATES = [
  process.env.PW_CORE,
  homedir() + '/.npm/_npx/705bc6b22212b352/node_modules/playwright-core',
  homedir() + '/.npm/_npx/31e32ef8478fbf80/node_modules/playwright-core',
  homedir() + '/.npm/_npx/9833c18b2d85bc59/node_modules/playwright-core',
].filter(Boolean)

function loadPlaywright() {
  for (const candidate of PW_CORE_CANDIDATES) {
    try {
      return require(candidate)
    } catch {
      /* try the next cached copy */
    }
  }
  throw new Error('playwright-core introuvable dans le cache npx (relancer le MCP Playwright une fois).')
}

const CHROMIUM =
  process.env.PW_CHROMIUM ||
  homedir() +
    '/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'

async function main() {
  const scriptPath = process.argv[2]
  if (!scriptPath) {
    console.error('usage: node browse.mjs <steps.json>')
    process.exit(1)
  }
  const spec = JSON.parse(readFileSync(scriptPath, 'utf8'))
  const { chromium } = loadPlaywright()
  const browser = await chromium.launch({ executablePath: CHROMIUM, headless: true })
  const page = await browser.newPage({ viewport: spec.viewport || { width: 1440, height: 900 } })

  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))

  const outPath = (p) => {
    const abs = isAbsolute(p) ? p : resolve(HERE, p)
    mkdirSync(dirname(abs), { recursive: true })
    return abs
  }

  for (const step of spec.steps || []) {
    if (step.goto) await page.goto(step.goto, { waitUntil: 'networkidle' })
    else if (step.theme) {
      await page.evaluate((theme) => {
        document.body.dataset.theme = theme
        try { localStorage.setItem('owismind.theme', theme) } catch {}
      }, step.theme)
      await page.waitForTimeout(250)
    } else if (step.wait) await page.waitForTimeout(step.wait)
    else if (step.waitText) await page.getByText(step.waitText).first().waitFor({ timeout: 15000 })
    else if (step.type) {
      const t = step.type
      await page.locator(t.selector).first().fill(t.text)
      if (t.enter) await page.locator(t.selector).first().press('Enter')
    } else if (step.click) await page.locator(step.click).first().click()
    else if (step.clickNth) await page.locator(step.clickNth.selector).nth(step.clickNth.index || 0).click()
    else if (step.drag) {
      // Horizontal pointer drag from an element's center to an absolute x.
      const box = await page.locator(step.drag.selector).first().boundingBox()
      if (box) {
        const y = box.y + box.height / 2
        await page.mouse.move(box.x + box.width / 2, y)
        await page.mouse.down()
        await page.mouse.move(step.drag.toX, y, { steps: 12 })
        await page.mouse.up()
      }
    }
    else if (step.eval) await page.evaluate(step.eval)
    else if (step.evalLog) {
      const result = await page.evaluate(step.evalLog)
      console.log('evalLog:', JSON.stringify(result, null, 1))
    }
    else if (step.shot) {
      await page.screenshot({ path: outPath(step.shot) })
      console.log('shot:', step.shot)
    } else if (step.shotFull) {
      await page.screenshot({ path: outPath(step.shotFull), fullPage: true })
      console.log('shotFull:', step.shotFull)
    }
  }

  await browser.close()
  if (consoleErrors.length) {
    console.log('\nCONSOLE ERRORS (' + consoleErrors.length + '):')
    for (const e of consoleErrors.slice(0, 20)) console.log('  -', e)
  } else {
    console.log('\nno console errors')
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
