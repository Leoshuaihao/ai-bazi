# AI 八字排盘 — 安全与体验修复 PRD

**文档版本**: 1.0  
**撰写日期**: 2026-07-18  
**撰写人**: 析客（Specky，需求分析师）  
**所属团队**: product-bazi-fix  
**产物状态**: 待评审

---

## 文档简介

本 PRD 基于三份研究报告（用户洞察、竞品扫描、指标仪表盘）撰写，针对 ai-bazi 项目当前被确认的安全漏洞和体验断点，定义修复范围、验收标准和执行时间线。文档面向工程团队和管理决策者，提供可落地的修复计划和明确的 Non-goals 边界。

---

## 1. 产品目标

三个清晰、正交的目标，按依赖关系排序：

| # | 目标 | 定义 | 成功衡量标准 | 对应来源 |
|---|------|------|-------------|----------|
| **G1** | **安全底线达标** | 消除所有一票否决级安全漏洞，使平台具备面向真实用户开放的基本信任条件 | P0/P1 安全漏洞清零；6 项安全 Headers 到位；CORS 白名单生效；JWT 随机密钥生效 | 安全报告 P0-1/2, P1-3/4/5/6；竞品扫描 §5.1 |
| **G2** | **核心流程可用** | 确保新用户在首次访问时能完成"排盘"这一最小闭环任务，注册/登录流程可走通 | 日期选择器正常可见可操作（Playwright 自动化验证）；真实验证码可送达手机号 | UX 报告 §2；用户洞察 §一 P0-Blokers |
| **G3** | **移动端可触达** | 消除移动端 UI 阻断问题，保证 390px 视口下核心交互元素完整可见可点击 | 移动端按钮可见率从 18.9% 提升至 ≥80%；文字溢出元素从 15 个降至 0 | UX 报告 §6；指标仪表盘 §2.1 |

> 三个目标的相互关系：G1 是 G2/G3 的前提（不安全的产品不该向用户开放）；G2 是激活/转化的基础；G3 支撑从社交渠道获取的用户增长。

---

## 2. 用户故事

### 故事 A：新用户首次排盘（对应 G1+G2）

**小王**在朋友圈看到朋友分享的"AI 八字排盘"链接，好奇点开。他不需要注册就能看到页面，点击「填入示例」按钮一键填充了示例信息，然后顺利点击日期选择器，选了 1990 年 6 月 15 日，点「开始排盘」。系统很快生成了完整的八字命盘——包括四柱、十神、用神和 AI 分析。小王觉得分析有道理，想注册账号保存命盘，输入手机号后真的收到了一条 6 位验证码短信，输入后成功登录。

**前后对比**:
- 修复前：日期选择器不可见 → 小王在 30 秒内离开
- 修复后：完整闭环可在 3 分钟内走完，且小王感知到安全性（HSTS 锁图标可见）

### 故事 B：移动端访问用户完成排盘（对应 G3）

**小陈**在手机上刷到八字排盘的推荐，用手机打开。页面正常加载，没有文字溢出、没有横向滚动条。大字号的出生日期选择按钮清晰可见，"填入示例"按钮也在屏幕内。小陈点击按钮，弹出滚轮日期选择器，选好日期和时间后点击确认。排盘结果以手机友好的单列卡片布局呈现，核心信息（四柱、用神）默认展开，详细内容可折叠查看。

**前后对比**:
- 修复前：15 个元素溢出，37 个按钮仅 7 个可见可点 → 放弃
- 修复后：按钮可见率 ≥80%，核心流程无阻塞

### 故事 C：安全漏洞修复后的用户信任感知（对应 G1）

**小李**是技术背景用户，再次访问 ai-bazi 时用浏览器开发者工具查看网络请求。他注意到：
- 地址栏出现🔒锁图标（HSTS 生效）
- 响应头中有 `X-Frame-Options: DENY` 和 `Content-Security-Policy`
- 尝试用 `https://evil.com` 做 Origin 跨域访问被拒绝
- 尝试 `990204` 万能验证码登录 → 失败（万能码已移除）

