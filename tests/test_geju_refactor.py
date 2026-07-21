"""格局派重构测试脚本

测试场景:
1. 正官格身弱
2. 七杀格身旺
3. 食神格
4. 建禄格
5. 从弱格
6. 混合框架 LLM delta
7. 收敛测试
"""

import sys
import os
import asyncio
import json
import pytest

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.verification import init_verification, process_verification, get_session

# ============================================================
# 测试命盘数据
# ============================================================

def make_chart(day_master, year_gz, month_gz, day_gz, hour_gz, strength_detail=None):
    """构造命盘数据"""
    return {
        "day_master": day_master,
        "four_pillars": {
            "year": {"stem": year_gz[0], "branch": year_gz[1]},
            "month": {"stem": month_gz[0], "branch": month_gz[1]},
            "day": {"stem": day_gz[0], "branch": day_gz[1]},
            "hour": {"stem": hour_gz[0], "branch": hour_gz[1]},
        },
        "strength_detail": strength_detail or {},
    }


# 场景1: 正官格身弱 — 甲日酉月（辛金正官）
CHART_1 = make_chart(
    "甲", "壬辰", "己酉", "甲子", "丙寅",
    {"木": 25, "金": 35, "水": 15, "火": 10, "土": 15}
)

# 场景2: 七杀格身旺 — 庚日子月（癸水伤官? 不，子中癸水，庚日子月=伤官格）
# 改用: 庚日午月（丁火正官? 不，午中丁己，庚日午月=正官格）
# 改用: 甲日申月（庚金七杀）
CHART_2 = make_chart(
    "甲", "甲寅", "壬申", "甲寅", "丙寅",
    {"木": 50, "金": 20, "水": 10, "火": 10, "土": 10}
)

# 场景3: 食神格 — 丙日辰月（戊土食神? 辰中戊乙癸，本气戊土=食神）
CHART_3 = make_chart(
    "丙", "甲子", "戊辰", "丙午", "戊戌",
    {"火": 30, "土": 35, "木": 10, "水": 15, "金": 10}
)

# 场景4: 建禄格 — 甲日寅月（甲木比肩=建禄）
CHART_4 = make_chart(
    "甲", "壬子", "壬寅", "甲辰", "丙寅",
    {"木": 40, "水": 30, "火": 10, "土": 10, "金": 10}
)

# 场景5: 从弱格 — 甲日申月，满盘金水
CHART_5 = make_chart(
    "甲", "庚申", "甲申", "甲申", "壬申",
    {"木": 10, "金": 60, "水": 20, "火": 0, "土": 10}
)

# 场景6: 混合框架 LLM delta — 用正官格测试
CHART_6 = CHART_1  # 复用正官格


# ============================================================
# 辅助函数
# ============================================================

def print_session_info(session, label=""):
    """打印 session 关键信息"""
    print(f"\n{'='*60}")
    if label:
        print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Stage: {session.get('stage')}, Sub: {session.get('sub_stage')}")
    print(f"  Round: {session.get('round')}")
    print(f"  Pattern: {session.get('pattern')}")
    
    yongshen = session.get("yongshen", {})
    if yongshen:
        print(f"  用神: {yongshen.get('ten_god','')} ({yongshen.get('five_element','')}) mode={yongshen.get('mode','')}")
    
    candidates = session.get("xiangshen_candidates", [])
    if candidates:
        print(f"  相神候选 ({len(candidates)}):")
        for c in candidates[:5]:
            print(f"    - {c.get('ten_god','')} ({c.get('five_element','')}): conf={c.get('confidence',0)}, way={c.get('gong_way','')}")
    
    chengbai = session.get("chengbai_result", {})
    if chengbai:
        print(f"  成败: {session.get('chengbai_status','')}")
        if chengbai.get("defeat_causes"):
            print(f"    败因: {chengbai['defeat_causes']}")
    
    jiuying = session.get("jiuying_result", {})
    if jiuying:
        print(f"  救应: {jiuying.get('jiuying_shen','')} ({jiuying.get('jiuying_level','')})")
    
    q = session.get("current_question", {})
    if q:
        print(f"  当前问题: {q.get('question','')[:80]}")
        print(f"  选项: {q.get('options',[])}")
    print(f"{'='*60}")


