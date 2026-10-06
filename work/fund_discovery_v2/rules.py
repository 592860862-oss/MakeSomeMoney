from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .models import FundSnapshot


MAX_DRAWDOWN_PCT = 13.0
SHORT_HISTORY_MIN_DAYS = 183
ALLOWED_SIGNALS = {
    "可分批试仓",
    "等待回踩或趋势确认",
    "继续观察",
    "暂不参与",
    "回避",
}
LOCK_WORDS = ("持有期", "定开", "定期开放", "封闭", "滚动持有", "锁定", "开放期")
RETURN_KEYS = ("r1w", "r1m", "r3m", "r6m", "r1y")
EARLY_RETURN_KEYS = ("r1w", "r1m", "r3m", "r6m")
RETURN_MOMENTUM_PAIRS = (
    ("近 1 月", "r1m", "近 3 月", "r3m"),
    ("近 3 月", "r3m", "近 6 月", "r6m"),
    ("近 6 月", "r6m", "近 1 年", "r1y"),
)
LOW_VOLATILITY_TYPES = ("货币/短债现金类", "纯债/债券指数", "普通债券/固收+")


@dataclass(frozen=True)
class EligibilityResult:
    passed: bool
    blockers: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class ScoreResult:
    total: float
    components: dict[str, float]
    notes: list[str]


@dataclass(frozen=True)
class SignalResult:
    level: int
    label: str
    reasons: list[str]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def preliminary_score(fund: FundSnapshot) -> float:
    values = (fund.r1w, fund.r1m, fund.r3m, fund.r6m)
    if any(value is None for value in values):
        return -9999.0
    r1w, r1m, r3m, r6m = (float(value) for value in values)
    score = (
        clamp(r1w, -6, 8) * 1.8
        + clamp(r1m, -8, 18) * 1.1
        + clamp(r3m, -15, 35) * 0.55
        + clamp(r6m, -20, 60) * 0.22
    )
    if r3m > 0:
        score += 6
    if r6m > 0:
        score += 4
    if r1w > 8 or r1m > 18:
        score -= 12
    if r1w <= -5:
        score -= 10
    return round(score, 3)


def missing_return_keys(fund: FundSnapshot) -> tuple[str, ...]:
    return tuple(key for key in RETURN_KEYS if getattr(fund, key) is None)


def missing_returns_blocker(fund: FundSnapshot, as_of: str) -> str:
    missing = missing_return_keys(fund)
    if not missing:
        return ""
    age_days = _age_days(fund.establish_date, as_of)
    labels = {
        "r1w": "近 1 周",
        "r1m": "近 1 月",
        "r3m": "近 3 月",
        "r6m": "近 6 月",
        "r1y": "近 1 年",
    }
    if any(key in missing for key in ("r1w", "r1m", "r3m")):
        return "关键收益数据不足：短中期收益窗口缺失"
    if "r6m" in missing:
        return "关键收益数据不足：近 6 月收益缺失"
    if "r1y" in missing:
        if age_days is not None and age_days < 365:
            return "关键收益数据不足：近 1 年收益缺失，无法满足近 1 月≤近 3 月≤近 6 月≤近 1 年硬规则"
        return "关键收益数据不足：近 1 年收益缺失"
    return "关键收益数据不足：" + "、".join(labels.get(key, key) for key in missing)


def is_short_history_observable(fund: FundSnapshot, as_of: str) -> bool:
    return False


def momentum_tolerance_pct(fund: FundSnapshot) -> float:
    if fund.fund_type in LOW_VOLATILITY_TYPES:
        return 0.50
    return 0.0


def return_momentum_blocker(fund: FundSnapshot) -> str:
    for short_label, short_key, long_label, long_key in RETURN_MOMENTUM_PAIRS:
        short_value = getattr(fund, short_key)
        long_value = getattr(fund, long_key)
        if short_value is None or long_value is None:
            continue
        if float(short_value) > float(long_value):
            return (
                "区间收益硬规则不符合："
                f"{short_label} {float(short_value):.2f}% > {long_label} {float(long_value):.2f}%"
            )
    return ""


