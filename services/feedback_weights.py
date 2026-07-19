"""反馈自适应权重模块 — V2.2

LLM复盘用户反馈 → 诊断错误层面 → 输出活权重调整。

架构：
    UserWeightStore (内存KV存储)
    ├── get_user_weights(session_id)
    ├── apply_adjustments(session_id, adjustments)
    └── reset_weights(session_id)

    FeedbackReviewer (LLM复盘)
    ├── build_review_prompt(predictions, feedbacks, current_weights, chart)
    ├── search_corpus_for_review(feedback_content)  # RAG检索相关典籍
    ├── review_feedback(...)  # 调用DeepSeek复盘
    └── parse_review_response(...)  # 解析结构化输出
"""

import json
import os
import re
from typing import Optional

from services.deepseek_client import call_deepseek
from services.rag_retriever import retrieve_by_stage

# ============================================================
# 常量
# ============================================================

DEFAULT_WEIGHT = 1.0
MIN_WEIGHT = 0.3
MAX_WEIGHT = 2.0
LEARNING_RATE = 0.15  # 单次调整最大步长

# 所有可能的阶段×典籍权重键
ALL_WEIGHT_KEYS = [
    "basics:sanming", "basics:ziping", "basics:dishui",
    "shishen:yuanhai", "shishen:ziping",
    "pattern:ziping", "pattern:dishui",
    "yongshen:ziping", "yongshen:qiongtong", "yongshen:dishui",
    "wangshuai:dishui", "wangshuai:ziping", "wangshuai:sanming",
]

# ============================================================
# 用户权重存储（内存KV，session级别）
# ============================================================

# {session_id: {key: float}}
_weight_store: dict[str, dict[str, float]] = {}


def get_user_weights(session_id: str) -> dict[str, float]:
    """获取或初始化用户的活权重表"""
    if session_id not in _weight_store:
        _weight_store[session_id] = {k: DEFAULT_WEIGHT for k in ALL_WEIGHT_KEYS}
    return _weight_store[session_id]


def apply_adjustments(
    session_id: str, adjustments: list[dict]
) -> dict[str, dict]:
    """应用LLM输出的权重调整。

    Args:
        session_id: 用户session ID
        adjustments: [
            {"key": "pattern:ziping", "action": "reduce", "factor": 0.85, "reason": "..."},
            {"key": "yongshen:qiongtong", "action": "boost", "factor": 1.15, "reason": "..."},
        ]

    Returns:
        {before: {key: old}, after: {key: new}, changes: [{key, old, new, reason}]}
    """
    weights = get_user_weights(session_id)
    before = dict(weights)
    changes = []

    for adj in adjustments:
        key = adj["key"]
        factor = adj.get("factor", 1.0)
        reason = adj.get("reason", "")

        old = weights.get(key, DEFAULT_WEIGHT)
        target = old * factor
        diff = target - old

        # 限制学习率
        clipped_diff = max(-LEARNING_RATE, min(LEARNING_RATE, diff))
        new = old + clipped_diff

        # 限制范围
        new = max(MIN_WEIGHT, min(MAX_WEIGHT, new))
        weights[key] = new

        changes.append({
            "key": key,
            "old": round(old, 3),
            "new": round(new, 3),
            "target": round(target, 3),
            "reason": reason,
        })

    return {
        "before": {k: round(v, 3) for k, v in before.items()},
        "after": {k: round(v, 3) for k, v in weights.items()},
        "changes": changes,
    }


def reset_weights(session_id: str) -> dict[str, float]:
    """重置用户权重为默认值"""
    _weight_store[session_id] = {k: DEFAULT_WEIGHT for k in ALL_WEIGHT_KEYS}
    return _weight_store[session_id]


# ============================================================
# LLM复盘系统
# ============================================================

