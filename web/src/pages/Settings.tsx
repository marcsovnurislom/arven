import { api } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, ErrorBox, PageTitle, Skeleton } from "../ui";

export function Settings({ theme, setTheme }: { theme: "dark" | "light"; setTheme: (t: "dark" | "light") => void }) {
  const { t, lang, setLang } = useI18n();
  const tg = useLoad(api.telegram, []);
  return (
    <>
      <PageTitle sub={t("honesty")}>{t("nav_settings")}</PageTitle>
      <div className="grid gap-4 md:grid-cols-2">
        <Card title={t("telegram")}>
          {tg.error && !tg.data && <ErrorBox error={tg.error} onRetry={tg.reload} />}
          {tg.loading && !tg.data && <Skeleton h={100} />}
          {tg.data && (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="muted">{t("dryRun")}</dt><dd className="text-right"><Chip tone={tg.data.dry_run ? "warn" : "up"}>{String(tg.data.dry_run)}</Chip></dd>
              <dt className="muted">{t("token")}</dt><dd className="text-right"><Chip tone={tg.data.token_configured ? "up" : "down"}>{tg.data.token_configured ? t("configured") : t("missing")}</Chip></dd>
              <dt className="muted">{t("chats")}</dt><dd className="num text-right">{tg.data.allowed_chats}</dd>
              <dt className="muted">{t("outbox")}</dt><dd className="num text-right">{Object.keys(tg.data.outbox).length ? Object.entries(tg.data.outbox).map(([k, v]) => `${k}: ${v}`).join(", ") : "—"}</dd>
            </dl>
          )}
          <p className="mt-3 text-xs faint">Token and chat ids live in the environment (.env), never in this app.</p>
        </Card>
        <Card title={t("language")}>
          <div className="flex gap-2" role="group" aria-label={t("language")}>
            <button className={`btn ${lang === "en" ? "primary" : ""}`} aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
            <button className={`btn ${lang === "ru" ? "primary" : ""}`} aria-pressed={lang === "ru"} onClick={() => setLang("ru")}>RU</button>
          </div>
          <div className="mt-4 text-sm muted">{t("theme")}</div>
          <div className="mt-2 flex gap-2" role="group" aria-label={t("theme")}>
            <button className={`btn ${theme === "dark" ? "primary" : ""}`} aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>Dark</button>
            <button className={`btn ${theme === "light" ? "primary" : ""}`} aria-pressed={theme === "light"} onClick={() => setTheme("light")}>Light</button>
          </div>
          <p className="mt-4 text-xs faint">Keyboard: 1-8 switch pages, T toggles theme, L toggles language.</p>
        </Card>
      </div>
    </>
  );
}