小李在技术社区发帖："ai-bazi 的安全配置比上次好了不少，基本防护都做起来了。"这种正向口碑对技术敏感的用户群体至关重要。

### 故事 D：老用户复访体验（对应 G2 延伸）

**老赵**上个月排过一次盘，今天来看看流年运势更新。页面打开速度比之前快（从 3.2s → <2s），上次排盘时保存的信息还在（基于账号）。他直接点击「流年预测」，系统利用缓存快速返回结果。AI 分析不再用全屏等待，而是逐步（SSE 流式）显示分析内容，感知等待感明显降低。

---

## 3. 需求池

### 优先级定义

| 优先级 | 定义 | 上线条件 |
|--------|------|----------|
| **P0** | 一票否决：不修复则不可面向任何用户开放 | 灰度/内测上线前必须完成 |
| **P1** | 上线阻塞：不修复则不可正式发布 | 正式上线前必须完成 |
| **P2** | 高优先级：上线后首月必须完成 | 首个迭代 Sprint 内完成 |

### P0 — 一票否决项（Wave 0，~3h）

| 编号 | 需求 | 优先级 | 验收标准 | 文件定位 | 预估工作量 |
|------|------|--------|----------|----------|------------|
| **REQ-P0-01** | **删除万能验证码 `990204`** | P0 | (1) 向 `/api/auth/login` 发送 `{"phone":"任意","code":"990204"}` 返回 400 错误；(2) 全局搜索 `990204` 无残留 | `api/routes/auth.py:47`（login 函数内 `is_dev_master` 逻辑）；关联行 55-71（dev 权限自动分配逻辑一并移除） | 0.5h |
| **REQ-P0-02** | **删除 dev-code 端点** | P0 | (1) `GET /api/auth/dev-code/{phone}` 返回 404；(2) 路由注册代码已完全移除 | `api/routes/auth.py:83-96`（`get_dev_code` 函数及 `@router.get("/dev-code/{phone}")` 装饰器） | 0.5h |
| **REQ-P0-03** | **修复 CORS allow_origins** | P0 | (1) `curl -H "Origin: https://evil.com" -I <站点>/api/health` 不返回 `Access-Control-Allow-Origin` 或返回值为白名单域名；(2) 生产环境白名单至少包含 `https://ai-bazi-production.up.railway.app` | `main.py:73-79`（`CORSMiddleware` 配置，`allow_origins=["*"]` → 限定为环境变量 `ALLOWED_ORIGINS` 列表，默认仅包含本站域名） | 0.5h |
| **REQ-P0-04** | **设置 JWT_SECRET 随机密钥** | P0 | (1) 代码中不存在 `dev-secret-change-in-production` 常量；(2) `JWT_SECRET` 环境变量未设置时，服务启动失败并打印明确错误信息；(3) 生产环境已部署随机 256-bit 密钥 | `services/auth.py:11`（`JWT_SECRET = os.getenv("JWT_SECRET", "...")` → `os.getenv("JWT_SECRET")` 无默认值，None 时抛异常） | 0.5h |
| **REQ-P0-05** | **修复日期选择器可见性** | P0 | (1) Playwright headless Chromium 测试中 `#birth-datetime-trigger` 元素 `isVisible()` 为 `true`；(2) 点击后日期滚轮面板正常弹出；(3) 选择日期后 label 正确更新 | `public/index.html`（`#birth-datetime-trigger` 元素及 `openDP` 函数）；`public/bazi.css`（排查 z-index/CSS 定位问题，`.date-btn` 样式及 `.date-picker-panel` 面板显示逻辑） | 2h |

### P1 — 上线前必须修复（Wave 1，~18h）

