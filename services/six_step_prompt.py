"""六步推导法 Prompt 嵌入模块

基于《子平真诠》格局派六步推导框架：
1. 定格局 → 2. 辨用神 → 3. 明喜忌 → 4. 十神定位 → 5. 宫位取象 → 6. 应期锁定

每步含：core_question / classical_basis（古籍原文）/ operation_rules（if-then 决策树）/ output_format
支持逐步调用（含 prior_conclusions 传递）和全量调用
"""

# ============================================================
# 六步模板定义
# ============================================================

SIX_STEP_TEMPLATES = {
    1: {
        "name": "定格局",
        "core_question": "命主的基本格局类型？",
        "classical_basis": (
            "《子平真诠·论用神》：'八字用神，专求月令。以日干配月令地支，而生克不同，格局分焉。'\n"
            "《子平真诠·论用神变化》：'甲生申月，申中庚壬戊并透，以庚为用者，本气也；"
            "壬戊透而庚不透，则以壬戊为用，透干不同则用神变。'\n"
            "《渊海子平·论日为主》：'以日为主，而取月令提纲所藏为用神。'"
        ),
        "operation_rules": (
            "IF 月令本气透干 → 以本气定格（正格）\n"
            "ELIF 月令本气不透，中气/余气透干 → 以透干之气定格\n"
            "ELIF 月令被冲/被合 → 重新审视定格之物，另寻透干之物为用\n"
            "ELIF 日主极弱（total_score < 15）且无根无气 → 考虑从格\n"
            "ELIF 日主极旺（total_score > 85）且无官杀制 → 考虑专旺格\n"
            "ELIF 日干与月干/时干五合，化神当令 → 考虑化气格\n"
            "ELSE → 以月令本气定格\n\n"
            "硬约束：\n"
            "- 优先使用 rules/pattern.py 的 determine_pattern_type() 结果\n"
            "- 格局类型不可跨大类翻转（正格不可能变成从格）\n"
            "- 官杀优先于其他十神定格"
        ),
        "output_format": (
            "格局类型：{正官格|七杀格|正财格|偏财格|正印格|偏印格|食神格|伤官格|"
            "建禄格|月刃格|从弱格|专旺格|化气格}\n"
            "定格局依据：{月令本气/天干透出/三合会局/化气}\n"
            "备选格局：{如有}\n"
            "格局类型：{正格/从格/专旺/化气}"
        ),
    },
    2: {
        "name": "辨用神",
        "core_question": "此格局的用神是什么？是顺用还是逆用？",
        "classical_basis": (
            "《子平真诠·论用神》：'善而顺用之，恶而逆用之。'\n"
            "《子平真诠·论用神成败得失》：'用神之成，在于得护得救。用神之败，在于被伤被破。'\n"
            "《滴天髓·真假》：'令上寻真聚得真，假神休要乱真神。'\n"
            "《滴天髓·真假》：'真神得用生平贵，用假终为碌碌人。'"
        ),
        "operation_rules": (
            "STEP 1: 确定用神（=月令定格之物，直接确定，不竞争）\n"
            "  - 正官格 → 用神=正官（善神，顺用）\n"
            "  - 七杀格 → 用神=七杀（恶神，逆用）\n"
            "  - 正财格 → 用神=正财（善神，顺用）\n"
            "  - ...（其他格局同理）\n\n"
            "STEP 2: 用神状态检查\n"
            "  - 透干有根 → 真神得用，上等\n"
            "  - 透干无根 → 假神得局，中等\n"
            "  - 有根不透 → 真神暗藏，中下等\n"
            "  - 无根不透 → 用神不显，下等\n\n"
            "STEP 3: 用神变化检查\n"
            "  - 月令逢冲 → 用神根气受损，重新审视\n"
            "  - 用神被合（非日主自合）→ 败格，看合化后能否成新格\n"
            "  - 透干变化 → 中气余气强透，可能改变用神"
        ),
        "output_format": (
            "用神（格局）：{十神名}\n"
            "用神五行：{金木水火土}\n"
            "使用模式：{顺用/逆用/顺势}\n"
            "用神状态：{真神得用/假神得局/真神暗藏/用神不显}\n"
            "用神变化：{有/无}（{如有，说明原因}）"
        ),
    },
    3: {
        "name": "明喜忌",
        "core_question": "此格局的相神配置和喜忌是什么？",
        "classical_basis": (
            "《子平真诠·论用神》：'财官印食，此四善神，顺用之；杀伤枭刃，此四恶神，逆用之。'\n"
            "《子平真诠·论用神格局高低》：'格局之高低，视乎有情无情、有力无力而已矣。'\n"
            "《子平真诠·论行运》：'运向用神则吉，运背用神则凶。'"
        ),
        "operation_rules": (
            "STEP 1: 确定相神（辅佐用神成格之物）\n"
            "  - 顺用：生用（如财生官）、护用（如印护官）\n"
            "  - 逆用：制用（如食神制杀）、化用（如印化杀）\n\n"
            "STEP 2: 确定喜忌五行\n"
            "  - 喜神 = 用神五行 + 相神五行 + 生扶用神/相神者\n"
            "  - 忌神 = 克制用神/相神者 + 被格局所忌者\n\n"
            "STEP 3: 确定大运喜忌方向\n"
            "  - 喜神运 → 用神/相神/生用神的十神运\n"
            "  - 忌神运 → 克制用神/帮扶忌神的十神运\n\n"
            "STEP 4: 成败救应检查\n"
            "  - 检查败因（如伤官克官、比劫夺财）\n"
            "  - 检查救应（如印制伤官、官杀制比劫）\n"
            "  - 救应等级：透干有根=上等，透干无根=中等，暗藏=下等"
        ),
        "output_format": (
            "相神配置：{十神名}({角色：生用/护用/制用/化用/泄用})\n"
            "喜神五行：{五行列表}\n"
            "忌神五行：{五行列表}\n"
            "喜神十神运：{十神运列表}\n"
            "忌神十神运：{十神运列表}\n"
            "败因检测：{有/无}（{如有，列出}）\n"
            "救应检测：{有/无}（{如有，列出救应之神和等级}）"
        ),
    },
    4: {
        "name": "十神定位",
        "core_question": "命局中各十神的分布、旺衰及互相关系如何？（主干，优先检查）",
        "classical_basis": (
            "《渊海子平·论十神》：'以日为主，定十神之吉凶，察岁运之得失。'\n"
            "《子平真诠·论十干配合性情》：'两干并透，而各有取用。'\n"
            "《滴天髓·生克》：'生方怕动库宜开，败地逢冲仔细推。'"
        ),
        "operation_rules": (
            "【主干】此步为核心推导主干，优先于宫位取象检查\n\n"
            "STEP 1: 十神通干统计\n"
            "  - 列出四柱天干各十神\n"
            "  - 标记透干十神的位置和力量\n\n"
            "STEP 2: 十神地支根气统计\n"
            "  - 统计各地支藏干对应的十神\n"
            "  - 标记有根（本气≥0.5/中气≥0.3/余气<0.3）\n\n"
            "STEP 3: 十神生克制化分析\n"
            "  - 相生关系链：列出连续相生链条\n"
            "  - 相克关系链：列出连续相克链条\n"
            "  - 判断最终受益/受损的十神\n\n"
            "STEP 4: 十神与格局的关系\n"
            "  - 用神十神的旺衰 → 决定格局力量\n"
            "  - 相神十神的配置 → 决定格局高低\n"
            "  - 忌神十神的制约 → 决定格局成败"
        ),
        "output_format": (
            "天干十神分布：\n"
            "  年干({十神}) 月干({十神}) 日干(日主) 时干({十神})\n"
            "地支十神根气：\n"
            "  年支: {藏干十神列表}\n"
            "  月支: {藏干十神列表}\n"
            "  日支: {藏干十神列表}\n"
            "  时支: {藏干十神列表}\n"
            "生克链条：{描述}\n"
            "最终判断：{用神旺衰 / 相神配置 / 忌神制约}"
        ),
    },
    5: {
        "name": "宫位取象",
        "core_question": "各宫位（年/月/日/时）的具体人事含义是什么？（分支，依赖前四步）",
        "classical_basis": (
            "《子平真诠·论六亲》：'六亲之论，以十神定其本，以宫位明其位，以旺衰判其力。"
            "三者合参，六亲之事可推矣。'\n"
            "《渊海子平·六亲总篇》：'年为祖上，月为父母兄弟，日为自身妻宫，时为子息。'\n"
            "《滴天髓·六亲》：'父母或兴与或替，岁月所关果非细。'"
        ),
        "operation_rules": (
            "【分支】此步依赖前四步（格局、用神、喜忌、十神定位）的结果\n\n"
            "年柱（祖上/童年，1-16岁）：\n"
            "  - 偏财在年柱 → 父亲祖业根基\n"
            "  - 正印在年柱 → 母亲/祖上教育\n"
            "  - 正官/七杀在年柱 → 祖上官职/地位\n\n"
            "月柱（父母/门第，17-32岁）：\n"
            "  - 正印在月柱 → 母亲/学历\n"
            "  - 偏财在月柱 → 父亲社会地位\n"
            "  - 比肩/劫财在月柱 → 兄弟姐妹\n"
            "  - 官杀在月柱 → 青年事业\n\n"
            "日柱（自身/配偶，33-48岁）：\n"
            "  - 正财在日支 → 妻子（男命）\n"
            "  - 正官在日支 → 丈夫（女命）\n"
            "  - 日支十神 → 配偶性格\n"
            "  - 日支与月支关系 → 婚姻质量\n\n"
            "时柱（子女/晚年，49岁+）：\n"
            "  - 食神在时柱 → 儿子\n"
            "  - 伤官在时柱 → 女儿\n"
            "  - 正官在时柱 → 子女有出息\n"
            "  - 时支与日支关系 → 晚年生活\n\n"
            "注意：宫位取象必须与十神定位结果交叉验证，"
            "不可脱离十神生克制化的主干单独使用。"
        ),
        "output_format": (
            "年柱取象：{宫位领域} → {十神分析} → {事件推断}\n"
            "月柱取象：{宫位领域} → {十神分析} → {事件推断}\n"
            "日柱取象：{宫位领域} → {十神分析} → {事件推断}\n"
            "时柱取象：{宫位领域} → {十神分析} → {事件推断}\n"
            "交叉验证：{与十神定位的一致性检查}"
        ),
    },
    6: {
        "name": "应期锁定",
        "core_question": "关键事件的发生时间窗口？大运流年如何应事？",
        "classical_basis": (
            "《子平真诠·论行运成格变格》：'大运行运，有行运而格局不变者，"
            "有行运而格局遂变者。变化之大，有不可以常理测者。'\n"
            "《子平真诠·论大运流年》：'大运主十年之否泰，流年主一岁之荣枯。'\n"
            "《滴天髓·岁运》：'休咎系乎运，尤系乎岁。'"
        ),
        "operation_rules": (
            "STEP 1: 大运分析\n"
            "  - 每步大运的十神属性（天干+地支）\n"
            "  - 大运是否补足原局不足 → 运中成格\n"
            "  - 大运是否改变格局性质 → 运中变格\n"
            "  - 大运是否破坏原局优势 → 运中破格\n"
            "  - 大运是否同时带来正负效应 → 运中并存\n"
            "  - 以上效应皆标注'运过即止'\n\n"
            "STEP 2: 流年分析\n"
            "  - 选取用神透干/得禄的流年 → 重点年份\n"
            "  - 选取忌神透干/得禄的流年 → 注意年份\n"
            "  - 刑冲合害分析：流年与命局、大运的关系\n\n"
            "STEP 3: 关键应期\n"
            "  - 结婚应期：财官到位之年（男命）、官星合入之年（女命）\n"
            "  - 事业应期：用神/相神得禄之年\n"
            "  - 变动应期：大运交脱之际（±2年）\n"
            "  - 注意应期：忌神透干/冲克用神之年"
        ),
        "output_format": (
            "当前大运：{干支}（{十神}运）→ {成格/变格/破格/并存}效应\n"
            "大运区间：{start_year}-{end_year}\n"
            "关键流年：\n"
            "  {年份}: {事件类型}（{分析依据}）\n"
            "大运交脱：{上一下运交界年份} ±2年\n"
            "中长期趋势：{描述}"
        ),
    },
}

