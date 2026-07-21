"""P1 Phase 2: 校验判定逻辑

用户完成全部7条反馈后，系统进行校验判定，决定是否进入修正闭环。

判定规则：
1. 核心三关（父母关、兄弟关、婚姻关）：每关 accurate 条数 >= 该关总条数 × 50% → 通过
   - "不确定" 不参与计数
2. 辅助项（性格、学历、事业、关键年份）：accurate + partial >= 50% → 通过
3. 最终判定：根据核心三关通过数和辅助通过数，决定修正路径
"""

from typing import Optional


def judge_core_gates(
    feedbacks: list[dict], predictions: list[dict]
) -> dict:
    """
    核心三关判定：父母关 + 兄弟关 + 婚姻关

    每关计算规则：该关 accurate 条数 >= 该关总条数 × 50% → 该关通过
    "不确定"(supplement) 不参与计数

    Args:
        feedbacks: 用户反馈列表 [{"prediction_id": "pred_01", "status": "accurate", ...}]
        predictions: 推断列表 [{"id": "pred_01", "category": "性格", "is_core": true, ...}]

    Returns:
        {
            "parent_pass": bool,
            "sibling_pass": bool,
            "marriage_pass": bool,
            "pass_count": int,
            "fail_count": int,
            "need_correction": bool,  # fail_count >= 2 时需要修正
            "details": {
                "parent": {"accurate": int, "total": int, "pass": bool},
                "sibling": {"accurate": int, "total": int, "pass": bool},
                "marriage": {"accurate": int, "total": int, "pass": bool},
            }
        }
    """
    # 构建 prediction_id → prediction 的映射
    pred_map = {p["id"]: p for p in predictions}

    # 构建 prediction_id → feedback 的映射
    fb_map = {f["prediction_id"]: f for f in feedbacks}

    # 找出核心三关对应的 prediction_id
    core_gates = {
        "parent": {"pred_ids": [], "name": "父母关"},
        "sibling": {"pred_ids": [], "name": "兄弟关"},
        "marriage": {"pred_ids": [], "name": "婚姻关"},
    }

    for p in predictions:
        if p.get("is_core"):
            category = p.get("category", "")
            if "父母" in category:
                core_gates["parent"]["pred_ids"].append(p["id"])
            elif "兄弟" in category:
                core_gates["sibling"]["pred_ids"].append(p["id"])
            elif "婚姻" in category:
                core_gates["marriage"]["pred_ids"].append(p["id"])

    # 对每关进行判定
    results = {"details": {}}
    pass_count = 0
    fail_count = 0

    for gate_key, gate_info in core_gates.items():
        accurate = 0
        total_valid = 0  # 排除"不确定"（supplement）

        for pred_id in gate_info["pred_ids"]:
            fb = fb_map.get(pred_id, {})
            status = fb.get("status", "")

            if status == "supplement":
                # "不确定"不参与计数
                continue

            total_valid += 1
            if status == "accurate":
                accurate += 1
            # "partial" 和 "inaccurate" 也算参与但不计入 accurate

        # 计算通过与否：accurate >= total × 0.5
        if total_valid == 0:
            passed = False  # 无有效反馈，默认不通过
        else:
            passed = accurate >= total_valid * 0.5

        if passed:
            pass_count += 1
        else:
            fail_count += 1

        gate_result = {
            "accurate": accurate,
            "total": total_valid,
            "pass": passed,
            "name": gate_info["name"],
        }
        results["details"][gate_key] = gate_result

    results["parent_pass"] = results["details"]["parent"]["pass"]
    results["sibling_pass"] = results["details"]["sibling"]["pass"]
    results["marriage_pass"] = results["details"]["marriage"]["pass"]
    results["pass_count"] = pass_count
    results["fail_count"] = fail_count
    results["need_correction"] = fail_count >= 2

    return results


