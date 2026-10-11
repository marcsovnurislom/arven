"""The manual trade journal of the web app (section 5.6, page 6): the owner's own trades, entirely separate from system
signals. It is the one write path of the web layer and it only ever writes ``<data_dir>/journal/trades.jsonl`` - never market
data, never an order (CLAUDE.md rule 12)."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class JournalEntryIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: int
    entry: float = Field(gt=0)
    stop: float | None = Field(default=None, gt=0)
    exit: float | None = Field(default=None, gt=0)
    size: float | None = Field(default=None, gt=0)
    fees: float = Field(default=0.0, ge=0)
    opened_at: str | None = None
    notes: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("side")
    @classmethod
    def _side(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("side must be 1 (long) or -1 (short)")
        return v


class ReviewLabelIn(BaseModel):
    """The owner's verdict on one S7 detector setup (docs/strategy_s7_trend_break_fib.md section 8)."""

    setup_id: str = Field(min_length=3, max_length=64, pattern=r"^(15m|1h|4h)-\d+-[LS]$")
    verdict: str = Field(pattern=r"^(yes|no|unsure)$")
    note: str = Field(default="", max_length=1000)


class TradeLabelIn(BaseModel):
    """The owner's verdict on one backtested S7 trade (page "S7 trades"): was the trade taken correctly?"""

    trade_id: str = Field(min_length=3, max_length=64, pattern=r"^(15m|1h|4h)-\d+-[LS]$")
    verdict: str = Field(pattern=r"^(ok|wrong|unsure)$")
    note: str = Field(default="", max_length=2000)


def r_multiple(entry: dict) -> float | None:
    """Result in units of the planned risk (needs entry, stop and exit); fees are not part of R here."""
    if entry.get("exit") is None or entry.get("stop") is None:
        return None
    risk = abs(entry["entry"] - entry["stop"])
    if not math.isfinite(risk) or risk <= 0:
        return None
    return entry["side"] * (entry["exit"] - entry["entry"]) / risk


def _path(data_dir: Path) -> Path:
    return data_dir / "journal" / "trades.jsonl"


def read_entries(data_dir: Path) -> list[dict]:
    p = _path(data_dir)
    if not p.exists():
        return []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _write_all(data_dir: Path, entries: list[dict]) -> None:
    p = _path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries), encoding="utf-8")


def add_entry(data_dir: Path, payload: JournalEntryIn) -> dict:
    entry = payload.model_dump()
    entry["id"] = uuid.uuid4().hex
    entry["created_at"] = datetime.now(timezone.utc).isoformat()
    entry["r_multiple"] = r_multiple(entry)
    entries = read_entries(data_dir)
    entries.append(entry)
    _write_all(data_dir, entries)
    return entry


def delete_entry(data_dir: Path, entry_id: str) -> bool:
    entries = read_entries(data_dir)
    kept = [e for e in entries if e["id"] != entry_id]
    if len(kept) == len(entries):
        return False
    _write_all(data_dir, kept)
    return True


def stats(entries: list[dict]) -> dict:
    rs = [e["r_multiple"] for e in entries if e.get("r_multiple") is not None]
    if not rs:
        return {"trades": len(entries), "with_r": 0, "total_r": 0.0, "expectancy_r": None, "win_rate": None}
    return {
        "trades": len(entries), "with_r": len(rs), "total_r": float(sum(rs)), "expectancy_r": float(sum(rs) / len(rs)),
        "win_rate": float(sum(1 for r in rs if r > 0) / len(rs)),
    }
