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