def judge_auxiliary(
    feedbacks: list[dict], predictions: list[dict]
) -> dict:
    """
    辅助项判定：非核心三关的项目

    判定规则：accurate + partial >= 50% 即通过

    Args:
        feedbacks: 用户反馈列表
        predictions: 推断列表

    Returns:
        {
            "pass_count": int,
            "total": int,
            "details": [{"category": str, "accurate": int, "partial": int, "total": int, "pass": bool}]
        }
    """
    pred_map = {p["id"]: p for p in predictions}
    fb_map = {f["prediction_id"]: f for f in feedbacks}

    # 找出非核心项的 prediction_id
    aux_items = {}
    for p in predictions:
        if not p.get("is_core"):
            category = p.get("category", "")
            pred_id = p["id"]
            aux_items[pred_id] = category

    pass_count = 0
    total_aux = len(aux_items)
    details = []

    for pred_id, category in aux_items.items():
        fb = fb_map.get(pred_id, {})
        status = fb.get("status", "")

        accurate = 1 if status == "accurate" else 0
        partial = 1 if status == "partial" else 0
        total_valid = 1  # 每条辅助项算1条

        # accurate + partial >= 50% → 通过
        passed = (accurate + partial) >= total_valid * 0.5

        if passed:
            pass_count += 1

        details.append({
            "category": category,
            "accurate": accurate,
            "partial": partial,
            "total": total_valid,
            "pass": passed,
        })

    return {
        "pass_count": pass_count,
        "total": total_aux,
        "details": details,
    }


def final_verdict(core: dict, aux: dict) -> dict:
    """
    综合分析核心三关和辅助项的判定结果，给出最终判定。

    判定逻辑：
    - 三关全过 (pass_count=3) + 辅助≥2通过 → verdict: "passed"，进入断未来
    - 三关全过 (pass_count=3) + 辅助<2通过 → verdict: "ai_fix"，走路径二
    - 三关≥2通过 + 辅助≥2通过 → verdict: "ai_fix_first"，先路径二，无效再路径一
    - 三关≤1通过 → verdict: "hour_fix"，走路径一（时钟修正）
    - 三关=0通过 → verdict: "hour_fix"（必须时钟修正）

    Args:
        core: judge_core_gates 返回结果
        aux: judge_auxiliary 返回结果

    Returns:
        {
            "verdict": "passed" | "ai_fix" | "hour_fix" | "ai_fix_first",
            "verdict_label": str,  # 中文描述
            "core_pass_count": int,
            "core_fail_count": int,
            "aux_pass_count": int,
            "aux_total": int,
            "suggestion": str,  # 修正建议
        }
    """
    core_pass = core["pass_count"]
    core_fail = core["fail_count"]
    aux_pass = aux["pass_count"]
    aux_total = aux["total"]

    if core_pass == 3 and aux_pass >= 2:
        verdict = "passed"
        verdict_label = "校验通过"
        suggestion = "核心三关全部通过，辅助项准确率良好。命盘准确度较高，可以进入断未来环节。"
    elif core_pass == 3 and aux_pass < 2:
        verdict = "ai_fix"
        verdict_label = "需AI修正"
        suggestion = "核心三关通过但辅助项偏差较大，建议通过AI重新判断旺衰/格局/用神来修正。"
    elif core_pass >= 2 and aux_pass >= 2:
        verdict = "ai_fix_first"
        verdict_label = "建议先AI修正，必要时再时钟修正"
        suggestion = "核心三关基本通过，先尝试AI修正路径（旺衰/格局/用神）。如AI修正无效，再考虑时钟修正。"
    elif core_pass >= 2 and aux_pass < 2:
        verdict = "ai_fix"
        verdict_label = "需AI修正"
        suggestion = "核心三关基本通过但辅助项偏差大，建议AI修正旺衰/格局判断。"
    elif core_pass <= 1:
        verdict = "hour_fix"
        verdict_label = "需时钟修正"
        suggestion = "核心三关准确率过低，大概率是出生时钟有误。建议先进行时钟修正（±1、±2时辰）。"
    else:
        # Fallback
        verdict = "ai_fix_first"
        verdict_label = "需修正"
        suggestion = "反馈结果不理想，建议进行修正。优先尝试AI修正路径。"

    return {
        "verdict": verdict,
        "verdict_label": verdict_label,
        "core_pass_count": core_pass,
        "core_fail_count": core_fail,
        "aux_pass_count": aux_pass,
        "aux_total": aux_total,
        "suggestion": suggestion,
    }


