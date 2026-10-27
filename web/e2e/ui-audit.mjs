// UI audit: every page x desktop / phone x dark / light on the running site (default http://127.0.0.1:8000): console
// errors, horizontal page scroll, text cut by its box, and whether the menu fits. Prints only the problems.
//   node e2e/ui-audit.mjs            (BTC)
//   MARKET=eurusd node e2e/ui-audit.mjs   (another market id from /api/markets)
import { chromium, devices } from "@playwright/test";
const PAGES = ["home","overview","sessions","events","charts","screener","signals","s7trades","s7review","strategies","universes","replay","mistakes","lab","journal","settings"];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const report = [];
for (const [dev, opts] of [["desktop", { viewport: { width: 1366, height: 768 } }], ["phone", devices["Pixel 7"]]]) {
  for (const theme of ["dark", "light"]) {
    const ctx = await browser.newContext({ ...opts, colorScheme: theme });
    await ctx.addInitScript(([th, mk]) => { try { localStorage.setItem("arven.lang", "ru"); localStorage.setItem("arven.theme", th); localStorage.setItem("arven.market", mk); } catch {} }, [theme, process.env.MARKET || "btc"]);
    const page = await ctx.newPage();
    for (const p of PAGES) {
      const errs = [];
      page.removeAllListeners("pageerror"); page.removeAllListeners("console");
      page.on("pageerror", (e) => errs.push(e.message)); page.on("console", (m) => m.type() === "error" && errs.push(m.text().slice(0, 120)));
      await page.goto(`http://127.0.0.1:8000/?nosse#/${p}`); await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
      const r = await page.evaluate(() => {
        const out = { hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth, cut: [] };
        for (const el of document.querySelectorAll("main *")) {
          const cs = getComputedStyle(el);
          if (el.children.length === 0 && !el.closest(".sr-only") && el.textContent.trim() && el.scrollWidth > el.clientWidth + 2 && cs.overflow !== "visible" && cs.textOverflow !== "ellipsis" && el.clientWidth > 0)
            out.cut.push(el.textContent.trim().slice(0, 40));
        }
        const nav = document.querySelector(".side-nav");
        if (nav && getComputedStyle(nav).display !== "none") out.nav = { scrollH: nav.scrollHeight, clientH: nav.clientHeight, canScroll: nav.scrollHeight <= nav.clientHeight + 1 || getComputedStyle(nav).overflowY === "auto" && nav.clientHeight < nav.scrollHeight };
        const sb = document.querySelector(".sidebar");
        if (sb && getComputedStyle(sb).display !== "none") out.sidebar = { scrollH: sb.scrollHeight, clientH: sb.clientHeight, navBottom: Math.round(document.querySelector(".side-nav").getBoundingClientRect().bottom), vh: innerHeight };
        return out;
      });
      report.push({ dev, theme, p, errs, ...r, cut: r.cut.slice(0, 4) });
    }
    await ctx.close();
  }
}
await browser.close();
for (const x of report) if (x.errs.length || x.hscroll > 1 || x.cut.length || (x.sidebar && x.sidebar.navBottom > x.sidebar.vh)) console.log(JSON.stringify(x));
console.log("pages checked:", report.length);
const s = report.find((x) => x.sidebar); console.log("sidebar sample:", JSON.stringify(s && { nav: s.nav, sidebar: s.sidebar }));
