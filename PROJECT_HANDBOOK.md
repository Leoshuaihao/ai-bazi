# AI 八字排盘引擎 · 项目手册

> 最后更新：2026-07-19 | 版本：V2.4

## 一、项目身份

**ai-bazi** 是一个基于 FastAPI + DeepSeek AI 的八字命理分析系统。核心能力：

1. **排盘引擎**：基于 lunar-python 的精确八字、大运、神煞、五行力量计算
2. **典籍 RAG**：检索《子平真诠》《滴天髓》《穷通宝鉴》等 8 本命理典籍原文，辅助 AI 判断
3. **断前事闭环**：生成 7 条过去推断→用户逐条反馈→校验判定→发现错误自动修正（时钟修正/AI重新判断）
4. **断未来预测**：基于校准命盘预测事业/财运/婚姻/健康四维度运势
5. **商业化**：积分系统、支付、邀请裂变、用户认证

技术栈：Python 3.11, FastAPI, SQLAlchemy async + aiosqlite, JWT, Docker + Railway 部署。

---

## 二、架构全景

```
                        public/index.html (前端)
                              |
                         main.py (FastAPI)
                              |
          ┌───────────────────┼───────────────────┐
     api/routes/          services/              rules/
     auth, payment,       ai_explainer,          wuxing, yongshen,
     points, chat,        classical_judge,        shensha
     liunian, liuyue      forecast, calibration,
                          correction, predictions,
                          rag_retriever, reanalysis,
                          deepseek_client, auth, gate
                              |
          ┌───────────────────┼───────────────────┐
     bazi_engine.py      orm/                   data/
     (lunar-python)      db, user,             classical_corpus/
                         entitlement,           (8本典籍, ~50万字)
                         points, invite,
                         order
```

### 核心数据流

```
用户输入出生信息
  → bazi_engine.calculate_bazi()           # 排盘
  → rules/yongshen.calculate_strength_detail()  # 旺衰+用神
  → rag_retriever.retrieve_all_stages()    # 典籍RAG检索（按阶段加权）
  → ai_explainer / classical_judge         # AI解释/典籍判断
  → predictions.generate_predictions()     # 断前事（7条）
  → calibration.run_calibration()          # 校验判定
  → correction (时钟修正 / AI修正)          # 修正闭环
  → forecast.generate_forecast()           # 断未来
```

### 四个模块层

| 层级 | 目录 | 职责 |
|------|------|------|
| **规则引擎** | `rules/` | 确定性计算：旺衰/用神/神煞/五行。不依赖 AI |
| **典籍 RAG** | `services/rag_retriever.py` | 从 8 本典籍库检索相关原文，支持按分析阶段加权 |
| **AI 判断** | `services/classical_judge.py` 等 | DeepSeek 基于原文做判断、解释、推测 |
| **业务编排** | `main.py`, `services/calibration.py` 等 | 串联规则引擎+RAG+AI，含反馈闭环 |

---

## 三、关键设计决策

### 决策 1：子平派单一体系
系统自称子平派，用《子平真诠》的"用神专求月令"为格局主线。不混用盲派、新派等其他体系。典籍权重设计遵循此原则。

### 决策 2：规则引擎 + AI 修正 而非纯 AI
旺衰/用神/神煞由确定性规则引擎先算，AI 只在规则引擎无法 100% 确定时介入（如从格判断、调候取舍）。设计理念是「先确定性的、再推测性的」。

### 决策 3：反馈闭环
用户对断定过去的推断逐条反馈（accurate/partial/inaccurate），系统据此判定是否需要修正时钟或重新判断旺衰/格局。**反馈当前不持久化**（ephemeral，仅在 session 中）。

### 决策 4：典籍 RAG 按阶段加权（2026-07-19）
每本典籍在不同分析阶段有不同的权威度（5阶段×8典籍）：
- 基础理论（basics） → 三命通会第一（百科全书）
- 十神解读（shishen） → 渊海子平第一（十神原始定义）
- 定格局（pattern） → 子平真诠第一（权重×2.0）
- 取用神（yongshen） → 子平真诠 + 穷通宝鉴并列
- 断旺衰（wangshuai） → 滴天髓第一
- 穷通宝鉴按月令+日干精准匹配过滤（ri_zhu_stem 分级：1.0/0.8/0.5/0.3/0.0）

### 决策 5：活权重（per-user 动态权重，2026-07-19 V2.2）
在固定 STAGE_PRIORITY 之上叠加 per-user 权重（0.3~2.0）：
- 用户反馈 inaccurate → LLM 复盘分析错误层面 → 定向调整权重
- Mock 模式：12条规则+5层面（旺衰/格局/用神/十神/AI过度）规则引擎V2
- 核心三关全挂 → 自动建议 recalibrate_time 校准时辰
- 学习率 0.15，单次调整幅度受限，可回滚

