// Lighthouse (performance / accessibility / best-practices / SEO) for every page, mobile and desktop presets, against the
// fixture server (scripts/web_fixture_server.py) using the system Chrome. Usage: node e2e/lighthouse.mjs <baseUrl> [outJson]
import fs from "node:fs";
import lighthouse from "lighthouse";
import { launch } from "chrome-launcher";

const base = process.argv[2] ?? "http://127.0.0.1:8124";
const out = process.argv[3] ?? "../docs/lighthouse.json";
const pages = ["home", "overview", "signals", "screener", "charts", "strategies", "journal", "lab", "settings"];
const chrome = await launch({ chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"] });
const rows = [];
for (const preset of ["mobile", "desktop"]) {
  for (const p of pages) {
    const config = preset === "desktop" ? { extends: "lighthouse:default", settings: { formFactor: "desktop", screenEmulation: { mobile: false, width: 1350, height: 940, deviceScaleFactor: 1, disabled: false }, throttlingMethod: "simulate", throttling: { rttMs: 40, throughputKbps: 10240, cpuSlowdownMultiplier: 1 } } } : undefined;
    const r = await lighthouse(`${base}/?nosse#/${p}`, { port: chrome.port, output: "json", logLevel: "error", onlyCategories: ["performance", "accessibility", "best-practices", "seo"] }, config);
    const c = r.lhr.categories;
    const row = { preset, page: p, performance: Math.round(c.performance.score * 100), accessibility: Math.round(c.accessibility.score * 100), bestPractices: Math.round(c["best-practices"].score * 100), seo: Math.round(c.seo.score * 100) };
    rows.push(row);
    console.log(JSON.stringify(row));
  }
}
await chrome.kill();
fs.writeFileSync(out, JSON.stringify({ generated: new Date().toISOString(), base, rows }, null, 2));
const min = (k) => Math.min(...rows.map((r) => r[k]));
console.log("MIN", JSON.stringify({ performance: min("performance"), accessibility: min("accessibility"), bestPractices: min("bestPractices"), seo: min("seo") }));