REVIEW_SYSTEM_PROMPT = """你是一位精通《子平真诠》《滴天髓》《穷通宝鉴》等八字典籍的命理复盘专家。

你的任务是分析用户的反馈数据，诊断错误原因，给出典籍权重调整建议。

## 分析原则

1. **不只看对错，要诊断错误层面**：每条 inaccurate 的预测，需要判断错误发生在哪个分析层面：
   - wangshuai_layer（旺衰层）：日主强弱判断错了
   - pattern_layer（格局层）：格局类型判错了
   - yongshen_layer（用神层）：用神取错了
   - shishen_layer（十神解读层）：十神含义或六亲对应错了
   - ai_overreach（AI过度推理）：规则判断没错，但AI在润色时推断过度导致失真

2. **参考典籍原文**：依据提供的典籍原文，判断该预测是否符合原书论述。

3. **权重调整要保守**：单次调整幅度不超过15%，不归零不无限放大。

4. **必须引用具体原文**作为推理依据。

## 输出格式（严格 JSON，不要包含其他内容）

{
  "overall_assessment": "综合评测（50字以内）",
  "error_analysis": {
    "wangshuai_layer": {"contribution": 0.3, "reason": "说明"},
    "pattern_layer": {"contribution": 0.1, "reason": "说明"},
    "yongshen_layer": {"contribution": 0.2, "reason": "说明"},
    "shishen_layer": {"contribution": 0.3, "reason": "说明"},
    "ai_overreach": {"contribution": 0.1, "reason": "说明"}
  },
  "weight_adjustments": [
    {
      "key": "pattern:ziping",
      "action": "reduce",
      "factor": 0.85,
      "reason": "《子平真诠》的格局判断在此八字中不适用，原因是..."
    }
  ],
  "citation": "引用相关典籍原文"
}"""


def _search_corpus_for_review(feedback_texts: list[str]) -> str:
    """为复盘检索相关典籍原文。

    从用户反馈中提取关键词，检索相关典籍章节。
    """
    all_keywords = set()
    # 简单关键词提取
    KEYWORD_PATTERNS = [
        "兄弟", "姐妹", "父母", "母亲", "父亲", "婚姻", "配偶", "老婆", "老公",
        "事业", "工作", "财运", "学历", "健康", "性格",
        "比劫", "官杀", "食伤", "印星", "财星", "用神", "忌神",
    ]
    for text in feedback_texts:
        for kw in KEYWORD_PATTERNS:
            if kw in text:
                all_keywords.add(kw)

    if not all_keywords:
        return "无相关典籍检索"

    keywords = list(all_keywords)
    # 按各阶段检索（V2.4: 含 basics/shishen 新阶段，top_k=3 确保覆盖 primary 典籍）
    texts = []
    for stage in ["basics", "shishen", "pattern", "yongshen", "wangshuai"]:
        results = retrieve_by_stage(stage, keywords, top_k=3)
        for r in results:
            source = r.get("source", "")
            chapter = r.get("chapter", "")
            excerpt = r.get("full_text", "")[:300]
            texts.append(f"《{source}·{chapter}》：{excerpt}")

    return "\n\n".join(texts) if texts else "无相关典籍检索"


def build_review_prompt(
    predictions: list[dict],
    feedbacks: list[dict],
    chart_summary: dict,
) -> str:
    """构建LLM复盘prompt。

    Args:
        predictions: 预测列表 [{"id","category","content","basis","depends_on"},...]
        feedbacks: 反馈列表 [{"prediction_id","status","note"},...]
        chart_summary: 命盘摘要 {"ri_zhu","ri_zhu_wx","month_branch","strength","pattern","yongshen"}

    Returns:
        格式化的复盘prompt
    """
    # 构建预测+反馈表格
    pred_fb_lines = []
    fb_map = {f["prediction_id"]: f for f in feedbacks}

    feedback_texts = []
    for pred in predictions:
        fb = fb_map.get(pred["id"], {})
        status = fb.get("status", "unknown")
        note = fb.get("note", "")

        line = (
            f"[{pred['category']}] 预测：{pred['content'][:120]}\n"
            f"  反馈：{status}"
        )
        if note:
            line += f" — {note}"
            feedback_texts.append(note)
        if status != "accurate":
            line += f"\n  依据：{pred.get('basis', '')}\n  溯源：{pred.get('depends_on', [])}"
        pred_fb_lines.append(line)

    pred_fb_section = "\n\n".join(pred_fb_lines)

    # 检索相关典籍
    corpus_texts = _search_corpus_for_review(feedback_texts)

    # 命盘摘要
    chart_section = (
        f"日主：{chart_summary.get('ri_zhu','')}（{chart_summary.get('ri_zhu_wx','')}）\n"
        f"月令：{chart_summary.get('month_branch','')}\n"
        f"旺衰：{chart_summary.get('strength','')}\n"
        f"格局：{chart_summary.get('pattern','')}\n"
        f"用神：{chart_summary.get('yongshen','')}"
    )

    return f"""以下是一个用户的反馈数据，请进行复盘分析。

【命盘摘要】
{chart_section}

【预测与反馈】
{pred_fb_section}

【相关典籍原文】
{corpus_texts}

请根据以上信息完成复盘分析，按JSON格式输出。重点分析 inaccurate 预测的错误来源，并结合典籍原文给出权重调整建议。"""


