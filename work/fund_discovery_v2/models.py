from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class FieldEvidence:
    source: str
    as_of: str
    status: str = "ok"
    confidence: str = "medium"
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "as_of": self.as_of,
            "status": self.status,
            "confidence": self.confidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FieldEvidence":
        return cls(
            source=str(value.get("source", "")),
            as_of=str(value.get("as_of", "")),
            status=str(value.get("status", "unknown")),
            confidence=str(value.get("confidence", "low")),
            note=str(value.get("note", "")),
        )


@dataclass
class FundSnapshot:
    code: str
    name: str
    nav_date: str = ""
    establish_date: str = ""
    category: str = ""
    fund_type: str = ""
    nav: float | None = None
    acc_nav: float | None = None
    r1w: float | None = None
    r1m: float | None = None
    r3m: float | None = None
    r6m: float | None = None
    r1y: float | None = None
    drawdown: float | None = None
    drawdown_primary: float | None = None
    drawdown_secondary: float | None = None
    drawdown_3y: float | None = None
    drawdown_since_inception: float | None = None
    nav_points: int = 0
    nav_points_3y: int = 0
    nav_points_since_inception: int = 0
    peer1m: float | None = None
    peer3m: float | None = None
    peer6m: float | None = None
    rank_pct: float | None = None
    scale: float | None = None
    manager_names: list[str] = field(default_factory=list)
    asset_hint: str = ""
    concepts: list[str] = field(default_factory=list)
    holdings: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, FieldEvidence] = field(default_factory=dict)
    data_conflict: bool = False
    canonical_name: str = ""
    share_class: str = ""
    alternate_share_codes: list[str] = field(default_factory=list)
    prelim_score: float = 0.0
    eligibility_passed: bool = False
    eligibility_blockers: list[str] = field(default_factory=list)
    eligibility_warnings: list[str] = field(default_factory=list)
    score: float | None = None
    score_components: dict[str, float] = field(default_factory=dict)
    score_notes: list[str] = field(default_factory=list)
    signal: str = ""
    signal_level: int = 0
    signal_reasons: list[str] = field(default_factory=list)
    opportunity_channel: str = ""

    @staticmethod
    def required_quality_fields() -> tuple[str, ...]:
        return (
            "nav_date",
            "establish_date",
            "r1w",
            "r1m",
            "r3m",
            "r6m",
            "r1y",
            "drawdown",
        )

    @property
    def completeness(self) -> float:
        complete = 0
        required = self.required_quality_fields()
        for key in required:
            value = getattr(self, key, None)
            evidence = self.provenance.get(key)
            value_present = value is not None and value != ""
            evidence_usable = evidence is None or evidence.status == "ok"
            if value_present and evidence_usable:
                complete += 1
        return round(complete / len(required), 3)

    @property
    def confidence(self) -> str:
        if self.data_conflict or self.completeness < 0.75:
            return "low"
        critical = [self.provenance.get(key) for key in self.required_quality_fields()]
        known = [item for item in critical if item is not None]
        if any(item.status in {"conflict", "error"} or item.confidence == "low" for item in known):
            return "low"
        if self.completeness == 1.0 and len(known) == len(critical) and all(
            item.confidence == "high" for item in known
        ):
            return "high"
        return "medium"

    def clone(self) -> "FundSnapshot":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "canonical_name": self.canonical_name,
            "share_class": self.share_class,
            "alternate_share_codes": list(self.alternate_share_codes),
            "nav_date": self.nav_date,
            "establish_date": self.establish_date,
            "category": self.category,
            "fund_type": self.fund_type,
            "nav": self.nav,
            "acc_nav": self.acc_nav,
            "returns": {
                "r1w": self.r1w,
                "r1m": self.r1m,
                "r3m": self.r3m,
                "r6m": self.r6m,
                "r1y": self.r1y,
            },
            "risk": {
                "drawdown": self.drawdown,
                "drawdown_1y": self.drawdown,
                "drawdown_primary": self.drawdown_primary,
                "drawdown_secondary": self.drawdown_secondary,
                "drawdown_3y": self.drawdown_3y,
                "drawdown_since_inception": self.drawdown_since_inception,
                "nav_points": self.nav_points,
                "nav_points_3y": self.nav_points_3y,
                "nav_points_since_inception": self.nav_points_since_inception,
                "data_conflict": self.data_conflict,
            },
            "relative": {
                "peer1m": self.peer1m,
                "peer3m": self.peer3m,
                "peer6m": self.peer6m,
                "rank_pct": self.rank_pct,
            },
            "scale": self.scale,
            "manager_names": list(self.manager_names),
            "asset_hint": self.asset_hint,
            "concepts": list(self.concepts),
            "holdings": copy.deepcopy(self.holdings),
            "provenance": {key: value.to_dict() for key, value in self.provenance.items()},
            "data_quality": {
                "completeness": self.completeness,
                "confidence": self.confidence,
            },
            "decision": {
                "eligibility_passed": self.eligibility_passed,
                "eligibility_blockers": list(self.eligibility_blockers),
                "eligibility_warnings": list(self.eligibility_warnings),
                "score": self.score,
                "score_components": dict(self.score_components),
                "score_notes": list(self.score_notes),
                "signal": self.signal,
                "signal_level": self.signal_level,
                "signal_reasons": list(self.signal_reasons),
                "opportunity_channel": self.opportunity_channel,
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FundSnapshot":
        returns = raw.get("returns") or raw
        risk = raw.get("risk") or raw
        relative = raw.get("relative") or raw
        decision = raw.get("decision") or raw
        provenance = {
            key: value if isinstance(value, FieldEvidence) else FieldEvidence.from_dict(value)
            for key, value in (raw.get("provenance") or {}).items()
        }
        return cls(
            code=str(raw.get("code", "")),
            name=str(raw.get("name", "")),
            canonical_name=str(raw.get("canonical_name", "")),
            share_class=str(raw.get("share_class", "")),
            alternate_share_codes=list(raw.get("alternate_share_codes") or []),
            nav_date=str(raw.get("nav_date", "")),
            establish_date=str(raw.get("establish_date", "")),
            category=str(raw.get("category", "")),
            fund_type=str(raw.get("fund_type", "")),
            nav=_optional_float(raw.get("nav")),
            acc_nav=_optional_float(raw.get("acc_nav")),
            r1w=_optional_float(returns.get("r1w")),
            r1m=_optional_float(returns.get("r1m")),
            r3m=_optional_float(returns.get("r3m")),
            r6m=_optional_float(returns.get("r6m")),
            r1y=_optional_float(returns.get("r1y")),
            drawdown=_optional_float(risk.get("drawdown", risk.get("drawdown_1y"))),
            drawdown_primary=_optional_float(risk.get("drawdown_primary")),
            drawdown_secondary=_optional_float(risk.get("drawdown_secondary")),
            drawdown_3y=_optional_float(risk.get("drawdown_3y")),
            drawdown_since_inception=_optional_float(risk.get("drawdown_since_inception")),
            nav_points=int(risk.get("nav_points") or 0),
            nav_points_3y=int(risk.get("nav_points_3y") or 0),
            nav_points_since_inception=int(risk.get("nav_points_since_inception") or 0),
            data_conflict=bool(risk.get("data_conflict", raw.get("data_conflict", False))),
            peer1m=_optional_float(relative.get("peer1m")),
            peer3m=_optional_float(relative.get("peer3m")),
            peer6m=_optional_float(relative.get("peer6m")),
            rank_pct=_optional_float(relative.get("rank_pct")),
            scale=_optional_float(raw.get("scale")),
            manager_names=_manager_names(raw),
            asset_hint=str(raw.get("asset_hint", "")),
            concepts=list(raw.get("concepts") or []),
            holdings=copy.deepcopy(raw.get("holdings") or []),
            provenance=provenance,
            prelim_score=float(raw.get("prelim_score") or 0.0),
            eligibility_passed=bool(decision.get("eligibility_passed", False)),
            eligibility_blockers=list(decision.get("eligibility_blockers") or []),
            eligibility_warnings=list(decision.get("eligibility_warnings") or []),
            score=_optional_float(decision.get("score")),
            score_components={
                str(key): float(value) for key, value in (decision.get("score_components") or {}).items()
            },
            score_notes=list(decision.get("score_notes") or []),
            signal=str(decision.get("signal", "")),
            signal_level=int(decision.get("signal_level") or 0),
            signal_reasons=list(decision.get("signal_reasons") or []),
            opportunity_channel=str(decision.get("opportunity_channel", raw.get("opportunity_channel", ""))),
        )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _manager_names(raw: dict[str, Any]) -> list[str]:
    names = raw.get("manager_names", raw.get("fund_manager_names", raw.get("fund_manager", [])))
    if isinstance(names, str):
        candidates = re.split(r"[、,，/]+", names)
    elif isinstance(names, list):
        candidates = names
    else:
        candidates = []
    output: list[str] = []
    for name in candidates:
        text = str(name).strip()
        if text and text not in output:
            output.append(text)
    return output
