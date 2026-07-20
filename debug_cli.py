#!/usr/bin/env python3
"""
断前事本地调试 CLI — 终端交互式状态面板 + 对话工具
=====================================================

用法:
  # 无 LLM（纯规则降级）
  python debug_cli.py

  # 有 LLM
  DEEPSEEK_API_KEY=sk-xxx python debug_cli.py

命令:
  1-4  → 选择预设选项
  自由文本 → 直接发送
  !state  → 重打状态面板
  !history → 打印完整问答历史
  !step   → 打印 step_results 详情
  !cands  → 打印用神候选详情
  !diag   → 打印诊断链每步状态
  !llm on/off → 切换 LLM
  !llm    → 查看 LLM 状态
  !quit   → 退出
"""

import asyncio
import os
import sys
import time
import textwrap

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.verification import (
    init_verification,
    process_verification,
    _verification_sessions,
)

# ============================================================
# 预置示例盘
# ============================================================

PRESET_CHARTS = {
    "1": {
        "name": "癸水丑月身弱-七杀格",
        "data": {
            "day_master": "癸",
            "four_pillars": {
                "month": {"stem": "乙", "branch": "丑", "hidden_stems": [{"stem": "己", "weight": 0.6}]},
                "year":  {"stem": "戊", "branch": "寅", "hidden_stems": [{"stem": "甲", "weight": 0.6}]},
                "day":   {"stem": "癸", "branch": "亥", "hidden_stems": [{"stem": "壬", "weight": 0.7}]},
                "hour":  {"stem": "丙", "branch": "辰", "hidden_stems": [{"stem": "戊", "weight": 0.6}]},
            },
            "strength_detail": {"total_score": 30},
        },
    },
    "2": {
        "name": "甲木寅月身旺-建禄格",
        "data": {
            "day_master": "甲",
            "four_pillars": {
                "month": {"stem": "甲", "branch": "寅", "hidden_stems": [{"stem": "甲", "weight": 0.6}]},
                "year":  {"stem": "壬", "branch": "辰", "hidden_stems": [{"stem": "乙", "weight": 0.3}]},
                "day":   {"stem": "甲", "branch": "午", "hidden_stems": [{"stem": "丁", "weight": 0.5}]},
                "hour":  {"stem": "丙", "branch": "戌", "hidden_stems": [{"stem": "戊", "weight": 0.5}]},
            },
            "strength_detail": {"total_score": 75},
        },
    },
    "3": {
        "name": "庚金申月身旺-建禄格",
        "data": {
            "day_master": "庚",
            "four_pillars": {
                "month": {"stem": "庚", "branch": "申", "hidden_stems": [{"stem": "庚", "weight": 0.7}]},
                "year":  {"stem": "丙", "branch": "子", "hidden_stems": [{"stem": "癸", "weight": 0.5}]},
                "day":   {"stem": "庚", "branch": "辰", "hidden_stems": [{"stem": "戊", "weight": 0.5}]},
                "hour":  {"stem": "壬", "branch": "午", "hidden_stems": [{"stem": "丁", "weight": 0.5}]},
            },
            "strength_detail": {"total_score": 70},
        },
    },
    "4": {
        "name": "丙火午月极旺-月刃格",
        "data": {
            "day_master": "丙",
            "four_pillars": {
                "month": {"stem": "戊", "branch": "午", "hidden_stems": [{"stem": "丁", "weight": 0.7}]},
                "year":  {"stem": "乙", "branch": "巳", "hidden_stems": [{"stem": "丙", "weight": 0.5}]},
                "day":   {"stem": "丙", "branch": "午", "hidden_stems": [{"stem": "丁", "weight": 0.5}]},
                "hour":  {"stem": "甲", "branch": "辰", "hidden_stems": [{"stem": "戊", "weight": 0.5}]},
            },
            "strength_detail": {"total_score": 85},
        },
    },
}

# ============================================================
# 状态面板渲染
# ============================================================

W = 56  # 面板宽度


def _box_top(title=""):
    return f"╔{'═' * W}╗\n║  {'🔬 断前事调试面板':<{W-4}}{'':>4}║"


def _box_line(text):
    return f"║  {text:<{W-2}} ║"


def _box_bot():
    return f"╚{'═' * W}╝"


