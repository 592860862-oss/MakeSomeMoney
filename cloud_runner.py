"""Cloud runner. No third-party Python dependencies; credentials only from secrets."""
import os,json,time,urllib.request,sys
from pathlib import Path
from work.fund_discovery_v2.pipeline import run_discovery,DiscoveryConfig
from work.fund_discovery_v2.providers import EastmoneyProvider

base=os.environ['PAGES_URL'].rstrip('/')
if not base.startswith('https://'): raise ValueError('PAGES_URL must use HTTPS')
job=os.environ['JOB_ID']
def api(action,payload):
    request=urllib.request.Request(base+'/api/runner/'+job+'/'+action,json.dumps(payload,ensure_ascii=False).encode(),{'Content-Type':'application/json','Accept':'application/json','User-Agent':'MakeSomeMoney-FundRunner/1.1','Authorization':'Bearer '+os.environ['RUNNER_SECRET']}
    with urllib.request.urlopen(request,timeout=60) as r:return json.load(r)

def progress(message):
    print(message,flush=True)
    try:api('progress',{'message':message})
    except Exception:print('Progress upload delayed',flush=True)

if __name__=='__main__':
    try:
        config=api('claim',{})
        result=run_discovery(EastmoneyProvider(cache_dir=Path('output/cache'),use_cache=False),DiscoveryConfig(end_date=config['date']),Path('output'),progress=progress)
        report=json.loads(result['report_paths']['json'].read_text(encoding='utf-8'))
        snapshot=json.loads(result['snapshot_path'].read_text(encoding='utf-8'))
        for attempt in range(3):
            try:api('complete',{'report':report,'snapshot':snapshot});break
            except Exception:
                if attempt==2:raise
                time.sleep(5)
        print('Report uploaded',flush=True)
    except Exception as exc:
        try:api('fail',{'message':'云端扫描未完成：'+type(exc).__name__+'；请查看 Actions 日志'})
        except Exception:pass
        raise