# 中间层主次关系提醒文本
TRUNK_BRANCH_REMINDER = (
    "【中间层主次关系提醒】\n"
    "优先检查十神定位和生克制化主干，"
    "再展开宫位取象和刑冲合害分支。"
    "分支不纠缠，以主干推导为准。"
)


def build_step_prompt(step_number: int, bazi_data: dict, rag_results: dict = None,
                      prior_conclusions: dict = None) -> str:
    """构建单步推导 Prompt

    Args:
        step_number: 步骤编号 1-6
        bazi_data: 排盘数据（含四柱、用神、旺衰等）
        rag_results: RAG 检索结果（可选）
        prior_conclusions: 前几步的结论（可选），用于传递上下文

    Returns:
        格式化的单步提示词字符串
    """
    if step_number not in SIX_STEP_TEMPLATES:
        raise ValueError(f"step_number 必须在 1-6 之间，收到: {step_number}")

    template = SIX_STEP_TEMPLATES[step_number]
    lines = []

    # 标题
    lines.append(f"## 第{step_number}步：{template['name']}")
    lines.append("")

    # 核心问题
    lines.append(f"### 核心问题")
    lines.append(template["core_question"])
    lines.append("")

    # 古籍依据
    lines.append(f"### 古籍依据")
    lines.append(template["classical_basis"])
    lines.append("")

    # 操作规则
    lines.append(f"### 操作规则")
    lines.append(template["operation_rules"])
    lines.append("")

    # 输出格式
    lines.append(f"### 输出格式")
    lines.append(template["output_format"])
    lines.append("")

    # 中间层提醒（每步都必须包含）
    lines.append(TRUNK_BRANCH_REMINDER)
    lines.append("")

    # 前几步结论传递
    if prior_conclusions:
        lines.append("### 前序步骤结论")
        for step, conclusion in sorted(prior_conclusions.items()):
            if step < step_number:
                lines.append(f"第{step}步（{SIX_STEP_TEMPLATES[step]['name']}）结论：")
                lines.append(str(conclusion))
                lines.append("")

    # 命盘数据
    if bazi_data:
        lines.append("### 命盘数据")
        lines.append(_format_bazi_data(bazi_data))
        lines.append("")

    # RAG 检索结果
    if rag_results:
        lines.append("### 相关典籍参考")
        for key, text in rag_results.items():
            lines.append(f"- {key}: {text}")
        lines.append("")

    return "\n".join(lines)


