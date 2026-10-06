from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRACKED_SIGNALS = {"可分批试仓", "等待回踩或趋势确认", "继续观察"}
HORIZON_CALENDAR_DAYS = {"20d": 28, "60d": 84, "120d": 168}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_snapshot(
    history_dir: Path,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> Path:
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    serializable = _jsonable(payload)
    encoded = json.dumps(serializable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:10]
    date_label = str(serializable.get("snapshot_date") or timestamp.date().isoformat())
    stem = f"snapshot_{date_label}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{digest}"
    path = history_dir / f"{stem}.json"
    suffix = 2
    while path.exists():
        path = history_dir / f"{stem}_{suffix}.json"
        suffix += 1
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def rolling_validation(
    history_dir: Path,
    current_date: str,
    current_nav: dict[str, float | None],
    provider: str | None = None,
) -> dict[str, Any]:
    current_day = datetime.strptime(current_date, "%Y-%m-%d").date()
    returns: dict[str, list[float]] = {label: [] for label in HORIZON_CALENDAR_DAYS}
    by_signal: dict[str, dict[str, list[float]]] = {
        label: {} for label in HORIZON_CALENDAR_DAYS
    }
    observations: dict[tuple[str, str, str], tuple[Any, dict[str, Any]]] = {}

    for path in sorted(Path(history_dir).glob("snapshot_*.json")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            snapshot_day = datetime.strptime(snapshot["snapshot_date"], "%Y-%m-%d").date()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if provider is not None and str(snapshot.get("provider", "")) != provider:
            continue
        elapsed = (current_day - snapshot_day).days
        if elapsed < 0:
            continue
        rule_version = str(snapshot.get("rule_version", "unknown"))
        snapshot_provider = str(snapshot.get("provider", "unknown"))
        for fund in snapshot.get("funds") or []:
            code = str(fund.get("code", ""))
            if code:
                observations[(snapshot["snapshot_date"], code, f"{snapshot_provider}|{rule_version}")] = (snapshot_day, fund)

    for snapshot_day, fund in observations.values():
        elapsed = (current_day - snapshot_day).days
        if elapsed < 0:
            continue
        signal = str(fund.get("signal") or (fund.get("decision") or {}).get("signal") or "")
        if signal not in TRACKED_SIGNALS:
            continue
        code = str(fund.get("code", ""))
        old_nav = _float_or_none(fund.get("validation_nav"))
        if old_nav is None:
            old_nav = _float_or_none(fund.get("acc_nav"))
        if old_nav is None:
            old_nav = _float_or_none(fund.get("nav"))
        new_nav = _float_or_none(current_nav.get(code))
        if not code or old_nav is None or old_nav <= 0 or new_nav is None:
            continue
        outcome = round((new_nav / old_nav - 1) * 100, 4)
        for label, minimum_days in HORIZON_CALENDAR_DAYS.items():
            if elapsed >= minimum_days:
                returns[label].append(outcome)
                by_signal[label].setdefault(signal, []).append(outcome)

    horizons: dict[str, Any] = {}
    total_samples = 0
    for label, values in returns.items():
        total_samples += len(values)
        horizons[label] = _summarize(values)
        horizons[label]["by_signal"] = {
            signal: _summarize(signal_values) for signal, signal_values in sorted(by_signal[label].items())
        }
    return {
        "status": "ready" if total_samples else "insufficient_history",
        "method": "前瞻快照滚动验证；20/60/120 个交易日分别用 28/84/168 个自然日近似成熟窗口",
        "horizons": horizons,
    }


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "samples": 0,
            "positive_hit_rate_pct": None,
            "median_return_pct": None,
            "worst_return_pct": None,
        }
    return {
        "samples": len(values),
        "positive_hit_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "median_return_pct": round(statistics.median(values), 2),
        "worst_return_pct": round(min(values), 2),
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