| 编号 | 需求 | 优先级 | 验收标准 | 文件定位 | 预估工作量 |
|------|------|--------|----------|----------|------------|
| **REQ-P1-01** | **集成真实短信发送服务** | P1 | (1) 用户调用 `/api/auth/send-code` 后手机号收到真实 6 位数字验证码；(2) 验证码 5 分钟内有效；(3) 60 秒内重复请求返回 cooldown 错误；(4) 日志中不记录完整手机号 | `services/auth.py:23-30`（`send_sms` 函数，替换 `print()` 为阿里云 SMS SDK / 腾讯云 SMS SDK 调用）；`api/routes/auth.py:24-41`（send_code 路由验证） | 16h |
| **REQ-P1-02** | **添加 6 项安全响应头** | P1 | (1) 所有 HTML/API 响应均包含以下 Header：`Strict-Transport-Security: max-age=31536000; includeSubDomains`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Content-Security-Policy: default-src 'self'`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy: camera=(), microphone=(), geolocation=()`；(2) `curl -I <站点>` 验证 6 项全部存在 | `main.py`（新增 `SecurityHeadersMiddleware` 中间件，在 `CORSMiddleware` 之后注册）；`nginx.conf`（如部署 nginx 反代则在此添加） | 1h |
| **REQ-P1-03** | **升级 PyJWT 至 2.13.0+** | P1 | (1) `pip list \| grep PyJWT` 版本 ≥ 2.13.0；(2) 全量测试通过（登录/Token 验证无回归）；(3) CVE 扫描结果清零 | `requirements.txt`（`PyJWT` 依赖版本号升级）；`services/auth.py`（`jwt.decode` 调用确认 API 兼容，2.13.0 强制要求 `algorithms` 参数） | 1h |

### P2 — 上线后首月迭代（Wave 2，~24h）

| 编号 | 需求 | 优先级 | 验收标准 | 文件定位 | 预估工作量 |
|------|------|--------|----------|----------|------------|
| **REQ-P2-01** | **修复移动端 15 个文字溢出** | P2 | (1) Playwright 390px 视口中 `text-overflow` 检查 0 个溢出元素；(2) 每个卡片/标签文字完整可读无截断 | `public/bazi.css`（在 `@media (max-width: 480px)` 规则块中为溢出容器添加 `overflow-wrap: break-word; word-break: break-all; hyphens: auto`，必要时调整 `font-size` 和 `padding`） | 4h |
| **REQ-P2-02** | **提升移动端按钮可见率（18.9% → ≥80%）** | P2 | (1) Playwright 390px 视口中至少 30/37 个按钮可见可点击（≥80%）；(2) 核心按钮（排盘、示例填充、发送、确认）100% 可见 | `public/bazi.css`（调整 `@media (max-width: 480px)` 内按钮 `display` 策略：关键按钮始终可见，次要按钮放入折叠菜单；调整 button 的 `min-width` 和 `padding`） | 4h |
| **REQ-P2-03** | **添加前端表单验证** | P2 | (1) 出生日期/时间/城市/性别在提交前均有即时校验；(2) 无效输入时字段边框变红 + 下方显示中文错误提示（如"月份范围：1-12"）；(3) 缺少必填字段时「开始排盘」按钮置灰不可点击 | `public/index.html`（为关键表单字段添加 `input` / `change` 事件监听器，在 `handleChartSubmit` 函数之前插入 `validateForm()` 校验函数） | 3h |
| **REQ-P2-04** | **隐藏服务器版本信息** | P2 | (1) `curl -I <站点>` 不返回 `Server: uvicorn`；(2) 不返回 Python/框架版本信息 | `main.py`（FastAPI app 初始化时设置 `app.root_path`；或自定义 `server` 响应头为通用值）；`nginx.conf`（添加 `server_tokens off`） | 0.5h |
| **REQ-P2-05** | **简化 API 错误信息** | P2 | (1) 所有 4xx/5xx 错误返回统一 JSON 格式 `{"detail": "请求参数有误，请检查后重试"}`；(2) 不再暴露 Pydantic ValidationError 的详细路径和类型信息 | `main.py`（添加全局异常处理器 `@app.exception_handler(ValidationError)` 和 `@app.exception_handler(HTTPException)`，生产环境隐藏详细错误，或通过环境变量 `DEBUG` 控制） | 1h |
| **REQ-P2-06** | **添加基础 ARIA 标签（≥20 个）** | P2 | (1) 使用 axe-core 扫描，ARIA 标签数 ≥ 20；(2) 关键交互元素（按钮、输入框、选择器）均有 `aria-label` 或 `<label>` 关联 | `public/index.html`（为表单字段添加 `<label for="...">`、为按钮添加 `aria-label`、为动态内容区添加 `aria-live` 区域） | 3h |
| **REQ-P2-07** | **信息层级优化：核心卡片默认展开 + 细节可折叠** | P2 | (1) 排盘结果区域拆分：核心信息（四柱、用神、五行力量、一句话总结）默认展开；细节信息（藏干、大运详表、古籍引用）默认折叠，点击展开；(2) 首屏卡片数量从 58 → < 15 | `public/index.html`（为结果卡片添加 `<details>/<summary>` 折叠组件或自定义 accordion 逻辑）；`public/bazi.css`（折叠面板样式） | 4h |
| **REQ-P2-08** | **添加基本缓存策略** | P2 | (1) 静态资源（CSS/JS/图片）响应头含 `Cache-Control: public, max-age=86400`；(2) `GET /api/chart` 幂等接口对相同参数 1 小时内结果添加 `Cache-Control: private, max-age=3600` | `main.py`（添加 `CacheControlMiddleware` 中间件，按 URL 路径前缀区分缓策略）；`nginx.conf`（静态资源缓存配置） | 4h |

