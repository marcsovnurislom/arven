import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, SidePill, Skeleton, Stat, fmt, fmtPct, fmtR, signClass } from "../ui";

const num = (v: FormDataEntryValue | null) => (v === null || String(v).trim() === "" ? null : Number(v));

export function Journal() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.journal, []);
  const [formError, setFormError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = {
      symbol: String(f.get("symbol") || "BTCUSD"),
      side: Number(f.get("side")),
      entry: num(f.get("entry")),
      stop: num(f.get("stop")),
      exit: num(f.get("exit")),
      size: num(f.get("size")),
      fees: num(f.get("fees")) ?? 0,
      notes: String(f.get("notes") ?? ""),
      tags: String(f.get("tags") ?? "").split(",").map((x) => x.trim()).filter(Boolean),
    };
    try {
      await api.addJournal(body);
      setFormError(null);
      (e.target as HTMLFormElement).reset();
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const s = data?.stats;
  return (
    <>
      <PageTitle sub="Your own trades, kept apart from system signals.">{t("nav_journal")}</PageTitle>
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card title={t("addTrade")}>
          <form onSubmit={submit} className="grid gap-3" aria-label={t("addTrade")}>
            <label className="grid gap-1 text-sm">Symbol<input name="symbol" defaultValue="BTCUSD" required /></label>
            <label className="grid gap-1 text-sm">{t("side")}
              <select name="side" defaultValue="1"><option value="1">{t("long")}</option><option value="-1">{t("short")}</option></select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1 text-sm">{t("entry")}<input name="entry" type="number" step="any" min="0" required /></label>
              <label className="grid gap-1 text-sm">{t("stop")}<input name="stop" type="number" step="any" min="0" /></label>
              <label className="grid gap-1 text-sm">{t("exit")}<input name="exit" type="number" step="any" min="0" /></label>
              <label className="grid gap-1 text-sm">Fees<input name="fees" type="number" step="any" min="0" defaultValue="0" /></label>
            </div>
            <label className="grid gap-1 text-sm">{t("tags")}<input name="tags" placeholder="fomo, moved stop" /></label>
            <label className="grid gap-1 text-sm">{t("notes")}<textarea name="notes" rows={3} /></label>
            {formError && <p role="alert" className="text-sm down">{formError}</p>}
            <button className="btn primary" type="submit">{t("save")}</button>
          </form>
        </Card>
        <div className="grid gap-4">
          {error && !data && <ErrorBox error={error} onRetry={reload} />}
          {loading && !data && <Skeleton h={160} />}
          {s && (
            <Card>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Trades" value={s.trades} sub={`${s.with_r} with R`} />
                <Stat label={t("totalR")} value={fmtR(s.total_r)} tone={signClass(s.total_r)} />
                <Stat label="Expectancy" value={fmtR(s.expectancy_r)} tone={signClass(s.expectancy_r)} />
                <Stat label={t("winRate")} value={fmtPct(s.win_rate)} />
              </div>
            </Card>
          )}
          {data && data.entries.length === 0 && <Empty>{t("emptyJournal")}</Empty>}
          {data && data.entries.length > 0 && (
            <Card>
              <div className="overflow-x-auto">
                <table>
                  <thead><tr><th>Symbol</th><th>{t("side")}</th><th>{t("entry")}</th><th>{t("stop")}</th><th>{t("exit")}</th><th>R</th><th>Tags</th><th /></tr></thead>
                  <tbody>
                    {data.entries.map((e) => (
                      <tr key={e.id}>
                        <td className="num">{e.symbol}</td>
                        <td><SidePill side={e.side} /></td>
                        <td className="num">{fmt(e.entry)}</td>
                        <td className="num">{fmt(e.stop)}</td>
                        <td className="num">{fmt(e.exit)}</td>
                        <td className={`num ${signClass(e.r_multiple)}`}>{fmtR(e.r_multiple)}</td>
                        <td>{e.tags.map((x) => <Chip key={x}>{x}</Chip>)}</td>
                        <td><button className="btn" onClick={async () => { await api.deleteJournal(e.id); reload(); }} aria-label={`${t("delete")} ${e.symbol}`}>{t("delete")}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