def _hr():
    """分隔线"""
    return f"╠{'═' * W}╣"


def print_state_panel(session, t_start, last_llm_time=None):
    """打印完整状态面板"""
    sr = session.get("step_results", {})
    wangshuai = sr.get("wangshuai", {})
    gan = sr.get("gan_touchu", {})
    heju = sr.get("zhi_heju", {})

    pattern = sr.get("pattern", "?")
    source = sr.get("pattern_source", "?")
    w_level = wangshuai.get("level", "?")
    w_dir = wangshuai.get("yongshen_direction", "?")

    stage = session.get("stage", "?")
    sub = session.get("sub_stage", "?")
    conf = session.get("confidence", 0)
    quality = session.get("quality", "待判定")
    purity = session.get("purity", "?")
    l1 = session.get("l1_answer", "?")

    # 轮次
    r = session.get("round", 0)
    elapsed = time.time() - t_start if t_start else 0

    lines = []
    lines.append(_box_top())
    lines.append(_box_line(f"Round {r}    阶段: {stage}/{sub}    耗时: {elapsed:.0f}s"))
    lines.append(_hr())

    # Step 结果
    touched = gan.get("touched_stem", "无")
    tg = gan.get("touched_ten_god", "")
    gl = gan.get("level", "")
    touch_str = f"{touched}({tg},{gl})" if touched and tg else "无"
    heju_type = heju.get("type", "无")
    heju_hua = f"→{heju.get('hua_wuxing','')}" if heju.get("hua_wuxing") else ""
    heju_pending = "[待定]" if heju.get("pending") else ""

    lines.append(_box_line(f"Step0: 格局={pattern}  来源={source}"))
    lines.append(_box_line(f"       透干={touch_str}  合局={heju_type}{heju_hua}{heju_pending}"))
    lines.append(_box_line(f"       旺衰={w_level}  方向={w_dir}"))

    # 当前状态
    q_str = ""
    if quality and quality != "待判定":
        q_str = f"  品质={quality}"
    yq = session.get("phase2_youqing")
    yl = session.get("phase2_youli")
    pq = ""
    if yq is not None:
        pq = f"  有情={'是' if yq else '否'}"
    if yl is not None:
        pq += f"  有力={'是' if yl else '否'}"

    l1_str = ""
    if l1 and l1 != "?":
        delta = {"High": "+15", "Medium": "不变", "Low": "-20"}.get(l1, "")
        l1_str = f"  L1={l1}({delta})"

    lines.append(_box_line(""))
    lines.append(_box_line(f"格局置信度: {conf}%{q_str}"))
    lines.append(_box_line(f"纯杂: {purity}{l1_str}{pq}"))

    # 下一阶段条件
    lines.append(_box_line(""))
    lines.append(_box_line(_next_stage_info(session)))

    # LLM 状态
    lines.append(_box_line(""))
    has_llm = bool(os.environ.get("DEEPSEEK_API_KEY", "").startswith("sk-"))
    llm_status = "已启用 (DeepSeek)" if has_llm else "已禁用 (纯规则降级)"
    llm_line = f"LLM: {llm_status}"
    if last_llm_time:
        llm_line += f"    上轮LLM: {last_llm_time:.1f}s"
    lines.append(_box_line(llm_line))

    # 诊断路径
    diag_path = session.get("diagnosis_path", [])
    if diag_path:
        steps = "→".join([d.get("step", "?") for d in diag_path[-5:]])
        lines.append(_box_line(f"诊断路径: {steps}"))
    dc = session.get("diagnosis_count", 0)
    lines.append(_box_line(f"累积否定: {dc}/3"))

    # 用神候选（仅 yongshen 阶段）
    yc = session.get("yongshen_candidates")
    if yc and stage == "yongshen":
        lines.append(_hr())
        lines.append(_box_line("用神候选 (按置信度降序):"))
        for i, c in enumerate(yc[:5]):
            ys = c.get("yong_shen", "?")
            el = c.get("five_element", "?")
            gw = c.get("gong_way", "")
            cf = c.get("confidence", 0)
            src = c.get("source", "?")
            lines.append(_box_line(f"  {i+1}. {ys}({el}) {cf}%  [{gw}]  {src}"))
        if len(yc) > 1:
            lead = yc[0]["confidence"] - yc[1]["confidence"]
            lock_ok = yc[0]["confidence"] >= 65 and lead >= 20
            lines.append(_box_line(f"  → 锁定条件: ≥65% 且领先≥20%  (当前领先{lead}%, {'达标' if lock_ok else '未达标'})"))

    # 诊断链详细
    if stage == "diagnosis":
        lines.append(_hr())
        lines.append(_box_line(f"诊断链 D{session.get('diagnosis_sub_stage', '?')}/5:"))
        for ds in range(1, 6):
            marker = _diag_marker(session, ds)
            label = _diag_label(ds)
            lines.append(_box_line(f"  D{ds}({label}): {marker}"))

    lines.append(_box_bot())

    print("\n".join(lines))
    print()