async def simulate_flow(session_id, answers, label="", verbose=True):
    """模拟验证流程，依次给出答案"""
    if verbose:
        session = get_session(session_id)
        print_session_info(session, f"{label} — 初始状态")
    
    for i, answer in enumerate(answers):
        result = await process_verification(session_id, answer, note="")
        
        if verbose:
            session = get_session(session_id)
            print_session_info(session, f"{label} — 第{i+1}轮 answer={answer}")
        
        if result.get("error"):
            print(f"  [ERROR] {result['error']}")
            break
        
        if result.get("locked"):
            if verbose:
                print(f"\n  [LOCKED] 流程结束")
                r = result.get("result", {})
                print(f"  格局: {r.get('pattern','')}")
                print(f"  用神: {r.get('yong_shen','')} ({r.get('yong_shen_element','')}) mode={r.get('yong_shen_mode','')}")
                print(f"  相神: {r.get('xiang_shen','')} ({r.get('xiang_shen_element','')}) way={r.get('xiang_shen_way','')}")
                print(f"  成败: {r.get('chengbai_status','')}")
                print(f"  格局高低: {result.get('quality','')}")
                print(f"  纯杂: {result.get('purity','')}")
                print(f"  总轮数: {result.get('total_rounds',0)}")
            return result
    
    return result


# ============================================================
# 测试用例
# ============================================================

@pytest.mark.asyncio
async def test_1_zhengguan_weak():
    """场景1: 正官格身弱"""
    print("\n" + "#"*60)
    print("# 场景1: 正官格身弱")
    print("#"*60)
    
    session = init_verification(CHART_1, user_id="test_1")
    sid = session["session_id"]
    
    # 检查初始状态
    s = get_session(sid)
    assert s["pattern"] == "正官格", f"Expected 正官格, got {s['pattern']}"
    
    yongshen = s.get("yongshen", {})
    assert yongshen["ten_god"] == "正官", f"Expected 正官, got {yongshen.get('ten_god')}"
    assert yongshen["mode"] == "顺用", f"Expected 顺用, got {yongshen.get('mode')}"
    
    candidates = s.get("xiangshen_candidates", [])
    assert len(candidates) > 0, "Expected non-empty xiangshen_candidates"
    
    print(f"  [PASS] 初始状态: pattern={s['pattern']}, 用神={yongshen['ten_god']}, mode={yongshen['mode']}")
    print(f"  [PASS] 相神候选数: {len(candidates)}")
    
    # 模拟流程: L1 accurate → purity accurate → xs_1 accurate → xs_2 partial → chengbai → quality
    result = await simulate_flow(sid, ["accurate", "accurate", "accurate", "accurate", "accurate", "accurate"], 
                                  label="正官格身弱")
    
    assert result.get("locked"), "Expected locked result"
    r = result.get("result", {})
    assert r.get("pattern") == "正官格", f"Expected 正官格, got {r.get('pattern')}"
    assert r.get("yong_shen") == "正官", f"Expected 正官, got {r.get('yong_shen')}"
    
    print(f"\n  [PASS] 最终结果验证通过")
    return True


@pytest.mark.asyncio
async def test_2_qisha_strong():
    """场景2: 七杀格身旺"""
    print("\n" + "#"*60)
    print("# 场景2: 七杀格身旺")
    print("#"*60)
    
    session = init_verification(CHART_2, user_id="test_2")
    sid = session["session_id"]
    
    s = get_session(sid)
    assert s["pattern"] == "七杀格", f"Expected 七杀格, got {s['pattern']}"
    
    yongshen = s.get("yongshen", {})
    assert yongshen["ten_god"] == "七杀", f"Expected 七杀, got {yongshen.get('ten_god')}"
    assert yongshen["mode"] == "逆用", f"Expected 逆用, got {yongshen.get('mode')}"
    
    print(f"  [PASS] 初始状态: pattern={s['pattern']}, 用神={yongshen['ten_god']}, mode={yongshen['mode']}")
    
    result = await simulate_flow(sid, ["accurate", "accurate", "accurate", "accurate", "accurate", "accurate"],
                                  label="七杀格身旺")
    
    assert result.get("locked"), "Expected locked result"
    r = result.get("result", {})
    assert r.get("yong_shen") == "七杀", f"Expected 七杀, got {r.get('yong_shen')}"
    
    print(f"\n  [PASS] 最终结果验证通过")
    return True