def run_calibration(
    feedbacks: list[dict], predictions: list[dict]
) -> dict:
    """
    执行完整的校验判定流程。

    Args:
        feedbacks: 用户反馈列表
        predictions: 推断列表

    Returns:
        完整的校验结果，包含 core、aux、verdict 三个部分
    """
    core = judge_core_gates(feedbacks, predictions)
    aux = judge_auxiliary(feedbacks, predictions)
    verdict = final_verdict(core, aux)

    return {
        "core": core,
        "auxiliary": aux,
        "verdict": verdict,
    }


# ============================================================
# P0 Module 2+3: 六维验证评分卡 + 三重判定
# ============================================================


class HexagramValidator:
    """六维验证评分卡

    六大验证维度，每个维度 0-10 分，输出打分依据 + 古籍引用。

    理论依据：
    - 《滴天髓·旺衰》"能知衰旺之真机，其于三命之奥，思过半矣"
    - 《子平真诠·论用神成败得失》"用神之成，在于得护得救"
    - 《滴天髓·真假》"令上寻真聚得真，假神休要乱真神"
    - 《子平真诠·论行运成格变格》"大运交脱之际，亦为人生之转折点"
    - 《渊海子平·六亲总篇》"用日干为主：正印正母；偏印偏母及祖父也"
    - 《滴天髓·论性情》"五气不戾，性正情和；浊乱偏枯，性乖情逆"
    """

    SOURCES = {
        "旺衰验证": "《滴天髓·旺衰》：'能知衰旺之真机，其于三命之奥，思过半矣'",
        "格局喜忌验证": "《子平真诠·论用神成败得失》：'用神之成，在于得护得救。用神之败，在于被伤被破'",
        "用神验证": "《滴天髓·真假》：'令上寻真聚得真，假神休要乱真神'",
        "大运走向验证": "《子平真诠·论大运流年》：'大运交脱之际，亦为人生之转折点'",
        "六亲验证": "《渊海子平·六亲总篇》：'用日干为主：正印正母；偏印偏母及祖父也'",
        "性格验证": "《滴天髓·论性情》：'五气不戾，性正情和；浊乱偏枯，性乖情逆'",
    }

    def score_wangshuai(
        self,
        feedback_stats: dict,
        yongshen_data: dict,
    ) -> dict:
        """旺衰验证 (0-10)

        通过反馈中的"运势好坏"条目与用神喜忌的一致性来打分。
        大运吉凶方向反推法：统计喜神运中 positive 反馈的比例。

        Args:
            feedback_stats: 反馈统计数据
            yongshen_data: 用神分析数据

        Returns:
            dict: {"dimension": "旺衰验证", "score": int, "detail": str, "source": str}
        """
        # 获取 basic 信息
        accurate = feedback_stats.get("accurate_count", 0)
        inaccurate = feedback_stats.get("inaccurate_count", 0)
        total = feedback_stats.get("total_count", 0)

        if total == 0:
            return {
                "dimension": "旺衰验证",
                "score": 5,
                "detail": "无反馈数据可供评估旺衰",
                "source": self.SOURCES["旺衰验证"],
            }

        score = min(10, int((accurate / max(total, 1)) * 10))
        detail = f"旺衰判断准确率 {accurate}/{total}，得分 {score}/10"

        return {
            "dimension": "旺衰验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["旺衰验证"],
        }

    def score_pattern_jixi(
        self,
        feedback_stats: dict,
        pattern_data: dict,
    ) -> dict:
        """格局喜忌验证 (0-10)

        通过用户反馈的喜忌方向与格局喜忌规则的匹配度来打分。

        Args:
            feedback_stats: 反馈统计数据
            pattern_data: 格局相关数据

        Returns:
            dict: {"dimension": "格局喜忌验证", "score": int, "detail": str, "source": str}
        """
        accurate = feedback_stats.get("accurate_count", 0)
        inaccurate = feedback_stats.get("inaccurate_count", 0)
        total = feedback_stats.get("total_count", 0)

        if total == 0:
            return {
                "dimension": "格局喜忌验证",
                "score": 5,
                "detail": "无反馈数据可供评估格局喜忌",
                "source": self.SOURCES["格局喜忌验证"],
            }

        score = min(10, int((accurate / max(total, 1)) * 10))
        detail = f"格局喜忌匹配度 {accurate}/{total}，得分 {score}/10"

        return {
            "dimension": "格局喜忌验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["格局喜忌验证"],
        }

    def score_yongshen(
        self,
        feedback_stats: dict,
        bazi_data: dict,
    ) -> dict:
        """用神验证 (0-10)

        选取 >=3 个用神透干的流年反馈，检查用户验证情况。

        Args:
            feedback_stats: 反馈统计数据
            bazi_data: 八字排盘数据

        Returns:
            dict: {"dimension": "用神验证", "score": int, "detail": str, "source": str}
        """
        accurate = feedback_stats.get("accurate_count", 0)
        total = feedback_stats.get("total_count", 0)
        ys_years_verified = feedback_stats.get("yongshen_years_verified", 0)

        if total == 0:
            return {
                "dimension": "用神验证",
                "score": 5,
                "detail": "无反馈数据可供评估用神",
                "source": self.SOURCES["用神验证"],
            }

        # 用神专项验证
        if ys_years_verified >= 3:
            score = min(10, int((accurate / max(total, 1)) * 10))
            detail = f"用神验证 {accurate}/{total}，用神年份专项验证 {ys_years_verified} 个"
        else:
            score = min(10, int((accurate / max(total, 1)) * 10))
            detail = f"用神验证 {accurate}/{total}，用神年份专项验证不足3个({ys_years_verified})"

        return {
            "dimension": "用神验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["用神验证"],
        }

    def score_dayun(
        self,
        feedback_stats: dict,
        dayun_data: dict,
    ) -> dict:
        """大运走向验证 (0-10)

        检验大运转换点的反馈是否与喜忌转变方向一致。

        Args:
            feedback_stats: 反馈统计数据
            dayun_data: 大运相关数据

        Returns:
            dict: {"dimension": "大运走向验证", "score": int, "detail": str, "source": str}
        """
        accurate = feedback_stats.get("accurate_count", 0)
        total = feedback_stats.get("total_count", 0)
        dayun_transitions = feedback_stats.get("dayun_transitions", 0)
        dayun_matched = feedback_stats.get("dayun_matched", 0)

        if total == 0 or dayun_transitions == 0:
            return {
                "dimension": "大运走向验证",
                "score": 5,
                "detail": "无大运转换反馈数据",
                "source": self.SOURCES["大运走向验证"],
            }

        score = min(10, int((dayun_matched / max(dayun_transitions, 1)) * 10))
        detail = f"大运转换验证 {dayun_matched}/{dayun_transitions} 个转换点一致"

        return {
            "dimension": "大运走向验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["大运走向验证"],
        }

    def score_six_kin(
        self,
        feedback_stats: dict,
        prediction_data: dict,
    ) -> dict:
        """六亲验证 (0-10)

        将 predictions 中六亲相关断事的反馈映射到对应十神的旺衰喜忌。
        六亲→十神映射（《渊海子平·六亲总篇》）：
        - 父母→偏财(父)、正印(母)
        - 兄弟→比肩/劫财
        - 配偶→正财(妻)、正官(夫)
        - 子女→食神(子)、伤官(女)

        Args:
            feedback_stats: 反馈统计数据
            prediction_data: 推断数据

        Returns:
            dict: {"dimension": "六亲验证", "score": int, "detail": str, "source": str}
        """
        accurate = feedback_stats.get("six_kin_accurate", 0)
        total = feedback_stats.get("six_kin_total", 0)

        if total == 0:
            return {
                "dimension": "六亲验证",
                "score": 5,
                "detail": "无六亲相关反馈",
                "source": self.SOURCES["六亲验证"],
            }

        score = min(10, int((accurate / max(total, 1)) * 10))
        detail = f"六亲验证 {accurate}/{total} 推断准确"

        return {
            "dimension": "六亲验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["六亲验证"],
        }

    def score_xingge(
        self,
        feedback_stats: dict,
        prediction_data: dict,
    ) -> dict:
        """性格验证 (0-10)

        性格推断反馈与十神组合推论对照。
        ⚠️ 防巴纳姆效应：性格验证权重降低 50%。

        Args:
            feedback_stats: 反馈统计数据
            prediction_data: 推断数据

        Returns:
            dict: {"dimension": "性格验证", "score": int, "detail": str, "source": str}
        """
        personality_accurate = feedback_stats.get("xingge_accurate", 0)
        personality_total = feedback_stats.get("xingge_total", 0)

        if personality_total == 0:
            return {
                "dimension": "性格验证",
                "score": 5,
                "detail": "无性格反馈",
                "source": self.SOURCES["性格验证"],
            }

        # 性格验证权重降低 50%（防范巴纳姆效应）
        adjusted_accurate = personality_accurate * 0.5
        score = min(10, int(adjusted_accurate / max(personality_total, 1) * 10))

        detail = (
            f"性格验证 {personality_accurate}/{personality_total} 推断准确，"
            f"经巴纳姆效应 50% 折扣后得分 {score}/10"
        )

        return {
            "dimension": "性格验证",
            "score": score,
            "detail": detail,
            "source": self.SOURCES["性格验证"],
        }

    def generate_hexagram_report(
        self,
        feedback_stats: dict,
        yongshen_data: dict = None,
        pattern_data: dict = None,
        bazi_data: dict = None,
        dayun_data: dict = None,
        prediction_data: dict = None,
    ) -> dict:
        """生成完整的六维验证评分卡报告。

        Args:
            feedback_stats: 反馈统计数据 {
                "accurate_count": int,
                "inaccurate_count": int,
                "total_count": int,
                "six_kin_accurate": int,
                "six_kin_total": int,
                "xingge_accurate": int,
                "xingge_total": int,
                "yongshen_years_verified": int,
                "dayun_transitions": int,
                "dayun_matched": int,
            }
            yongshen_data: 用神数据
            pattern_data: 格局数据
            bazi_data: 八字数据
            dayun_data: 大运数据
            prediction_data: 推断数据

        Returns:
            dict: {
                "scores": [每个维度的打分 dict],
                "total_score": int,
                "max_score": int,
                "consistent_count": int,
                "consistent_ratio": float,
                "inconsistent_dims": list[str],
                "core_triangle_pass": bool,
                "pass": bool,  # >=4/6 一致性
            }
        """
        if yongshen_data is None:
            yongshen_data = {}
        if pattern_data is None:
            pattern_data = {}
        if bazi_data is None:
            bazi_data = {}
        if dayun_data is None:
            dayun_data = {}
        if prediction_data is None:
            prediction_data = {}

        scores = [
            self.score_wangshuai(feedback_stats, yongshen_data),
            self.score_pattern_jixi(feedback_stats, pattern_data),
            self.score_yongshen(feedback_stats, bazi_data),
            self.score_dayun(feedback_stats, dayun_data),
            self.score_six_kin(feedback_stats, prediction_data),
            self.score_xingge(feedback_stats, prediction_data),
        ]

        consistent_dims = [s for s in scores if s["score"] >= 6]
        inconsistent_dims = [s["dimension"] for s in scores if s["score"] < 6]

        # 核心三角（前三个维度）
        core_triangle_pass = all(
            scores[i]["score"] >= 6 for i in range(min(3, len(scores)))
        )

        return {
            "scores": scores,
            "total_score": sum(s["score"] for s in scores),
            "max_score": len(scores) * 10,
            "consistent_count": len(consistent_dims),
            "consistent_ratio": round(len(consistent_dims) / max(len(scores), 1), 2),
            "inconsistent_dims": inconsistent_dims,
            "core_triangle_pass": core_triangle_pass,
            "pass": len(consistent_dims) >= 4,
        }


