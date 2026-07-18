"""AI 解释模块 - 用 DeepSeek 生成通俗易懂的旺衰分析解释"""

import os
import httpx


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """你是一位精通《子平真诠》《滴天髓》《穷通宝鉴》的八字命理师。

你的任务是根据规则引擎计算出的日主旺衰分析数据，用通俗易懂的语言解释给用户听。

要求：
1. 逐项解释每个判断因素（得令、得地、得生、得助、克泄耗）
2. 每个解释引用相关原文（如"《滴天髓》云：'令上寻真最为先'"）
3. 用比喻让非专业人士也能理解（如"就像一棵小树需要阳光和土壤"）
4. 语言要口语化，像真人在聊天，不要学术化
5. 不要过于绝对，用"往往""一般来说"等词
6. 最后给出综合结论和用神建议
7. 每段解释控制在 100-150 字"""


# ============================================================
# DeepSeek API 调用
# ============================================================

async def call_deepseek(prompt: str, system_prompt: str) -> str:
    """
    调用 DeepSeek API 生成文本

    Args:
        prompt: 用户消息
        system_prompt: 系统提示

    Returns:
        AI 生成的文本，如果未配置 API Key 则返回空字符串
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return ""

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


# ============================================================
# 构建 Prompt
# ============================================================

def _build_prompt(strength_detail: dict, relevant_texts: list[dict]) -> str:
    """
    构建发送给 AI 的用户消息

    Args:
        strength_detail: 规则引擎输出的旺衰分析数据
        relevant_texts: RAG 检索到的相关原文

    Returns:
        格式化的用户消息
    """
    # 格式化原文引用
    texts_section = ""
    for i, text in enumerate(relevant_texts, 1):
        texts_section += f"\n{i}. 【{text['source']}·{text['chapter']}】{text['text']}\n   主题：{text['topic']} | 说明：{text.get('context', '')}\n"

    # 格式化旺衰数据
    data_section = f"""
日主：{strength_detail.get('ri_zhu', '')}（{strength_detail.get('ri_zhu_wuxing', '')}）
格局：{strength_detail.get('pattern', '')}
旺衰：{strength_detail.get('ri_zhu_strength', '')}
总分：{strength_detail.get('total_score', 0)}

得令（月令）：{strength_detail.get('deling', {}).get('conclusion', '')}
  详情：{'; '.join(strength_detail.get('deling', {}).get('detail', []))}

得地（通根）：{strength_detail.get('dedi', {}).get('conclusion', '')}
  详情：{'; '.join(strength_detail.get('dedi', {}).get('detail', []))}

得生（印星）：{strength_detail.get('desheng', {}).get('conclusion', '')}
  详情：{'; '.join(strength_detail.get('desheng', {}).get('detail', []))}

得助（比劫）：{strength_detail.get('dezhu', {}).get('conclusion', '')}
  详情：{'; '.join(strength_detail.get('dezhu', {}).get('detail', []))}

克泄耗：{strength_detail.get('ke_xie_hao', {}).get('conclusion', '')}
  详情：{'; '.join(strength_detail.get('ke_xie_hao', {}).get('detail', []))}

用神：{strength_detail.get('yongshen', {}).get('primary', '')}
喜神：{strength_detail.get('yongshen', {}).get('secondary', '')}
忌神：{strength_detail.get('yongshen', {}).get('ji_shen', '')}
"""

    prompt = f"""以下是规则引擎计算出的八字旺衰分析数据：

{data_section}

以下是检索到的相关命理典籍原文：
{texts_section}

