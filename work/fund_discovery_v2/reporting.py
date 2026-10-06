from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import FundSnapshot


SIGNAL_COLORS = {
    "可分批试仓": "#e8f3ff",
    "等待回踩或趋势确认": "#fff3d6",
    "继续观察": "#ffffff",
    "暂不参与": "#f1f3f5",
    "回避": "#2f3e46",
}


def render_html(result: dict[str, Any]) -> str:
    candidates = _funds(result.get("candidates"))
    pullback_watch = _funds(result.get("pullback_watch"))
    watchlist = _funds(result.get("watchlist"))
    risk_samples = _funds(result.get("risk_samples"))
    all_funds = candidates + pullback_watch + watchlist + risk_samples
    stats = result.get("stats") or {}
    validation = result.get("validation") or {}
    validation_html = _validation_html(validation)
    rejects = "".join(
        f"<li>{html.escape(str(reason))}：{count}</li>"
        for reason, count in sorted((result.get("reject_summary") or {}).items(), key=lambda item: -item[1])[:10]
    ) or "<li>无</li>"
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in (result.get("limitations") or [])
    )
    signal_counts = Counter(fund.signal for fund in all_funds)
    distribution = "；".join(f"{label} {signal_counts.get(label, 0)} 只" for label in SIGNAL_COLORS)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全市场中短期基金发现 V2</title>
