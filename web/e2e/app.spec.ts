import { expect, test, type Page } from "@playwright/test";

const PAGES = ["home", "overview", "signals", "screener", "charts", "strategies", "journal", "lab", "s7review", "s7trades", "settings"] as const;

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("favicon")) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

async function open(page: Page, name: string, lang = "en") {
  await page.addInitScript((l) => {
    try {
      if (!sessionStorage.getItem("seeded")) {
        localStorage.setItem("arven.lang", l); // seed once per tab so a reload keeps the user's later choice
        sessionStorage.setItem("seeded", "1");
      }
    } catch {
      /* ignore */
    }
  }, lang);
  await page.goto(`/?nosse#/${name}`);
}

test.describe("every page", () => {
  for (const name of PAGES) {
    test(`${name}: renders a heading, the honesty banner, and no console errors`, async ({ page }) => {
      const errors = collectErrors(page);
      await open(page, name);
      await expect(page.locator("main h1")).toBeVisible();
      await expect(page.locator("header").first()).toContainText("not advice");
      await page.waitForLoadState("networkidle");
      expect(errors).toEqual([]);
    });

    test(`${name}: no horizontal page scroll`, async ({ page }) => {
      await open(page, name);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});

test("overview shows the equity curve, three strategy cards and the small-sample warning", async ({ page }) => {
  await open(page, "overview");
  await expect(page.getByRole("img", { name: /Cumulative result in R/ })).toBeVisible();
  await expect(page.getByText("s4_impulse_retest").first()).toBeVisible();
  await expect(page.getByText("fewer than 100 closed signals")).toBeVisible();
  await expect(page.getByText("Agreement hypothesis")).toBeVisible();
});

test("home explains the product: pipeline of seven steps, honesty cards, counted stats", async ({ page }) => {
  await open(page, "home");
  await expect(page.getByRole("heading", { name: "ARVEN", level: 1 })).toBeVisible();
  await expect(page.getByRole("list").filter({ hasText: "Market data" }).getByRole("listitem")).toHaveCount(7);
  await expect(page.getByText("A sealed final exam")).toBeVisible();
  await expect(page.getByText("real orders sent")).toBeVisible();
});

test("guided tour walks through the pages and can be closed with Escape", async ({ page }) => {
  await open(page, "home");
  await page.getByRole("button", { name: "Guided tour" }).click();
  const dialog = page.getByRole("dialog", { name: "Guided tour" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/#\/overview/);
  await dialog.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/#\/signals/);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("signals: list, selection changes the detail, chart and ladder are drawn", async ({ page }) => {
  await open(page, "signals");
  const options = page.getByRole("listbox", { name: "Signals" }).getByRole("option");
  await expect(options).toHaveCount(3);
  await expect(page.locator("main canvas").first()).toBeVisible();
  await expect(page.getByText("TP1").first()).toBeVisible();
  const second = options.nth(1);
  const label = await second.innerText();
  await second.click();
  await expect(second).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("main")).toContainText(label.split("\n").find((l) => l.includes("_")) ?? "");
});

test("signals: filter by strategy", async ({ page }) => {
  await open(page, "signals");
  await page.getByLabel("Strategy").selectOption("s4_impulse_retest");
  await expect(page.getByRole("listbox", { name: "Signals" }).getByRole("option")).toHaveCount(1);
});

test("keyboard shortcuts: page switch, theme and language", async ({ page, isMobile }) => {
  test.skip(!!isMobile, "keyboard shortcuts are a desktop feature");
  await open(page, "home");
  await expect(page.locator("main h1")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("3");
  await expect(page).toHaveURL(/#\/signals/);
  const before = await page.locator("html").getAttribute("data-theme");
  await page.keyboard.press("t");
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", before ?? "");
  await page.keyboard.press("l");
  await expect(page.locator("main h1")).toHaveText("Сигналы");
});

test("language and theme choices persist across a reload", async ({ page }) => {
  await open(page, "settings");
  await page.getByRole("button", { name: "RU", exact: true }).first().click();
  await page.reload();
  await expect(page.locator("main h1")).toHaveText("Настройки");
});

test("journal: add a trade, see R, delete it", async ({ page }) => {
  await open(page, "journal");
  await expect(page.getByText("No journal entries yet")).toBeVisible();
  await page.getByLabel("Entry").fill("100");
  await page.getByLabel("Stop").fill("98");
  await page.getByLabel("Exit").fill("104");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: "+2.00R" })).toBeVisible();
  await page.getByRole("button", { name: /^Delete/ }).click();
  await expect(page.getByText("No journal entries yet")).toBeVisible();
});

test("charts: dragging back in time loads older history on demand", async ({ page, isMobile }) => {
  test.skip(!!isMobile, "uses a mouse drag");
  const olderRequests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/candles") && r.url().includes("before=")) olderRequests.push(r.url());
  });
  await open(page, "charts");
  await page.waitForLoadState("networkidle");
  const box = await page.locator("main canvas").first().boundingBox();
  expect(box).not.toBeNull();
  for (let k = 0; k < 14; k++) {
    await page.mouse.move(box!.x + 120, box!.y + 150);
    await page.mouse.down();
    await page.mouse.move(box!.x + box!.width - 60, box!.y + 150, { steps: 8 });
    await page.mouse.up();
  }
  await expect.poll(() => olderRequests.length, { timeout: 10_000 }).toBeGreaterThan(0);
});

test("S7 check: verdicts are saved through the API (the fixture server is shared by both projects)", async ({ page, request }) => {
  const review = await (await request.get("/api/s7/review?tf=1h")).json();
  const [first, second] = review.setups.map((x: { id: string }) => x.id);
  await open(page, "s7review");
  await expect(page.getByText(/\d \/ 2 reviewed/)).toBeVisible();
  await expect(page.locator("main canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "My pattern (Y)" }).click();
  await expect(page.getByText("#2")).toBeVisible(); // moved on to the next setup
  await page.keyboard.press("n");
  await expect(page.getByText("2 / 2 reviewed")).toBeVisible();
  const labels = (await (await request.get("/api/s7/labels?tf=1h")).json()).labels;
  expect(labels[first].verdict).toBe("yes");
  expect(labels[second].verdict).toBe("no");
});

test("offline: when the API is unreachable the page says so instead of inventing data", async ({ page }) => {
  await page.route("**/api/**", (route) => route.abort());
  await open(page, "overview");
  await expect(page.getByRole("alert")).toContainText("not reachable");
});

test("strategies: the forward review verdict and its interval", async ({ page }) => {
  await open(page, "strategies");
  const s6 = page.locator("[data-verdict=losing]");
  await expect(s6).toContainText("LOSING");
  await expect(page.locator("[data-verdict=too_few]")).toContainText("needs 30");
  await expect(page.getByText("[-0.52R, -0.08R]")).toBeVisible();
  await expect(page.locator("[data-verdict]")).toHaveCount(2); // a summary without a review shows none, not a made-up one
});

test("strategies in Russian: the verdict is translated", async ({ page }) => {
  await open(page, "strategies", "ru");
  await expect(page.locator("[data-verdict=losing]")).toContainText("УБЫТОЧНА");
});

test("lab lists the stored run with its sealed-test flag", async ({ page }) => {
  await open(page, "lab");
  await expect(page.getByRole("cell", { name: "run-fixture" })).toBeVisible();
  await expect(page.getByText("not touched")).toBeVisible();
});

test("settings never shows a bot token", async ({ page }) => {
  await open(page, "settings");
  await expect(page.getByText("Bot token")).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/\d{6,}:[A-Za-z0-9_-]{20,}/);
});

test("screenshots (SHOTS=1)", async ({ page }, info) => {
  test.skip(!process.env.SHOTS, "set SHOTS=1 to refresh docs/screenshots");
  for (const name of PAGES) {
    await open(page, name);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3600); // let the entrance animations finish
    await page.screenshot({ path: `../docs/screenshots/${name}-${info.project.name}.png`, fullPage: false });
  }
});
