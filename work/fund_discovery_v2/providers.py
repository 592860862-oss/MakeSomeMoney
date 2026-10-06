from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .models import FieldEvidence, FundSnapshot


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass(frozen=True)
class DrawdownCheck:
    value: float | None
    primary: float | None
    secondary: float | None
    conflict: bool
    confidence: str
    note: str


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "").replace(",", "")
    if text in {"", "--", "---", "None", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class HttpClient:
    def __init__(
        self,
        cache_dir: Path,
        retries: int = 3,
        cache_ttl_seconds: int = 6 * 3600,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.retries = max(1, retries)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.use_cache = use_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_bytes(self, url: str, referer: str = "", timeout: int = 25) -> bytes:
        cache_path = self._cache_path(url)
        if self.use_cache and self._is_fresh(cache_path):
            return cache_path.read_bytes()

        headers = {"User-Agent": USER_AGENT}
        if referer:
            headers["Referer"] = referer
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    content = response.read()
                if self.use_cache:
                    self._atomic_cache_write(cache_path, content)
                return content
            except Exception as exc:  # Network adapters must preserve the last usable cache.
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.35 * (attempt + 1))

        if self.use_cache and cache_path.exists():
            return cache_path.read_bytes()
        if last_error is None:
            raise RuntimeError(f"无法获取数据：{url}")
        raise last_error

    def get_text(self, url: str, referer: str = "", timeout: int = 25) -> str:
        content = self.get_bytes(url, referer=referer, timeout=timeout)
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", "replace")

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.bin"

    def _is_fresh(self, path: Path) -> bool:
        return path.exists() and time.time() - path.stat().st_mtime <= self.cache_ttl_seconds

    @staticmethod
    def _atomic_cache_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(path)


def parse_rank_text(text: str) -> list[dict[str, Any]]:
    match = re.search(r"datas\s*:\s*\[(.*?)\]\s*,\s*allRecords", text, re.S)
    if not match:
        raise ValueError("无法解析基金排行数据")
    funds: list[dict[str, Any]] = []
    for encoded_row in re.findall(r'"(.*?)"', match.group(1), re.S):
        columns = encoded_row.split(",")
        if len(columns) < 17:
            continue
        funds.append(
            {
                "code": columns[0],
                "name": columns[1],
                "abbr": columns[2],
                "nav_date": columns[3],
                "nav": to_float(columns[4]),
                "acc_nav": to_float(columns[5]),
                "r1w": to_float(columns[7]),
                "r1m": to_float(columns[8]),
                "r3m": to_float(columns[9]),
                "r6m": to_float(columns[10]),
                "r1y": to_float(columns[11]),
                "ytd": to_float(columns[14]),
                "establish_date": columns[16],
            }
        )
    return funds


def parse_meta_text(text: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in re.findall(r'\["(.*?)"\]', text):
        columns = row.split('\",\"')
        if len(columns) >= 4:
            output[columns[0]] = {
                "short": columns[1],
                "name": columns[2],
                "category": columns[3],
            }
    return output


def parse_nav_history(content: str) -> list[tuple[date, float]]:
    values: list[tuple[date, float]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) < 3:
            continue
        clean = [html.unescape(re.sub(r"<.*?>", "", cell, flags=re.S)).strip() for cell in cells]
        try:
            day = datetime.strptime(clean[0], "%Y-%m-%d").date()
        except ValueError:
            continue
        unit_value = to_float(clean[1])
        accumulated_value = to_float(clean[2])
        value = accumulated_value if accumulated_value is not None else unit_value
        if value is not None:
            values.append((day, value))
    return sorted(values)


def parse_nav_api_json(content: str) -> list[tuple[date, float]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("无法解析分页历史净值 JSON") from exc
    rows = (payload.get("Data") or {}).get("LSJZList") or []
    values: list[tuple[date, float]] = []
    for row in rows:
        try:
            day = datetime.strptime(str(row.get("FSRQ", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        accumulated = to_float(row.get("LJJZ"))
        unit = to_float(row.get("DWJZ"))
        value = accumulated if accumulated is not None else unit
        if value is not None:
            values.append((day, value))
    return sorted(values)


def compute_max_drawdown(
    values: Iterable[tuple[date, float]],
    minimum_points: int = 30,
) -> float | None:
    points = sorted(values)
    if len(points) < minimum_points:
        return None
    peak = points[0][1]
    worst = 0.0
    for _, value in points:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100)
    return round(worst, 2)


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def _date_or_fallback(value: str, fallback: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return datetime.strptime(fallback, "%Y-%m-%d").date()


def merge_drawdown_checks(
    primary: float | None,
    secondary: float | None,
    tolerance_pct_points: float = 1.0,
) -> DrawdownCheck:
    available = [value for value in (primary, secondary) if value is not None]
    if not available:
        return DrawdownCheck(None, primary, secondary, False, "low", "两个回撤端点均不可用")
    if len(available) == 1:
        source = "净值曲线端点" if primary is not None else "历史净值端点"
        return DrawdownCheck(available[0], primary, secondary, False, "medium", f"仅{source}可用")
    difference = abs(float(primary) - float(secondary))
    conflict = difference > tolerance_pct_points
    confidence = "low" if conflict else "high"
    note = f"两端点差异 {difference:.2f} 个百分点；采用较保守值"
    return DrawdownCheck(max(available), primary, secondary, conflict, confidence, note)


def extract_js_var(text: str, name: str) -> str | None:
    key = f"var {name}"
    start = text.find(key)
    if start < 0:
        return None
    equals = text.find("=", start)
    if equals < 0:
        return None
    index = equals + 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return None
    opener = text[index]
    closer = {"[": "]", "{": "}", '"': '"'}.get(opener)
    if closer is None:
        end = text.find(";", index)
        return text[index:end].strip()
    depth = 0
    in_string = False
    escaped = False
    for cursor in range(index, len(text)):
        char = text[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            if opener == '"' and cursor > index:
                return text[index : cursor + 1]
            in_string = True
        elif opener in "[{" and char == opener:
            depth += 1
        elif opener in "[{" and char == closer:
            depth -= 1
            if depth == 0:
                return text[index : cursor + 1]
    return None


def parse_full_curve_points(text: str) -> list[tuple[date, float]]:
    accumulated_raw = extract_js_var(text, "Data_ACWorthTrend")
    accumulated: list[tuple[date, float]] = []
    if accumulated_raw:
        try:
            for item in json.loads(accumulated_raw):
                if not isinstance(item, list) or len(item) < 2:
                    continue
                day = datetime.fromtimestamp(int(item[0]) / 1000).date()
                accumulated.append((day, float(item[1])))
        except (TypeError, ValueError, json.JSONDecodeError):
            accumulated = []
    if accumulated:
        return _unique_curve_points(accumulated)

    net_worth_raw = extract_js_var(text, "Data_netWorthTrend")
    net_values: list[tuple[date, float]] = []
    if net_worth_raw:
        try:
            for item in json.loads(net_worth_raw):
                day = datetime.fromtimestamp(int(item["x"]) / 1000).date()
                value = to_float(item.get("y"))
                if value is not None:
                    net_values.append((day, value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            net_values = []
    if net_values:
        return _unique_curve_points(net_values)

    return _unique_curve_points(_equity_return_index_points(text))


def parse_curve_points(text: str, start_date: str, end_date: str) -> list[tuple[date, float]]:
    return select_curve_window(parse_full_curve_points(text), start_date, end_date)


def select_curve_window(
    points: list[tuple[date, float]],
    start_date: str,
    end_date: str,
    include_prior_start: bool = True,
) -> list[tuple[date, float]]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    ordered = _unique_curve_points(points)
    selected: list[tuple[date, float]] = []
    if include_prior_start:
        prior = [point for point in ordered if point[0] <= start]
        if prior:
            selected.append(prior[-1])
    for point in ordered:
        if start < point[0] <= end and (not selected or selected[-1][0] != point[0]):
            selected.append(point)
        elif not include_prior_start and start <= point[0] <= end:
            selected.append(point)
    return selected


def _equity_return_index_points(text: str) -> list[tuple[date, float]]:
    net_worth_raw = extract_js_var(text, "Data_netWorthTrend")
    points: list[tuple[date, float]] = []
    if not net_worth_raw:
        return points
    try:
        index_value = 1.0
        for item in json.loads(net_worth_raw):
            day = datetime.fromtimestamp(int(item["x"]) / 1000).date()
            daily_return = to_float(item.get("equityReturn")) or 0.0
            if points:
                index_value *= 1 + daily_return / 100
            points.append((day, index_value))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return []
    return points


def _unique_curve_points(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    unique: dict[date, float] = {}
    for day, value in sorted(points):
        unique[day] = value
    return sorted(unique.items())


def series_return(data: list[list[Any]], days: int) -> float | None:
    if not data:
        return None
    last_timestamp, last_value = data[-1]
    target = float(last_timestamp) - days * 86400000
    prior = min(data, key=lambda point: abs(float(point[0]) - target))
    try:
        return round(float(last_value) - float(prior[1]), 4)
    except (TypeError, ValueError):
        return None


def parse_detail_text(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "peer1m": None,
        "peer3m": None,
        "peer6m": None,
        "rank_pct": None,
        "scale": None,
        "manager_names": [],
        "asset_hint": "",
    }
    manager_raw = extract_js_var(text, "Data_currentFundManager")
    if manager_raw:
        try:
            names: list[str] = []
            for item in json.loads(manager_raw):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if name and name not in names:
                    names.append(name)
            result["manager_names"] = names
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    grand_total = extract_js_var(text, "Data_grandTotal")
    if grand_total:
        try:
            series = json.loads(grand_total)
            peer = next((item for item in series if "同类平均" in item.get("name", "")), None)
            if peer:
                data = peer.get("data") or []
                result["peer1m"] = series_return(data, 30)
                result["peer3m"] = series_return(data, 90)
                result["peer6m"] = series_return(data, 180)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    similar_rank = extract_js_var(text, "Data_rateInSimilarType")
    if similar_rank:
        try:
            data = json.loads(similar_rank)
            if data:
                position = to_float(data[-1].get("y"))
                count = to_float(data[-1].get("sc"))
                if position is not None and count:
                    result["rank_pct"] = round(position / count * 100, 2)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    scale_raw = extract_js_var(text, "Data_fluctuationScale")
    if scale_raw:
        try:
            series = json.loads(scale_raw).get("series") or []
            if series:
                result["scale"] = to_float(series[-1].get("y"))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    asset_raw = extract_js_var(text, "Data_assetAllocation")
    if asset_raw:
        try:
            hints = []
            for item in json.loads(asset_raw).get("series") or []:
                data = item.get("data") or []
                if data:
                    hints.append(f"{item.get('name', '')} {data[-1]}%")
            result["asset_hint"] = "；".join(hints[:3])
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return result


def parse_holdings_table(text: str) -> list[dict[str, str]]:
    decoded = html.unescape(text)
    holdings: list[dict[str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", decoded, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) < 5:
            continue
        clean = [re.sub(r"<.*?>", "", cell, flags=re.S).strip() for cell in cells]
        if not clean or not clean[0].isdigit():
            continue
        code = clean[1] if len(clean) > 1 else ""
        name = clean[2] if len(clean) > 2 else ""
        ratio = next((value for value in clean if "%" in value), "")
        if code and name:
            holdings.append({"code": code, "name": name, "ratio": ratio})
    return holdings


NAME_CONCEPTS = (
    ("AI/科技成长", ("人工智能", "数字", "科技", "智能", "信息", "互联网", "计算机", "电子")),
    ("半导体/芯片", ("半导体", "芯片", "集成电路")),
    ("新能源/电池", ("新能源", "电池", "光伏", "碳中和")),
    ("医药/创新药", ("医药", "医疗", "健康", "创新药", "生物")),
    ("黄金/贵金属", ("黄金", "贵金属")),
    ("港股/全球配置", ("港股", "全球", "海外", "QDII", "纳斯达克", "标普")),
    ("债券/固收", ("债", "货币", "现金", "短融", "同业存单")),
)
HOLDING_CONCEPTS = (
    ("AI算力/光模块", ("新易盛", "中际旭创", "天孚通信", "寒武纪", "工业富联", "胜宏科技")),
    ("半导体/芯片", ("北方华创", "中芯国际", "海光信息", "兆易创新", "澜起科技")),
    ("新能源/电池", ("宁德时代", "阳光电源", "比亚迪", "亿纬锂能")),
    ("创新药/医药", ("恒瑞医药", "百济神州", "药明康德", "迈瑞医疗")),
    ("黄金/贵金属", ("山东黄金", "中金黄金", "紫金矿业", "赤峰黄金")),
    ("港股互联网", ("腾讯控股", "阿里巴巴", "美团", "小米集团")),
    ("消费/白酒", ("贵州茅台", "五粮液", "泸州老窖", "山西汾酒")),
    ("金融地产", ("招商银行", "宁波银行", "中国平安", "保利发展")),
    ("军工/高端制造", ("中航沈飞", "航发动力", "中航光电")),
    ("债券/固收", ("国债", "金融债", "企业债", "中期票据", "同业存单")),
)


def infer_concepts(name: str, holdings: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for concept, keywords in NAME_CONCEPTS:
        if any(keyword in name for keyword in keywords):
            found.append(concept)
    holding_text = " ".join(str(item.get("name", "")) for item in holdings)
    for concept, keywords in HOLDING_CONCEPTS:
        if any(keyword in holding_text for keyword in keywords):
            found.append(concept)
    unique: list[str] = []
    for concept in found:
        if concept not in unique:
            unique.append(concept)
    return unique[:3] or ["综合/风格轮动"]


def classify_fund(name: str, category: str) -> str:
    text = f"{name} {category}"
    if any(word in text for word in ("货币", "现金", "短债", "超短债", "同业存单")):
        return "货币/短债现金类"
    if "纯债" in text or ("债券" in text and not any(word in text for word in ("混合", "增强", "可转债", "二级"))):
        return "纯债/债券指数"
    if any(word in text for word in ("可转债", "转债")):
        return "可转债/高弹性债券"
    if any(word in text for word in ("固收", "增强债", "二级债", "债券")):
        return "普通债券/固收+"
    if any(word in text for word in ("QDII", "全球", "海外", "港股", "纳斯达克", "标普")):
        return "QDII/海外"
    if any(word in text for word in ("半导体", "芯片", "人工智能", "军工", "新能源", "医药", "黄金", "有色")):
        return "行业主题/高波动赛道"
    if any(word in text for word in ("股票", "指数", "ETF", "联接", "混合", "LOF")):
        return "主动权益/宽基指数"
    return "类型待确认"


class EastmoneyProvider:
    provider_name = "东方财富/天天基金公开数据"

    def __init__(self, cache_dir: Path, use_cache: bool = True) -> None:
        self.http = HttpClient(cache_dir=cache_dir, use_cache=use_cache)

    def fetch_universe(self, end_date: str) -> tuple[list[FundSnapshot], str]:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        start_date = (end - timedelta(days=365)).isoformat()
        params = {
            "op": "ph",
            "dt": "kf",
            "ft": "all",
            "rs": "",
            "gs": "0",
            "sc": "3yzf",
            "st": "desc",
            "sd": start_date,
            "ed": end_date,
            "qdii": "",
            "tabSubtype": ",,,,,",
            "pi": "1",
            "pn": "20000",
            "dx": "1",
        }
        rank_url = "https://fund.eastmoney.com/data/rankhandler.aspx?" + urllib.parse.urlencode(params)
        rank_text = self.http.get_text(rank_url, "https://fund.eastmoney.com/data/fundranking.html", timeout=45)
        rows = parse_rank_text(rank_text)

        meta: dict[str, dict[str, str]] = {}
        try:
            meta_text = self.http.get_text(
                "https://fund.eastmoney.com/js/fundcode_search.js",
                "https://fund.eastmoney.com/",
                timeout=30,
            )
            meta = parse_meta_text(meta_text)
        except Exception:
            meta = {}

        funds: list[FundSnapshot] = []
        for raw in rows:
            item_meta = meta.get(raw["code"], {})
            name = item_meta.get("name") or raw["name"]
            category = item_meta.get("category", "")
            fund = FundSnapshot(
                code=raw["code"],
                name=name,
                nav_date=raw["nav_date"],
                establish_date=raw["establish_date"],
                category=category,
                fund_type=classify_fund(name, category),
                nav=raw["nav"],
                acc_nav=raw["acc_nav"],
                r1w=raw["r1w"],
                r1m=raw["r1m"],
                r3m=raw["r3m"],
                r6m=raw["r6m"],
                r1y=raw["r1y"],
            )
            for field in ("nav_date", "establish_date", "acc_nav", "r1w", "r1m", "r3m", "r6m", "r1y"):
                value = getattr(fund, field)
                fund.provenance[field] = FieldEvidence(
                    source="东方财富基金排行",
                    as_of=fund.nav_date or end_date,
                    status="ok" if value is not None and value != "" else "missing",
                    confidence="high" if value is not None and value != "" else "low",
                )
            funds.append(fund)
        return funds, start_date

    def enrich(self, fund: FundSnapshot, start_date: str, end_date: str) -> FundSnapshot:
        output = fund.clone()
        primary: float | None = None
        secondary: float | None = None
        primary_points = 0
        drawdown_3y: float | None = None
        drawdown_since_inception: float | None = None
        points_3y = 0
        points_since_inception = 0
        detail_errors: list[str] = []

        detail_url = f"https://fund.eastmoney.com/pingzhongdata/{fund.code}.js"
        try:
            end_day = _date_or_fallback(fund.nav_date, end_date)
            one_year_start = _shift_years(end_day, 1).isoformat()
            three_year_start = _shift_years(end_day, 3).isoformat()
            since_start = fund.establish_date or "1900-01-01"
            detail_text = self.http.get_text(
                detail_url,
                f"https://fund.eastmoney.com/{fund.code}.html",
                timeout=25,
            ).lstrip("\ufeff")
            curve_all = parse_full_curve_points(detail_text)
            curve = select_curve_window(curve_all, one_year_start, end_day.isoformat())
            curve_3y = select_curve_window(curve_all, three_year_start, end_day.isoformat())
            curve_since = select_curve_window(curve_all, since_start, end_day.isoformat())
            primary_points = len(curve)
            points_3y = len(curve_3y)
            points_since_inception = len(curve_since)
            primary = compute_max_drawdown(curve)
            drawdown_3y = compute_max_drawdown(curve_3y)
            drawdown_since_inception = compute_max_drawdown(curve_since)
            for key, value in parse_detail_text(detail_text).items():
                setattr(output, key, value)
        except Exception as exc:
            detail_errors.append(f"净值曲线端点失败：{type(exc).__name__}")

        check = merge_drawdown_checks(primary, secondary)
        output.drawdown = check.value
        output.drawdown_primary = primary
        output.drawdown_secondary = secondary
        output.drawdown_3y = drawdown_3y
        output.drawdown_since_inception = drawdown_since_inception
        output.data_conflict = check.conflict
        output.nav_points = primary_points
        output.nav_points_3y = points_3y
        output.nav_points_since_inception = points_since_inception
        output.provenance["drawdown"] = FieldEvidence(
            source="东方财富净值曲线 + 历史净值独立端点",
            as_of=end_day.isoformat(),
            status="conflict" if check.conflict else ("ok" if check.value is not None else "missing"),
            confidence=check.confidence,
            note="；".join([check.note] + detail_errors),
        )
        output.provenance["drawdown_primary"] = FieldEvidence(
            source="东方财富 pingzhongdata 净值曲线",
            as_of=end_day.isoformat(),
            status="ok" if primary is not None else "missing",
            confidence="high" if primary is not None else "low",
        )
        output.provenance["drawdown_secondary"] = FieldEvidence(
            source="东方财富 F10 历史净值端点",
            as_of=end_day.isoformat(),
            status="ok" if secondary is not None else "missing",
            confidence="high" if secondary is not None else "low",
        )
        output.provenance["drawdown_3y"] = FieldEvidence(
            source="东方财富净值曲线",
            as_of=end_day.isoformat(),
            status="ok" if drawdown_3y is not None else "missing",
            confidence="high" if drawdown_3y is not None else "low",
            note=f"近 3 年窗口有效净值点 {points_3y} 个；成立不足 3 年时为可得历史窗口",
        )
        output.provenance["drawdown_since_inception"] = FieldEvidence(
            source="东方财富净值曲线",
            as_of=end_day.isoformat(),
            status="ok" if drawdown_since_inception is not None else "missing",
            confidence="high" if drawdown_since_inception is not None else "low",
            note=f"成立以来窗口有效净值点 {points_since_inception} 个",
        )

        for field in ("peer1m", "peer3m", "peer6m", "rank_pct", "scale"):
            value = getattr(output, field)
            output.provenance[field] = FieldEvidence(
                source="东方财富基金详情",
                as_of=end_date,
                status="ok" if value is not None else "missing",
                confidence="medium" if value is not None else "low",
            )
        output.provenance["manager_names"] = FieldEvidence(
            source="东方财富基金详情",
            as_of=end_date,
            status="ok" if output.manager_names else "missing",
            confidence="high" if output.manager_names else "low",
        )

        if output.drawdown is not None and output.drawdown <= 13:
            try:
                output.holdings = self._fetch_holdings(output.code, end_date)
            except Exception:
                output.holdings = []
        output.concepts = infer_concepts(output.name, output.holdings)
        output.provenance["holdings"] = FieldEvidence(
            source="东方财富基金持仓披露",
            as_of=end_date,
            status="ok" if output.holdings else "missing",
            confidence="medium" if output.holdings else "low",
            note="as_of 为抓取截止日；实际披露日以基金公告为准",
        )
        return output

    def cross_check(self, fund: FundSnapshot, start_date: str, end_date: str) -> FundSnapshot:
        output = fund.clone()
        end_day = _date_or_fallback(fund.nav_date, end_date)
        start_day = _shift_years(end_day, 1)
        points: list[tuple[date, float]] = []
        seen_dates: set[date] = set()
        for page_index in range(1, 21):
            params = {
                "fundCode": fund.code,
                "pageIndex": str(page_index),
                "pageSize": "20",
                "startDate": start_day.isoformat(),
                "endDate": end_day.isoformat(),
            }
            url = "https://api.fund.eastmoney.com/f10/lsjz?" + urllib.parse.urlencode(params)
            text = self.http.get_text(
                url,
                f"https://fund.eastmoney.com/{fund.code}.html",
                timeout=25,
            )
            page_points = parse_nav_api_json(text)
            if not page_points:
                break
            for day, value in page_points:
                if start_day <= day <= end_day and day not in seen_dates:
                    points.append((day, value))
                    seen_dates.add(day)
            if min(day for day, _ in page_points) <= start_day or len(page_points) < 20:
                break

        secondary = compute_max_drawdown(points)
        if secondary is None:
            raise RuntimeError(f"{fund.code} 分页历史净值不足 30 个有效点")
        primary = output.drawdown_primary if output.drawdown_primary is not None else output.drawdown
        check = merge_drawdown_checks(primary, secondary)
        output.drawdown = check.value
        output.drawdown_primary = primary
        output.drawdown_secondary = secondary
        output.data_conflict = check.conflict
        output.nav_points = max(output.nav_points, len(points))
        output.provenance["drawdown"] = FieldEvidence(
            source="东方财富净值曲线 + API 分页历史净值独立端点",
            as_of=end_date,
            status="conflict" if check.conflict else "ok",
            confidence=check.confidence,
            note=check.note,
        )
        output.provenance["drawdown_secondary"] = FieldEvidence(
            source="东方财富 API 分页历史净值端点",
            as_of=end_date,
            status="ok",
            confidence="high",
            note=f"一年窗口有效净值点 {len(points)} 个",
        )
        return output

    def _fetch_holdings(self, code: str, end_date: str) -> list[dict[str, str]]:
        year = end_date[:4]
        for kind in ("jjcc", "zqcc"):
            params = {"type": kind, "code": code, "topline": "10", "year": year, "month": ""}
            url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?" + urllib.parse.urlencode(params)
            try:
                text = self.http.get_text(
                    url,
                    f"https://fundf10.eastmoney.com/ccmx_{code}.html",
                    timeout=20,
                )
                rows = parse_holdings_table(text)
                if rows:
                    return rows[:10]
            except Exception:
                continue
        return []


class FixtureProvider:
    provider_name = "离线固定夹具"

    def __init__(self, fixture_path: Path) -> None:
        raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("fixture 顶层必须是基金数组")
        self._funds = [FundSnapshot.from_dict(item) for item in raw]
        for fund in self._funds:
            for field in fund.required_quality_fields():
                value = getattr(fund, field)
                fund.provenance.setdefault(
                    field,
                    FieldEvidence(
                        source=self.provider_name,
                        as_of=fund.nav_date,
                        status="ok" if value is not None and value != "" else "missing",
                        confidence="high" if value is not None and value != "" else "low",
                    ),
                )

    def fetch_universe(self, end_date: str) -> tuple[list[FundSnapshot], str]:
        start = (datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=365)).isoformat()
        return [fund.clone() for fund in self._funds], start

    def enrich(self, fund: FundSnapshot, start_date: str, end_date: str) -> FundSnapshot:
        return fund.clone()