### 决策 6：Mock 回退
DeepSeek API Key 未配置时自动回退到模板化输出（规则推导），保证系统不掉线。反馈复盘同样有 Mock 规则引擎V2 回退。

### 决策 7：用户名密码认证
注册/登录用 PBKDF2-SHA256 密码哈希（60万次迭代），JWT 7天过期。短信验证码预留但未启用。

---

## 四、开发约定

### 代码风格
- Python 类型注解（`dict[str, int]` 等）
- 异步优先（`async def` + `await`）
- 公共函数文档用 Google-style docstring

### 模块边界
- `rules/` **不得**引入 AI 或 HTTP 依赖（纯计算）
- `services/` 可以调 DeepSeek API、数据库
- `main.py` 只做路由编排，不放业务逻辑
- `orm/` 只放数据模型，不放业务逻辑

### Mock 模式
所有 AI 调用的 service 必须提供 mock 回退：
```python
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    return generate_mock_explanation(...)  # 模板化输出
```

### 测试
```bash
cd /Users/lee/WorkSpace/WorkBuddy/ai-bazi
python -m pytest tests/ -v
```

### 运行
```bash
cd /Users/lee/WorkSpace/WorkBuddy/ai-bazi
python main.py  # 默认在 0.0.0.0:8022
```

### 部署
项目部署在 Railway，Dockerfile 为入口。环境变量通过 Railway Dashboard 管理（非 .env 文件）。

---

## 五、当前状态与路线图

### 已完成

| 版本 | 日期 | 内容 |
|------|------|------|
| V2.0 | 2026-07-18 | P0安全修复：删除万能验证码、JWT_SECRET必填、CORS白名单、PBKDF2密码哈希 |
| V2.0 | 2026-07-18 | 短信验证码→用户名密码认证 |
| V2.0 | 2026-07-18 | 大运流年 key_years/key_actions bug修复 |
| V2.0 | 2026-07-19 | 典籍库从3本扩到8本（三命通会、渊海子平等新增） |
| V2.1 | 2026-07-19 | **典籍RAG权重重构**：5阶段感知检索+穷通宝鉴日干精准过滤 |
| V2.2 | 2026-07-19 | **反馈自适应系统**：per-user活权重+LLM复盘+3个API端点 |
| V2.2 | 2026-07-19 | 补齐：Mock复盘规则逻辑V2（12条规则+5层面定向调整+校准联动） |
| V2.3 | 2026-07-19 | **SQLite典籍库**：FTS5全文检索（3.6MB, 281章, 8本典籍） |
| V2.3 | 2026-07-19 | 补齐：穷通宝鉴精准日干过滤（ri_zhu_stem分级+章节注入加分） |
| V2.4 | 2026-07-19 | **新典籍挂载**：三命通会+渊海子平接入RAG（basics/shishen阶段） |

### V2.1-V2.4 详细改动清单

**核心已修改文件：**
- `services/rag_retriever.py`：
  - `STAGE_PRIORITY` 5阶段×8典籍权重映射（basics/shishen/pattern/yongshen/wangshuai）
  - `retrieve_by_stage()` / `retrieve_all_stages()` 支持 user_weights + ri_zhu_stem
  - `search_corpus_fts()` FTS5检索 + 穷通宝鉴精准日干章节注入加分
  - `_filter_qiongtong_noise()` ri_zhu_stem 分级匹配（1.0/0.8/0.5/0.3/0.0）
- `services/feedback_weights.py`：
  - LLM复盘 + Mock规则引擎V2（`_MOCK_ERROR_PATTERNS` 12条 + `_MOCK_LAYER_ADJUSTMENTS` 5层面）
  - `_analyze_error_layer()` 错误层面分析
  - 校准联动（核心三关全挂→建议 recalibrate_time）
  - 3个API端点：`/api/feedback/review`、`/weights`、`/weights/reset`
- `services/predictions.py`：`CATEGORY_DEPENDS_MAP` 7类预测→分析阶段映射
- `models.py`：PreEventStatement 新增 depends_on 字段，新增 FeedbackReviewRequest
- `main.py`：3个端点加 session_id/ri_zhu_stem 参数，传入 user_weights
- `scripts/build_corpus_db.py`：构建 SQLite 典籍库
- `data/classical_corpus.db`：SQLite数据库（3.6MB, 281章, FTS5索引）