def _next_stage_info(session):
    """根据当前 sub_stage 返回下一个阶段条件描述"""
    sub = session.get("sub_stage", "")
    
    stage_map = {
        "L1": "L1 → 确认后进 Phase2",
        "purity": "纯杂确认后进 Phase2",
        "phase2_L2": "Phase2 L2(有情) → L3(有力)",
        "phase2_L3": "Phase2 L3(有力) → 品质判定 → 用神或诊断",
        "tongguan": "通关确认后进用神验证",
    }
    
    for prefix, info in stage_map.items():
        if sub.startswith(prefix):
            return f"→ {info}"
    
    if sub.startswith("diag_D"):
        return f"诊断链 {sub} → 满足条件则推进或回 Phase2"
    if sub.startswith("ys_"):
        return "用神验证 → 置信度≥65%且领先≥20%则锁定"
    
    return "(状态未识别)"


def _diag_marker(session, step_num):
    """返回诊断步骤的当前状态标记"""
    sub = session.get("sub_stage", "")
    ds = session.get("diagnosis_sub_stage", 1)
    path = {d.get("step", ""): d for d in session.get("diagnosis_path", [])}
    
    diag_keys = {1: "D1", 2: "D2", 3: "D3", 4: "D4", 5: "D5"}
    key = diag_keys.get(step_num, "")
    
    if sub == f"diag_{key}" and ds == step_num:
        return "← 当前"
    
    for p in session.get("diagnosis_path", []):
        if p.get("step", "").startswith(key):
            ans = p.get("answer", "?")
            return f"{ans}"
    
    return "待定"


def _diag_label(step_num):
    return {1: "月令被冲", 2: "月令被合", 3: "中气取格", 4: "救应", 5: "时辰校验"}.get(step_num, "?")


# ============================================================
# 对话区
# ============================================================

def print_question(q):
    """打印当前问题"""
    print(f"╔{'═' * W}╗")
    print(f"║  {'💬 命理师':<{W-4}}{'':>4}║")
    # 问题文本自动换行
    q_text = q.get("question", "(无问题)")
    for line in textwrap.wrap(q_text, width=W-4):
        print(f"║  {line:<{W-2}} ║")
    
    # 选项
    options = q.get("options", [])
    if options:
        print(f"║{' ' * W}║")
        print(f"║  可用选项:{' ' * (W-11)}║")
        for i, opt in enumerate(options):
            label = f"    [{i+1}] {opt}"
            print(f"║  {label:<{W-2}} ║")
    
    print(f"╚{'═' * W}╝")


def print_history(session):
    """打印完整问答历史"""
    print(f"\n{'─' * W}")
    print("📜 问答历史")
    print(f"{'─' * W}")
    for h in session.get("history", []):
        r = h.get("round", "?")
        stage = h.get("stage", "?")
        sub = h.get("sub_stage", "?")
        q = h.get("question", "")[:80]
        a = h.get("answer", "")
        print(f"  R{r} [{stage}/{sub}]")
        print(f"    Q: {q}")
        print(f"    A: {a}")
    print(f"{'─' * W}\n")


def print_step_details(session):
    """打印 step_results 全部子字段"""
    sr = session.get("step_results", {})
    print(f"\n{'─' * W}")
    print("📋 step_results 详情")
    print(f"{'─' * W}")
    for k, v in sr.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for sk, sv in v.items():
                print(f"    {sk}: {sv}")
        else:
            print(f"  {k}: {v}")
    print(f"{'─' * W}\n")


