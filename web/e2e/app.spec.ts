import { expect, test, type Page } from "@playwright/test";

const PAGES = ["overview", "signals", "screener", "charts", "strategies", "journal", "lab", "settings"] as const;

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

test("overview shows the forward table with the small-sample warning", async ({ page }) => {
  await open(page, "overview");
  await expect(page.getByRole("row")).toHaveCount(4); // header + 3 strategies
  await expect(page.getByText("fewer than 100 closed signals")).toBeVisible();
  await expect(page.getByText("Agreement hypothesis")).toBeVisible();
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
  await open(page, "overview");
  await expect(page.locator("main h1")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("2");
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

test("offline: when the API is unreachable the page says so instead of inventing data", async ({ page }) => {
  await page.route("**/api/**", (route) => route.abort());
  await open(page, "overview");
  await expect(page.getByRole("alert")).toContainText("not reachable");
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
    await page.waitForTimeout(600);
    await page.screenshot({ path: `../docs/screenshots/${name}-${info.project.name}.png`, fullPage: false });
  }
});