<style>
body{{margin:0;background:#f4f6f8;color:#24313d;font-family:"Microsoft YaHei",Arial,sans-serif}}
.wrap{{max-width:1600px;margin:auto;padding:24px}} .hero{{background:#183153;color:#fff;border-radius:10px;padding:24px}}
h1{{margin:0 0 8px;font-size:25px}} h2{{font-size:18px;margin:24px 0 10px}}
.hero p{{margin:5px 0;color:#dbe8f5;font-size:13px}} .cards{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}
.card{{background:#fff;border:1px solid #dce3ea;border-radius:8px;padding:12px 15px;min-width:135px}}
.num{{font-size:22px;font-weight:700}} .label,.muted{{font-size:11px;color:#667788}}
.panel{{background:#fff;border:1px solid #dce3ea;border-radius:8px;padding:15px;margin:14px 0;line-height:1.7;font-size:13px}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:12px}} th{{background:#29445f;color:#fff;padding:8px;border:1px solid #3b5873}}
td{{padding:7px;border:1px solid #dce3ea;vertical-align:top;line-height:1.45}} .dark{{color:#fff}}
.pill{{display:inline-block;border-radius:12px;padding:2px 7px;background:#e6edf5;margin:1px;font-size:11px}}
</style>
</head>
<body><div class="wrap">
<section class="hero">
  <h1>全市场中短期基金发现 V2</h1>
  <p>研究视角：所有基金均按尚未持有、寻找建仓机会处理；重点观察约 20–120 个交易日。</p>
  <p>数据来源：{html.escape(str(result.get('provider', '')))}；数据日期：{html.escape(str(result.get('end_date', '')))}；规则版本：{html.escape(str(result.get('rule_version', '')))}；近 1 年最大回撤统一上限：13%。</p>
  <p>本报告用于研究筛选，不构成收益承诺或确定性买卖结论。</p>
</section>
<div class="cards">
  {_card(stats.get('universe', 0), '原始基金')}
  {_card(stats.get('rough', 0), '进入详情')}
  {_card(stats.get('evaluated', 0), '完成三层判断')}
  {_card(stats.get('cross_checked', 0), '第二回撤端点核验')}
  {_card(stats.get('deduplicated', 0), '底层策略去重后')}
  {_card(len(candidates), '全周期递增候选')}
  {_card(len(pullback_watch), '回踩观察')}
  {_card(len(watchlist), '观察池')}
</div>
<div class="panel">
  <strong>决策结构：</strong>入池资格、综合评分与建仓信号相互独立；高分不能绕过近 1 周急跌、13% 回撤或数据冲突闸门。<br>
  <strong>策略通道：</strong>硬性只保留近 1 月收益率 ≤ 近 3 月收益率 ≤ 近 6 月收益率 ≤ 近 1 年收益率的基金；强中期+短期回踩通道也必须先满足这条硬规则，且只给观察或等待确认。<br>
  <strong>信号分布：</strong>{html.escape(distribution)}<br>
  <strong>份额去重：</strong>同一底层策略只保留一个数据质量与中短期条件更合适的代表份额；其他代码随代表记录披露。实际渠道费率与可申购状态尚未完整核验。
</div>
<h2>全周期递增候选</h2>{_fund_table(candidates)}
<h2>强中期+短期回踩观察</h2>{_fund_table(pullback_watch)}
<h2>继续观察</h2>{_fund_table(watchlist)}
<h2>风险闸门样本</h2>{_fund_table(risk_samples)}
<h2>历史快照滚动验证</h2>{validation_html}
<div class="panel"><strong>剔除摘要</strong><ul>{rejects}</ul></div>
<div class="panel"><strong>数据与方法限制</strong><ul>{limitations}</ul></div>
</div></body></html>"""


def write_reports(
    output_dir: Path,
    result: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stem = f"fund_discovery_v2_{result.get('end_date', timestamp.date().isoformat())}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    paths = _unique_paths(output_dir, stem)
    payload = _serializable_result(result)
    paths["html"].write_text(render_html(result), encoding="utf-8")
    paths["json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(paths["csv"], result)
    return paths


def _unique_paths(output_dir: Path, stem: str) -> dict[str, Path]:
    suffix = 1
    while True:
        candidate_stem = stem if suffix == 1 else f"{stem}_{suffix}"
        paths = {extension: output_dir / f"{candidate_stem}.{extension}" for extension in ("html", "csv", "json")}
        if not any(path.exists() for path in paths.values()):
            return paths
        suffix += 1


def _serializable_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "rule_version",
        "end_date",
        "provider",
        "stats",
        "reject_summary",
        "reject_details",
        "validation",
        "limitations",
    )
    payload = {key: result.get(key) for key in keys if key in result}
    for key in ("candidates", "pullback_watch", "short_history_watch", "watchlist", "risk_samples"):
        payload[key] = [fund.to_dict() for fund in _funds(result.get(key))]
    return payload


def _write_csv(path: Path, result: dict[str, Any]) -> None:
    headers = [
        "池",
        "名称",
        "代码",
        "基金经理",
        "底层策略",
        "份额类别",
        "同组其他代码",
        "基金类型",
        "近1周%",
        "近1月%",
        "近3月%",
        "近6月%",
        "近一年涨跌幅%",
        "近1年最大回撤%",
        "近3年最大回撤%",
        "成立以来最大回撤%",
        "入池资格",
        "综合评分",
        "建仓信号",
        "机会通道",
        "信号理由",
        "完整度",
        "置信度",
        "数据日期",
        "数据来源",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        pools = (
            ("全周期递增候选", _funds(result.get("candidates"))),
            ("强中期+短期回踩观察", _funds(result.get("pullback_watch"))),
            ("观察池", _funds(result.get("watchlist"))),
            ("风险闸门样本", _funds(result.get("risk_samples"))),
        )
        for pool, funds in pools:
            for fund in funds:
                writer.writerow(
                    [
                        pool,
                        fund.name,
                        fund.code,
                        "、".join(fund.manager_names),
                        fund.canonical_name,
                        fund.share_class,
                        "、".join(fund.alternate_share_codes),
                        fund.fund_type,
                        fund.r1w,
                        fund.r1m,
                        fund.r3m,
                        fund.r6m,
                        fund.r1y,
                        fund.drawdown,
                        fund.drawdown_3y,
                        fund.drawdown_since_inception,
                        "通过" if fund.eligibility_passed else "未通过",
                        fund.score,
                        fund.signal,
                        fund.opportunity_channel,
                        "；".join(fund.signal_reasons),
                        fund.completeness,
                        fund.confidence,
                        fund.nav_date,
                        "、".join(_sources(fund)),
                    ]
                )


def _fund_table(funds: list[FundSnapshot]) -> str:
    if not funds:
        return '<div class="panel">本区暂无项目。</div>'
    rows = []
    for index, fund in enumerate(funds, 1):
        background = SIGNAL_COLORS.get(fund.signal, "#fff")
        css_class = "dark" if fund.signal == "回避" else ""
        source_text = "、".join(_sources(fund)) or "未记录"
        alternative = "、".join(fund.alternate_share_codes) or "无"
        blockers = "；".join(fund.eligibility_blockers) or "无"
        managers = "、".join(fund.manager_names) or "--"
        rows.append(
            f"""<tr style="background:{background}" class="{css_class}">
<td>{index}</td><td><strong>{html.escape(fund.name)}</strong><br><span class="muted">{html.escape(fund.code)}</span><br><span class="pill">{html.escape(fund.opportunity_channel or '未分组')}</span></td>
<td>{html.escape(managers)}</td>
<td>{html.escape(fund.canonical_name or fund.name)}<br><span class="muted">份额 {html.escape(fund.share_class or '--')}；其他 {html.escape(alternative)}</span></td>
<td>{_pct(fund.r1w)}</td><td>{_pct(fund.r1m)}</td><td>{_pct(fund.r3m)}</td><td>{_pct(fund.r6m)}</td><td>{_pct(fund.r1y)}</td>
<td>{_pct(fund.drawdown)}<br><span class="muted">主 {_pct(fund.drawdown_primary)} / 副 {_pct(fund.drawdown_secondary)}；统一上限 13%</span></td>
<td>{_pct(fund.drawdown_3y)}<br><span class="muted">有效净值点 {fund.nav_points_3y}</span></td>
<td>{_pct(fund.drawdown_since_inception)}<br><span class="muted">有效净值点 {fund.nav_points_since_inception}</span></td>
<td>{'通过' if fund.eligibility_passed else '未通过'}<br><span class="muted">{html.escape(blockers)}</span></td>
<td><strong>{'--' if fund.score is None else f'{fund.score:.1f}'}</strong><br><span class="muted">{html.escape(_component_text(fund))}</span></td>
<td><strong>{html.escape(fund.signal)}</strong><br><span class="muted">{html.escape('；'.join(fund.signal_reasons))}</span></td>
<td>完整度 {fund.completeness:.0%}<br>置信度 {html.escape(fund.confidence)}<br><span class="muted">数据日期 {html.escape(fund.nav_date)}<br>数据来源 {html.escape(source_text)}</span></td>
</tr>"""
        )
    header = "".join(
        f"<th>{label}</th>"
        for label in ("序号", "基金", "基金经理", "底层策略/份额", "近1周", "近1月", "近3月", "近6月", "近一年涨跌幅", "近1年最大回撤", "近3年最大回撤", "成立以来最大回撤", "入池资格", "评分", "建仓信号", "数据契约")
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _validation_html(validation: dict[str, Any]) -> str:
    if validation.get("status") != "ready":
        return '<div class="panel"><strong>历史样本不足。</strong>已开始保存不可覆盖快照；只有观察窗口成熟后才统计命中率和收益分布。</div>'
    lines = []
    for label, data in (validation.get("horizons") or {}).items():
        lines.append(
            f"<li>{html.escape(label)}：样本 {data.get('samples', 0)}，正收益命中率 {_pct(data.get('positive_hit_rate_pct'))}，"
            f"中位收益 {_pct(data.get('median_return_pct'))}，最差收益 {_pct(data.get('worst_return_pct'))}</li>"
        )
    return f"<div class=\"panel\"><p>{html.escape(str(validation.get('method', '')))}</p><ul>{''.join(lines)}</ul></div>"


def _sources(fund: FundSnapshot) -> list[str]:
    output: list[str] = []
    for evidence in fund.provenance.values():
        if evidence.source and evidence.source not in output:
            output.append(evidence.source)
    return output


def _component_text(fund: FundSnapshot) -> str:
    labels = {"trend": "趋势", "risk": "风险", "relative": "同类", "quality": "质量"}
    return " / ".join(f"{labels.get(key, key)} {value:.1f}" for key, value in fund.score_components.items())


def _funds(values: Any) -> list[FundSnapshot]:
    output = []
    for value in values or []:
        output.append(value if isinstance(value, FundSnapshot) else FundSnapshot.from_dict(value))
    return output


def _card(value: Any, label: str) -> str:
    return f'<div class="card"><div class="num">{html.escape(str(value))}</div><div class="label">{html.escape(label)}</div></div>'


def _pct(value: Any) -> str:
    try:
        return "--" if value is None else f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "--"
