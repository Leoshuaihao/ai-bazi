# AI八字排盘引擎 - 安全审查报告

**测试时间**: 2026-07-18  
**测试目标**: https://ai-bazi-production.up.railway.app  
**测试人员**: security-tester  
**审查范围**: 信息泄漏、认证/授权、输入验证、依赖安全、CORS和Headers安全

---

## 一、安全发现汇总

| 严重程度 | 数量 | 说明 |
|---------|------|------|
| P0（严重） | 2 | 需立即修复，否则不应上线 |
| P1（高危） | 4 | 上线前必须修复 |
| P2（中危） | 3 | 建议修复，不阻塞上线 |

---

## 二、详细发现

### P0 - 严重

#### 1. 开发模式万能验证码暴露在生产环境

- **文件**: `api/routes/auth.py:47`
- **问题**: 生产环境保留了开发模式万能验证码 `990204`，任何知道此验证码的人可绕过短信验证登录任意账户
- **风险**: 攻击者可使用万能验证码登录任意手机号账户，获取该账户的所有数据和权限
- **验证**: 代码中硬编码了万能验证码逻辑
- **修复建议**: 
  - 通过环境变量控制开发模式开关，生产环境默认关闭
  - 或直接删除万能验证码逻辑

#### 2. 开发端点 `/api/auth/dev-code/{phone}` 暴露在生产环境

- **文件**: `api/routes/auth.py:83-96`
- **问题**: `/api/auth/dev-code/{phone}` 端点允许任何人获取任意手机号的验证码
- **风险**: 攻击者可获取任意用户的短信验证码，从而登录任意账户
- **验证**: 访问 `https://ai-bazi-production.up.railway.app/api/auth/dev-code/13800138000` 返回 `{"code":"none"}`
- **修复建议**: 立即删除此端点，或通过环境变量控制仅在开发环境启用

---

### P1 - 高危

#### 3. CORS 配置过于宽松

- **文件**: `main.py:73-79`
- **问题**: `allow_origins=["*"]` 允许任何域名携带凭证访问
- **风险**: 攻击者可从恶意网站发起跨域请求，携带用户凭证（如JWT）进行操作
- **验证**: `curl -H "Origin: https://evil.com" -I https://ai-bazi-production.up.railway.app/api/health` 返回 `access-control-allow-origin: https://evil.com` 且 `access-control-allow-credentials: true`
- **修复建议**: 
  - 限制 `allow_origins` 为实际使用的域名
  - 或设置 `allow_credentials=False`（但会影响需要凭证的跨域请求）

#### 4. JWT 密钥使用默认值

- **文件**: `services/auth.py:11`
- **问题**: `JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")`，生产环境未设置环境变量时使用默认密钥
- **风险**: 攻击者可使用默认密钥伪造JWT token，冒充任意用户
- **验证**: 检查 `.env` 文件，`JWT_SECRET=your-jwt-secret-here` 为默认值
- **修复建议**: 
  - 确保生产环境设置随机的JWT密钥
  - 删除代码中的默认值，要求必须设置环境变量

#### 5. 缺少必要的安全 Headers

- **问题**: 响应中缺少多个安全相关的HTTP头
- **缺失的Headers**:
  - `Strict-Transport-Security` (HSTS)
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY` 或 `SAMEORIGIN`
  - `Content-Security-Policy`
  - `Referrer-Policy`
  - `Permissions-Policy`
- **风险**: 
  - 缺少HSTS可能导致中间人攻击
  - 缺少X-Frame-Options可能导致点击劫持
  - 缺少Content-Security-Policy可能无法有效防御XSS
- **验证**: `curl -I https://ai-bazi-production.up.railway.app/` 响应中无上述安全头
- **修复建议**: 在FastAPI中间件中添加必要的安全头

#### 6. 服务器版本信息泄漏

- **文件**: HTTP响应头
- **问题**: 响应头包含 `server: railway-hikari` 和 `x-hikari-trace`、`x-railway-edge` 等内部信息
- **风险**: 泄漏服务器技术栈信息，帮助攻击者针对性攻击
- **验证**: `curl -I https://ai-bazi-production.up.railway.app/` 返回 `server: railway-hikari`
- **修复建议**: 在生产环境隐藏或自定义Server头

---

### P2 - 中危

#### 7. PyJWT 版本存在已知漏洞

- **文件**: `requirements.txt:8`
- **问题**: `pyjwt>=2.8` 版本存在多个CVE漏洞
  - CVE-2026-48525: DoS攻击 (CVSS 5.3)
  - CVE-2026-48526: 算法混淆攻击 (CVSS 7.4)
  - CVE-2026-48523: 算法绕过 (CVSS 5.4)
  - CVE-2026-48522: SSRF风险 (CVSS 4.2)