def _normalize_adjustments(adjustments: list[dict]) -> list[dict]:
    """标准化 DeepSeek 返回的调整动作名称。

    DeepSeek 可能返回 "reduce"/"increase"（或其他变体），
    统一为 "decrease"/"increase"。
    """
    normalized = []
    for adj in adjustments:
        a = dict(adj)  # copy
        action = a.get("action", "").lower()
        if action == "reduce":
            a["action"] = "decrease"
        normalized.append(a)
    return normalized


def _generate_calibration_suggestions(
    review: dict,
    predictions: list[dict],
    feedbacks: list[dict],
) -> list[dict]:
    """基于复盘结果生成校准建议（AI路径也适用）

    规则：
    - 核心三关（父母/兄弟/婚姻）全部 inaccurate → 建议 recalibrate_time
    - wangshuai_layer contribution ≥ 0.4 且核心≥2 inaccurate → 建议 recalibrate_time
    - 降权 > 0 → 建议 continue_collecting_feedback
    """
    suggested = []
    error_analysis = review.get("error_analysis", {})

    # 统计核心三关
    core_categories = {"父母关", "兄弟关", "婚姻关"}
    fb_map = {fb.get("prediction_id"): fb for fb in feedbacks}
    pred_map = {p.get("id"): p for p in predictions}

    core_inaccurate = 0
    for pid, fb in fb_map.items():
        pred = pred_map.get(pid, {})
        if pred.get("category") in core_categories and fb.get("status") == "inaccurate":
            core_inaccurate += 1

    # 旺衰层贡献度
    wangshuai_contribution = 0
    for layer_name, info in error_analysis.items():
        if "旺衰" in layer_name or "wangshuai" in layer_name:
            wangshuai_contribution = info.get("contribution", 0)

    # 规则1: 核心三关全挂
    if core_inaccurate >= 3:
        suggested.append({
            "action": "recalibrate_time",
            "confidence": 0.85,
            "reason": "核心三关（父母/兄弟/婚姻）全部不准确，极可能时辰或日柱有误，建议重新校准出生时间。"
        })

    # 规则2: 旺衰贡献高 + 核心多挂
    if wangshuai_contribution >= 0.4 and core_inaccurate >= 2:
        existing = any(s["action"] == "recalibrate_time" for s in suggested)
        if not existing:
            suggested.append({
                "action": "recalibrate_time",
                "confidence": 0.75,
                "reason": "旺衰判断是主要错误来源（贡献{:.0%}），核心预测大面积不准确，建议校准时辰。".format(wangshuai_contribution)
            })

    # 规则3: 有任何降权 → 建议继续收集反馈
    adjustments = review.get("weight_adjustments", [])
    has_reduce = any(
        a.get("action", "").lower() in ("reduce", "decrease") for a in adjustments
    )
    if has_reduce:
        suggested.append({
            "action": "continue_collecting_feedback",
            "confidence": 0.7,
            "reason": "典籍权重已根据本次反馈调整，建议进入下一轮断前事验证效果。"
        })

    return suggested