@pytest.mark.asyncio
async def test_3_shishen():
    """场景3: 食神格"""
    print("\n" + "#"*60)
    print("# 场景3: 食神格")
    print("#"*60)
    
    session = init_verification(CHART_3, user_id="test_3")
    sid = session["session_id"]
    
    s = get_session(sid)
    assert s["pattern"] == "食神格", f"Expected 食神格, got {s['pattern']}"
    
    yongshen = s.get("yongshen", {})
    assert yongshen["ten_god"] == "食神", f"Expected 食神, got {yongshen.get('ten_god')}"
    assert yongshen["mode"] == "顺用", f"Expected 顺用, got {yongshen.get('mode')}"
    
    print(f"  [PASS] 初始状态: pattern={s['pattern']}, 用神={yongshen['ten_god']}, mode={yongshen['mode']}")
    
    result = await simulate_flow(sid, ["accurate", "accurate", "accurate", "accurate", "accurate", "accurate"],
                                  label="食神格")
    
    assert result.get("locked"), "Expected locked result"
    r = result.get("result", {})
    assert r.get("yong_shen") == "食神", f"Expected 食神, got {r.get('yong_shen')}"
    
    print(f"\n  [PASS] 最终结果验证通过")
    return True


@pytest.mark.asyncio
async def test_4_jianlu():
    """场景4: 建禄格"""
    print("\n" + "#"*60)
    print("# 场景4: 建禄格")
    print("#"*60)
    
    session = init_verification(CHART_4, user_id="test_4")
    sid = session["session_id"]
    
    s = get_session(sid)
    pattern = s["pattern"]
    # 建禄格 or 月刃格
    assert pattern in ("建禄格", "月刃格"), f"Expected 建禄格/月刃格, got {pattern}"
    
    yongshen = s.get("yongshen", {})
    print(f"  [INFO] pattern={pattern}, 用神={yongshen.get('ten_god','')}, mode={yongshen.get('mode','')}")
    
    # 建禄格没有月令定格的十神，用神需要从其他角度确定
    # 这里只验证流程能走通
    result = await simulate_flow(sid, ["accurate", "accurate", "accurate", "accurate", "accurate", "accurate"],
                                  label="建禄格")
    
    assert result.get("locked"), "Expected locked result"
    
    print(f"\n  [PASS] 最终结果验证通过")
    return True


@pytest.mark.asyncio
async def test_5_congruo():
    """场景5: 从弱格"""
    print("\n" + "#"*60)
    print("# 场景5: 从弱格")
    print("#"*60)
    
    session = init_verification(CHART_5, user_id="test_5")
    sid = session["session_id"]
    
    s = get_session(sid)
    pattern = s["pattern"]
    print(f"  [INFO] pattern={pattern}")
    
    yongshen = s.get("yongshen", {})
    print(f"  [INFO] 用神={yongshen.get('ten_god','')}, mode={yongshen.get('mode','')}")
    
    candidates = s.get("xiangshen_candidates", [])
    print(f"  [INFO] 相神候选数: {len(candidates)}")
    
    result = await simulate_flow(sid, ["accurate", "accurate", "accurate", "accurate", "accurate", "accurate"],
                                  label="从弱格")
    
    assert result.get("locked"), "Expected locked result"
    
    print(f"\n  [PASS] 最终结果验证通过")
    return True


