"""断前事生成模块 - 模拟大师"先断过去让命主验证，建立信任后再进入修正闭环"

支持两种模式：
1. Mock 模板（无 API Key 时）：基于规则引擎推导
2. AI 生成（有 DEEPSEEK_API_KEY 时）：调用 DeepSeek API

生成顺序严格遵循"过三关"规则：
  性格(1) → 父母关(2) → 兄弟关(3) → 学历(4) → 婚姻关(5) → 事业(6) → 关键年份(7)
"""

import os
import re
import json

from models import BaziChart, PreEventStatement

# ============================================================
# Phase 0: 以下旧生成函数 + 模板已删除
# - CATEGORY_DEPENDS_MAP
# - PERSONALITY_MAP
# - _build_personality, _build_parents, _build_siblings, _build_education, _build_marriage, _build_career, _build_key_years
# - generate_mock_predictions
# - PREDICTION_SYSTEM_PROMPT
# - generate_ai_predictions
# - generate_predictions
# - MOCK_BUILDER_ORDER
# ============================================================
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP, get_sheng, get_ke, get_i_sheng, get_i_ke
from services.deepseek_client import call_deepseek


# ============================================================
# 五行关系辅助
# ============================================================

# 六冲
CLASH_PAIRS = {
    "子": "午", "午": "子",
    "丑": "未", "未": "丑",
    "寅": "申", "申": "寅",
    "卯": "酉", "酉": "卯",
    "辰": "戌", "戌": "辰",
    "巳": "亥", "亥": "巳",
}


def _get_stem_wuxing(stem: str) -> str:
    """获取天干五行"""
    return WUXING_MAP.get(stem, "")


def _calc_ten_god_chars(day_master_stem: str, other_stem: str) -> str:
    """计算十神（返回中文名）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    ot_wx = WUXING_MAP.get(other_stem, "")
    if not dm_wx or not ot_wx:
        return ""
    # 阴阳
    YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
               "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
    same_yy = YINYANG.get(day_master_stem, -1) == YINYANG.get(other_stem, -1)
    if dm_wx == ot_wx:
        return "比肩" if same_yy else "劫财"
    if get_sheng(dm_wx) == ot_wx:
        return "偏印" if same_yy else "正印"
    if get_i_sheng(dm_wx) == ot_wx:
        return "食神" if same_yy else "伤官"
    if get_i_ke(dm_wx) == ot_wx:
        return "偏财" if same_yy else "正财"
    if get_ke(dm_wx) == ot_wx:
        return "七杀" if same_yy else "正官"
    return ""


def _count_bi_jie(day_master_stem: str, four_pillars: dict) -> int:
    """统计比劫数量（天干+地支藏干）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    count = 0
    for pos in ["year", "month", "hour"]:  # 跳过日柱本身
        pillar = four_pillars[pos]
        stem = pillar.get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == dm_wx:
            count += 1
        # 地支藏干
        branch = pillar.get("branch", "")
        for hs in HIDDEN_STEMS_MAP.get(branch, []):
            hs_wx = WUXING_MAP.get(hs.get("stem", ""), "")
            if hs_wx == dm_wx:
                count += 0.5
    return int(count)


def _count_yin_xing(day_master_stem: str, four_pillars: dict) -> int:
    """统计印星出现次数"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    yin_wx = get_sheng(dm_wx)
    count = 0
    for pos in ["year", "month", "day", "hour"]:
        pillar = four_pillars[pos]
        stem = pillar.get("stem", "")
        if WUXING_MAP.get(stem, "") == yin_wx:
            count += 1
        branch = pillar.get("branch", "")
        for hs in HIDDEN_STEMS_MAP.get(branch, []):
            if WUXING_MAP.get(hs.get("stem", ""), "") == yin_wx:
                count += 0.5
    return int(count)


def _is_yin_xing_solid(day_master_stem: str, four_pillars: dict) -> bool:
    """判断印星是否得地（月支为印星五行或有强根）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    yin_wx = get_sheng(dm_wx)
    month_branch = four_pillars.get("month", {}).get("branch", "")
    if WUXING_MAP.get(month_branch, "") == yin_wx:
        return True
    # 检查是否有印星天干透出
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        if WUXING_MAP.get(stem, "") == yin_wx:
            return True
    return False