def build_full_pipeline_prompt(bazi_data: dict, rag_results: dict = None) -> str:
    """构建完整六步推导 Prompt（全量调用）

    Args:
        bazi_data: 排盘数据
        rag_results: RAG 检索结果（可选）

    Returns:
        完整的六步推导提示词
    """
    lines = []
    lines.append("# 子平格局派六步推导法 - 完整流程")
    lines.append("")
    lines.append("请按照以下六步顺序，逐步推导命盘：")
    lines.append("")
    lines.append("1. 定格局 → 2. 辨用神 → 3. 明喜忌 → 4. 十神定位 → 5. 宫位取象 → 6. 应期锁定")
    lines.append("")
    lines.append(TRUNK_BRANCH_REMINDER)
    lines.append("")

    # 命盘数据
    if bazi_data:
        lines.append("## 命盘数据")
        lines.append(_format_bazi_data(bazi_data))
        lines.append("")

    # RAG 检索结果
    if rag_results:
        lines.append("## 相关典籍参考")
        for key, text in rag_results.items():
            lines.append(f"- {key}: {text}")
        lines.append("")

    # 逐步展开
    for step_number in range(1, 7):
        template = SIX_STEP_TEMPLATES[step_number]
        lines.append(f"---")
        lines.append(f"## 第{step_number}步：{template['name']}")
        lines.append("")
        lines.append(f"**核心问题**：{template['core_question']}")
        lines.append("")
        lines.append(f"**操作规则**：")
        lines.append(template["operation_rules"])
        lines.append("")
        lines.append(f"**输出格式**：")
        lines.append(template["output_format"])
        lines.append("")
        lines.append(TRUNK_BRANCH_REMINDER)
        lines.append("")

    return "\n".join(lines)