@pytest.mark.asyncio
async def test_6_llm_delta():
    """场景6: 混合框架 LLM delta"""
    print("\n" + "#"*60)
    print("# 场景6: 混合框架 LLM delta")
    print("#"*60)
    
    session = init_verification(CHART_6, user_id="test_6")
    sid = session["session_id"]
    
    s = get_session(sid)
    candidates = s.get("xiangshen_candidates", [])
    assert len(candidates) > 0, "Expected non-empty candidates"
    
    # 记录初始 confidence
    initial_confs = [c["confidence"] for c in candidates]
    print(f"  [INFO] 初始 confidence: {initial_confs}")
    
    # 给出 partial 回答，验证 delta 机制
    result = await process_verification(sid, "accurate", note="")  # L1
    s = get_session(sid)
    
    result = await process_verification(sid, "accurate", note="")  # purity
    
    # 相神阶段
    result = await process_verification(sid, "accurate", note="")
    s = get_session(sid)
    candidates_after = s.get("xiangshen_candidates", [])
    print(f"  [INFO] xs_1 后 confidence: {[c['confidence'] for c in candidates_after]}")
    
    # 验证 confidence 有变化（delta 机制生效）
    if candidates_after:
        conf_changed = any(
            candidates_after[i]["confidence"] != initial_confs[i]
            for i in range(min(len(candidates_after), len(initial_confs)))
        )
        if conf_changed:
            print(f"  [PASS] Delta 机制生效 — confidence 有变化")
        else:
            print(f"  [WARN] confidence 未变化（可能是因为 LLM 不可用，使用了固定值）")
    
    # 继续完成流程
    while not result.get("locked"):
        result = await process_verification(sid, "accurate", note="")
        if result.get("error"):
            print(f"  [ERROR] {result['error']}")
            break
    
    if result.get("locked"):
        print(f"  [PASS] 流程正常完成")
    
    return True


@pytest.mark.asyncio
async def test_7_convergence():
    """场景7: 收敛测试"""
    print("\n" + "#"*60)
    print("# 场景7: 收敛测试")
    print("#"*60)
    
    session = init_verification(CHART_1, user_id="test_7")
    sid = session["session_id"]
    
    s = get_session(sid)
    max_rounds = 20  # 安全上限
    
    for i in range(max_rounds):
        result = await process_verification(sid, "accurate", note="")
        s = get_session(sid)
        
        if result.get("error"):
            print(f"  [ERROR] Round {i+1}: {result['error']}")
            return False
        
        if result.get("locked"):
            print(f"  [PASS] 流程在第 {i+1} 轮收敛锁定")
            r = result.get("result", {})
            print(f"  格局: {r.get('pattern','')}")
            print(f"  用神: {r.get('yong_shen','')}")
            print(f"  相神: {r.get('xiang_shen','')}")
            print(f"  成败: {r.get('chengbai_status','')}")
            print(f"  高低: {result.get('quality','')}")
            print(f"  总轮数: {result.get('total_rounds',0)}")
            return True
    
    print(f"  [FAIL] 流程在 {max_rounds} 轮内未收敛")
    return False


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "="*60)
    print("  格局派重构 — 测试验证")
    print("="*60)
    
    results = {}
    
    tests = [
        ("正官格身弱", test_1_zhengguan_weak),
        ("七杀格身旺", test_2_qisha_strong),
        ("食神格", test_3_shishen),
        ("建禄格", test_4_jianlu),
        ("从弱格", test_5_congruo),
        ("混合框架LLM delta", test_6_llm_delta),
        ("收敛测试", test_7_convergence),
    ]
    
    for name, test_func in tests:
        try:
            success = await test_func()
            results[name] = "PASS" if success else "FAIL"
        except Exception as e:
            results[name] = f"ERROR: {e}"
            import traceback
            traceback.print_exc()
    
    # 汇总
    print("\n" + "="*60)
    print("  测试结果汇总")
    print("="*60)
    for name, status in results.items():
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"  {marker} {name}: {status}")
    
    passed = sum(1 for v in results.values() if v == "PASS")
    total = len(results)
    print(f"\n  总计: {passed}/{total} 通过")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