def _has_guan_yin_xiang_sheng(day_master_stem: str, four_pillars: dict) -> bool:
    """判断是否有官印相生格局（事业倾向体制内）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    guan_wx = get_ke(dm_wx)      # 官杀五行
    yin_wx = get_sheng(dm_wx)    # 印星五行
    has_guan = False
    has_yin = False
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == guan_wx:
            has_guan = True
        if stem_wx == yin_wx:
            has_yin = True
    return has_guan and has_yin


def _has_shishang_sheng_cai(day_master_stem: str, four_pillars: dict) -> bool:
    """判断是否有食伤生财格局（事业倾向技术/创业）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    shishang_wx = get_i_sheng(dm_wx)  # 食伤五行
    cai_wx = get_i_ke(dm_wx)          # 财星五行
    has_shishang = False
    has_cai = False
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == shishang_wx:
            has_shishang = True
        if stem_wx == cai_wx:
            has_cai = True
    return has_shishang and has_cai


def _get_key_years(dayun: list, four_pillars: dict) -> list[int]:
    """获取关键年份（大运交接年 + 冲日支的年份）"""
    years = set()
    # 大运交接年份
    for i in range(len(dayun)):
        d = dayun[i]
        if hasattr(d, 'start_year'):
            years.add(d.start_year)
        elif isinstance(d, dict):
            years.add(d.get("start_year", 0))
        if i > 0 and i < len(dayun):
            prev = dayun[i - 1]
            prev_end = prev.end_year if hasattr(prev, 'end_year') else prev.get("end_year", 0)
            curr_start = d.start_year if hasattr(d, 'start_year') else d.get("start_year", 0)
            if prev_end and curr_start and prev_end != curr_start:
                years.add(prev_end)
        if len(years) >= 3:
            break
    return sorted([y for y in years if y > 0])[:3]


# ============================================================
# Mock 模板生成（无 API Key 时使用）
# ============================================================

# ============================================================
# Phase 0: PERSONALITY_MAP + _build_* 函数已删除
# ============================================================
# ============================================================
# Phase 0: _build_career + _build_key_years + generate_mock_predictions 已删除
# ============================================================


# ============================================================
# AI 生成（有 API Key 时）
# ============================================================

# ============================================================
# Phase 0: PREDICTION_SYSTEM_PROMPT + generate_ai_predictions + generate_predictions 已删除
# ============================================================


def _build_chart_summary(chart_data: dict) -> str:
    """构建排盘摘要供 AI 使用"""
    pillars = chart_data.get("four_pillars", {})
    day_master = chart_data.get("day_master", "")
    yongshen = chart_data.get("yongshen", {})
    dayun = chart_data.get("dayun", [])

    lines = ["## 排盘数据"]
    current_age = chart_data.get("current_age", 0)
    current_year = chart_data.get("current_year", 0)
    # 年龄信息，约束AI推断时间节点
    if current_age > 0:
        lines.append(f"命主当前年龄：{current_age}岁（{current_year}年），请在近过去时间范围内推断")
        lines.append(f"重要约束：你推断的所有事件必须是十年内已经发生的事，不要推断未来。")
        lines.append(f"例如：27岁的人，说'25岁左右有过变动'是合理的，说'中年后'是不合理的。")
        birth_year = chart_data.get("birth_year", 0)
        if birth_year:
            kaoyear = birth_year + 18
            lines.append(f"硬性约束：命主出生于{birth_year}年，高考/升学大约在{kaoyear}年前后。所有涉及时间的推断必须基于命主实际出生年计算，禁止使用训练数据中的默认年份（如'2014年高考'等）。")
    lines.append(f"日主：{day_master}（五行{WUXING_MAP.get(day_master, '')}）")

    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        stem = p.get("stem", "")
        branch = p.get("branch", "")
        stem_tg = p.get("stem_ten_god", "")
        hidden = p.get("hidden_stems", [])
        hidden_str = "、".join([f"{h.get('stem','')}({h.get('ten_god','')})" for h in hidden])
        lines.append(f"{pos_names[pos]}：{stem}{branch} 天干十神={stem_tg} 藏干=[{hidden_str}] 纳音={p.get('nayin','')}")

    # 用神
    ys_primary = yongshen.get("primary", "")
    ys_pattern = yongshen.get("pattern", "")
    lines.append(f"用神：{ys_primary}，格局：{ys_pattern}")

    # 大运摘要
    lines.append("大运：")
    for d in dayun[:6]:
        lines.append(f"  {d.get('stem','')}{d.get('branch','')}({d.get('ten_god','')})"
                     f" {d.get('start_age','')}-{d.get('end_age','')}岁"
                     f" ({d.get('start_year','')}-{d.get('end_year','')})")

    # 神煞
    shensha = chart_data.get("shensha", [])
    if shensha:
        ss_str = "、".join([f"{s.get('name','')}({s.get('position','')})" for s in shensha])
        lines.append(f"神煞：{ss_str}")

    return "\n".join(lines)


