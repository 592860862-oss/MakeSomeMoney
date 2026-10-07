const schema=[
 {"key":"order_1m_3m","label":"近1月收益 ≤ 近3月收益","group":"收益筛选","default":true},
 {"key":"order_3m_6m","label":"近3月收益 ≤ 近6月收益","group":"收益筛选","default":true},
 {"key":"order_6m_1y","label":"近6月收益 ≤ 近1年收益","group":"收益筛选","default":true},
 {"key":"exclude_locked","label":"排除锁定期、定开或封闭基金","group":"资格筛选","default":true},
 {"key":"age_enabled","label":"启用最低成立天数","group":"资格筛选","default":true},
 {"key":"min_age_days","label":"最低成立天数","group":"资格筛选","default":365,"min":0,"max":7300,"step":1},
 {"key":"dd_enabled","label":"启用近一年最大回撤上限","group":"风险筛选","default":true},
 {"key":"max_dd","label":"近一年最大回撤上限 %","group":"风险筛选","default":13,"min":1,"max":100,"step":0.1},
 {"key":"trend_enabled","label":"排除近3月与近6月收益均不为正","group":"风险筛选","default":true},
 {"key":"week_enabled","label":"启用近一周急跌排除","group":"风险筛选","default":true},
 {"key":"week_loss","label":"近一周急跌排除阈值 %（跌幅）","group":"风险筛选","default":8,"min":1,"max":50,"step":0.1},
 {"key":"exclude_conflict","label":"排除关键回撤数据冲突","group":"风险筛选","default":true},
 {"key":"deduplicate","label":"同一底层基金的不同份额去重","group":"结果组织","default":true},
 {"key":"concept_cap_enabled","label":"限制同一主题在各池的数量","group":"结果组织","default":true},
 {"key":"concept_cap","label":"每池同一主题最多只数","group":"结果组织","default":5,"min":1,"max":100,"step":1},
 {"key":"candidate_limit","label":"候选池最多只数","group":"结果组织","default":30,"min":1,"max":100,"step":1},
 {"key":"watch_limit","label":"观察池最多只数","group":"结果组织","default":20,"min":1,"max":100,"step":1},
 {"key":"pullback_limit","label":"回踩池最多只数","group":"结果组织","default":20,"min":1,"max":100,"step":1},
 {"key":"risk_sample_limit","label":"风险样本最多只数（非推荐）","group":"结果组织","default":20,"min":0,"max":100,"step":1},
 {"key":"rough_limit","label":"详情分析上限（非全市场基金总数）","group":"执行设置","default":1800,"min":50,"max":3000,"step":1},
 {"key":"cross_check_limit","label":"第二回撤端点核验上限","group":"执行设置","default":60,"min":0,"max":200,"step":1},
 {"key":"entry_score","label":"试仓信号最低评分","group":"信号阈值","default":82,"min":0,"max":100,"step":1},
 {"key":"confirm_score","label":"趋势确认信号最低评分","group":"信号阈值","default":72,"min":0,"max":100,"step":1},
 {"key":"watch_score","label":"观察信号最低评分","group":"信号阈值","default":60,"min":0,"max":100,"step":1},
 {"key":"week_caution","label":"周跌幅暂缓试仓阈值 %","group":"信号阈值","default":5,"min":0.1,"max":50,"step":0.1},
 {"key":"week_hot","label":"周涨幅过热阈值 %","group":"信号阈值","default":8,"min":0.1,"max":100,"step":0.1},
 {"key":"month_hot","label":"月涨幅过热阈值 %","group":"信号阈值","default":18,"min":0.1,"max":200,"step":0.1},
 {"key":"entry_dd","label":"直接试仓的近一年回撤上限 %","group":"信号阈值","default":10,"min":1,"max":100,"step":0.1},
 {"key":"pullback_score","label":"回踩确认最低评分","group":"回踩识别","default":58,"min":0,"max":100,"step":1},
 {"key":"pullback_3m","label":"中期强势：3月收益阈值 %","group":"回踩识别","default":10,"min":0,"max":200,"step":0.1},
 {"key":"pullback_6m","label":"中期强势：6月收益阈值 %","group":"回踩识别","default":15,"min":0,"max":300,"step":0.1},
 {"key":"pullback_3m_strong","label":"单独满足强势：3月收益 %","group":"回踩识别","default":20,"min":0,"max":300,"step":0.1},
 {"key":"pullback_6m_strong","label":"单独满足强势：6月收益 %","group":"回踩识别","default":25,"min":0,"max":400,"step":0.1},
 {"key":"pullback_month_max","label":"回踩月收益上限 %","group":"回踩识别","default":5,"min":-50,"max":50,"step":0.1},
 {"key":"pullback_gap","label":"3月与1月收益最小差值（百分点）","group":"回踩识别","default":3,"min":0,"max":100,"step":0.1},
 {"key":"pullback_month_min","label":"回踩月收益下限 %","group":"回踩识别","default":-30,"min":-100,"max":0,"step":0.1}
]
;
const defaults=Object.fromEntries(schema.map(s=>[s.key,s.default]));
const enc=new TextEncoder();
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json=(v,status=200,headers={})=>Response.json(v,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...headers}});
export function settings(raw={}){
 if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).some(k=>!(k in defaults)))throw Error('未知扫描条件');
 const c={...defaults,...raw};
 for(const s of schema){const v=c[s.key];if(typeof s.default==='boolean'){if(typeof v!=='boolean')throw Error(s.label+'格式无效')}else if(!Number.isFinite(v)||v<s.min||v>s.max||s.step===1&&!Number.isInteger(v))throw Error(s.label+'超出范围')}
 if(!(c.watch_score<=c.confirm_score&&c.confirm_score<=c.entry_score))throw Error('观察评分 ≤ 确认评分 ≤ 试仓评分');
 if(c.week_caution>=c.week_loss)throw Error('周跌幅暂缓阈值应小于急跌阈值');
 if(c.pullback_month_min>c.pullback_month_max)throw Error('回踩下限不能大于上限');
 return c;
}
async function equal(a,b){if(!a||!b)return false;const digest=async x=>new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(x)));const [x,y]=await Promise.all([digest(a),digest(b)]);return x.reduce((n,v,i)=>n|(v^y[i]),0)===0}
async function sign(value,password){const key=await crypto.subtle.importKey('raw',enc.encode(password),{name:'HMAC',hash:'SHA-256'},false,['sign']);return [...new Uint8Array(await crypto.subtle.sign('HMAC',key,enc.encode(value)))].map(x=>x.toString(16).padStart(2,'0')).join('')}
const cookie=(v,age)=>`fund_session=${v}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${age}`;
async function authorized(req,env){const v=req.headers.get('Cookie')?.match(/(?:^|;\s*)fund_session=([^;]+)/)?.[1];if(!v||!env.APP_PASSWORD)return false;const [expiry,nonce,mac]=v.split('.');if(!expiry||!nonce||!mac||Date.now()>Number(expiry))return false;return equal(mac,await sign(expiry+'.'+nonce,env.APP_PASSWORD))}
async function body(req,max=5_000_000){let n=0;const chunks=[];const reader=req.body?.getReader();if(!reader)return {};try{while(true){const r=await reader.read();if(r.done)break;n+=r.value.length;if(n>max){await reader.cancel();throw Error('请求过大')}chunks.push(r.value)}}finally{reader.releaseLock()}const data=new Uint8Array(n);let at=0;for(const b of chunks){data.set(b,at);at+=b.length}return JSON.parse(new TextDecoder().decode(data))}
export function validateReport(r,c){
 if(r?.rule_version!=='discovery-v3.0'||!r.stats||!Array.isArray(r.candidates))throw Error('报告版本不匹配');
 if(JSON.stringify(settings(r.scan_settings))!==JSON.stringify(c))throw Error('报告扫描条件与任务不匹配');
 let count=0;
 for(const pool of ['candidates','pullback_watch','watchlist','risk_samples','short_history_watch'])for(const f of r[pool]||[]){
  count++;if(!/^\d{6}$/.test(f.code))throw Error('基金代码无效');
  const v=f.returns||{};
  for(const [k,a,b] of [['order_1m_3m','r1m','r3m'],['order_3m_6m','r3m','r6m'],['order_6m_1y','r6m','r1y']])if(c[k]&&(!Number.isFinite(v[a])||!Number.isFinite(v[b])||v[a]>v[b]))throw Error('报告不符合本次收益筛选');
  if(!['可分批试仓','等待回踩或趋势确认','继续观察','暂不参与','回避'].includes(f.decision?.signal))throw Error('报告信号无效');
 }if(count>500)throw Error('报告数量过大');return r;
}
function conditionsHTML(c){return '<ul>'+schema.map(s=>`<li>${esc(s.label)}：${esc(typeof c[s.key]==='boolean'?(c[s.key]?'启用':'关闭'):c[s.key])}</li>`).join('')+'</ul>'}
function emailHTML(r){const pct=v=>Number.isFinite(v)?v.toFixed(2)+'%':'待核实';return `<h1>澄观 · 基金研究报告</h1><p>截止 ${esc(r.end_date)} · ${esc(r.rule_version)} · 全部按未持仓评估</p>`+[['candidates','建仓候选'],['pullback_watch','回踩观察'],['watchlist','观察池'],['risk_samples','风险样本（非推荐）']].map(([k,n])=>`<h2>${n}</h2><table border="1" cellpadding="7"><tr><th>基金 / 经理</th><th>近1年涨跌幅</th><th>1年最大回撤</th><th>3年最大回撤</th><th>成立以来最大回撤</th><th>信号</th></tr>${(r[k]||[]).map(f=>`<tr><td>${esc(f.name)} ${esc(f.code)}<br>${esc((f.manager_names||[]).join('/'))}</td><td>${pct(f.returns?.r1y)}</td>${['drawdown_1y','drawdown_3y','drawdown_since_inception'].map(k=>`<td>${pct(f.risk?.[k])}</td>`).join('')}<td>${esc(f.decision?.signal)}</td></tr>`).join('')}</table>`).join('')+'<h2>本次扫描条件</h2>'+conditionsHTML(r.scan_settings?settings(r.scan_settings):defaults)+'<p>数据不足不等于买点；历史收益与回撤不保证未来表现。评分公式与资格条件分开评估。</p>'}
async function sendEmail(env,id){
 if(!env.RESEND_API_KEY||!env.EMAIL_FROM||!env.EMAIL_TO)throw Error('邮件服务未配置');
 const db=env.FUND_DB, prior=await db.prepare('SELECT status FROM mail WHERE report_id=?').bind(id).first();
 if(prior?.status==='sent')return '该报告已发送，已阻止重复发送';
 if(prior?.status==='sending')throw Error('邮件发送结果待确认，请检查邮件服务记录');
 const obj=await env.FUND_REPORTS.get('reports/'+id+'.json');if(!obj)throw Error('报告不存在');
 const claim=await db.prepare("INSERT INTO mail(report_id,status,updated) VALUES (?,'sending',?) ON CONFLICT(report_id) DO UPDATE SET status='sending',updated=excluded.updated WHERE mail.status='failed'").bind(id,new Date().toISOString()).run();
 if(!claim.meta.changes)throw Error('邮件已在处理中');
 const r=await obj.json();
 const response=await fetch('https://api.resend.com/emails',{method:'POST',headers:{Authorization:'Bearer '+env.RESEND_API_KEY,'Content-Type':'application/json','Idempotency-Key':'fund-report/'+id},body:JSON.stringify({from:env.EMAIL_FROM,to:[env.EMAIL_TO],subject:`中短期基金研究报告（${r.end_date}）`,html:emailHTML(r)})});
 if(!response.ok){await response.body?.cancel();await db.prepare("UPDATE mail SET status='failed' WHERE report_id=?").bind(id).run();throw Error('邮件服务拒绝请求，状态码 '+response.status+'；检查发件域名、收件人限制和额度')}
 await response.body?.cancel();await db.prepare("UPDATE mail SET status='sent' WHERE report_id=?").bind(id).run();return '报告已提交邮件服务发送（不代表已进入收件箱）';
}
export default {async fetch(req,env){const url=new URL(req.url),route=url.pathname.slice(5);try{
 if(!url.pathname.startsWith('/api/')){
  const allow=['/','/index.html','/app.js','/style.css','/v2.css','/assets/wealth-light-v2.png'];
  if(!allow.includes(url.pathname))return new Response('Not found',{status:404});
  const res=await env.ASSETS.fetch(req);const h=new Headers(res.headers);h.set('X-Content-Type-Options','nosniff');h.set('Referrer-Policy','same-origin');h.set('Content-Security-Policy',"default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");h.set('Cache-Control','no-cache');return new Response(res.body,{status:res.status,headers:h});
 }
 if(req.method==='POST'&&req.headers.get('Origin')&&req.headers.get('Origin')!==url.origin)return json({error:'来源不允许'},403);
 if(!env.FUND_DB||!env.FUND_REPORTS)return json({error:'存储绑定未配置'},503);
 const db=env.FUND_DB;
 if(route==='login'&&req.method==='POST'){
  const ip=req.headers.get('CF-Connecting-IP')||'local', bucket=Math.floor(Date.now()/600000),hash=await sign(ip,env.APP_PASSWORD||'not-configured');
  const attempt=await db.prepare('INSERT INTO auth_limits(k,n) VALUES (?,1) ON CONFLICT(k) DO UPDATE SET n=n+1 RETURNING n').bind(bucket+':'+hash).first();
  if(attempt.n>10)return json({error:'尝试过于频繁，请10分钟后重试'},429);
  const b=await body(req,2048);if(!await equal(b.password,env.APP_PASSWORD))return json({error:'访问口令不正确'},401);
  const v=(Date.now()+8*3600000)+'.'+crypto.randomUUID();await db.prepare('DELETE FROM auth_limits WHERE k < ?').bind((bucket-1)+':').run();
  return json({ok:true},200,{'Set-Cookie':cookie(v+'.'+await sign(v,env.APP_PASSWORD),28800)});
 }
 if(route==='logout'&&req.method==='POST')return json({ok:true},200,{'Set-Cookie':cookie('',0)});
 const runner=route.startsWith('runner/');
 if(runner?!await equal(req.headers.get('Authorization')?.replace(/^Bearer /,''),env.RUNNER_SECRET):!await authorized(req,env))return json({error:'请先登录研究台'},401);
 if(route==='status')return json({database:true,scanner:!!(env.GITHUB_TOKEN&&env.GITHUB_REPO),email:!!(env.RESEND_API_KEY&&env.EMAIL_FROM&&env.EMAIL_TO),version:'3.0'});
 if(route==='conditions')return json(schema);
 if(route==='reports'&&req.method==='GET')return json((await db.prepare('SELECT * FROM reports ORDER BY created DESC LIMIT 100').all()).results);
 if(route.startsWith('reports/')&&req.method==='GET'){const id=route.split('/')[1];if(!/^[\w-]{1,80}$/.test(id))throw Error('编号无效');const obj=await env.FUND_REPORTS.get('reports/'+id+'.json');return obj?new Response(obj.body,{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):json({error:'报告不存在'},404)}
 if(route.startsWith('jobs/')&&req.method==='GET'){
  const j=await db.prepare('SELECT * FROM jobs WHERE id=?').bind(route.split('/')[1]).first();if(!j)return json({error:'任务不存在'},404);
  if(['queued','running'].includes(j.status)&&Date.now()-Date.parse(j.created)>55*60000){await db.prepare("UPDATE jobs SET status='failed',message='任务超时，请查看GitHub日志' WHERE id=?").bind(j.id).run();j.status='failed';j.message='任务超时，请查看GitHub日志'}return json(j);
 }
 if(req.method!=='POST')return json({error:'接口不存在'},404);
 const b=await body(req);
 if(route==='jobs'){
  const c=settings(b.settings),today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
  if(!/^\d{4}-\d{2}-\d{2}$/.test(b.date)||b.date>today||new Date(b.date).toISOString().slice(0,10)!==b.date)throw Error('日期无效');
  if(!/^[-\w.]+\/[-\w.]+$/.test(env.GITHUB_REPO||'')||!env.GITHUB_TOKEN)throw Error('GitHub未配置');
  await db.prepare("UPDATE jobs SET status='failed',message='任务超时' WHERE status IN ('queued','running') AND created < ?").bind(new Date(Date.now()-55*60000).toISOString()).run();
  const id=crypto.randomUUID();try{await db.batch([db.prepare("INSERT INTO jobs(id,date,status,message,created,auto_email) VALUES (?,?,'queued','等待GitHub启动',?,?)").bind(id,b.date,new Date().toISOString(),b.email===true?1:0),db.prepare('INSERT INTO job_settings(id,settings) VALUES (?,?)').bind(id,JSON.stringify(c))])}catch{return json({error:'已有任务正在运行，请勿重复启动'},409)}
  try{const r=await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/scan-v3.yml/dispatches`,{method:'POST',headers:{Authorization:'Bearer '+env.GITHUB_TOKEN,Accept:'application/vnd.github+json','User-Agent':'FundObservatory/3','Content-Type':'application/json'},body:JSON.stringify({ref:env.GITHUB_REF||'main',inputs:{job_id:id}})});await r.body?.cancel();if(!r.ok)throw Error('GitHub启动失败（'+r.status+'），请核对scan-v3.yml及权限')}catch(e){await db.prepare("UPDATE jobs SET status='failed',message=? WHERE id=?").bind(e.message,id).run();throw e}return json({id},202);
 }
 if(route==='email')return json({message:await sendEmail(env,b.reportId)});
 if(runner){const [,id,action]=route.split('/');const j=await db.prepare('SELECT * FROM jobs WHERE id=?').bind(id).first();if(!j)return json({error:'任务不存在'},404);const cfg=await db.prepare('SELECT settings FROM job_settings WHERE id=?').bind(id).first();if(!cfg)throw Error('旧任务请使用旧部署完成');const c=settings(JSON.parse(cfg.settings));
  if(action==='claim'){const claim=await db.prepare("UPDATE jobs SET status='running',message='已认领，正在扫描' WHERE id=? AND status='queued'").bind(id).run();if(!claim.meta.changes)return json({error:'任务已被执行'},409);return json({...j,settings:c,engine:'v3'})}
  if(action==='progress'){await db.prepare("UPDATE jobs SET message=? WHERE id=? AND status='running'").bind(String(b.message).slice(0,500),id).run();return json({ok:true})}
  if(action==='fail'){await db.prepare("UPDATE jobs SET status='failed',message=? WHERE id=? AND status IN ('queued','running')").bind(String(b.message).slice(0,500),id).run();return json({ok:true})}
  if(action==='complete'){if(j.status==='completed')return json({ok:true,email:j.email_status});if(j.status!=='running')throw Error('任务状态无效');const report=validateReport(b.report,c);if(report.end_date!==j.date)throw Error('报告日期不匹配');await env.FUND_REPORTS.put('reports/'+id+'.json',JSON.stringify(report));if(b.snapshot)await env.FUND_REPORTS.put('snapshots/'+id+'.json',JSON.stringify(b.snapshot));await db.prepare('INSERT OR IGNORE INTO reports(id,date,created) VALUES (?,?,?)').bind(id,j.date,new Date().toISOString()).run();let email='未请求';if(j.auto_email)try{email=await sendEmail(env,id)}catch(e){email=e.message}await db.prepare("UPDATE jobs SET status='completed',message='报告已生成',email_status=? WHERE id=?").bind(email,id).run();return json({ok:true,email})}
 }
 return json({error:'接口不存在'},404);
 }catch(e){return json({error:e.message||'服务异常'},400)}}};