def is_pullback_opportunity(fund: FundSnapshot) -> bool:
    if any(getattr(fund, key) is None for key in ("r1w", "r1m", "r3m", "r6m", "r1y")):
        return False
    if return_momentum_blocker(fund):
        return False
    r1w = float(fund.r1w)
    r1m = float(fund.r1m)
    r3m = float(fund.r3m)
    r6m = float(fund.r6m)
    tolerance = max(3.0, momentum_tolerance_pct(fund))
    strong_midterm = (r3m >= 10 and r6m >= 15) or r3m >= 20 or r6m >= 25
    recent_pullback = r1m <= 5 and r1m < r3m - tolerance
    not_broken = r1w > -8 and r1m >= -30 and r3m > 0 and r6m > 0
    return strong_midterm and recent_pullback and not_broken


def classify_opportunity_channel(fund: FundSnapshot, as_of: str) -> str:
    if is_pullback_opportunity(fund):
        return "强中期+短期回踩"
    if not missing_return_keys(fund) and not return_momentum_blocker(fund):
        return "全周期收益递增"
    return "普通观察"


def assess_eligibility(
    fund: FundSnapshot,
    as_of: str,
    max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
) -> EligibilityResult:
    blockers: list[str] = []
    warnings: list[str] = []

    missing = missing_return_keys(fund)
    pullback = is_pullback_opportunity(fund)
    if missing:
        blockers.append(missing_returns_blocker(fund, as_of))

    momentum_blocker = return_momentum_blocker(fund)
    if momentum_blocker:
        blockers.append(momentum_blocker)
    elif pullback:
        warnings.append("强中期+短期回踩观察：全周期收益递增，短期回撤只给观察或确认信号")

    if any(word in fund.name for word in LOCK_WORDS):
        blockers.append("存在锁定期或定期开放特征")

    age_days = _age_days(fund.establish_date, as_of)
    if age_days is None:
        blockers.append("成立日期无法确认")
    elif age_days < 365:
        blockers.append("成立不足 1 年")

    if fund.drawdown is None:
        blockers.append("一年最大回撤无法核验")
    elif fund.drawdown > max_drawdown_pct:
        blockers.append(f"一年最大回撤 {fund.drawdown:.2f}% 超过统一上限 13%")
    elif fund.drawdown > 11:
        warnings.append("一年最大回撤接近统一上限 13%")

    if fund.r3m is not None and fund.r6m is not None and fund.r3m <= 0 and fund.r6m <= 0:
        blockers.append("近 3 月和近 6 月趋势均未转正")

    if fund.r1w is not None:
        if fund.r1w <= -8:
            blockers.append(f"近 1 周跌幅达到或超过 8%（当前 {fund.r1w:.2f}%）")
        elif fund.r1w <= -5:
            warnings.append("近 1 周快速回落，暂不宜试仓")
        elif fund.r1w > 8:
            warnings.append("近 1 周涨幅过热，存在追涨风险")

    if fund.r1m is not None and fund.r1m > 18:
        warnings.append("近 1 月涨幅过热，等待回踩更稳妥")

    if fund.data_conflict:
        blockers.append("关键回撤数据端点冲突，结论置信度低")

    return EligibilityResult(not blockers, blockers, warnings)


