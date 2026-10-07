import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const old=root+'/legacy-ui';
let app=fs.readFileSync(old+'/app.js','utf8');
app=app.replace("key=sessionStorage.getItem('fund-key')||''","key=''");
const start=app.indexOf('async function api('),end=app.indexOf('\nfunction valid',start);
app=app.slice(0,start)+`async function api(route,body){const r=await fetch('/api/'+route,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok){if(r.status===401&&route!=='login')lock();throw Error(d.error||'服务请求失败')}return d}\n`+app.slice(end);
app=app.replace("if(!valid(x))throw Error('报告包含不符合永久收益规则的基金，已拒绝载入');",'');
app=app.replace('四周期收益硬规则：通过。','条件以该报告留存的扫描设置为准。');
app=app.replace('通过固定收益筛选','符合本报告筛选条件');
// Remove obsolete handlers, not only overwrite them at runtime.
app=app.split('\n').filter(line=>!line.startsWith("$('#settingsBtn').onclick=")&&!line.startsWith("$('#scanBtn').onclick=")&&!line.startsWith("$('#methodBtn').onclick=")&&!line.startsWith('function valid(')).join('\n');
app=app.slice(0,app.indexOf("fetch('sample.json')"))+fs.readFileSync(root+'/ui-extension.js','utf8');
// Disable buttons which need a report until a report is available.
app=app.replace("function load(r,id=null){","function load(r,id=null){$('#exportBtn').disabled=false;$('#emailBtn').disabled=false;");
fs.writeFileSync(root+'/site/app.js',app);
let html=fs.readFileSync(old+'/index.html','utf8').replace('</head><body>','<link rel="stylesheet" href="v2.css"></head><body class="locked"><div id="appShell" inert>');
html=html.replace('固定策略 discovery-v2.5','自定义策略 discovery-v3.0').replace('⚙　连接与设置','⚙　工作区设置').replace('<main><header>','<main><div class="topline"><span>澄观 / 基金研究工作区</span><span id="serviceStatus">安全访问 · 未登录</span><button id="logoutBtn">退出登录</button></div><header>');
html=html.replace('发现值得进一步研究的基金','让每一次选择，都有据可依').replace('＋ 发起全市场扫描','＋ 新建全市场扫描').replace('正在载入研究数据…','登录后加载你的研究报告');
html=html.replace('永久收益规则','可配置扫描策略').replace('近 1 月 ≤ 近 3 月 ≤ 近 6 月 ≤ 近 1 年','收益比较 · 风险边界 · 入场节奏').replace('近一年最大回撤上限 13%','每次扫描独立保存条件');
html=html.replace('id="exportBtn"','id="exportBtn" disabled').replace('id="emailBtn"','id="emailBtn" disabled');
html=html.replace('</main>','</main></div><section id="loginGate" class="login-gate"><form id="loginForm" class="login-card"><div class="login-emblem">◈</div><span class="eyebrow">PRIVATE RESEARCH WORKSPACE</span><h1>欢迎回到澄观</h1><p>连接你的基金研究工作区。<br>登录后查看报告、定制条件与发起扫描。</p><label for="loginPassword">工作区访问口令</label><input id="loginPassword" type="password" autocomplete="current-password" placeholder="请输入访问口令" required autofocus><button id="loginSubmit" class="primary" type="submit">安全进入研究台 →</button><p id="loginError" class="login-error" role="alert"></p><p>口令由 Cloudflare 服务端验证<br>登录前不会加载真实基金报告</p></form></section>');
fs.writeFileSync(root+'/site/index.html',html);
let worker=fs.readFileSync(root+'/server.mjs','utf8').replace("import schema from './conditions.json' with {type:'json'};",'const schema='+fs.readFileSync(root+'/conditions.json','utf8')+';');
fs.writeFileSync(root+'/site/_worker.js',worker);
if(fs.existsSync(root+'/backend'))fs.copyFileSync(root+'/conditions.json',root+'/backend/conditions.json');
console.log('Built V3 runtime / V2 light UI');
