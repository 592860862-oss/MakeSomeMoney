from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from . import RULE_VERSION, SCHEMA_VERSION
from .history import rolling_validation, write_snapshot
from .identity import deduplicate_share_classes
from .models import FundSnapshot
from .reporting import write_reports
from .rules import (
    LOCK_WORDS,
    assess_eligibility,
    classify_opportunity_channel,
    derive_entry_signal,
    is_pullback_opportunity,
    is_short_history_observable,
    missing_return_keys,
    missing_returns_blocker,
    preliminary_score,
    return_momentum_blocker,
    score_fund,
)


class DiscoveryProvider(Protocol):
    provider_name: str

    def fetch_universe(self, end_date: str) -> tuple[list[FundSnapshot], str]: ...

    def enrich(self, fund: FundSnapshot, start_date: str, end_date: str) -> FundSnapshot: ...


@dataclass(frozen=True)
class DiscoveryConfig:
    end_date: str
    workers: int = 24
    rough_limit: int = 1800
    candidate_limit: int = 30
    watch_limit: int = 20
    pullback_limit: int = 20
    short_history_limit: int = 20
    risk_sample_limit: int = 20
    cross_check_limit: int = 60
    candidate_concept_cap: int = 5
    watch_concept_cap: int = 4
    pullback_concept_cap: int = 5
    short_history_concept_cap: int = 4

    def validate(self) -> None:
        datetime.strptime(self.end_date, "%Y-%m-%d")
        for label, value in (
            ("workers", self.workers),
            ("rough_limit", self.rough_limit),
            ("candidate_limit", self.candidate_limit),
            ("watch_limit", self.watch_limit),
            ("pullback_limit", self.pullback_limit),
            ("short_history_limit", self.short_history_limit),
        ):
            if value <= 0:
                raise ValueError(f"{label} 必须大于 0")