- **风险**: 攻击者可利用已知漏洞进行DoS攻击或伪造token
- **修复建议**: 升级到 `pyjwt>=2.13.0`

#### 8. SMS 验证码仅打印到控制台

- **文件**: `services/auth.py:23-30`
- **问题**: `send_sms` 函数仅打印到控制台，未实际发送短信
- **风险**: 生产环境无法发送真实验证码，用户无法正常登录
- **修复建议**: 集成实际的短信发送服务（如阿里云SMS SDK）

#### 9. 详细错误信息泄漏

- **问题**: API响应中包含详细的Pydantic验证错误信息
- **验证**: 
  - `curl -X POST ... -d '{"invalid_json":'` 返回详细的JSON解析错误
  - `curl -X POST ... -d '{"year": "1990 OR 1=1",...}'` 返回详细的类型错误
- **风险**: 泄漏内部数据模型和验证逻辑，帮助攻击者理解系统
- **修复建议**: 在生产环境返回通用错误信息，将详细错误记录到日志

---

## 三、认证/授权分析

### 已认证的API端点（需要JWT）
- `/api/chat/*` - AI聊天相关
- `/api/liuyue/*` - 六月相关
- `/api/liunian/*` - 六年相关
- `/api/payment/*` - 支付相关
- `/api/points/*` - 积分相关
- `/api/invite/*` - 邀请相关

### 未认证的API端点（无需JWT）
- `/api/health` - 健康检查
- `/api/shichen` - 时辰查询
- `/api/cities` - 城市查询
- `/api/chart` - 八字排盘
- `/api/chart/analyze` - 命盘分析
- `/api/analysis` - 命局分析
- `/api/classical-analysis` - 古籍分析
- `/api/predictions/*` - 预测相关
- `/api/calibrate/*` - 校准相关
- `/api/forecast/*` - 预测相关
- `/api/dayun/*` - 大运相关
- `/api/chat` (main.py版本) - 聊天（使用session_id而非JWT）

### JWT安全评估
- **算法**: HS256 (对称算法)
- **过期时间**: 7天
- **签名方式**: 对称签名，密钥安全性至关重要
- **风险**: 如果密钥泄漏，攻击者可伪造任意用户token

---

## 四、输入验证分析

### SQL注入
- **测试方法**: 在year字段输入 `1990 OR 1=1`
- **结果**: 被Pydantic模型拒绝（类型验证）
- **结论**: 由于使用ORM和Pydantic，SQL注入风险较低

### XSS
- **测试方法**: 在birthplace字段输入 `<script>alert(1)</script>`
- **结果**: 服务端正常处理，返回JSON响应
- **结论**: API返回JSON，XSS风险较低；但前端渲染时需确保转义

### 路径遍历
- **测试方法**: 访问 `/.env`、`/../.env`
- **结果**: 返回404
- **结论**: 路径遍历防护有效

---

## 五、依赖安全检查

| 依赖 | 当前版本要求 | 已知漏洞 | 建议 |
|------|-------------|---------|------|
| fastapi | >=0.100.0 | 无直接漏洞（CVE是fastapi-users，非fastapi本身） | 保持 |
| pyjwt | >=2.8 | CVE-2026-48525/48526/48523/48522 | 升级到>=2.13.0 |
| sqlalchemy | >=2.0 | 无已知高危漏洞 | 保持 |
| uvicorn | >=0.23.0 | 无已知高危漏洞 | 保持 |
| httpx | >=0.27 | 无已知高危漏洞 | 保持 |

---

## 六、上线标准评估

### 必须修复（不满足则不上线）

1. **删除万能验证码和dev-code端点** [P0]
2. **确保JWT_SECRET使用随机强密钥** [P1]
3. **修复CORS配置** [P1]

### 强烈建议修复

4. 添加安全Headers [P1]
5. 隐藏服务器版本信息 [P1]
6. 升级PyJWT到2.13.0+ [P2]
7. 实现真实的SMS发送功能 [P2]
8. 简化错误响应信息 [P2]

### 通过项

- 输入验证（Pydantic）防护SQL注入有效
- 路径遍历防护有效
- .git文件未暴露
- API文档（/api/docs）未暴露
- 主要API端点功能正常

---

## 七、结论

**当前状态：不满足上线标准**

**主要阻塞项**：
1. 万能验证码和dev-code端点暴露在生产环境（P0）
2. CORS配置过于宽松（P1）
3. JWT密钥可能使用默认值（P1）

**建议**：
1. 立即修复P0问题
2. 上线前修复P1问题
3. 在后续迭代中修复P2问题

---

*报告生成时间: 2026-07-18 20:59*