---

## 4. 关键依赖关系与执行顺序

```
                    ┌─────────────────────────┐
                    │  REQ-P1-01: 集成真实SMS  │ ← 前置依赖
                    │        (16h)             │
                    └──────────┬──────────────┘
                               │ SMS 可用后
                    ┌──────────▼──────────────┐
          ┌─────────┤  REQ-P0-01: 删除万能验证码│← 必须在 SMS 可用后才能删
          │         │  REQ-P0-02: 删除dev端点   │
          │         └─────────────────────────┘
          │
          │  ┌─────────────────────────┐
          ├──┤  REQ-P0-03: 修复CORS     │← 无依赖，可并行
          │  └─────────────────────────┘
          │
          │  ┌─────────────────────────┐
          ├──┤  REQ-P0-04: 设置JWT密钥   │← 无依赖，可并行
          │  └─────────────────────────┘
          │
          │  ┌─────────────────────────┐
          └──┤  REQ-P0-05: 修复日期选择器 │← 无依赖，可并行
             └─────────────────────────┘

                               │ P0 全部完成后
                    ┌──────────▼──────────────┐
                    │  REQ-P1-02: 安全Headers   │
                    │  REQ-P1-03: 升级PyJWT     │
                    │  以上两个无依赖，可并行    │
                    └──────────┬──────────────┘
                               │ 正式上线
                    ┌──────────▼──────────────┐
                    │  P2 各项: 首月迭代       │
                    │  P2-01~08 内部无强依赖    │
                    │  可并行推进               │
                    └─────────────────────────┘
```

---

## 5. 修改文件清单

### Wave 0（P0，~3h）— 改动文件

