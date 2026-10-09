// Screenshots of the REAL data views: start `arven web` first (python -m arven web --port 8766), then
//   node e2e/real-shots.mjs http://127.0.0.1:8766
// Writes docs/screenshots/real/<page>-<viewport>.png using the installed Chrome.
import fs from "node:fs";
import { chromium, devices } from "@playwright/test";

const base = process.argv[2] ?? "http://127.0.0.1:8766";
const out = "../docs/screenshots/real";
fs.mkdirSync(out, { recursive: true });
const pages = ["home", "overview", "signals", "charts", "strategies", "lab"];
const browser = await chromium.launch({ channel: "chrome", headless: true });
for (const [name, ctxOpts] of [["desktop", { viewport: { width: 1440, height: 900 }, colorScheme: "dark" }], ["phone", { ...devices["Pixel 7"], colorScheme: "dark" }]]) {
  const ctx = await browser.newContext({ ...ctxOpts, locale: "en-US" });
  await ctx.addInitScript(() => { try { localStorage.setItem("arven.lang", "en"); localStorage.setItem("arven.theme", "dark"); } catch {} });
  const page = await ctx.newPage();
  for (const p of pages) {
    await page.goto(`${base}/?nosse#/${p}`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(p === "home" ? 4200 : 3000);
    await page.screenshot({ path: `${out}/${p}-${name}.png` });
    if (p === "home" || p === "overview") {
      // scroll through the page so every on-scroll reveal has played before the full-page capture
      const h = await page.evaluate(() => document.body.scrollHeight);
      for (let y = 0; y < h; y += 500) { await page.evaluate((v) => window.scrollTo(0, v), y); await page.waitForTimeout(250); }
      await page.waitForTimeout(2200);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `${out}/${p}-${name}-full.png`, fullPage: true });
    }
  }
  await ctx.close();
}
await browser.close();
console.log("done");