def _parse_predictions_json(response: str) -> list[dict]:
    """从 AI 响应中解析 predictions JSON 数组"""
    # 尝试直接解析
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 数组
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


# ============================================================
# Phase 0: generate_ai_predictions 已删除
# ============================================================


# ============================================================
# Phase 0: generate_predictions 主函数已删除
# ============================================================


# ============================================================
# 动态题量：AI 判断信息是否充足 + 逐条生成
# ============================================================

MAX_PREDICTIONS = 10  # 上限保护：最多问 10 条
CORE_GATES = {"父母关", "兄弟关", "婚姻关"}  # 核心三关

# ============================================================
# Phase 0: MOCK_BUILDER_ORDER 已删除
# ============================================================

JUDGE_SUFFICIENT_PROMPT = """你是一位命理师。系统已经向用户提出了以下断事问题，用户给出了反馈。

已问的问题和反馈：
{predictions_with_feedback}

请判断：根据目前的反馈情况，信息是否已经足够进行命盘校准和未来预测？

判断标准：
- 核心三关（父母、兄弟、婚姻）是否都已涉及且用户给出了明确反馈？
- 用户的反馈是否足够一致（没有大量矛盾）？
- 再继续问下去，获取新信息的边际收益是否已经很低？

如果信息充足，返回JSON：{{"sufficient": true, "reason": "已覆盖核心三关且用户反馈一致"}}
如果还需要继续，返回JSON：{{"sufficient": false, "suggestion": "下一题可以从XX角度问"}}

只返回JSON，不要包含其他内容。"""


def _core_gates_covered(asked_categories: set) -> bool:
    """检查核心三关（父母、兄弟、婚姻）是否都已涉及"""
    return CORE_GATES.issubset(asked_categories)


def _get_next_category_suggestion(asked_categories: set) -> str:
    """根据已问类别，建议下一题方向"""
    all_categories = ["性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"]
    remaining = [c for c in all_categories if c not in asked_categories]
    if not remaining:
        return "建议换个角度深入询问"
    # 优先建议核心三关
    core_remaining = [c for c in remaining if c in CORE_GATES]
    if core_remaining:
        return f"建议下一题涉及{core_remaining[0]}"
    return f"建议下一题涉及{remaining[0]}"


def judge_info_sufficient(
    chart_data: dict,
    asked_predictions: list[dict],
    feedbacks: list[dict],
) -> dict:
    """判断当前信息是否足够进行命盘校准

    双模式：
    - 无 API Key：如果已问 >= 5 条且核心三关已覆盖 → sufficient=True
    - 有 API Key：至少3条后调用 DeepSeek AI 判断

    Args:
        chart_data: 排盘数据（预留）
        asked_predictions: 已经问过的推断列表
        feedbacks: 用户反馈列表

    Returns:
        {"sufficient": bool, "reason": str, "next_suggestion": str}
    """
    asked_count = len(asked_predictions)
    asked_categories = {p.get("category", "") for p in asked_predictions}

    # 上限保护
    if asked_count >= MAX_PREDICTIONS:
        return {
            "sufficient": True,
            "reason": f"已达到最大题量（{MAX_PREDICTIONS}条），信息已充足",
            "next_suggestion": "可以进入校准分析了",
        }

    # 无 API Key 时使用 Mock 逻辑
    if not os.getenv("DEEPSEEK_API_KEY"):
        if asked_count >= 5 and _core_gates_covered(asked_categories):
            return {
                "sufficient": True,
                "reason": "已覆盖核心三关且达到最小题量",
                "next_suggestion": "可以进入下一步了",
            }
        return {
            "sufficient": False,
            "reason": "还需继续收集信息",
            "next_suggestion": _get_next_category_suggestion(asked_categories),
        }

    # 有 API Key 时：至少问 3 条再让 AI 判断
    if asked_count < 3:
        return {
            "sufficient": False,
            "reason": "题量不足（至少3条后才触发AI判断）",
            "next_suggestion": _get_next_category_suggestion(asked_categories),
        }

    # 同步方式调用 AI（在主函数中用 run_ai_judge 处理）
    # 这里返回一个标记，让调用方知道需要异步处理
    return {
        "sufficient": False,
        "reason": "需要AI判断",
        "next_suggestion": "",
        "_needs_ai": True,
    }