| 文件路径 | 修改类型 | 对应需求 | 修改说明 |
|----------|----------|----------|----------|
| `api/routes/auth.py` | 删除代码 | REQ-P0-01, REQ-P0-02 | 删除第 44-80 行万能验证码逻辑（`is_dev_master` 分支 + dev 权限/积分自动分配）；删除第 83-96 行 `get_dev_code` 端点 |
| `main.py` | 修改配置 | REQ-P0-03 | 将 `allow_origins=["*"]` 改为读取环境变量，默认仅包含本站域名 |
| `services/auth.py` | 修改配置 | REQ-P0-04 | 将 `JWT_SECRET` 默认值删除，无环境变量时启动抛异常 |
| `public/index.html` | 修改 CSS/JS | REQ-P0-05 | 排查 `#birth-datetime-trigger` 按钮的 visibility/display/z-index 问题 |
| `public/bazi.css` | 修改 CSS | REQ-P0-05 | 修复日期选择器按钮及弹窗的 CSS 层级和定位 |

### Wave 1（P1，~18h）— 改动文件

| 文件路径 | 修改类型 | 对应需求 | 修改说明 |
|----------|----------|----------|----------|
| `services/auth.py` | 重写函数 | REQ-P1-01 | 替换 `send_sms()` 为真实 SDK 调用（阿里云/腾讯云 SMS） |
| `requirements.txt` | 新增依赖 | REQ-P1-01 | 添加 SMS SDK 依赖（如 `dysmsapi20170525` 或 `tencentcloud-sdk-python`） |
| `.env.example` / `.env` | 新增配置项 | REQ-P1-01 | 添加 `SMS_ACCESS_KEY_ID`、`SMS_ACCESS_KEY_SECRET`、`SMS_SIGN_NAME`、`SMS_TEMPLATE_CODE` |
| `api/routes/auth.py` | 删除代码 | REQ-P0-01, REQ-P0-02 | Wave 0 改动确认（如果 Wave 0 未部署） |
| `main.py` | 新增中间件 | REQ-P1-02 | 添加 `SecurityHeadersMiddleware`（6 项安全响应头） |
| `nginx.conf` | 修改配置 | REQ-P1-02 | 确认或添加安全响应头（如使用 nginx 反向代理） |
| `requirements.txt` | 修改版本号 | REQ-P1-03 | `PyJWT` → `>=2.13.0` |
| `services/auth.py` | 修改代码 | REQ-P1-03 | PyJWT 2.13.0+ 要求 `jwt.decode` 必须显式传入 `algorithms` 参数 |

### Wave 2（P2，~24h）— 改动文件

| 文件路径 | 修改类型 | 对应需求 | 修改说明 |
|----------|----------|----------|----------|
| `public/bazi.css` | 修改 CSS | REQ-P2-01, REQ-P2-02 | 移动端文字溢出修复 + 按钮可见性优化 |
| `public/index.html` | 新增 JS | REQ-P2-03 | 表单前端验证函数 `validateForm()` |
| `main.py` | 修改中间件 | REQ-P2-04 | 隐藏 `Server` 响应头 |
| `nginx.conf` | 修改配置 | REQ-P2-04 | `server_tokens off` |
| `main.py` | 新增异常处理 | REQ-P2-05 | 全局异常处理器，生产环境隐藏详细错误 |
| `public/index.html` | 新增 ARIA 标签 | REQ-P2-06 | 为表单和交互元素添加 ARIA 属性 |
| `public/index.html` | 新增折叠逻辑 | REQ-P2-07 | 结果卡片 `<details>/<summary>` 折叠展开 |
| `public/bazi.css` | 新增折叠样式 | REQ-P2-07 | 折叠面板样式 |
| `main.py` | 新增中间件 | REQ-P2-08 | 缓存策略中间件，按路径类型设置 Cache-Control |
| `nginx.conf` | 修改配置 | REQ-P2-08 | 静态资源缓存配置 |

---

## 6. Non-Goals（明确不做什么）

以下事项**明确不在本次修复范围内**，避免范围蔓延：