def score_fund(fund: FundSnapshot) -> ScoreResult:
    r1w = fund.r1w or 0.0
    r1m = fund.r1m or 0.0
    r3m = fund.r3m or 0.0
    r6m = fund.r6m or 0.0
    drawdown = fund.drawdown if fund.drawdown is not None else MAX_DRAWDOWN_PCT

    trend = (
        clamp(5 + r1w * 1.5, 0, 10)
        + clamp(5 + r1m * 0.6, 0, 10)
        + clamp(4 + r3m * 0.35, 0, 12)
        + clamp(3 + r6m * 0.2, 0, 8)
    )
    if r1m > 0 and r3m > 0 and r6m > 0:
        trend += 4
    if r3m / 3 > (r6m / 6) * 1.03:
        trend += 3
    if r1w > 8:
        trend -= 6
    if r1m > 18:
        trend -= 5
    trend = clamp(trend, 0, 40)

    drawdown_room = clamp(5 + (MAX_DRAWDOWN_PCT - drawdown) / MAX_DRAWDOWN_PCT * 10, 0, 15)
    reward_risk = clamp(((r3m + r6m) / max(drawdown * 2, 1)) * 5, 0, 7)
    positive_bonus = 3 if r3m > 0 and r6m > 0 else 0
    risk = clamp(drawdown_room + reward_risk + positive_bonus, 0, 25)

    wins = 0
    excess = 0.0
    for own, peer in ((r1m, fund.peer1m), (r3m, fund.peer3m), (r6m, fund.peer6m)):
        if peer is None:
            continue
        difference = own - peer
        wins += int(difference > 0)
        excess += clamp(difference, -10, 20)
    relative = wins * 4 + clamp(excess * 0.3, -3, 4)
    if fund.rank_pct is not None:
        if fund.rank_pct <= 10:
            relative += 5
        elif fund.rank_pct <= 30:
            relative += 4
        elif fund.rank_pct <= 50:
            relative += 2
        elif fund.rank_pct > 70:
            relative -= 2
    relative = clamp(relative, 0, 20)

    confidence_bonus = {"high": 5.0, "medium": 3.0, "low": 0.0}[fund.confidence]
    quality = clamp(fund.completeness * 10 + confidence_bonus, 0, 15)

    components = {
        "trend": round(trend, 1),
        "risk": round(risk, 1),
        "relative": round(relative, 1),
        "quality": round(quality, 1),
    }
    total = round(sum(components.values()), 1)
    notes = [
        f"近 1 周 {r1w:.2f}% 已计入趋势与风控",
        f"一年最大回撤按统一 13% 上限评估（当前 {drawdown:.2f}%）",
        f"近 3 年最大回撤 {_format_pct(fund.drawdown_3y)}；成立以来最大回撤 {_format_pct(fund.drawdown_since_inception)}",
        f"同类比较胜出 {wins}/3 项",
        f"数据完整度 {fund.completeness:.0%}、置信度 {fund.confidence}",
    ]
    return ScoreResult(total, components, notes)


def _format_pct(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}%"


def derive_entry_signal(
    fund: FundSnapshot,
    eligibility: EligibilityResult,
    score: ScoreResult,
) -> SignalResult:
    severe = any(
        marker in blocker
        for blocker in eligibility.blockers
        for marker in ("超过统一上限 13%", "跌幅达到或超过 8%", "数据端点冲突")
    )
    if severe:
        return SignalResult(1, "回避", list(eligibility.blockers))
    if not eligibility.passed:
        return SignalResult(2, "暂不参与", list(eligibility.blockers))

    warning_text = "；".join(eligibility.warnings)
    pullback = "强中期+短期回踩" in warning_text

    if fund.confidence == "low":
        label = "继续观察" if score.total >= 75 else "暂不参与"
        level = 3 if label == "继续观察" else 2
        return SignalResult(level, label, ["数据置信度偏低，不能给出试仓信号"] + list(eligibility.warnings))

    if fund.r1w is not None and fund.r1w <= -5:
        if pullback and fund.r1w > -8:
            return SignalResult(3, "继续观察", ["强中期但近 1 周仍在快速回落，等待止跌确认"] + list(eligibility.warnings))
        return SignalResult(2, "暂不参与", ["近 1 周快速回落，等待风险释放"])

    if pullback:
        if score.total >= 58:
            return SignalResult(4, "等待回踩或趋势确认", list(eligibility.warnings))
        return SignalResult(3, "继续观察", list(eligibility.warnings) or ["回踩结构尚需更多确认"])

    overheated = (fund.r1w is not None and fund.r1w > 8) or (fund.r1m is not None and fund.r1m > 18)
    drawdown_near_limit = fund.drawdown is not None and fund.drawdown > 10

    if score.total >= 82:
        if fund.drawdown_secondary is None:
            return SignalResult(4, "等待回踩或趋势确认", ["第二回撤端点尚未完成核验，不能直接给出试仓信号"])
        if overheated or drawdown_near_limit or (fund.r1w is not None and fund.r1w < 0):
            reasons = list(eligibility.warnings) or ["综合条件较强，但入场节奏尚不理想"]
            return SignalResult(4, "等待回踩或趋势确认", reasons)
        return SignalResult(5, "可分批试仓", ["资格、评分和风险闸门均满足"])
    if score.total >= 72:
        return SignalResult(4, "等待回踩或趋势确认", list(eligibility.warnings) or ["条件接近试仓阈值"])
    if score.total >= 60:
        return SignalResult(3, "继续观察", ["趋势或风险补偿尚未达到建仓阈值"])
    return SignalResult(2, "暂不参与", ["综合评分不足，当前没有合适的建仓性价比"])


def _age_days(establish_date: str, as_of: str) -> int | None:
    try:
        born = datetime.strptime(establish_date, "%Y-%m-%d").date()
        end = datetime.strptime(as_of, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (end - born).days