async def run_ai_judge_sufficient(
    asked_predictions: list[dict],
    feedbacks: list[dict],
) -> dict:
    """异步调用 AI 判断信息是否充足"""
    # 构建问题+反馈文本
    lines = []
    for pred in asked_predictions:
        pid = pred.get("id", "")
        category = pred.get("category", "")
        content = pred.get("content", "")
        fb = next((f for f in feedbacks if f.get("prediction_id") == pid), None)
        fb_status = fb.get("status", "未反馈") if fb else "未反馈"
        fb_note = fb.get("note", "") if fb else ""

        line = f"- [{category}] {content}\n  用户反馈：{fb_status}"
        if fb_note:
            line += f"（{fb_note}）"
        lines.append(line)

    predictions_text = "\n".join(lines)
    prompt = JUDGE_SUFFICIENT_PROMPT.format(predictions_with_feedback=predictions_text)

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是一位经验丰富的命理师。只返回JSON格式的判断结果。",
            timeout=30,
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=300,
        )

        if content and not content.startswith("[API_"):
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
                return {
                    "sufficient": bool(result.get("sufficient", False)),
                    "reason": result.get("reason", ""),
                    "next_suggestion": result.get("suggestion", ""),
                }
    except Exception:
        pass

    # AI 调用失败，回退到 Mock 逻辑
    asked_count = len(asked_predictions)
    asked_categories = {p.get("category", "") for p in asked_predictions}
    if asked_count >= 5 and _core_gates_covered(asked_categories):
        return {
            "sufficient": True,
            "reason": "已覆盖核心三关（AI判断回退）",
            "next_suggestion": "可以进入下一步了",
        }
    return {
        "sufficient": False,
        "reason": "还需继续收集信息（AI判断回退）",
        "next_suggestion": _get_next_category_suggestion(asked_categories),
    }


async def generate_single_prediction(
    chart: BaziChart,
    chart_data: dict,
    asked_categories: set,
    feedbacks: list[dict],
) -> PreEventStatement | None:
    """动态生成下一条推断（AI+Mock 双模式）

    根据已问类别和用户反馈，动态生成一条新的推断。

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据字典
        asked_categories: 已经问过的类别集合
        feedbacks: 用户反馈列表

    Returns:
        下一条 PreEventStatement，如果无法生成返回 None
    """
    seq = len(asked_categories) + 1

    # 优先 AI 生成
    if os.getenv("DEEPSEEK_API_KEY"):
        ai_pred = await _ai_generate_single(chart, chart_data, asked_categories, feedbacks, seq)
        if ai_pred:
            return ai_pred

    # 回退到 Mock：从剩余类别中选下一个
    return _mock_generate_single(chart, asked_categories, seq)