def print_candidates(session):
    """打印用神候选详情"""
    yc = session.get("yongshen_candidates")
    if not yc:
        print("  (当前非用神验证阶段，无用神候选数据)\n")
        return
    
    print(f"\n{'─' * W}")
    print("🎯 用神候选详情")
    print(f"{'─' * W}")
    for i, c in enumerate(yc):
        print(f"  {i+1}. {c.get('yong_shen','?')}({c.get('five_element','?')})")
        print(f"     置信度: {c.get('confidence',0)}%  权重: ×{c.get('weight',1.0)}")
        print(f"     来源: {c.get('source','?')}  做功: {c.get('gong_way','?')}")
        print(f"     维度: {c.get('dim','?')}")
        print(f"     问题: {c.get('question','?')[:60]}")
        print()
    print(f"{'─' * W}\n")


def print_diag_details(session):
    """打印诊断链每步状态"""
    print(f"\n{'─' * W}")
    print("🔍 诊断链详情")
    print(f"{'─' * W}")
    print(f"  当前步骤: D{session.get('diagnosis_sub_stage','?')}/5")
    print(f"  累积否定: {session.get('diagnosis_count',0)}/3")
    print()
    
    for d in session.get("diagnosis_path", []):
        print(f"  [{d.get('step','?')}] {d.get('action','?')}")
        if d.get("answer"):
            print(f"       回答: {d['answer']}")
        if d.get("result"):
            print(f"       结果: {d['result']}")
    
    # D4 救应数据
    jd = session.get("_jiuying_data")
    if jd:
        print(f"\n  救应检测: protection={jd.get('has_protection')} blocked={jd.get('protection_blocked')} blocker={jd.get('blocker')}")
    print(f"{'─' * W}\n")


def print_lock_result(session):
    """打印锁定结果"""
    res = session.get("locked_yongshen", session.get("yongshen_candidates", [{}])[0] if session.get("yongshen_candidates") else {})
    quality = session.get("quality", "?")
    purity = session.get("purity", "?")
    source = session.get("step_results", {}).get("pattern_source", "?")
    pattern = session.get("step_results", {}).get("pattern", "?") or session.get("pattern", "?")
    conf = session.get("confidence", 0)
    rounds = session.get("round", 0)
    path = "→".join([d.get("step", "?") for d in session.get("diagnosis_path", [])])

    print(f"╔{'═' * W}╗")
    print(f"║  {'✅ 验证完成！':<{W-2}} ║")
    print(f"║{' ' * W}║")
    print(f"║  格局: {pattern:<20s} 置信度: {conf}%{' ' * (W-30 - len(pattern) - len(str(conf)))} ║")
    print(f"║  品质: {quality:<6s}  纯杂: {purity:<4s}  来源: {source:<12s}{' ' * (W-34)} ║")
    print(f"║{' ' * W}║")
    if res:
        ys = res.get("yong_shen", "?")
        el = res.get("five_element", "?")
        yc = res.get("confidence", 0)
        gw = res.get("gong_way", "?")
        print(f"║  用神: {ys}({el})  置信度: {yc}%{' ' * (W-24 - len(ys) - len(str(yc)))} ║")
        print(f"║  做功方式: {gw:<30s}{' ' * (W-30)} ║")
    print(f"║{' ' * W}║")
    print(f"║  总轮数: {rounds}    诊断路径: {path[:40]}{' ' * (W-45)} ║")
    print(f"╚{'═' * W}╝")
    print()


# ============================================================
# 命令处理
# ============================================================

def handle_command(cmd, session):
    """处理 ! 开头的命令，返回 True 表示 quit"""
    parts = cmd.split()
    c = parts[0].lower()
    
    if c == "!quit" or c == "!q":
        return True
    elif c == "!state":
        print_state_panel(session, 0)
    elif c == "!history" or c == "!h":
        print_history(session)
    elif c == "!step":
        print_step_details(session)
    elif c == "!cands":
        print_candidates(session)
    elif c == "!diag":
        print_diag_details(session)
    elif c == "!llm":
        if len(parts) > 1:
            if parts[1] == "on":
                os.environ["DEEPSEEK_API_KEY"] = input("  API Key: ").strip()
                print("  LLM 已启用\n")
            elif parts[1] == "off":
                os.environ.pop("DEEPSEEK_API_KEY", None)
                print("  LLM 已禁用\n")
            else:
                print(f"  用法: !llm on|off\n")
        else:
            has = bool(os.environ.get("DEEPSEEK_API_KEY", "").startswith("sk-"))
            print(f"  LLM: {'已启用' if has else '已禁用'}\n")
    elif c == "!" or c == "!help":
        print_help()
    else:
        print(f"  未知命令: {c}  (输入 ! 查看帮助)\n")
    
    return False