def run_discovery(
    provider: DiscoveryProvider,
    config: DiscoveryConfig,
    output_root: Path,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    config.validate()
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    history_dir = output_root / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now or datetime.now(timezone.utc)
    announce = progress or (lambda _message: None)

    universe, start_date = provider.fetch_universe(config.end_date)
    if not universe:
        raise RuntimeError("全市场数据源没有返回基金记录")
    announce(f"原始基金：{len(universe)}")

    rejects: Counter[str] = Counter()
    prelim: list[FundSnapshot] = []
    for fund in universe:
        reason = _light_filter_reason(fund, config.end_date)
        if reason:
            rejects[reason] += 1
            continue
        fund.prelim_score = preliminary_score(fund)
        if fund.prelim_score <= -9000:
            rejects["关键收益数据不足"] += 1
            continue
        prelim.append(fund)
    prelim.sort(key=lambda fund: (-fund.prelim_score, fund.code))
    rough = prelim[: config.rough_limit]
    announce(f"轻量预筛后：{len(prelim)}；进入详情补充：{len(rough)}")

    detailed: list[FundSnapshot] = []
    failures = 0
    max_workers = max(1, min(config.workers, 32))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(provider.enrich, fund, start_date, config.end_date): fund.code
            for fund in rough
        }
        for completed, future in enumerate(as_completed(futures), 1):
            try:
                detailed.append(future.result())
            except Exception as exc:
                failures += 1
                rejects[f"详情补充失败：{type(exc).__name__}"] += 1
            if completed % 200 == 0:
                announce(f"详情补充进度：{completed}/{len(futures)}")
    announce(f"完成详情：{len(detailed)}；失败：{failures}")

    evaluated: list[FundSnapshot] = []
    for fund in detailed:
        evaluated.append(_apply_decision(fund, config.end_date))

    deduplicated = deduplicate_share_classes(evaluated)
    cross_checked = 0
    cross_check_failures = 0
    cross_check = getattr(provider, "cross_check", None)
    if callable(cross_check) and config.cross_check_limit > 0:
        targets = sorted(
            [
                fund
                for fund in deduplicated
                if fund.drawdown_secondary is None
                and (fund.drawdown is None or fund.drawdown <= 13)
                and (fund.score or 0) >= 60
            ],
            key=lambda fund: (-(fund.score or 0), fund.drawdown or 999, fund.code),
        )[: config.cross_check_limit]
        if targets:
            announce(f"第二回撤端点核验：{len(targets)} 只候选")
            replacements: dict[str, FundSnapshot] = {}
            with ThreadPoolExecutor(max_workers=max(1, min(config.workers, 12))) as executor:
                futures = {
                    executor.submit(cross_check, fund, start_date, config.end_date): fund.code
                    for fund in targets
                }
                for future in as_completed(futures):
                    code = futures[future]
                    try:
                        replacements[code] = _apply_decision(future.result(), config.end_date)
                        cross_checked += 1
                    except Exception as exc:
                        cross_check_failures += 1
                        rejects[f"第二回撤端点核验失败：{type(exc).__name__}"] += 1
            deduplicated = [replacements.get(fund.code, fund) for fund in deduplicated]

    for fund in deduplicated:
        for blocker in fund.eligibility_blockers:
            rejects[blocker] += 1

    candidates = _collect_with_concept_cap(
        [
            fund
            for fund in deduplicated
            if fund.opportunity_channel == "全周期收益递增" and fund.signal in {"可分批试仓", "等待回踩或趋势确认"}
        ],
        config.candidate_limit,
        config.candidate_concept_cap,
    )
    selected_codes = {fund.code for fund in candidates}
    pullback_watch = _collect_with_concept_cap(
        [
            fund
            for fund in deduplicated
            if fund.code not in selected_codes
            and fund.opportunity_channel == "强中期+短期回踩"
            and fund.signal in {"等待回踩或趋势确认", "继续观察"}
        ],
        config.pullback_limit,
        config.pullback_concept_cap,
    )
    selected_codes.update(fund.code for fund in pullback_watch)
    short_history_watch = _collect_with_concept_cap(
        [
            fund
            for fund in deduplicated
            if fund.code not in selected_codes
            and fund.opportunity_channel == "短历史观察"
            and fund.signal in {"等待回踩或趋势确认", "继续观察"}
        ],
        config.short_history_limit,
        config.short_history_concept_cap,
    )
    selected_codes.update(fund.code for fund in short_history_watch)
    watchlist = _collect_with_concept_cap(
        [fund for fund in deduplicated if fund.code not in selected_codes and fund.signal == "继续观察"],
        config.watch_limit,
        config.watch_concept_cap,
    )
    selected_codes.update(fund.code for fund in watchlist)
    risk_samples = sorted(
        [fund for fund in deduplicated if fund.signal in {"暂不参与", "回避"}],
        key=lambda fund: (fund.signal_level, -(fund.score or 0), fund.code),
    )[: config.risk_sample_limit]

    current_nav = {
        fund.code: (fund.acc_nav if fund.acc_nav is not None else fund.nav)
        for fund in deduplicated
        if fund.acc_nav is not None or fund.nav is not None
    }
    validation = rolling_validation(history_dir, config.end_date, current_nav, provider=provider.provider_name)
    stats = {
        "universe": len(universe),
        "preliminary": len(prelim),
        "rough": len(rough),
        "evaluated": len(evaluated),
        "deduplicated": len(deduplicated),
        "detail_failures": failures,
        "cross_checked": cross_checked,
        "cross_check_failures": cross_check_failures,
        "candidates": len(candidates),
        "pullback_watch": len(pullback_watch),
        "short_history_watch": len(short_history_watch),
        "watchlist": len(watchlist),
        "risk_samples": len(risk_samples),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "end_date": config.end_date,
        "provider": provider.provider_name,
        "stats": stats,
        "reject_summary": dict(_aggregate_rejects(rejects).most_common()),
        "reject_details": dict(rejects.most_common()),
        "candidates": candidates,
        "pullback_watch": pullback_watch,
        "short_history_watch": short_history_watch,
        "watchlist": watchlist,
        "risk_samples": risk_samples,
        "validation": validation,
        "limitations": [
            "回撤使用同一公开提供方的两个独立端点交叉核验，尚不等同于跨提供方核验。",
            "份额实际渠道费率、申购状态和到账时延尚未形成可靠统一数据源，当前不宣称代表份额费用最低。",
            "滚动验证是从本版本上线后积累的前瞻快照，不冒充无生存偏差的全市场历史回测。",
        ],
    }
    report_paths = write_reports(output_root, result, now=timestamp)
    snapshot_funds = candidates + pullback_watch + short_history_watch + watchlist
    snapshot_payload = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "snapshot_date": config.end_date,
        "provider": provider.provider_name,
        "funds": [fund.to_dict() for fund in snapshot_funds],
    }
    snapshot_path = write_snapshot(history_dir, snapshot_payload, now=timestamp)
    result["report_paths"] = report_paths
    result["snapshot_path"] = snapshot_path
    announce(
        "底层策略去重后："
        f"{len(deduplicated)}；全周期递增候选：{len(candidates)}；回踩观察：{len(pullback_watch)}；"
        f"短历史观察：{len(short_history_watch)}；观察池：{len(watchlist)}"
    )
    return result