class ValidationJudge:
    """三重判定标准

    理论依据（《子平断前事研究报告》第 2 章 2.5 节）：
    1. 多维一致性（>=4/6） — 核心三角任意维度矛盾则失败
    2. 反例容限（<=1） — 不允许出现与核心判断直接矛盾的明确反例
    3. 流年交叉一致性（>=3） — 至少 3 个以上互不关联的关键流年验证一致
    """

    def check_multi_dimension(
        self,
        scores: list[dict],
        threshold: int = 6,
        min_dims: int = 4,
    ) -> dict:
        """判定 >=4/6 维度一致性（score >= threshold 视为一致）

        Args:
            scores: 六维打分列表
            threshold: 通过阈值
            min_dims: 最少需要通过的维度数

        Returns:
            dict: {"name": "多维一致性", "pass": bool, "detail": str, ...}
        """
        # 核心三角：旺衰、格局喜忌、用神
        core_dims = ["旺衰验证", "格局喜忌验证", "用神验证"]
        core_scores = {s["dimension"]: s["score"] for s in scores}

        core_all_pass = all(
            core_scores.get(d, 0) >= threshold for d in core_dims
        )
        total_consistent = sum(1 for s in scores if s["score"] >= threshold)

        return {
            "name": "多维一致性",
            "pass": total_consistent >= min_dims,
            "detail": f"{total_consistent}/6 维度一致（需 >= {min_dims}）",
            "core_triangle_pass": core_all_pass,
            "core_triangle_detail": " → ".join(
                f"{d}({core_scores.get(d, 'N/A')}分)" for d in core_dims
            ),
            "consistent_count": total_consistent,
            "threshold": threshold,
        }

    def check_counter_example(self, feedback_data: list[dict]) -> dict:
        """反例容限检查

        明确反例 A 类：用神到位之年遭遇重大灾厄
        明确反例 B 类：六亲既定事实与推论根本矛盾

        Args:
            feedback_data: 用户反馈列表 [{"status": "accurate"|"inaccurate", ...}]

        Returns:
            dict: {"name": "反例容限", "pass": bool, "total_counter_examples": int, ...}
        """
        counter_examples = []

        for fb in feedback_data:
            status = fb.get("status", "")
            note = fb.get("note", "")

            if status != "inaccurate":
                continue

            # A 类：用神到位之年遭遇重大灾厄
            negative_keywords = ["重大", "灾", "祸", "离婚", "去世", "破产", "失业", "事故"]
            is_major = any(kw in note for kw in negative_keywords)

            if is_major:
                counter_examples.append({
                    "type": "A",
                    "detail": f"用户反馈重大负面事件: {note if note else '(无备注)'}",
                    "is_major": True,
                })
            else:
                # B 类：普通 inaccurate
                counter_examples.append({
                    "type": "B",
                    "detail": f"用户反馈不准确: {note if note else '(无备注)'}",
                    "is_major": False,
                })

        major_count = sum(1 for ex in counter_examples if ex.get("is_major"))

        return {
            "name": "反例容限",
            "pass": major_count <= 1,
            "total_counter_examples": len(counter_examples),
            "major_counter_examples": major_count,
            "examples": counter_examples,
            "detail": f"{major_count} 个明确反例（允许 <=1）",
        }

    def check_liunian_cross(self, liunian_feedback: list[dict]) -> dict:
        """流年交叉一致性检查

        至少 3 个互不关联的关键流年验证一致

        Args:
            liunian_feedback: 流年反馈列表 [
                {"year": 2010, "status": "verified"|"contradicted", "dayun_index": 0},
            ]

        Returns:
            dict: {"name": "流年交叉一致性", "pass": bool, "detail": str, ...}
        """
        verified = [f for f in liunian_feedback if f.get("status") == "verified"]
        contradicted = [f for f in liunian_feedback if f.get("status") == "contradicted"]

        # "互不关联"：不在同一大运内，不属于连续年份（间隔 >= 2 年）
        selected = []
        used_dayun = set()

        for yr_item in verified:
            dn = yr_item.get("dayun_index", -1)
            if dn in used_dayun or dn < 0:
                continue
            # 确保不与已选年份连续
            if any(abs(yr_item.get("year", 0) - s.get("year", 0)) < 2
                   for s in selected):
                continue
            selected.append(yr_item)
            used_dayun.add(dn)

        consistent = len(selected)

        return {
            "name": "流年交叉一致性",
            "pass": consistent >= 3,
            "detail": f"{consistent}/{len(verified)} 个互不关联的流年验证一致（需 >= 3）",
            "selected_years": selected,
            "contradicted_count": len(contradicted),
        }

    def final_verdict(
        self,
        hexagram_report: dict,
        feedback_stats: dict,
    ) -> dict:
        """三重标准综合最终判定。

        Args:
            hexagram_report: HexagramValidator.generate_hexagram_report() 的输出
            feedback_stats: 反馈统计数据

        Returns:
            dict: {
                "status": "PASS" | "CONDITIONAL_PASS" | "FAIL" | "INDETERMINATE",
                "message": str,
                "pass_count": int,
                "criteria": {...},
                "need_correction": bool,
                "correction_trigger": dict | None,
            }
        """
        scores = hexagram_report.get("scores", [])

        # 多维一致性
        multi_dim = self.check_multi_dimension(scores)

        # 反例容限
        counter_ex = self.check_counter_example(
            feedback_stats.get("feedbacks", [])
        )

        # 流年交叉一致性
        liunian = self.check_liunian_cross(
            feedback_stats.get("liunian_feedback", [])
        )

        passes = [multi_dim["pass"], counter_ex["pass"], liunian["pass"]]
        pass_count = sum(passes)

        if pass_count == 3:
            status = "PASS"
            message = "三重标准全部通过，命盘可锁定，可进入断未来。"
            need_correction = False
            correction_trigger = None
        elif pass_count == 2:
            status = "CONDITIONAL_PASS"
            message = "两重标准通过，可进入断未来但不锁死，建议加强验证。"
            need_correction = False
            correction_trigger = None
        elif pass_count == 1:
            status = "INDETERMINATE"
            message = "仅一重标准通过，数据不足，建议增加验证问题。"
            need_correction = True
            correction_trigger = {
                "level": 1,
                "reason": "数据不足以做出明确判定",
            }
        else:
            status = "FAIL"
            message = "三重标准全部失败，必须触发修正流程。"
            need_correction = True
            correction_trigger = {
                "level": 0 if not multi_dim["core_triangle_pass"] else 1,
                "reason": (
                    "核心三角失败"
                    if not multi_dim["core_triangle_pass"]
                    else f"反例过多({counter_ex['major_counter_examples']}个) + 流年验证不足"
                ),
            }

        return {
            "status": status,
            "message": message,
            "pass_count": pass_count,
            "criteria": {
                "multi_dim": multi_dim,
                "counter_examples": counter_ex,
                "liunian_cross": liunian,
            },
            "need_correction": need_correction,
            "correction_trigger": correction_trigger,
        }