**已验证效果（1999-02-04 14:30 丁火丑月男命）：**
- 子平真诠 Top-5 占比从 62% 降到 37%
- 滴天髓·旺衰 从零入选变 primary 权威 Top-5
- 穷通宝鉴噪声从 120 章过滤到精准匹配
- 活权重闭环：反馈 inaccurate → 复盘降权 → 滴天髓浮上 Top-1
- 核心三关全挂 → 自动建议换时辰校准

### 规划中

| 版本 | 内容 | 优先级 |
|------|------|--------|
| V2.5 | 全局反馈统计（跨用户累积准确率调整全局权重） | 🟢 低 |

### 技术债务
- 反馈数据不持久化（无法跨会话学习，活权重仅在内存中）
- 5本新典籍无结构化 index.json（已通过 SQLite FTS5 补偿，但章节级 topic/keywords 标注仍不完整）
- `data/classical_corpus/` 里 `dishui/`+`dishui_chanwei/`+`dishui_ren/` 信息重叠
- 前端仅有静态 HTML，无 SPA 框架
- 测试覆盖率不完整（缺3项补齐的专门测试脚本）

---

## 六、新 Agent 上手指南

### 第一天：理解系统
1. 阅读本文档
2. 运行项目：`cd ai-bazi && python main.py`
3. 调用 `POST /api/chart` 排一个盘体验流程
4. 阅读 `services/classical_judge.py` 理解三角度用神判断
5. 阅读 `services/calibration.py` 理解反馈闭环

### 开发流程
1. **先读 `rag_retriever.py`**——几乎所有改动都涉及典籍检索
2. 改动 `rules/` 前先跑 `pytest tests/test_strength.py` 确认不破坏引擎
3. 改动 `services/` 后确保有 mock 回退路径
4. 改完运行 `pytest tests/` 全量测试
5. 推送到 Railway 前确保 `.env` 里 `DEEPSEEK_API_KEY` 在 Railway Dashboard 已配置

### 关键文件速查

| 需求 | 文件 |
|------|------|
| 改排盘逻辑 | `bazi_engine.py` |
| 改旺衰/用神规则 | `rules/yongshen.py` |
| 改典籍RAG检索 | `services/rag_retriever.py` |
| 改典籍AI判断 | `services/classical_judge.py` |
| 改AI解释文案 | `services/ai_explainer.py` |
| 改断前事 | `services/predictions.py` |
| 改校验判定 | `services/calibration.py` |
| 改修正逻辑 | `services/correction.py` |
| 改断未来 | `services/forecast.py` |
| 改认证 | `services/auth.py` + `api/routes/auth.py` |
| 改数据库 | `orm/` |
| 看测试用例 | `tests/` |

### 术语表

| 术语 | 英文/代码 | 含义 |
|------|----------|------|
| 日主 | ri_zhu / day_master | 出生日的天干，代表命主本人 |
| 日干 | ri_zhu_stem | 日主的天干（甲乙丙丁...），用于穷通宝鉴精准匹配 |
| 旺衰 | strength / wangshuai | 日主在八字中的强弱程度 |
| 用神 | yongshen | 对日主最有利的五行 |
| 格局 | pattern | 月令决定的八字结构类型（正官格/七杀格等） |
| 大运 | dayun | 每十年一换的运势周期 |
| 流年 | liunian | 某一年的运势 |
| 十神 | ten_god | 天干与日主的关系（比肩/劫财/食神/伤官...） |
| 子平 | ziping | 《子平真诠》，格局论命核心典籍 |
| 滴天髓 | dishui | 《滴天髓》，命理哲学纲领典籍 |
| 穷通 | qiongtong | 《穷通宝鉴》，调候用神工具书 |
| 三命通会 | sanming | 《三命通会》，命理百科全书（basics阶段primary） |
| 渊海子平 | yuanhai | 《渊海子平》，十神原始定义（shishen阶段primary） |
| 基础理论 | basics stage | 分析阶段0：天干地支五行基础（三命通会primary） |
| 十神解读 | shishen stage | 分析阶段1：十神→六亲映射（渊海子平primary） |
| 定格局 | pattern stage | 分析阶段2：判断格局类型（子平真诠primary） |
| 取用神 | yongshen stage | 分析阶段3：判断用神 |
| 断旺衰 | wangshuai stage | 分析阶段4：判断日主强弱（滴天髓primary） |
| 活权重 | user_weights | per-user 动态权重，由反馈复盘驱动调整（0.3~2.0） |
| 校准联动 | recalibrate_time | 核心三关全挂时建议换时辰重新排盘 |
