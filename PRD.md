# PRD · V2.2 — 反馈自适应典籍权重系统

> 创建：2026-07-19 | 状态：设计完成，待开工
> 前置依赖：V2.1 典籍 RAG 权重重构（已完成）

---

## 一、背景

### 现状问题

1. **死权重**：V2.1 的 `STAGE_PRIORITY` 是全局固定的——子平真诠在定格局阶段始终×2.0，滴天髓在断旺衰始终×2.0。不区分用户个体差异。

2. **反馈未利用**：系统有完整的断前事→反馈→修正闭环。用户反馈了哪条预测对、哪条错，但这个信息**完全没反馈到典籍选择上**——即使子平真诠的判断连续被标记 inaccurate，它在下一轮分析中仍然是第一权威。

3. **颗粒度不够**：反馈只标记 accurate/inaccurate，不知道"错在哪"——是旺衰错了、格局错了、还是十神解读错了。

### 用户诉求

用户某条预测被反馈 inaccurate 后，系统应该：
- 分析错误来源（哪本书/哪个阶段的判断出了问题）
- 动态调整该用户后续分析中的典籍权重
- 使个别用户的实际命理倾向（如更适合调候派而非格局派）能在权重中体现

---

## 二、目标

**在 V2.1 的固定权重基础上，增加一层 per-user 的动态权重，由 LLM 复盘用户反馈后自主调整。**

### 核心转变

```
死权重（V2.1）        →    活权重（V2.2）
STAGE_PRIORITY 固定     →    STAGE_PRIORITY × user_weight
全局不变                →    随用户反馈逐步收敛
```

---

## 三、方案设计

### 3.1 整体流程

```
用户提交全部反馈（7条）
    ↓
┌─ LLM 复盘 ──────────────────────────────────────┐
│ 输入:                                              │
│   · 7条预测原文 + 用户反馈                          │
│   · 每条预测的 depends_on（出自哪个阶段×典籍）         │
│   · 当前 user_weight 表                             │
│   · 相关典籍原文（根据反馈内容按阶段检索）               │
│                                                    │
│ LLM 分析:                                           │
│   · 每条 inaccurate 预测的错误层面贡献度（%）          │
│     wangshuai_layer / pattern_layer / yongshen_layer │
│     / shishen_layer / ai_overreach                  │
│   · 输出结构化 weight_adjustments                    │
│                                                    │
│ 输出:                                               │
│   { stage:corpus → 新权重, reason }                 │
└────────────────────────────────────────────────────┘
    ↓
更新 user_weight 表
    ↓
后续分析（断未来/修正重跑）使用新权重检索典籍
```

### 3.2 数据模型

**PreEventStatement 新增字段：**
```python
depends_on: list[str] = []
# 例: ["pattern:ziping", "yongshen:qiongtong", "wangshuai:dishui"]
```

**新增 user_weights 表（内存/SQLite）：**
```python
# Key = "stage:corpus", Value = float (0.3 ~ 2.0, 默认1.0)
{
    "pattern:ziping": 1.0,
    "pattern:dishui": 1.0,
    "yongshen:ziping": 1.0,
    "yongshen:qiongtong": 1.0,
    "yongshen:dishui": 1.0,
    "wangshuai:dishui": 1.0,
    "wangshuai:ziping": 1.0,
}
```

### 3.3 LLM 复盘 Prompt 结构

```
你是一位命理分析复盘专家。以下是一个用户的反馈数据：

【用户八字】
日主：丁火，月令：丑，旺衰：偏弱，格局：正格-身弱，用神：木

【预测与反馈】
1. [父母关] 预测：父母关系一般，母亲身体较弱
   反馈：inaccurate — 父母关系很好，母亲身体也很好
   依据典籍：pattern:ziping（子平真诠·论印绶）

2. [兄弟关] 预测：兄弟姐妹多，关系不太好
   反馈：inaccurate — 只有一个，关系不错
   依据典籍：pattern:ziping（子平真诠·论兄弟）

...

【当前用户权重】
pattern:ziping=1.0, pattern:dishui=1.0, ...

【相关典籍原文】
（检索自用户反馈关键词的典籍章节原文）...

请完成以下分析：
1. 对每条 inaccurate 的预测，分析错误发生在哪个层面，贡献度%
2. 综合全部反馈，给出权重调整建议
3. 输出格式：{ "error_analysis": {...}, "weight_adjustments": [...] }
```