async def _ai_generate_single(
    chart: BaziChart,
    chart_data: dict,
    asked_categories: set,
    feedbacks: list[dict],
    seq: int,
) -> PreEventStatement | None:
    """使用 AI 生成单条推断"""
    summary = _build_chart_summary(chart_data)

    asked_lines = []
    for cat in sorted(asked_categories):
        asked_lines.append(f"- 已问：{cat}")
    asked_info = "\n".join(asked_lines) if asked_lines else "（尚无）"

    fb_lines = []
    for fb in feedbacks:
        pid = fb.get("prediction_id", "")
        fb_lines.append(
            f"- {pid}: {fb.get('status', '')}"
            + (f"（{fb.get('note', '')}）" if fb.get("note") else "")
        )
    fb_info = "\n".join(fb_lines) if fb_lines else "（尚无反馈）"

    prompt = f"""{summary}

已知用户已经回答了以下类别的问题：
{asked_info}

用户对已有问题的反馈：
{fb_info}

请生成第{seq}条断前事推断。要求：
1. 选择上述"已问"中没有涉及的新类别，优先核心三关（父母关、兄弟关、婚姻关）
2. 如果前面的推断中用户反馈某个方向不准，请换一个角度
3. 推断必须具体、可验证，引用典籍原文（《滴天髓》《子平真诠》《渊海子平》《穷通宝鉴》）
4. 每条推断2-3句话

输出格式（严格JSON，不要包含任何其他内容）：
[{{
  "id": "pred_{seq:02d}",
  "category": "分类",
  "is_core": false,
  "sequence": {seq},
  "title": "标题",
  "content": "推断内容",
  "classical_quote": "《X书》：引用原文",
  "basis": "命理依据简述",
  "confidence": 0.85
}}]"""

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是一位严格遵循子平派体系的命理师，拥有30年实战经验。只返回JSON格式的单条推断。",
            timeout=30,
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=800,
        )

        if content and not content.startswith("[API_"):
            items = _parse_predictions_json(content)
            if items:
                item = items[0] if isinstance(items, list) else items
                cat = item.get("category", "")
                return PreEventStatement(
                    id=item.get("id", f"pred_{seq:02d}"),
                    category=cat,
                    is_core=cat in CORE_GATES,
                    sequence=seq,
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    classical_quote=item.get("classical_quote", ""),
                    basis=item.get("basis", ""),
                    confidence=float(item.get("confidence", 0.8)),
                )
    except Exception:
        pass

    return None


def _mock_generate_single(
    chart: BaziChart,
    asked_categories: set,
    seq: int,
) -> PreEventStatement | None:
    """[Phase 0: 已废弃] 旧 Mock 模板生成，V2 不再使用。返回 None。"""
    return None


# ============================================================
# P0 Module 8: 高区分度断事智能选取
# ============================================================