def print_help():
    print(f"""
{'─' * W}
命令列表:
  !state   - 重新打印完整状态面板
  !history - 打印完整问答历史
  !step    - 打印 step_results 全部子字段
  !cands   - 打印用神候选详情
  !diag    - 打印诊断链每步状态
  !llm     - 查看 LLM 状态
  !llm on  - 启用 LLM（输入 API Key）
  !llm off - 禁用 LLM
  !quit    - 退出
{'─' * W}
""")


# ============================================================
# 主循环
# ============================================================

async def run_debug():
    """主入口"""
    print()
    print("=" * W)
    print("  断前事本地调试 CLI v1.0")
    print("=" * W)
    print()
    
    # 选示例盘
    print("选择一个示例命盘:")
    for k, v in PRESET_CHARTS.items():
        print(f"  [{k}] {v['name']}")
    print(f"  [c] 自定义输入（暂不支持，请选预设）")
    print()
    
    choice = input("选择: ").strip()
    if choice not in PRESET_CHARTS:
        choice = "1"
        print(f"默认选: {PRESET_CHARTS[choice]['name']}")
    
    chart_info = PRESET_CHARTS[choice]
    chart = chart_info["data"]
    
    print(f"\n已选: {chart_info['name']}")
    print()

    while True:
        await run_session(chart, chart_info["name"])

        again = input("\n换一个盘重新开始? (y/N): ").strip().lower()
        if again != "y":
            break
        
        print("\n选择一个示例命盘:")
        for k, v in PRESET_CHARTS.items():
            print(f"  [{k}] {v['name']}")
        choice = input("选择: ").strip()
        if choice not in PRESET_CHARTS:
            choice = "1"
        chart_info = PRESET_CHARTS[choice]
        chart = chart_info["data"]
        print()


async def run_session(chart, chart_name):
    """运行一次完整的验证会话"""
    t_start = time.time()
    last_llm_time = None

    # 初始化
    result = init_verification(chart)
    sid = result["session_id"]

    while True:
        session = _verification_sessions.get(sid)
        if not session:
            print("会话已过期，重新开始...")
            break

        # 检查是否已锁定
        if session.get("stage") == "locked":
            print_state_panel(session, t_start, last_llm_time)
            print_lock_result(session)
            return

        # 打印状态面板 + 问题
        print_state_panel(session, t_start, last_llm_time)
        q = session.get("current_question", {})
        print_question(q)

        # 用户输入
        user_input = input("你: ").strip()

        if not user_input:
            continue

        # 命令处理
        if user_input.startswith("!"):
            quit_requested = handle_command(user_input, session)
            if quit_requested:
                print("再见!")
                sys.exit(0)
            continue

        # 映射数字到选项
        options = q.get("options", [])
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(options):
                chosen = options[idx]
                print(f"  → 选择了: {chosen}")
                user_input = chosen
            else:
                print(f"  无效选项 (1-{len(options)})\n")
                continue

        # 调用后端
        print(f"  处理中...", end="", flush=True)
        t_round = time.time()
        try:
            result = await process_verification(sid, user_input)
            last_llm_time = time.time() - t_round
        except Exception as e:
            print(f"\n  ❌ 错误: {e}\n")
            continue
        print(f" 完成 ({last_llm_time:.1f}s)")

        # 打印用户回答确认
        print()

        if result.get("locked"):
            # 最后再打一次面板
            session = _verification_sessions.get(sid)
            if session:
                print_state_panel(session, t_start, last_llm_time)
                print_lock_result(session)
            return


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(run_debug())
    except KeyboardInterrupt:
        print("\n\n再见!")
    except EOFError:
        print("\n")