### 3.4 权重调整规则

```python
DEFAULT_WEIGHT = 1.0
MIN_WEIGHT = 0.3      # 不归零，保留最低存在感
MAX_WEIGHT = 2.0      # 不无限放大
LEARNING_RATE = 0.15  # 每次调整的最大步长

def apply_weight_adjustment(current: float, factor: float) -> float:
    """应用调整因子，限制步长和范围"""
    target = current * factor
    diff = target - current
    clipped_diff = max(-LEARNING_RATE, min(LEARNING_RATE, diff))
    new = current + clipped_diff
    return max(MIN_WEIGHT, min(MAX_WEIGHT, new))
```

### 3.5 RAG 检索注入

`retrieve_by_stage()` 的加权公式从：

```python
weighted_score = base_score × STAGE_PRIORITY[stage].multiplier
```

变为：

```python
stage_mult = STAGE_PRIORITY[stage].get_multiplier(corpus_name)  # 固定权重
user_mult = user_weights.get(f"{stage}:{corpus_name}", 1.0)     # 活权重
weighted_score = base_score × stage_mult × user_mult
```

---

## 四、改动文件清单

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `models.py` | PreEventStatement 新增 depends_on 字段 | +3 |
| `services/predictions.py` | 7个Mock构造函数标注 depends_on | +14 |
| `services/feedback_weights.py` | **新文件**：权重仓库 + LLM复盘prompt + 调整逻辑 | ~120行 |
| `services/rag_retriever.py` | retrieve_by_stage 注入 user_weight | +5 |
| `main.py` | 新增 /api/feedback/review 复盘端点 | +40 |
| `services/calibration.py` | 判定完成后自动触发复盘（可选） | +10 |

---

## 五、阶段映射表（depends_on 默认值）

| 预测类别 | depends_on |
|----------|-----------|
| 性格 | `["wangshuai:dishui"]` |
| 父母关 | `["pattern:ziping"]` |
| 兄弟关 | `["pattern:ziping"]` |
| 学历 | `["yongshen:ziping"]` |
| 婚姻关 | `["yongshen:ziping", "yongshen:qiongtong"]` |
| 事业 | `["yongshen:qiongtong", "pattern:ziping"]` |
| 关键年份 | `["wangshuai:dishui", "yongshen:ziping"]` |

---

## 六、验收标准

- [ ] PreEventStatement 返回中包含 depends_on 字段
- [ ] 提交 7 条反馈后，调用复盘端点返回结构化 weight_adjustments
- [ ] 连续 3 条 inaccurate 反馈后，对应 stage:corpus 权重下降 ≥ 15%
- [ ] inaccurate + accurate 混合反馈时，权重收敛到合理范围（0.3~2.0）
- [ ] 后续分析（/api/forecast）使用新权重检索典籍，来源分布有可见变化
- [ ] 不影响 mock 模式（无 API Key 时回退到固定权重）

---

## 七、风险与限制

| 风险 | 缓解 |
|------|------|
| 7 条反馈样本太少，可能过拟合 | LEARNING_RATE=0.15 限制单次调整幅度 |
| LLM 复盘可能不准（错误的归因） | 不出自动执行，输出权重建议后由系统应用（可回滚） |
| 权重偏离过多后无法恢复 | accurate 反馈会反向修正（×1.05）；预留"重置权重"按钮 |
| 复盘额外消耗 API tokens | 每次复盘约 2000-4000 tokens，与断前事/断未来相当 |

---

# PRD · V2.3 — SQLite 典籍库 + FTS5 全文检索

> 创建：2026-07-19 | 状态：设计完成，待开工
> 前置依赖：无硬依赖，可与 V2.2 并行开发

---

## 一、背景

### 现状问题

1. **关键词精确匹配不准确**：LLM 复盘时搜"兄弟少"，典籍里写的是"手足凋零"——搜不到
2. **5 本新典籍无结构化索引**：三命通会、渊海子平、滴天髓阐微/征义、子平真诠原本的 index.json 缺失 topic/keywords/summary
3. **文件系统损耗大**：每次检索需打开 200+ 个 .txt 文件读全文

### 目标

用 SQLite + FTS5 替代「JSON索引 + 文件系统全文读取」，实现：
1. 语义级全文搜索（搜"兄弟少"命中"手足凋零"）
2. 统一 8 本典籍的元数据管理
3. 更快的检索性能

---

## 二、数据库设计