| # | Non-goal | 原因 | 未来考虑时机 |
|---|----------|------|-------------|
| N1 | **不重构整个排盘引擎** | 排盘精度（真太阳时、节气计算）当前已可用，无已知精度问题。竞品分析表明排盘引擎本身是正确的 | 如果发现排盘精度问题 → 另行立项 |
| N2 | **不做 App（iOS/Android）** | PWA 即可覆盖移动端用户，Native App 开发成本高、需单独设计。先修复 Web 移动端体验 | 日活 > 5,000 后评估 |
| N3 | **不添加多语言支持** | 八字是中国传统文化产品，目标用户为中文用户。多语言是增长策略而非修复项 | 出海决策后 |
| N4 | **不接入第三方 AI 模型对比** | 当前典籍 RAG + 断前事校准已经构成差异化。多流派分析是功能扩展而非修复 | 用户反馈强烈需求后 |
| N5 | **不重新设计整体 UI** | 当前视觉风格（星图/命盘主题）在用户洞察中评价正常。问题在于信息层级和组织方式，不是设计语言 | 品牌升级项目时 |
| N6 | **不做付费 / 会员体系** | 修复优先于盈利。安全漏洞修复完成前讨论付费是"本末倒置" | 安全达标 + 体验稳定后 |
| N7 | **不做隐私政策 & 用户协议页面** | 重要但不阻断上线。合法合规文本需要法务审核，工期与安全修复并行推进 | P2 迭代中预留 2h |
| N8 | **不做 Redis 缓存层 / CDN / Gunicorn 切换** | 这些是架构优化（指标仪表盘 Wave 3），非当前修复范围。当前单线程部署能满足初期流量（< 1000 DAU） | DAU 突破 1000 后 |
| N9 | **不修改日历类型验证（calendar_type）** | 指标仪表盘列为低优先级（API-01），不影响核心功能 | Wave 2 中作为小修附带处理 |
| N10 | **不做断前事校准交互打磨** | 这是差异化护城河的深度打磨，不是修复。需要独立 PRD 和 UX 设计 | Wave 3 独立立项 |

---

## 7. 时间线 & 里程碑

### 总览

```
Week 1 | Week 2 | Week 3 | Week 4 |
  Wave 0     Wave 1     Wave 2（首月持续）
  ────────   ─────────  ────────────────
  P0安全修复  P1安全+认证  P2 体验优化
  ~3h        ~18h        ~24h
  ████       ██████      [持续交付]
```

### 详细里程碑

| 里程碑 | 时间 | 完成标准 | 包含需求 | 可交付物 | 风险 |
|--------|------|----------|----------|----------|------|
| **M0: 安全防火墙** | Day 1-2（<3h） | 4 个 P0 安全项全部修复并部署到生产 | REQ-P0-03, REQ-P0-04 | 更新后的 main.py / services/auth.py；CORS curl 测试通过 | 低。改动量小，仅代码删除和配置修改 |
| **M1: 核心功能恢复** | Day 2-3（<2h） | 日期选择器在桌面端/移动端均可见可操作 | REQ-P0-05 | CSS 修复验证截图 + Playwright 测试通过 | 中。CSS 层级/定位排查可能比预期复杂 |
| **M2: 认证可用** | Day 3-7（<16h） | 真实短信验证码可送达，万能验证码已删除 | REQ-P1-01, REQ-P0-01, REQ-P0-02 | SMS SDK 集成 + 删除 dev 代码后的 auth.py | **高。SMS 集成涉及第三方服务开通、模板审核，这是工期最长的不确定项** |
| **M3: 安全加固完成** | Day 7（<2h） | 6 项安全 Headers 到位 + PyJWT 升级完成 | REQ-P1-02, REQ-P1-03 | 更新后的 main.py / requirements.txt | 低 |
| **M4: 正式上线** | Day 7-10 | 产品达到面向公众开放的安全和体验标准 | 所有 P0 + P1 | 上线前检查清单全部通过 | 中。取决于 SMS 集成进度 |
| **M5: 体验优化 v2.1** | Day 10-30（<24h） | 移动端体验改善、表单验证到位、信息层级优化 | REQ-P2-01 ~ P2-08 | v2.1 版本发布 | 低。均为常规前端修复 |

