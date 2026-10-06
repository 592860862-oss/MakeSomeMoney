from __future__ import annotations

import re
from collections import defaultdict

from .models import CONFIDENCE_ORDER, FundSnapshot


_SHARE_CLASSES = "ACEHIRY"
_SHARE_SUFFIX = re.compile(
    rf"(?:(?<=[\u4e00-\u9fff）)])|(?<=[\s\-_/－]))([{_SHARE_CLASSES}])(?:类|份额)?$",
    re.IGNORECASE,
)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "").strip())


def detect_share_class(name: str) -> str:
    clean = _clean_name(name)
    match = _SHARE_SUFFIX.search(clean)
    return match.group(1).upper() if match else ""


def canonical_fund_name(name: str) -> str:
    clean = _clean_name(name)
    match = _SHARE_SUFFIX.search(clean)
    if match:
        clean = clean[: match.start()].rstrip("-_/－")
    clean = clean.replace("(", "（").replace(")", "）")
    return clean


def strategy_key(fund: FundSnapshot) -> str:
    return f"{canonical_fund_name(fund.name)}|{fund.fund_type.strip()}"


def deduplicate_share_classes(funds: list[FundSnapshot]) -> list[FundSnapshot]:
    groups: dict[str, list[FundSnapshot]] = defaultdict(list)
    for fund in funds:
        groups[strategy_key(fund)].append(fund)

    selected: list[FundSnapshot] = []
    for key in sorted(groups):
        group = groups[key]
        ordered = sorted(
            group,
            key=lambda item: (
                -int(item.eligibility_passed),
                -CONFIDENCE_ORDER.get(item.confidence, 0),
                -item.completeness,
                -(item.score if item.score is not None else -1.0),
                item.drawdown if item.drawdown is not None else float("inf"),
                item.code,
            ),
        )
        representative = ordered[0].clone()
        representative.canonical_name = canonical_fund_name(representative.name)
        representative.share_class = detect_share_class(representative.name)
        representative.alternate_share_codes = sorted(item.code for item in group if item.code != representative.code)
        selected.append(representative)
    return selected