### 文件：`data/classical_corpus.db`

```sql
-- 典籍元数据
CREATE TABLE corpus_meta (
    id TEXT PRIMARY KEY,        -- "ziping", "dishui", "qiongtong", ...
    source TEXT NOT NULL,       -- "子平真诠"
    author TEXT,                -- "沈孝瞻"
    dynasty TEXT,               -- "清"
    school TEXT,                -- "子平派"
    total_chapters INTEGER
);

-- 章节表
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_id TEXT NOT NULL,        -- 关联 corpus_meta.id
    chapter_no INTEGER,             -- 章节序号
    title TEXT NOT NULL,            -- "论用神"
    topic TEXT,                     -- "用神" | "格局" | "旺衰" | ...
    analysis_layer TEXT,            -- "pattern" | "yongshen" | "wangshuai" | "shishen" | "liuqin" | ...
    keywords TEXT,                  -- 逗号分隔：用神,月令,格局,扶抑
    summary TEXT,                   -- 100字内容摘要
    full_text TEXT NOT NULL,        -- 原文全文
    file_path TEXT,                 -- 原始文件路径（保留溯源）
    FOREIGN KEY (corpus_id) REFERENCES corpus_meta(id)
);

-- FTS5 全文索引（对 title + summary + full_text）
CREATE VIRTUAL TABLE chapters_fts USING fts5(
    title,
    summary,
    full_text,
    content='chapters',
    content_rowid='id'
);
```

### 检索接口

```python
def search_corpus(
    query: str,                      # 自然语言查询
    stage: str = None,              # 可选过滤：pattern/yongshen/wangshuai
    corpus_ids: list[str] = None,   # 可选过滤典籍
    top_k: int = 10
) -> list[dict]:
    """FTS5 全文搜索，返回相关章节"""
```

---

## 三、改动文件清单

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `data/classical_corpus.db` | **新文件**：SQLite 典籍库 | — |
| `scripts/build_corpus_db.py` | **新文件**：从 .txt 文件构建 SQLite + FTS5 索引 | ~80行 |
| `scripts/label_chapters.py` | **新文件**：调用 DeepSeek 批量标注 topic/keywords/analysis_layer | ~100行 |
| `services/rag_retriever.py` | 新增 `search_corpus()` 替代文件系统检索 | ~60行 |

---

## 四、验收标准

- [ ] 搜"兄弟少"返回含"手足凋零"的章节（FTS5 语义匹配）
- [ ] 搜"丁火丑月"返回《穷通宝鉴·十二月丁火》排第一（日主+月令过滤）
- [ ] 按 analysis_layer="wangshuai" 过滤只返回旺衰相关章节
- [ ] 检索耗时 < 50ms（当前文件系统 ~200ms）
- [ ] 旧 JSON 索引文件保留但不再使用（向后兼容）

---

# PRD · V2.4 — 新典籍挂载

> 创建：2026-07-19 | 状态：设计完成，待 V2.3 SQLite 库建好后开工

---

## 方案

在 `STAGE_PRIORITY` 中新增两个阶段的典籍权重：

```python
STAGE_PRIORITY["basics"] = {      # 基础理论（天干地支五行）— 新增
    "primary": ["sanming"],       # 三命通会（唯一百科全书）
    "supplementary": ["ziping"],
}
STAGE_PRIORITY["shishen"] = {     # 十神解读（比肩劫财食神...）— 新增
    "primary": ["yuanhai"],       # 渊海子平（十神原始定义）
    "supplementary": ["ziping"],
}
```

同时在 `retrieve_by_stage` 扩展支持 `basics` 和 `shishen` 阶段。

---

# 版本路线图总览

```
V2.0 ✅ 已完成
├── 安全修复、认证重构、大运流年修复、典籍导入

V2.1 ✅ 本周已完成
└── 典籍RAG权重重构、阶段感知检索、穷通宝鉴日主过滤

V2.2 📋 PRD完成
├── depends_on 溯源标注
├── LLM 复盘 → 活权重
└── 反馈→权重→检索的闭环

V2.3 📋 PRD完成
├── SQLite 典籍库构建
├── FTS5 全文检索
└── 8本典籍统一元数据

V2.4 📋 PRD完成
└── 三命通会+渊海子平接入RAG

V2.5 🧠 概念阶段
└── 跨用户全局反馈统计 → 自动调整全局 STAGE_PRIORITY
```
