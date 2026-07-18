"""流年分析 API —— 60甲子循环推流年干支 + AI 五维分析"""
import re, json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from services.gate import require_auth
from services.deepseek_client import call_deepseek

router = APIRouter(prefix="/api/liunian", tags=["liunian"])

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
WUXING_OF = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
B_WUXING_OF = {
    "寅": "木", "卯": "木", "巳": "火", "午": "火",
    "申": "金", "酉": "金", "亥": "水", "子": "水",
    "辰": "土", "丑": "土", "戌": "土", "未": "土",
}
_SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
_I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_I_KE = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}
_YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
            "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
WX_COLOR = {"金": "#fbbf24", "木": "#4ade80", "水": "#60a5fa", "火": "#f87171", "土": "#a78bfa"}

# 五虎遁：年干 → 正月(寅月)天干
WU_HU_DUN = {"甲": "丙", "乙": "戊", "丙": "庚", "丁": "壬", "戊": "甲",
             "己": "丙", "庚": "戊", "辛": "庚", "壬": "壬", "癸": "甲"}


def _year_gz(year: int) -> str:
    base = 4
    idx = (year - base) % 60
    return GAN[idx % 10] + ZHI[idx % 12]


def _ten_god(day_master: str, stem: str) -> str:
    dm_wx = WUXING_OF.get(day_master, "")
    ot_wx = WUXING_OF.get(stem, "")
    if not dm_wx or not ot_wx:
        return ""
    same_yy = _YINYANG.get(day_master) == _YINYANG.get(stem)
    if dm_wx == ot_wx:
        return "比肩" if same_yy else "劫财"
    if _SHENG.get(dm_wx) == ot_wx:
        return "偏印" if same_yy else "正印"
    if _I_SHENG.get(dm_wx) == ot_wx:
        return "食神" if same_yy else "伤官"
    if _I_KE.get(dm_wx) == ot_wx:
        return "偏财" if same_yy else "正财"
    if _KE.get(dm_wx) == ot_wx:
        return "七杀" if same_yy else "正官"
    return ""


def _xi_ji(gz: str, yongshen: dict) -> str:
    stem = gz[0]
    ys_p = (yongshen.get("primary") or "").strip()
    ys_s = (yongshen.get("secondary") or "").strip()
    ys_j = (yongshen.get("ji_shen") or "").strip()
    wx = WUXING_OF.get(stem, "")
    if wx and (wx == ys_p or wx == ys_s):
        return "喜"
    if wx and wx == ys_j:
        return "忌"
    return "平"


def _derive_month_pillars(year_gz: str) -> list:
    """从年柱推12个流月干支，返回 [{stem, branch, ten_god, xi_ji, gan_index}...]"""
    year_stem = year_gz[0]
    first_stem_index = GAN.index(WU_HU_DUN[year_stem])
    months = []
    # 寅月=2 (0-indexed in ZHI)
    for m in range(12):
        branch_index = (2 + m) % 12
        stem_index = (first_stem_index + m) % 10
        months.append({
            "stem": GAN[stem_index],
            "branch": ZHI[branch_index],
        })
    return months


class LiuNianRequest(BaseModel):
    chart_data: dict
    year: int = 0
    feedbacks: list = []
    predictions: list = []


class DimItem(BaseModel):
    summary: str = ""
    score: int = 50
    key_actions: dict = {}


class LiuNianResponse(BaseModel):
    year: int
    year_gz: str
    ten_god: str
    xi_ji: str
    analysis: dict[str, DimItem]


