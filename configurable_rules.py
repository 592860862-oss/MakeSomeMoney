"""Per-run rules. Original v2.5 modules are read-only dependencies."""
import json, math
from pathlib import Path
from datetime import date
from work.fund_discovery_v2.rules import LOCK_WORDS, preliminary_score, score_fund

SCHEMA = json.loads((Path(__file__).parent / 'conditions.json').read_text(encoding='utf-8'))
DEFAULTS = {x['key']: x['default'] for x in SCHEMA}

def validate_settings(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError('未知扫描条件')
    result = dict(DEFAULTS)
    for spec in SCHEMA:
        k = spec['key']; v = raw.get(k, spec['default'])
        if isinstance(spec['default'], bool):
            if not isinstance(v, bool): raise ValueError(k + ' 必须是布尔值')
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not spec['min'] <= v <= spec['max']:
            raise ValueError(k + ' 超出允许范围')
        elif spec['step'] == 1 and int(v) != v: raise ValueError(k + ' 必须是整数')
        result[k] = v
    if not result['watch_score'] <= result['confirm_score'] <= result['entry_score']:
        raise ValueError('观察评分 ≤ 确认评分 ≤ 试仓评分')
    if result['week_caution'] >= result['week_loss']:
        raise ValueError('周跌幅暂缓阈值应小于急跌阈值')
    if result['pullback_month_min'] > result['pullback_month_max']:
        raise ValueError('回踩月收益下限不能大于上限')
    return result

def light_reason(f, end, c):
    # Missing returns remain a data-quality gate, not an investment preference.
    if any(getattr(f,k) is None for k in ('r1w','r1m','r3m','r6m','r1y')):
        return '数据不足：评分需要完整周/月/季/半年/年收益，未将缺失视作零'
    for enabled,a,b in [('order_1m_3m','r1m','r3m'),('order_3m_6m','r3m','r6m'),('order_6m_1y','r6m','r1y')]:
        if c[enabled] and getattr(f,a) > getattr(f,b): return f'本次收益筛选未通过：{a} > {b}'
    if c['exclude_locked'] and any(w in f.name for w in LOCK_WORDS): return '存在锁定期或定开特征'
    if c['age_enabled']:
        try: age = (date.fromisoformat(end)-date.fromisoformat(f.establish_date)).days
        except (ValueError, TypeError): return '成立日期无法确认'
        if age < c['min_age_days']: return f"成立不足 {c['min_age_days']} 天"
    return ''

def decide(f, end, c):
    blockers = []; warnings = []; severe = False
    reason = light_reason(f,end,c)
    if reason: blockers.append(reason)
    if f.drawdown is None: blockers.append('一年最大回撤无法核验，不能可靠评分')
    elif c['dd_enabled'] and f.drawdown > c['max_dd']:
        blockers.append(f"一年最大回撤 {f.drawdown:.2f}% 超过本次上限 {c['max_dd']}%"); severe=True
    if c['trend_enabled'] and f.r3m is not None and f.r6m is not None and f.r3m <= 0 and f.r6m <= 0:
        blockers.append('近3月和近6月趋势均未转正')
    if c['week_enabled'] and f.r1w is not None and f.r1w <= -c['week_loss']:
        blockers.append(f"近一周跌幅超过本次阈值 {c['week_loss']}%"); severe=True
    if c['exclude_conflict'] and f.data_conflict:
        blockers.append('回撤数据端点冲突'); severe=True
    if any(getattr(f,k) is None for k in ('r1w','r1m','r3m','r6m')) or f.drawdown is None:
        f.score=None; f.score_components={}; f.score_notes=['关键数据缺失，不计算评分']
    else:
        # Keep a versioned benchmark formula; eligibility threshold is separate.
        score=score_fund(f); f.score=score.total; f.score_components=score.components
        f.score_notes=[n for n in score.notes if '统一 13%' not in n]
        f.score_notes += ['评分公式沿用V2.5；其中13%仅为风险评分基准，不是本次入池上限。']
    score=f.score or 0
    pullback = all(getattr(f,k) is not None for k in ('r1w','r1m','r3m','r6m')) and (
        ((f.r3m>=c['pullback_3m'] and f.r6m>=c['pullback_6m']) or f.r3m>=c['pullback_3m_strong'] or f.r6m>=c['pullback_6m_strong'])
        and c['pullback_month_min']<=f.r1m<=c['pullback_month_max'] and f.r1m < f.r3m-c['pullback_gap']
        and f.r1w>-c['week_loss'] and f.r3m>0 and f.r6m>0)
    f.opportunity_channel='强中期+短期回踩' if pullback else '自定义条件候选'
    f.eligibility_passed=not blockers; f.eligibility_blockers=blockers; f.eligibility_warnings=warnings
    level=2; reasons=blockers or ['综合评分未达到本次观察阈值']
    if severe: level=1
    elif not blockers:
        if f.confidence=='low':
            level=3 if score>=c['watch_score'] else 2; reasons=['置信度低，不给试仓信号']
        elif f.r1w<=-c['week_caution']:
            level=3 if pullback else 2; reasons=['短期快速回落，等待风险释放']
        elif pullback:
            level=4 if score>=c['pullback_score'] else 3; reasons=['强中期回踩结构，等待入场确认']
        elif score>=c['entry_score']:
            level=5; reasons=['满足本次资格、评分及入场条件']
            if f.drawdown_secondary is None or f.r1w>c['week_hot'] or f.r1m>c['month_hot'] or f.drawdown>c['entry_dd'] or f.r1w<0:
                level=4; reasons=['等待节奏或第二端点确认；评分高不等于立即买入']
        elif score>=c['confirm_score']: level=4; reasons=['达到本次趋势确认评分']
        elif score>=c['watch_score']: level=3; reasons=['达到本次观察评分']
    f.signal_level=level; f.signal={1:'回避',2:'暂不参与',3:'继续观察',4:'等待回踩或趋势确认',5:'可分批试仓'}[level]
    f.signal_reasons=reasons
    return f