def _format_bazi_data(bazi_data: dict) -> str:
    """格式化命盘数据为可读字符串"""
    lines = []

    # 出生信息
    birth = bazi_data.get("birth_info", {})
    if birth:
        y, m, d = birth.get("year", ""), birth.get("month", ""), birth.get("day", "")
        h, mi = birth.get("hour", ""), birth.get("minute", "")
        lines.append(f"出生时间：{y}年{m}月{d}日 {h}时{mi}分")

    # 四柱
    fp = bazi_data.get("four_pillars", {})
    if fp:
        pillars = []
        for pos in ["year", "month", "day", "hour"]:
            p = fp.get(pos, {})
            stem = p.get("stem", "?")
            branch = p.get("branch", "?")
            pillars.append(f"{stem}{branch}")
        lines.append(f"四柱：{' '.join(pillars)}")

    # 日主
    dm = bazi_data.get("day_master", "")
    if dm:
        lines.append(f"日主：{dm}")

    # 格局
    pattern = bazi_data.get("pattern", "")
    if pattern:
        lines.append(f"格局：{pattern}")

    # 用神
    yongshen = bazi_data.get("yongshen", {})
    if yongshen:
        ys_tg = yongshen.get("ten_god", yongshen.get("tiangan", ""))
        ys_wx = yongshen.get("five_element", yongshen.get("wuxing", ""))
        ys_mode = yongshen.get("mode", "")
        lines.append(f"用神：{ys_tg}({ys_wx}) - {ys_mode}")

    # 旺衰
    wangshuai = bazi_data.get("wangshuai", bazi_data.get("step_results", {}).get("wangshuai", {}))
    if isinstance(wangshuai, dict):
        wl = wangshuai.get("level", "")
        if wl:
            lines.append(f"旺衰：{wl}")

    # 大运
    dayun = bazi_data.get("dayun", [])
    if dayun:
        lines.append(f"大运：{len(dayun)}步")
        for da in dayun[:3]:
            lines.append(f"  {da.get('stem','')}{da.get('branch','')} "
                        f"({da.get('ten_god','')}) "
                        f"{da.get('start_year','')}-{da.get('end_year','')}")

    return "\n".join(lines)