@router.post("", response_model=LiuNianResponse)
async def get_liunian(
    req: LiuNianRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    cd = req.chart_data
    day_master = cd.get("day_master", "")
    yongshen = cd.get("yongshen", {}) or cd.get("strength_detail", {}).get("yongshen", {})

    if not day_master:
        raise HTTPException(status_code=400, detail="排盘数据不完整")

    target_year = req.year or 2026
    gz = _year_gz(target_year)
    tg = _ten_god(day_master, gz[0])
    xj = _xi_ji(gz, yongshen)

    # Find which dayun this year belongs to
    dayun = cd.get("dayun", [])
    current_dayun = None
    for du in dayun:
        sy = du.get("start_year", 0)
        ey = du.get("end_year", 0)
        if sy <= target_year <= ey:
            current_dayun = du
            break

    # Derive 12 monthly pillars
    months = _derive_month_pillars(gz)
    month_lines = []
    month_labels = ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"]
    for i, mp in enumerate(months):
        m_stem = mp["stem"]
        m_branch = mp["branch"]
        m_tg = _ten_god(day_master, m_stem)
        m_xj = _xi_ji(m_stem + m_branch, yongshen)
        month_lines.append(
            f"  {i+1}月 {m_stem}{m_branch}（{m_tg}，{m_xj}）"
        )

    prompt = _build_liunian_prompt(cd, gz, tg, xj, target_year, yongshen, current_dayun, month_lines, req.feedbacks, req.predictions)
    ai_text = await call_deepseek(
        prompt,
        system_prompt="你是专业八字命理师，请用简洁中文回答，严格按JSON格式输出。",
        temperature=0.5, max_tokens=2000,
    )

    analysis = _parse_liunian_ai(ai_text)

    return LiuNianResponse(
        year=target_year, year_gz=gz, ten_god=tg, xi_ji=xj,
        analysis={
            "career": DimItem(**analysis.get("career", {})),
            "wealth": DimItem(**analysis.get("wealth", {})),
            "marriage": DimItem(**analysis.get("marriage", {})),
            "relationship": DimItem(**analysis.get("relationship", {})),
            "health": DimItem(**analysis.get("health", {})),
        },
    )


def _build_liunian_prompt(cd, year_gz, ten_god, xi_ji, year, yongshen, current_dayun, month_lines, feedbacks=None, predictions=None):
    import datetime
    current_year = datetime.datetime.now().year
    day_master = cd.get("day_master", "")
    dm_wx = WUXING_OF.get(day_master, "")
    gender = "男" if cd.get("gender") == "male" else "女"

    # 推算出生年
    dayun_list = cd.get("dayun", [])
    birth_year = 1990
    if dayun_list:
        first_du = dayun_list[0]
        sy = first_du.get("start_year", 0)
        sa = first_du.get("start_age", 0)
        if sy and sa is not None:
            birth_year = sy - sa
    age = current_year - birth_year

    ys_p = yongshen.get("primary", "")
    ys_s = yongshen.get("secondary", "")
    ys_j = yongshen.get("ji_shen", "")
    ys_pattern = yongshen.get("pattern", "")
    ys_strength = yongshen.get("ri_zhu_strength", "")
    pillars = cd.get("four_pillars", {})
    wuxing_score = cd.get("wuxing_score", {})

    lines = ["## 命主信息"]
    lines.append(f"日主：{day_master}（五行{dm_wx}）")
    lines.append(f"性别：{gender}")
    lines.append(f"出生年份：{birth_year}年")
    lines.append(f"当前年龄：{age}岁（{current_year}年）")
    lines.append(f"用神：{ys_p}，喜神：{ys_s}，忌神：{ys_j}")
    lines.append(f"格局：{ys_pattern}，日主强弱：{ys_strength}")

    # 四柱（含藏干）
    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    lines.append("\n## 四柱排盘")
    stem_wx_map = {}
    branch_wx_map = {}
    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        stem = p.get("stem", "")
        branch = p.get("branch", "")
        stem_tg = p.get("stem_ten_god", "")
        nayin = p.get("nayin", "")
        hidden = p.get("hidden_stems", [])
        hidden_str = "、".join([f"{h.get('stem', '')}({h.get('ten_god', '')})" for h in hidden])
        stem_wx_map[pos] = WUXING_OF.get(stem, "")
        branch_wx_map[pos] = B_WUXING_OF.get(branch, "")
        lines.append(f"  {pos_names[pos]}：{stem}{branch} 十神={stem_tg} 藏干=[{hidden_str}] 纳音={nayin}")

    # 十神分布
    tg_counts = {}
    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        for tg_key in [p.get("stem_ten_god", ""), p.get("branch_ten_god", "")]:
            if tg_key:
                tg_counts[tg_key] = tg_counts.get(tg_key, 0) + 1
    if tg_counts:
        lines.append(f"十神分布：{', '.join(f'{k}{v}次' for k, v in sorted(tg_counts.items(), key=lambda x: -x[1]))}")

    # 职业倾向
    career_hints = {
        "金": "宜珠宝、金融、精密制造、法律",
        "木": "宜教育、医疗、环保、文化传播",
        "水": "宜物流、贸易、传媒、旅游",
        "火": "宜能源、餐饮、互联网、演艺",
        "土": "宜地产、建筑、农业、金融中介",
    }
    lines.append(f"职业倾向提示：{career_hints.get(dm_wx, '根据命局自行判断')}")

    # 四柱五行结构
    lines.append(f"四柱五行：年{stem_wx_map.get('year','')}{branch_wx_map.get('year','')} 月{stem_wx_map.get('month','')}{branch_wx_map.get('month','')} 日{stem_wx_map.get('day','')}（日主）{branch_wx_map.get('day','')} 时{stem_wx_map.get('hour','')}{branch_wx_map.get('hour','')}")

    # 五行力量
    if wuxing_score:
        lines.append("\n## 五行力量")
        ws = wuxing_score
        lines.append(f"  金={ws.get('jin', 0):.1f}% 木={ws.get('mu', 0):.1f}% 水={ws.get('shui', 0):.1f}% 火={ws.get('huo', 0):.1f}% 土={ws.get('tu', 0):.1f}%")

    # 神煞
    shensha = cd.get("shensha", [])
    if shensha:
        ss_str = "、".join([f"{s.get('name', '')}({s.get('position', '')})" for s in shensha])
        lines.append(f"\n## 神煞\n  {ss_str}")

    # 断前事反馈
    feedbacks = feedbacks or []
    predictions = predictions or []
    if feedbacks:
        STATUS_LABELS = {"confirmed": "确认正确", "wrong": "确认错误", "partially_correct": "部分正确"}
        lines.append("\n## 断前事校准反馈")
        for i, fb in enumerate(feedbacks):
            if not fb.get("status"):
                continue
            pred = predictions[i] if i < len(predictions) else {}
            status_cn = STATUS_LABELS.get(fb.get("status", ""), fb.get("status", ""))
            note = fb.get("note", "")
            note_str = f"，备注：{note}" if note else ""
            lines.append(f"  第{i+1}条：{pred.get('category','断前事')} → {status_cn}{note_str}")

    # 大运
    if current_dayun:
        du_stem = current_dayun.get("stem", "")
        du_branch = current_dayun.get("branch", "")
        du_tg = current_dayun.get("ten_god", "")
        lines.append(f"\n## 当前大运")
        lines.append(f"  {du_stem}{du_branch}（{du_tg}），{current_dayun.get('start_year','')}-{current_dayun.get('end_year','')}年，{current_dayun.get('start_age','')}-{current_dayun.get('end_age','')}岁")

    # 流年
    lines.append(f"\n## 分析目标流年")
    lines.append(f"  {year}年 {year_gz}（{ten_god}，喜忌：{xi_ji}）")

    # 12 流月
    lines.append(f"\n## {year}年12流月干支（含十神喜忌）")
    for ml in month_lines:
        lines.append(ml)

    # 分析要求
    lines.append(f"\n## 分析要求")
    lines.append(f"请基于以上完整命局信息，分析{year}年运势。")
    lines.append(f"summary需要2-3句话的详细分析，结合流月喜忌说明原因和趋势。")
    lines.append(f"score为0-100整数（参考：喜年60-85，平年40-65，忌年20-45）。")
    lines.append(f"key_actions基于具体月份的喜忌给出建议，如{{\\\"3月(庚辰 劫财 喜)\\\":\\\"劫财帮身，合作有利\\\"}}，最多4条。")
    lines.append(f"\n严格按以下JSON格式输出，只输出JSON：")
    template = """{
  "career": {"summary": "分析2-3句", "score": 60, "key_actions": {"3月(庚辰 劫财 喜)": "合作有利"}},
  "wealth": {"summary": "分析2-3句", "score": 60, "key_actions": {"6月(癸未 食神 喜)": "财运佳"}},
  "marriage": {"summary": "分析2-3句", "score": 60, "key_actions": {}},
  "relationship": {"summary": "分析2-3句", "score": 60, "key_actions": {}},
  "health": {"summary": "分析2-3句", "score": 60, "key_actions": {}}
}"""
    lines.append(template)
    return "\n".join(lines)


def _parse_liunian_ai(text: str) -> dict:
    """解析 AI 返回的 JSON，兜底返回默认值"""
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {
        dim: {"summary": text[:100] if text else "暂无分析", "score": 50, "key_actions": {}}
        for dim in ["career", "wealth", "marriage", "relationship", "health"]
    }
