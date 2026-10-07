# 澄观浅色研究台 / 自定义扫描 V3

## 本版变化
暖白、浅灰绿和少量香槟金；登录前虚化外壳，不请求真实报告；8小时 HttpOnly 会话；退出清除页面报告；登录限流；修改 APP_PASSWORD 后旧会话失效。

扫描表单的三个收益比较条件均可单独关闭，也可全部关闭。资格过滤、评分、交易信号分离。所有扫描条件写入任务、报告、邮件，历史报告不随新表单变化。缺失收益不是负收益，也不作为零参与评分；数据可靠性保障不提供关闭开关。评分仍使用版本化 V2.5 公式，其13%风险评分基准不等于自定义资格上限。

## 发布顺序（保留旧文件）
1. 先确认旧任务已结束。在 GitHub main 添加 cloud_runner_v3.py、configurable_rules.py、conditions.json、test_configurable.py、.github/workflows/scan-v3.yml。不要改旧 scan.yml/cloud_runner.py/work 目录。
2. Cloudflare → Storage & Databases → D1 → FUND_DB 对应数据库 → Console，执行 migration.sql 两条 CREATE TABLE IF NOT EXISTS；不删除旧表。
3. Workers & Pages → makesomemoney → Settings → Bindings：保留 FUND_DB (D1)、FUND_REPORTS (R2)。保留现有 RUNNER_SECRET、GITHUB_TOKEN、RESEND_API_KEY 和邮箱设置。
4. 在 makesomemoney → Settings → Variables and Secrets → Production，添加或编辑 APP_PASSWORD，类型选 Secret。由你自行输入新口令并保存，切勿发到聊天或写进 GitHub。变量名称必须完全一致。
5. 创建新的生产部署，上传 site 文件夹内容（index.html 必须在压缩包根目录），包含 _worker.js、app.js、style.css、v2.css、assets/wealth-light-v2.png。不上传 sample.json、测试工具、backend 或密钥。
6. 用无痕窗口检查登录前看不清页面、不能读 /api/reports；正确口令登录后修改条件并发起扫描。确认 GitHub Fund discovery V3 成功；检查网页报告的条件快照和邮件状态。

以后修改口令：重复第4步，再创建新生产部署。已经生成的旧部署可能仍可从其专用地址访问，应由 Cloudflare Access 或删除不再需要的预览部署另行控制；不要把生产口令用于公开分享。

## 回退
Cloudflare 的 Deployments 中选择升级前的成功生产部署 → Rollback。旧入口 scan.yml/cloud_runner.py 原样保留；新增数据库表可保留，不影响旧版。回退到旧版也会恢复旧版登录方式和固定条件，需知悉其保护较弱。

## 已验证与待验证
本地 Python 5项规则单元测试通过；Node 模拟 D1/R2 测试通过登录、会话轮换、跨站请求拒绝、可选条件传递、任务锁、回调、报告和重复发信保护；网页实际点击验证登录、三个比较开关全部取消和13→20回撤值修改。外部 GitHub/Resend 在本地测试中为模拟，不代表生产部署或邮件送达。

## 美术资产
使用内置图片生成工具制作 wealth-light-v2.png：浅色专业基金研究台横幅，暖白留白、右侧半透明浅鼠尾草绿玻璃曲线及少量香槟金细线，无文字。此前 imagegen2 因缺少本地 API 配置，已按用户同意改用内置生成。