async def review_feedback(
    predictions: list[dict],
    feedbacks: list[dict],
    chart_summary: dict,
    session_id: str = "",
) -> dict:
    """LLM复盘用户反馈，输出权重调整建议。

    Args:
        predictions: 预测列表
        feedbacks: 反馈列表
        chart_summary: 命盘摘要
        session_id: 用户session（用于获取当前权重）

    Returns:
        {
            review: LLM复盘结果（含error_analysis + weight_adjustments）,
            applied: 权重变化前后对比（仅在auto_apply时）
        }
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return _mock_review(predictions, feedbacks, session_id=session_id)

    prompt = build_review_prompt(predictions, feedbacks, chart_summary)

    try:
        response = await call_deepseek(
            prompt=prompt,
            system_prompt=REVIEW_SYSTEM_PROMPT,
            timeout=45,
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=2000,
        )

        review = _parse_review_json(response)
        if not review:
            return _mock_review(predictions, feedbacks)

        # 应用权重调整
        adjustments_raw = review.get("weight_adjustments", [])
        adjustments = _normalize_adjustments(adjustments_raw)
        review["weight_adjustments"] = adjustments
        applied = apply_adjustments(session_id, adjustments) if session_id else None

        # 基于 error_analysis 生成校准建议
        suggested_actions = _generate_calibration_suggestions(review, predictions, feedbacks)
        review["suggested_actions"] = suggested_actions

        # 获取当前权重
        new_weights = get_user_weights(session_id) if session_id else {}

        return {
            "review": review,
            "applied": applied,
            "new_weights": new_weights,
            "suggested_actions": suggested_actions,
            "method": "ai_deepseek",
        }

    except Exception:
        return _mock_review(predictions, feedbacks, session_id=session_id)


def _parse_review_json(response: str) -> Optional[dict]:
    """从LLM响应中提取JSON"""
    # 尝试直接解析
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取 { ... } 块
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# Mock 复盘规则引擎
# ============================================================

# 反馈 note 关键词 → 错误层面映射
_MOCK_ERROR_PATTERNS = [
    # (category_keywords, note_keywords, primary_layer, explanation)
    # 兄弟关
    (("兄弟", "比劫"), ("一个", "独生", "只有", "没有", "少", "姐妹"), "shishen_layer",
     "兄弟数量判断错误：比劫多≠兄弟多，十神→六亲映射在此八字不适用"),
    (("兄弟", "比劫"), ("关系好", "和睦", "不错", "关系"), "shishen_layer",
     "兄弟关系判断错误：劫财争合推断过度"),

    # 父母关
    (("父母",), ("关系好", "和睦", "健康", "在", "没", "没死", "活着", "去世", "离异"), "pattern_layer",
     "父母断错误：年柱十神配六亲可能需查渊海子平原始定义"),
    (("父母",), ("富", "有钱", "生意", "经商", "从商"), "shishen_layer",
     "父母职业判断错误：六亲映射需参考渊海子平"),

    # 性格
    (("性格",), ("内向", "安静", "温和", "温柔", "不是", "相反"), "wangshuai_layer",
     "性格判断错误：日主旺衰判断可能偏差，导致性格特征错位"),
    (("性格",), ("急躁", "冲动", "暴", "刚", "强", "强势"), "wangshuai_layer",
     "性格判断错误：旺衰倾向可能需要调整"),

    # 学历
    (("学历",), ("高中", "中专", "初中", "大专", "低", "不", "没有", "没读"), "yongshen_layer",
     "学历判断错误：印星为用神/忌神的判断需修正"),

    # 婚姻关
    (("婚姻",), ("晚", "没结", "未婚", "离", "离异"), "yongshen_layer",
     "婚姻应期判断错误：用神/忌神在流年中的作用需修正"),
    (("婚姻",), ("幸福", "好", "不错"), "ai_overreach",
     "婚姻幸福度推断过度：典籍判断无误，AI润色过度"),

    # 事业
    (("事业", "工作"), ("不好", "一般", "普通", "打工", "上班", "事业单位", "失业"), "yongshen_layer",
     "事业判断错误：食伤/官杀为用忌的判断需修正"),
    (("事业", "工作"), ("好", "不错", "创业", "老板", "成功"), "yongshen_layer",
     "事业高度判断偏差：用神五行可能需要调整"),

    # 关键年份
    (("关键年份", "年份"), None, "wangshuai_layer",
     "关键年份判断错误：旺衰判断偏差导致大运流年分析不准"),
]

# 错误层面 → 权重调整动作
_MOCK_LAYER_ADJUSTMENTS = {
    "wangshuai_layer": [
        ("wangshuai:dishui", "reduce", 0.85, "滴天髓旺衰判断可能不符合此八字"),
        ("wangshuai:sanming", "boost", 1.10, "可参考三命通会的旺衰判断"),
    ],
    "pattern_layer": [
        ("pattern:ziping", "reduce", 0.85, "子平真诠格局判断可能不符合此八字"),
        ("shishen:yuanhai", "boost", 1.10, "六亲映射应参考渊海子平原始定义"),
    ],
    "yongshen_layer": [
        ("yongshen:ziping", "reduce", 0.88, "子平真诠用神取法可能不符合此八字"),
        ("yongshen:qiongtong", "boost", 1.10, "可参考穷通宝鉴的调候用神"),
    ],
    "shishen_layer": [
        ("pattern:ziping", "reduce", 0.88, "子平真诠十神→六亲映射可能不适用"),
        ("shishen:yuanhai", "boost", 1.15, "十神定义应参考渊海子平原始定义"),
    ],
    "ai_overreach": [
        ("wangshuai:dishui", "reduce", 0.93, "典籍判断无误，AI推理过度需轻微调整"),
    ],
}


def _analyze_error_layer(
    pred: dict, fb_note: str
) -> tuple[str, str, list[str]]:
    """根据预测类别和反馈内容，分析错误层面。

    Returns:
        (primary_layer, explanation, secondary_layers)
    """
    category = pred.get("category", "")
    note = fb_note

    # 遍历所有规则
    for cat_keywords, note_keywords, layer, explanation in _MOCK_ERROR_PATTERNS:
        # 检查类别匹配
        cat_match = any(kw in category for kw in cat_keywords)
        if not cat_match:
            continue

        # 检查 note 关键词匹配（None = 任意匹配）
        if note_keywords is None:
            return (layer, explanation, [])

        note_match = any(kw in note for kw in note_keywords)
        if note_match:
            return (layer, explanation, [])

    # 无匹配规则：默认按 depends_on 的第一个判断
    depends = pred.get("depends_on", [])
    if depends:
        first_dep = depends[0]
        if ":dishui" in first_dep:
            return ("wangshuai_layer", "无法精准定位，推测旺衰层", [])
        elif ":qiongtong" in first_dep:
            return ("yongshen_layer", "无法精准定位，推测用神层", [])
        elif ":yuanhai" in first_dep:
            return ("shishen_layer", "无法精准定位，推测十神层", [])

    return ("pattern_layer", "无法精准定位，推测格局层", [])


def _mock_review(predictions: list[dict], feedbacks: list[dict], session_id: str = "") -> dict:
    """Mock复盘：基于规则推导，不调用AI

    规则引擎流程：
    1. 对每条 inaccurate 反馈，分析 note 内容判断错误层面
    2. 按层面统计贡献度
    3. 对受影响的层面定向调整权重（reduce 错误典籍，boost 替代典籍）
    4. 避免全量机械降权

    Args:
        session_id: 用户session，用于将权重调整应用到正确的会话
    """
    fb_map = {f["prediction_id"]: f for f in feedbacks}
    inaccurate_count = 0
    layer_contributions = {layer: 0 for layer in _MOCK_LAYER_ADJUSTMENTS}
    layer_details = []

    for pred in predictions:
        fb = fb_map.get(pred["id"], {})
        if fb.get("status") != "inaccurate":
            continue

        inaccurate_count += 1
        note = fb.get("note", "")
        content = pred.get("content", "")

        # 分析错误层面
        primary_layer, explanation, _ = _analyze_error_layer(pred, note)
        layer_contributions[primary_layer] = layer_contributions.get(primary_layer, 0) + 1
        layer_details.append({
            "category": pred.get("category", ""),
            "content": content[:60],
            "feedback": note[:60],
            "diagnosed_layer": primary_layer,
            "explanation": explanation,
        })

    if inaccurate_count == 0:
        return {
            "review": {
                "overall_assessment": "全部预测准确，无需调整",
                "weight_adjustments": [],
            },
            "applied": None,
            "method": "mock_rule",
        }

    # 计算各层面贡献度（百分比）
    total_hits = sum(layer_contributions.values())
    error_analysis = {}
    for layer in _MOCK_LAYER_ADJUSTMENTS:
        count = layer_contributions.get(layer, 0)
        contribution = round(count / max(total_hits, 1), 2)
        layer_names = {
            "wangshuai_layer": "旺衰层",
            "pattern_layer": "格局层",
            "yongshen_layer": "用神层",
            "shishen_layer": "十神解读层",
            "ai_overreach": "AI过度推理",
        }
        # 找到该层面被诊断的具体原因
        reasons = [d["explanation"] for d in layer_details if d["diagnosed_layer"] == layer]
        reason = reasons[0] if reasons else f"{layer_names.get(layer, layer)}可能有偏差"
        error_analysis[layer] = {"contribution": contribution, "reason": reason}

    # 根据各层面命中次数生成权重调整
    # 使用集合去重：同一个 key 可能被多个诊断触发，取最强的 action
    adjustments_map = {}
    for layer, count in layer_contributions.items():
        if count == 0:
            continue
        for key, action, base_factor, reason in _MOCK_LAYER_ADJUSTMENTS.get(layer, []):
            # 多次命中同一层面则增强调整幅度
            factor = base_factor if action == "reduce" else base_factor + (count - 1) * 0.05
            factor = factor if action == "reduce" else min(base_factor + (count - 1) * 0.05, 1.25)

            if key not in adjustments_map:
                adjustments_map[key] = (action, factor, reason)
            else:
                # 同一 key 有多个调整，取更强的
                old_action, old_factor, old_reason = adjustments_map[key]
                if action == "boost" and old_action == "reduce":
                    # boost 和 reduce 冲突，取命中次数多的层面
                    adjustments_map[key] = (action, factor, reason)
                elif action == "reduce" and old_factor > factor:
                    # 取更强（更低）的 reduce
                    adjustments_map[key] = (action, factor, reason)
                elif action == "boost" and factor > old_factor:
                    # 取更强的 boost
                    adjustments_map[key] = (action, factor, reason)

    adjustments = []
    for key, (action, factor, reason) in adjustments_map.items():
        adjustments.append({
            "key": key,
            "action": action,
            "factor": round(factor, 3),
            "reason": reason,
        })

    # 整理综合评估
    layer_summary = []
    for layer, count in layer_contributions.items():
        if count > 0:
            layer_name = {
                "wangshuai_layer": "旺衰判断",
                "pattern_layer": "格局判断",
                "yongshen_layer": "用神判断",
                "shishen_layer": "十神解读",
                "ai_overreach": "AI推理",
            }.get(layer, layer)
            layer_summary.append(f"{layer_name}({count}条)")

    # --- 生成校准联动建议 ---
    suggested_actions = []
    wangshuai_cont = error_analysis.get("wangshuai_layer", {}).get("contribution", 0)
    pattern_cont = error_analysis.get("pattern_layer", {}).get("contribution", 0)
    combined_fundamental = wangshuai_cont + pattern_cont

    # 核心三关是否被标记 inaccurate
    core_categories = {"父母关", "兄弟关", "婚姻关"}
    core_inaccurate = sum(
        1 for d in layer_details
        if d["category"] in core_categories
    )

    if core_inaccurate >= 3:
        suggested_actions.append({
            "action": "recalibrate_time",
            "reason": (
                f"核心三关（父母/兄弟/婚姻）全部不准确，"
                f"极可能时辰或日柱有误。强烈建议换时辰校准。"
            ),
            "confidence": 0.85,
            "auto_trigger": False,
            "endpoint": "/api/calibrate/compare",
            "method": "POST",
            "params": {"session_id": session_id},
        })
    elif combined_fundamental >= 0.7 or (wangshuai_cont >= 0.4 and core_inaccurate >= 2):
        suggested_actions.append({
            "action": "recalibrate_time",
            "reason": (
                f"旺衰层+格局层错误占比{int(combined_fundamental*100)}%，"
                f"核心三关{core_inaccurate}条不准，可能时辰有误。"
                f"建议尝试换时辰重新排盘校准。"
            ),
            "confidence": round(combined_fundamental, 2),
            "auto_trigger": False,
            "endpoint": "/api/calibrate/compare",
            "method": "POST",
            "params": {"session_id": session_id},
        })
    elif wangshuai_cont >= 0.5:
        suggested_actions.append({
            "action": "recalibrate_time",
            "reason": f"旺衰层错误占{int(wangshuai_cont*100)}%，可能时辰或日主强弱判断有误",
            "confidence": round(wangshuai_cont, 2),
            "auto_trigger": False,
            "endpoint": "/api/calibrate/compare",
            "method": "POST",
            "params": {"session_id": session_id},
        })

    return {
        "review": {
            "overall_assessment": (
                f"{inaccurate_count}条预测不准确，主要涉及{', '.join(layer_summary)}。"
                f"共调整{len(adjustments)}个典籍权重。"
            ),
            "error_analysis": error_analysis,
            "weight_adjustments": adjustments,
            "diagnosis_details": layer_details,
            "suggested_actions": suggested_actions,
        },
        "applied": apply_adjustments(session_id or "mock_session", adjustments) if adjustments else None,
        "method": "mock_rule_v2",
        "suggested_actions": suggested_actions,
    }
