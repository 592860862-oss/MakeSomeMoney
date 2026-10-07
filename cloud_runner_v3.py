"""Configurable discovery; original modules remain available for rollback."""
import json, os, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from configurable_rules import validate_settings, light_reason, decide, preliminary_score
from work.fund_discovery_v2.providers import EastmoneyProvider
from work.fund_discovery_v2.identity import deduplicate_share_classes
from work.fund_discovery_v2.history import write_snapshot, rolling_validation

def run(provider, end, settings, progress=print):
    c=validate_settings(settings); rejects=Counter(); start_time=datetime.now(timezone.utc).isoformat()
    universe,start=provider.fetch_universe(end)
    if not universe: raise RuntimeError('数据源未返回基金')
    prelim=[]
    for f in universe:
        reason=light_reason(f,end,c)
        if reason: rejects[reason]+=1
        else: f.prelim_score=preliminary_score(f); prelim.append(f)
    rough=sorted(prelim,key=lambda f:(-f.prelim_score,f.code))[:int(c['rough_limit'])]
    progress(f'原始基金 {len(universe)}；通过预筛 {len(prelim)}；详情分析 {len(rough)}')
    detailed=[]; failures=0
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures=[pool.submit(provider.enrich,f,start,end) for f in rough]
        for n,future in enumerate(as_completed(futures),1):
            try: detailed.append(decide(future.result(),end,c))
            except Exception as e: failures+=1; rejects['详情失败：'+type(e).__name__]+=1
            if n%100==0: progress(f'详情进度 {n}/{len(rough)}')
    if rough and not detailed: raise RuntimeError('全部详情请求失败，不能发布空报告')
    funds=deduplicate_share_classes(detailed) if c['deduplicate'] else detailed
    cross=getattr(provider,'cross_check',None); checked=0
    if callable(cross):
        targets=sorted([f for f in funds if f.eligibility_passed],key=lambda f:-(f.score or 0))[:int(c['cross_check_limit'])]
        for f in targets:
            try:
                enriched=decide(cross(f,start,end),end,c)
                funds=[enriched if x.code==f.code else x for x in funds]; checked+=1
            except Exception as e: rejects['第二端点核验失败：'+type(e).__name__]+=1
    for f in funds: rejects.update(f.eligibility_blockers)
    selected=set()
    def collect(predicate,limit):
        chosen=[]; counts=Counter()
        for f in sorted(funds,key=lambda f:(-f.signal_level,-(f.score or 0),f.code)):
            if len(chosen)>=limit: break
            theme=f.concepts[0] if f.concepts else f.fund_type
            if f.code in selected or not predicate(f): continue
            if c['concept_cap_enabled'] and counts[theme]>=c['concept_cap']: continue
            chosen.append(f); selected.add(f.code); counts[theme]+=1
        return chosen
    candidates=collect(lambda f:f.eligibility_passed and f.opportunity_channel!='强中期+短期回踩' and f.signal_level>=4,c['candidate_limit'])
    pullback=collect(lambda f:f.eligibility_passed and f.opportunity_channel=='强中期+短期回踩' and f.signal_level>=3,c['pullback_limit'])
    watch=collect(lambda f:f.eligibility_passed and f.signal_level==3,c['watch_limit'])
    risk=collect(lambda f:f.signal_level<=2,c['risk_sample_limit'])
    history=Path('output/history-v3'); history.mkdir(parents=True,exist_ok=True)
    snapshot={'schema_version':'3.0','rule_version':'discovery-v3.0','snapshot_date':end,'provider':provider.provider_name,'scan_settings':c,'funds':[f.to_dict() for f in candidates+pullback+watch]}
    validation=rolling_validation(history,end,{f.code:f.acc_nav if f.acc_nav is not None else f.nav for f in funds if f.nav is not None},provider=provider.provider_name)
    write_snapshot(history,snapshot)
    report={'schema_version':'3.0','rule_version':'discovery-v3.0','end_date':end,'created_at':start_time,'provider':provider.provider_name,'scan_settings':c,'stats':{'universe':len(universe),'preliminary':len(prelim),'evaluated':len(detailed),'deduplicated':len(funds),'detail_failures':failures,'cross_checked':checked,'candidates':len(candidates),'pullback_watch':len(pullback),'watchlist':len(watch)},'reject_summary':dict(rejects),'validation':validation,'short_history_watch':[]}
    for key,items in [('candidates',candidates),('pullback_watch',pullback),('watchlist',watch),('risk_samples',risk)]:report[key]=[f.to_dict() for f in items]
    Path('output/report-v3.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    return report,snapshot

def main():
    base=os.environ['PAGES_URL'].rstrip('/'); job=os.environ['JOB_ID']
    if not base.startswith('https://'):raise ValueError('HTTPS required')
    def api(action,payload):
        req=urllib.request.Request(base+'/api/runner/'+job+'/'+action,json.dumps(payload,ensure_ascii=False).encode(),{'Content-Type':'application/json','Accept':'application/json','User-Agent':'MakeSomeMoney-FundRunner/3.0','Authorization':'Bearer '+os.environ['RUNNER_SECRET']})
        with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)
    def progress(msg):
        print(msg,flush=True)
        try:api('progress',{'message':msg})
        except Exception:print('Progress callback delayed',flush=True)
    try:
        job_data=api('claim',{})
        if job_data.get('engine')!='v3':raise ValueError('Frontend/backend versions differ')
        report,snapshot=run(EastmoneyProvider(cache_dir=Path('output/cache'),use_cache=False),job_data['date'],job_data.get('settings'),progress)
        for attempt in range(3):
            try: result=api('complete',{'report':report,'snapshot':snapshot});break
            except Exception:
                if attempt==2:raise
                time.sleep(5)
        print('Report uploaded; email status:',result.get('email'),flush=True)
    except Exception as e:
        try:api('fail',{'message':'扫描失败：'+type(e).__name__+'；请查看GitHub日志'})
        except Exception:pass
        raise
if __name__=='__main__':main()