请根据以上数据，逐项解释日主的旺衰情况。要求：
1. 逐项解释得令、得地、得生、得助、克泄耗
2. 每项引用相关原文
3. 用比喻让外行人也能听懂
4. 最后给出综合结论和用神建议
5. 语言口语化，像朋友聊天"""

    return prompt


# ============================================================
# Mock 模式（无 API Key 时的模板解释）
# ============================================================

def generate_mock_explanation(strength_detail: dict, relevant_texts: list[dict]) -> str:
    """
    无 API Key 时的模板化解释

    根据 strength_detail 中的数据，引用知识库原文，生成通俗解释。

    Args:
        strength_detail: 规则引擎输出的旺衰分析数据
        relevant_texts: RAG 检索到的相关原文

    Returns:
        模板化的解释文本
    """
    ri_zhu = strength_detail.get("ri_zhu", "")
    ri_zhu_wx = strength_detail.get("ri_zhu_wuxing", "")
    pattern = strength_detail.get("pattern", "")
    ri_zhu_strength = strength_detail.get("ri_zhu_strength", "")
    total_score = strength_detail.get("total_score", 0)

    # 获取各维度结论
    deling = strength_detail.get("deling", {})
    dedi = strength_detail.get("dedi", {})
    desheng = strength_detail.get("desheng", {})
    dezhu = strength_detail.get("dezhu", {})
    ke_xie_hao = strength_detail.get("ke_xie_hao", {})
    yongshen = strength_detail.get("yongshen", {})

    # 构建原文引用映射
    texts_by_topic: dict[str, list[dict]] = {}
    for t in relevant_texts:
        topic = t.get("topic", "")
        texts_by_topic.setdefault(topic, []).append(t)

    def _get_quote(topic: str) -> str:
        """从检索结果中取一条原文引用"""
        entries = texts_by_topic.get(topic, [])
        if entries:
            e = entries[0]
            return '《' + e['source'] + '》云："' + e['text'] + '"'
        return ""

    # 五行比喻
    wuxing_metaphor = {
        "金": "一把刚硬的宝剑",
        "木": "一棵扎根大地的树木",
        "水": "一条奔流不息的河流",
        "火": "一团温暖明亮的火焰",
        "土": "一座厚重稳固的山丘",
    }
    metaphor = wuxing_metaphor.get(ri_zhu_wx, "一个独特的生命")

    # 构建解释
    sections = []

    # 标题
    sections.append(f"## {ri_zhu}{ri_zhu_wx}日主旺衰分析\n")
    sections.append(f"你的日主是{ri_zhu}，五行属{ri_zhu_wx}。{metaphor}，我们来看看它的「生存环境」如何。\n")

    # 得令
    deling_quote = _get_quote("得令")
    if deling["score"] >= 50:
        deling_explain = f"首先看得令——月令是判断旺衰最重要的因素。{deling['conclusion']}，说明{ri_zhu_wx}在当月处于最旺的状态，就像{metaphor}正好生长在最适合的季节。"
    elif deling["score"] >= 25:
        deling_explain = f"首先看得令——月令是判断旺衰最重要的因素。{deling['conclusion']}，说明{ri_zhu_wx}在当月有一定的助力，就像{metaphor}得到了季节的眷顾。"
    elif deling["score"] > 0:
        deling_explain = f"首先看得令——月令是判断旺衰最重要的因素。{deling['conclusion']}，说明{ri_zhu_wx}在当月得到的助力有限，就像{metaphor}虽然有阳光但不太充足。"
    else:
        deling_explain = f"首先看得令——月令是判断旺衰最重要的因素。{deling['conclusion']}，说明{ri_zhu_wx}在当月没有得到助力，就像{metaphor}赶上了不太有利的季节。"
    if deling_quote:
        deling_explain += f" {deling_quote}"
    sections.append(f"### 得令（月令）\n{deling_explain}\n")

    # 得地
    dedi_quote = _get_quote("得地")
    if dedi["score"] >= 40:
        dedi_explain = f"再看得地——也就是地支中有没有{ri_zhu_wx}的「根」。{dedi['conclusion']}，多个地支都有根气，就像{metaphor}的根系深深扎入土壤，站得很稳。"
    elif dedi["score"] >= 24:
        dedi_explain = f"再看得地——也就是地支中有没有{ri_zhu_wx}的「根」。{dedi['conclusion']}，部分地支有根，就像{metaphor}的根系还不错，能站住脚。"
    elif dedi["score"] >= 8:
        dedi_explain = f"再看得地——也就是地支中有没有{ri_zhu_wx}的「根」。{dedi['conclusion']}，只有个别地支有根，就像{metaphor}的根系不太发达，有点飘。"
    else:
        dedi_explain = f"再看得地——也就是地支中有没有{ri_zhu_wx}的「根」。{dedi['conclusion']}，几乎没有根基，就像{metaphor}被悬在空中，缺乏支撑。"
    if dedi_quote:
        dedi_explain += f" {dedi_quote}"
    sections.append(f"### 得地（通根）\n{dedi_explain}\n")

    # 得生
    desheng_quote = _get_quote("得生")
    if desheng["score"] >= 30:
        desheng_explain = f"接下来看得生——有没有印星来生扶你。{desheng['conclusion']}，印星力量充足，就像{metaphor}得到了充沛的雨露滋润。"
    elif desheng["score"] >= 15:
        desheng_explain = f"接下来看得生——有没有印星来生扶你。{desheng['conclusion']}，有一些印星帮助，就像{metaphor}偶尔能喝到水。"
    elif desheng["score"] > 0:
        desheng_explain = f"接下来看得生——有没有印星来生扶你。{desheng['conclusion']}，印星力量有限，就像{metaphor}只能得到少量的养分。"
    else:
        desheng_explain = f"接下来看得生——有没有印星来生扶你。{desheng['conclusion']}，没有任何印星生扶，就像{metaphor}完全没有水源，只能靠自己。"
    if desheng_quote:
        desheng_explain += f" {desheng_quote}"
    sections.append(f"### 得生（印星）\n{desheng_explain}\n")

    # 得助
    dezhu_quote = _get_quote("得助")
    if dezhu["score"] >= 30:
        dezhu_explain = f"再看得助——比劫是否帮你。{dezhu['conclusion']}，比劫众多，就像{metaphor}身边有一群伙伴并肩作战。"
    elif dezhu["score"] >= 15:
        dezhu_explain = f"再看得助——比劫是否帮你。{dezhu['conclusion']}，有一些比劫帮忙，就像{metaphor}有几个朋友可以依靠。"
    elif dezhu["score"] > 0:
        dezhu_explain = f"再看得助——比劫是否帮你。{dezhu['conclusion']}，比劫力量有限，就像{metaphor}偶尔有人搭把手。"
    else:
        dezhu_explain = f"再看得助——比劫是否帮你。{dezhu['conclusion']}，完全没有比劫帮身，就像{metaphor}孤军奋战，只能靠自己。"
    if dezhu_quote:
        dezhu_explain += f" {dezhu_quote}"
    sections.append(f"### 得助（比劫）\n{dezhu_explain}\n")

    # 克泄耗
    ke_quote = _get_quote("十神")
    penalty = abs(ke_xie_hao.get("score", 0))
    if penalty == 0:
        ke_explain = f"最后看克泄耗——有没有力量在消耗你。{ke_xie_hao['conclusion']}，没有官杀、食伤、财星来克制消耗，就像{metaphor}没有风雨侵袭，可以安心成长。"
    elif penalty <= 15:
        ke_explain = f"最后看克泄耗——有没有力量在消耗你。{ke_xie_hao['conclusion']}，有一些克泄耗的力量，但不算太重，就像{metaphor}遇到了一些小风雨，基本能扛住。"
    elif penalty <= 30:
        ke_explain = f"最后看克泄耗——有没有力量在消耗你。{ke_xie_hao['conclusion']}，克泄耗的力量中等，就像{metaphor}遇到了不小的风雨，需要一些保护。"
    else:
        ke_explain = f"最后看克泄耗——有没有力量在消耗你。{ke_xie_hao['conclusion']}，克泄耗的力量很重，就像{metaphor}遭遇了暴风雨，压力很大。"
    if ke_quote:
        ke_explain += f" {ke_quote}"
    sections.append(f"### 克泄耗\n{ke_explain}\n")

    # 综合结论
    sections.append(f"### 综合结论\n")
    if total_score >= 80:
        conclusion = f"综合来看，你的日主{ri_zhu}{ri_zhu_wx}总分{total_score}分，属于{ri_zhu_strength}的状态。就像{metaphor}处于巅峰状态，力量充沛。"
    elif total_score >= 60:
        conclusion = f"综合来看，你的日主{ri_zhu}{ri_zhu_wx}总分{total_score}分，属于{ri_zhu_strength}的状态。就像{metaphor}精力充沛，能够承担重任。"
    elif total_score >= 40:
        conclusion = f"综合来看，你的日主{ri_zhu}{ri_zhu_wx}总分{total_score}分，属于{ri_zhu_strength}的状态。就像{metaphor}状态不错，各方面比较均衡。"
    elif total_score >= 20:
        conclusion = f"综合来看，你的日主{ri_zhu}{ri_zhu_wx}总分{total_score}分，属于{ri_zhu_strength}的状态。就像{metaphor}力量有些不足，需要外部的支持和帮助。"
    else:
        conclusion = f"综合来看，你的日主{ri_zhu}{ri_zhu_wx}总分{total_score}分，属于{ri_zhu_strength}的状态。就像{metaphor}非常虚弱，需要特别的呵护。"

    if "从弱" in pattern:
        conclusion += f" 这是一个{pattern}的命局，{ri_zhu}太弱了，与其硬撑不如顺势而为，借助外力来发展。"
    elif "从强" in pattern:
        conclusion += f" 这是一个{pattern}的命局，{ri_zhu}太强了，顺势而为，继续加强自身优势就好。"
    else:
        conclusion += f" 这是{pattern}的命局。"

    sections.append(f"{conclusion}\n")

    # 用神建议
    primary = yongshen.get("primary", "")
    secondary = yongshen.get("secondary", "")
    ji_shen = yongshen.get("ji_shen", "")
    yongshen_quote = _get_quote("用神")

    sections.append(f"### 用神建议\n")
    yongshen_explain = f"根据旺衰分析，你的用神是{primary}五行，喜神是{secondary}五行，忌神是{ji_shen}五行。"
    if total_score >= 50:
        yongshen_explain += f" 身强宜泄耗，日常生活中可以多亲近{primary}和{secondary}属性的事物，比如颜色、方位、行业等。"
    else:
        yongshen_explain += f" 身弱宜扶助，日常生活中可以多亲近{primary}和{secondary}属性的事物来增强自身力量。"
    if yongshen_quote:
        yongshen_explain += f" {yongshen_quote}"
    sections.append(f"{yongshen_explain}\n")

    # 免责声明
    sections.append("---\n*以上分析基于传统命理规则引擎计算，仅供参考和学习之用。*")

    return "\n".join(sections)


# ============================================================
# 主函数：生成旺衰分析解释
# ============================================================

async def generate_strength_explanation(
    strength_detail: dict,
    relevant_texts: list[dict],
) -> str:
    """
    用 DeepSeek API 生成通俗易懂的旺衰分析解释

    如果未配置 DEEPSEEK_API_KEY，则使用模板化的 Mock 解释。

    Args:
        strength_detail: 规则引擎输出的旺衰分析数据
        relevant_texts: RAG 检索到的相关原文

    Returns:
        通俗易懂的旺衰分析解释文本
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        return generate_mock_explanation(strength_detail, relevant_texts)

    try:
        prompt = _build_prompt(strength_detail, relevant_texts)
        result = await call_deepseek(prompt, SYSTEM_PROMPT)
        if result:
            return result
        # API 调用失败时回退到 Mock
        return generate_mock_explanation(strength_detail, relevant_texts)
    except Exception:
        # 任何异常都回退到 Mock
        return generate_mock_explanation(strength_detail, relevant_texts)