class SmartPredictionSelector:
    """高区分度断事智能选取器

    三方评分：理论区分度(5分) + 参数覆盖度(3分) + 用户友好度(2分)，满分10分。

    理论依据：
    - "过三关"：《渊海子平》传统验证方法论，父母关/兄弟关/婚姻关 是命理检验的核心
    - 高区分度优先：优先选择理论区隔度高的类别验证命盘
    - 动态题量：连续3条"不确定" → 降为3题，降低用户疲劳度

    使用方式：
        selector = SmartPredictionSelector()
        selected = selector.select_top_predictions(candidates, uncertainty, history)
    """

    BASE_DISCRIMINATION = {
        "父母关": 8,
        "兄弟关": 7,
        "婚姻关": 7,
        "学历": 6,
        "事业": 5,
        "关键年份": 5,
        "性格": 3,
    }

    # "过三关"加成：父母关/兄弟关/婚姻关 +0.5 理论分
    CORE_GATE_BONUS = {"父母关": 0.5, "兄弟关": 0.5, "婚姻关": 0.5}

    # 每个类别的大致回答时间（分钟）
    ESTIMATED_TIME = {
        "父母关": 2.0,
        "兄弟关": 1.5,
        "婚姻关": 2.0,
        "学历": 1.0,
        "事业": 1.5,
        "关键年份": 2.5,
        "性格": 1.0,
    }

    def calculate_discrimination_score(
        self,
        prediction: dict,
        uncertainty: dict = None,
        history: dict = None,
    ) -> dict:
        """计算单个预测的综合区分度得分。

        三方评分：
        - 理论区分度(5分)：基于 BASE_DISCRIMINATION + 过三关加成
        - 参数覆盖度(3分)：基于不确定性参数覆盖
        - 用户友好度(2分)：基于回答难度和用时

        Args:
            prediction: 单条预测 dict，含 "category" 字段
            uncertainty: 不确定性报告 dict（可选）
            history: 历史反馈 dict（可选）

        Returns:
            dict: {"category": str, "total": float, "detail": {...}}
        """
        if uncertainty is None:
            uncertainty = {}
        if history is None:
            history = {}

        category = prediction.get("category", "")

        # 1. 理论区分度 (max 5)
        base = self.BASE_DISCRIMINATION.get(category, 5)
        # 归一化到 0-5
        theory_score = min(5.0, base / 10.0 * 5.0)

        # 过三关加成 (+0.5 for core gates)
        gate_bonus = self.CORE_GATE_BONUS.get(category, 0.0)
        theory_score = min(5.0, theory_score + gate_bonus)

        # 2. 参数覆盖度 (max 3)
        uncertainty_score = self._calc_uncertainty_coverage(
            category, uncertainty
        )

        # 3. 用户友好度 (max 2)
        friendliness_score = self._calc_friendliness(category, history)

        total = theory_score + uncertainty_score + friendliness_score

        return {
            "category": category,
            "total": round(total, 2),
            "detail": {
                "theory": round(theory_score, 2),
                "uncertainty_coverage": round(uncertainty_score, 2),
                "friendliness": round(friendliness_score, 2),
            },
        }

    def _calc_uncertainty_coverage(
        self, category: str, uncertainty: dict
    ) -> float:
        """计算该类别覆盖了多少不确定参数维度。

        参数覆盖度满分 3 分，根据类别的溯源依赖匹配不确定性维度。
        """
        from services.precheck.uncertainty_labeler import UncertaintyReport

        overall_risk = uncertainty.get("overall_risk", 0.0)

        # 基于 overall_risk 计算覆盖分
        # overall_risk 越高 → 该预测越有验证价值 → 得分越高
        score = min(3.0, overall_risk * 3.0)
        return round(score, 2)

    def _calc_friendliness(
        self, category: str, history: dict = None
    ) -> float:
        """计算用户友好度，基于回答难度和时间。

        用户友好度满分 2 分：
        - 越容易回答的类别得分越高
        - 已经被问过的类别得分降低
        """
        if history is None:
            history = {}

        time = self.ESTIMATED_TIME.get(category, 2.0)
        # 时间越短越友好：用 1/time 归一化
        # max_time = 2.5 (关键年份), so 1.0/2.5 = 0.4, 2*0.4 = 0.8
        # min_time = 1.0 (学历/性格), so 1.0/1.0 = 1.0, 2*1.0 = 2.0
        raw_score = (1.0 / max(time, 0.5)) * 2.0
        score = min(2.0, raw_score)

        # 历史惩罚：如果该类已被问过，略微降低
        asked_count = history.get("asked_counts", {}).get(category, 0)
        if asked_count > 0:
            score = max(0.5, score - asked_count * 0.3)

        return round(score, 2)

    def select_top_predictions(
        self,
        candidates: list[dict],
        uncertainty: dict = None,
        history: dict = None,
        max_count: int = 5,
    ) -> list[dict]:
        """从候选中选取高分预测，最多 max_count 条。

        动态题量：
        - 连续3条"不确定"(supplement) → max_count 降为3

        Args:
            candidates: 候选预测列表 [{"id": "pred_01", "category": "父母关", ...}]
            uncertainty: 不确定性报告 dict
            history: 历史反馈 dict {
                "supplement_streak": int,  # 连续不确定次数
                "asked_counts": dict,       # 各分类已被问次数
            }
            max_count: 最大选取数量

        Returns:
            list[dict]: 按综合得分降序排列的预测列表
        """
        if uncertainty is None:
            uncertainty = {}
        if history is None:
            history = {}

        # 动态题量：连续3条"不确定" → 降为3题
        supplement_streak = history.get("supplement_streak", 0)
        if supplement_streak >= 3:
            max_count = 3

        # 计算每个候选项的得分
        scored = []
        for candidate in candidates:
            score = self.calculate_discrimination_score(
                candidate, uncertainty, history
            )
            scored.append((candidate, score))

        # 按得分降序排列
        scored.sort(key=lambda x: x[1]["total"], reverse=True)

        # 选取前 max_count 条
        selected = [s[0] for s in scored[:max_count]]
        return selected

