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
        adjustments = review.get("weight_adjustments", [])
        applied = apply_adjustments(session_id, adjustments) if session_id else None

        return {
            "review": review,
            "applied": applied,
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
# Mock 复盘（无 API Key 时的规则推导）
# ============================================================

def _mock_review(predictions: list[dict], feedbacks: list[dict], session_id: str = "") -> dict:
    """Mock复盘：基于规则推导，不调用AI

    Args:
        session_id: 用户session，用于将权重调整应用到正确的会话
    """
    fb_map = {f["prediction_id"]: f for f in feedbacks}
    inaccurate_count = 0
    inaccurate_categories = []

    for pred in predictions:
        fb = fb_map.get(pred["id"], {})
        if fb.get("status") == "inaccurate":
            inaccurate_count += 1
            inaccurate_categories.append(pred.get("category", ""))

    if inaccurate_count == 0:
        return {
            "review": {
                "overall_assessment": "全部预测准确，无需调整",
                "weight_adjustments": [],
            },
            "applied": None,
            "method": "mock_rule",
        }

    # 统计每个阶段×典籍被标记 inaccurate 的次数
    stage_corpus_hits = {}
    for pred in predictions:
        fb = fb_map.get(pred["id"], {})
        if fb.get("status") == "inaccurate":
            for dep in pred.get("depends_on", []):
                stage_corpus_hits[dep] = stage_corpus_hits.get(dep, 0) + 1

    adjustments = []
    for key, hits in stage_corpus_hits.items():
        factor = max(0.80, 1.0 - hits * 0.10)
        adjustments.append({
            "key": key,
            "action": "reduce",
            "factor": factor,
            "reason": f"在 {inaccurate_count} 条 inaccurate 反馈中被标记 {hits} 次",
        })

    return {
        "review": {
            "overall_assessment": f"{inaccurate_count}条预测不准确，涉及{len(adjustments)}个典籍权重",
            "error_analysis": {
                "wangshuai_layer": {"contribution": 0.3, "reason": "旺衰判断可能有偏差"},
                "pattern_layer": {"contribution": 0.3, "reason": "格局判断可能有偏差"},
                "yongshen_layer": {"contribution": 0.2, "reason": "用神判断可能有偏差"},
                "shishen_layer": {"contribution": 0.1, "reason": "十神解读可能有偏差"},
                "ai_overreach": {"contribution": 0.1, "reason": "AI推理可能有偏差"},
            },
            "weight_adjustments": adjustments,
        },
        "applied": apply_adjustments(session_id or "mock_session", adjustments) if adjustments else None,
        "method": "mock_rule",
    }