def _apply_decision(fund: FundSnapshot, end_date: str) -> FundSnapshot:
    eligibility = assess_eligibility(fund, end_date)
    score = score_fund(fund)
    signal = derive_entry_signal(fund, eligibility, score)
    fund.opportunity_channel = classify_opportunity_channel(fund, end_date)
    fund.eligibility_passed = eligibility.passed
    fund.eligibility_blockers = list(eligibility.blockers)
    fund.eligibility_warnings = list(eligibility.warnings)
    fund.score = score.total
    fund.score_components = dict(score.components)
    fund.score_notes = list(score.notes)
    fund.signal = signal.label
    fund.signal_level = signal.level
    fund.signal_reasons = list(signal.reasons)
    return fund


def _light_filter_reason(fund: FundSnapshot, end_date: str) -> str:
    missing = missing_return_keys(fund)
    if missing:
        return missing_returns_blocker(fund, end_date)
    momentum_blocker = return_momentum_blocker(fund)
    if momentum_blocker:
        return momentum_blocker
    if any(word in fund.name for word in LOCK_WORDS):
        return "存在锁定期或定期开放特征"
    try:
        age = datetime.strptime(end_date, "%Y-%m-%d").date() - datetime.strptime(
            fund.establish_date, "%Y-%m-%d"
        ).date()
    except ValueError:
        return "成立日期无法确认"
    if age.days < 365:
        if not is_short_history_observable(fund, end_date):
            return "成立不足 1 年"
    return ""


def _aggregate_rejects(rejects: Counter[str]) -> Counter[str]:
    grouped: Counter[str] = Counter()
    for reason, count in rejects.items():
        grouped[_reject_group(reason)] += count
    return grouped


def _reject_group(reason: str) -> str:
    if reason.startswith("区间收益硬规则不符合：近 1 月"):
        return "区间收益硬规则不符合：近 1 月高于近 3 月"
    if reason.startswith("区间收益硬规则不符合：近 3 月"):
        return "区间收益硬规则不符合：近 3 月高于近 6 月"
    if reason.startswith("区间收益硬规则不符合：近 6 月"):
        return "区间收益硬规则不符合：近 6 月高于近 1 年"
    if reason.startswith("关键收益数据不足"):
        return reason
    if reason.startswith("短历史不足"):
        return "短历史不足：未达到观察池最低历史窗口"
    if reason.startswith("一年最大回撤"):
        return "一年最大回撤超过或缺失"
    if reason.startswith("近 1 周跌幅"):
        return "近 1 周急跌触发风控"
    if reason.startswith("近 3 月和近 6 月"):
        return "近 3 月和近 6 月趋势均未转正"
    return reason


def _collect_with_concept_cap(
    funds: list[FundSnapshot],
    limit: int,
    per_concept_cap: int,
) -> list[FundSnapshot]:
    counts: Counter[str] = Counter()
    selected: list[FundSnapshot] = []
    ordered = sorted(funds, key=lambda fund: (-fund.signal_level, -(fund.score or 0), fund.drawdown or 999, fund.code))
    for fund in ordered:
        concept = fund.concepts[0] if fund.concepts else fund.fund_type or "其他"
        if counts[concept] >= per_concept_cap:
            continue
        selected.append(fund)
        counts[concept] += 1
        if len(selected) >= limit:
            break
    return selected