### 关键路径分析

```
安全 P0 并行修复 (3h) ─┐
                        ├→ 上线安全基线达标 [Day 2]
日期选择器修复 (2h) ────┘

SMS 集成 (16h) ─┬→ 删除万能码/dev端点 ─┬→ 正式上线 [Day 7-10]
                │                     │
安全Headers (1h)┤                     │
升级PyJWT (1h)──┘                     │
                                      │
                        P2 体验优化 (24h) → v2.1 [Day 30]
```

**关键路径瓶颈**: SMS 集成（16h）是整个时间线的关键约束。如果第三方 SMS 服务开通和模板审核耗时较长（>3 个工作日），可先完成其他 P1 项并行推进。

### 风险缓解策略

| 风险 | 概率 | 缓解措施 |
|------|------|----------|
| SMS 审核周期长 | 中 | 提前启动 SMS 服务商开户流程（需求确认后立刻执行）；准备短信 Mock 模式作为临时灰度方案 |
| 日期选择器修复比预期复杂 | 中 | 如果 CSS 方案 2h 内无解，准备 Plan B：增加纯文本日期输入框作为备选方案 |
| PyJWT 升级导致兼容问题 | 低 | PyJWT 2.13.0 主要变更是强制 `algorithms` 参数，修改量 < 5 行。保留 1h 缓冲做回归测试 |
| 环境变量部署后未更新 | 中 | 提供 .env 模板和部署 checklist；在 main.py 启动时打印安全配置摘要（不泄漏密钥） |

---

## 8. 验收检查清单（上线前，由 QA / Team Lead 执行）

- [ ] `curl -X POST <站点>/api/auth/login -d '{"phone":"13800000001","code":"990204"}' -H "Content-Type: application/json"` → 返回 400
- [ ] `curl <站点>/api/auth/dev-code/13800000001` → 返回 404
- [ ] `curl -H "Origin: https://evil.com" -I <站点>/api/health` → 无 `Access-Control-Allow-Origin` 或值非 evil.com
- [ ] `curl -I <站点>/` → 包含全部 6 项安全响应头
- [ ] Playwright 测试：`#birth-datetime-trigger` 在 390px 和 1280px 视口中 isVisible() = true
- [ ] Playwright 测试：日期滚轮选择器可正常弹出、选择、确认
- [ ] 真实短信：手机号输入验证码请求后，确认收到短信
- [ ] PyJWT 版本：`pip show PyJWT` → Version ≥ 2.13.0
- [ ] CVE 扫描：PyJWT 无已知高危 CVE

---

## 9. 附录：数据来源与引用

| 文档 | 路径 | 关键引用 |
|------|------|----------|
| 用户洞察报告 | `deliverables/product-strategy/user-insight-2026-07-18.md` | 用户旅程痛点 §一；安全信任影响 §二；改进行动建议 §四 |
| 竞品扫描报告 | `deliverables/product-strategy/competitive-scan-2026-07-18.md` | 安全标准对比 §5.1；UX 标准对比 §5.2；修复优先级 §6 |
| 指标仪表盘 | `deliverables/product-strategy/metrics-dashboard-2026-07-18.md` | 一票否决项 §一；修复矩阵 §3.3；分波次计划 §7 |
| 安全审查报告 | `test_security_expert.md` | 9 个漏洞详细发现 |
| UX 测试报告 | `test_ux_expert.md` | 7 项测试结果 + 移动端专项指标 |
| API 测试报告 | `test_api_expert.md` | 9 个核心端点测试矩阵 |
| 性能测试报告 | `test_perf_expert.md` | 响应时间 + 瓶颈分析 |

---

*文档生成: 2026-07-18 | 需求分析师: 析客（Specky） | 团队: product-bazi-fix*
