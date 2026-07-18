"""流月详批 API —— 本年度 12 个月逐月分析"""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from services.gate import require_auth, require_entitlement
from services.deepseek_client import call_deepseek

router = APIRouter(prefix="/api/liuyue", tags=["liuyue"])

# ── 基础常量 ──────────────────────────────────────────
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
WUXING_OF = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
    "子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土",
    "巳": "火", "午": "火", "未": "土", "申": "金", "酉": "金",
    "戌": "土", "亥": "水",
}
GAN_INDEX = {g: i for i, g in enumerate(GAN)}
ZHI_INDEX = {z: i for i, z in enumerate(ZHI)}

# 五虎遁：年干 → 正月（寅月）天干
WU_HU_DUN = {
    "甲": "丙", "乙": "戊", "丙": "庚", "丁": "壬", "戊": "甲",
    "己": "丙", "庚": "戊", "辛": "庚", "壬": "壬", "癸": "甲",
}

# 十神计算（与 bazi_engine 一致）
_SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_KE   = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
_I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_I_KE    = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}
_YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
            "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}

# 神煞速查（精简版，高频神煞）
SHENSHA_DAY_STEM = {
    "天乙贵人": {"甲": ["丑", "未"], "戊": ["丑", "未"], "庚": ["丑", "未"],
                 "乙": ["子", "申"], "己": ["子", "申"],
                 "丙": ["亥", "酉"], "丁": ["亥", "酉"],
                 "壬": ["卯", "巳"], "癸": ["卯", "巳"], "辛": ["午", "寅"]},
    "文昌": {"甲": ["巳"], "乙": ["午"], "丙": ["申"], "丁": ["酉"],
             "戊": ["申"], "己": ["酉"], "庚": ["亥"], "辛": ["子"],
             "壬": ["寅"], "癸": ["卯"]},
    "桃花": {"子": ["酉"], "丑": ["午"], "寅": ["卯"], "卯": ["子"],
             "辰": ["酉"], "巳": ["午"], "午": ["卯"], "未": ["子"],
             "申": ["酉"], "酉": ["午"], "戌": ["卯"], "亥": ["子"]},
}
SHENSHA_YEAR_STEM = ["天乙贵人", "文昌"]  # 兼查年干


def _ten_god(day_master: str, stem: str) -> str:
    """计算十神"""
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


def _xi_ji(stem: str, branch: str, yongshen: dict) -> str:
    """判喜忌：天干优先"""
    ys_primary = (yongshen.get("primary") or "").strip()
    ys_secondary = (yongshen.get("secondary") or "").strip()
    ys_ji = (yongshen.get("ji_shen") or "").strip()
    wx_stem = WUXING_OF.get(stem, "")
    wx_branch = WUXING_OF.get(branch, "")

    def _match(wx):
        if wx == ys_primary or wx == ys_secondary:
            return "喜"
        if wx == ys_ji:
            return "忌"
        return None

    result = _match(wx_stem)
    if result:
        return result
    return _match(wx_branch) or "平"


def _branch_relations(month_branch: str, four_pillars: dict) -> list[str]:
    """地支关系：与四柱大运的刑冲合害"""
    results = []
    month_idx = ZHI_INDEX.get(month_branch, -1)
    if month_idx < 0:
        return results

    for pos in ["year", "month", "day", "hour"]:
        b = four_pillars.get(pos, {}).get("branch", "")
        if not b:
            continue
        bi = ZHI_INDEX.get(b, -1)
        # 六冲
        if (month_idx + 6) % 12 == bi:
            results.append(f"冲{pos}柱")
        # 六合
        he_pairs = [(0, 1), (2, 11), (3, 9), (4, 8), (5, 7), (6, 7)]
        for a, c in he_pairs:
            if {month_idx, bi} == {a, c}:
                results.append(f"合{pos}柱")
        # 三合
        triples = [(8, 0, 4), (2, 6, 10), (11, 3, 7), (5, 9, 1)]
        for t in triples:
            if month_idx in t and bi in t and month_idx != bi:
                results.append(f"半合{pos}柱")
                break
        # 自刑
        if month_idx == bi and month_branch in ["辰", "午", "酉", "亥"]:
            results.append(f"自刑{pos}柱")
        # 六害
        hai_pairs = [(0, 7), (1, 6), (2, 5), (3, 4), (8, 11), (9, 10)]
        if {month_idx, bi} in ({a, b} for a, b in hai_pairs):
            results.append(f"害{pos}柱")
    return results


def _shensha(month_branch: str, day_stem: str, year_stem: str, year_branch: str) -> list[str]:
    """精简神煞速查"""
    result = []
    for name, lookup in SHENSHA_DAY_STEM.items():
        if name in SHENSHA_YEAR_STEM and year_stem in lookup:
            if month_branch in lookup[year_stem]:
                result.append(name)
        if day_stem in lookup:
            if month_branch in lookup[day_stem]:
                result.append(name)
    return result


def _month_gz(year_stem: str, m: int) -> tuple[str, str]:
    """m=0 → 寅月, m=11 → 丑月, 返回 (干, 支)"""
    start_gan = WU_HU_DUN.get(year_stem, "甲")
    gan_idx = (GAN_INDEX[start_gan] + m) % 10
    zhi_idx = (2 + m) % 12  # 寅=index 2
    return GAN[gan_idx], ZHI[zhi_idx]


# ── 请求/响应模型 ─────────────────────────────────────
class LiuYueRequest(BaseModel):
    chart_data: dict  # chart.model_dump() 的完整数据
    year: int = 0     # 目标年，0=当前大运的当前年


class MonthItem(BaseModel):
    label: str           # "丙寅月"
    stem: str
    branch: str
    wuxing: str          # 天干五行
    ten_god: str
    xi_ji: str           # "喜"/"忌"/"平"
    relations: list[str] # 地支关系
    shensha: list[str]   # 神煞
    interpretation: str  # AI 解读


class LiuYueResponse(BaseModel):
    year: int
    months: list[MonthItem]


# ── API ──────────────────────────────────────────────
@router.post("", response_model=LiuYueResponse)
async def get_liuyue(
    req: LiuYueRequest,
    user_id: str = Depends(require_auth),
    _entitled: str = Depends(require_entitlement("liuyue")),
    db: AsyncSession = Depends(get_session),
):
    cd = req.chart_data
    day_master = cd.get("day_master", "")
    four_pillars = cd.get("four_pillars", {})
    year_stem = four_pillars.get("year", {}).get("stem", "")
    year_branch = four_pillars.get("year", {}).get("branch", "")
    yongshen = cd.get("yongshen", {}) or cd.get("strength_detail", {}).get("yongshen", {})

    if not day_master or not year_stem:
        raise HTTPException(status_code=400, detail="排盘数据不完整")

    target_year = req.year or 2026  # 默认当前年，可从大运推导

    # ── 逐月计算确定性项 ──
    months = []
    for m in range(12):
        stem, branch = _month_gz(year_stem, m)
        label = f"{stem}{branch}月"
        wx = WUXING_OF.get(stem, "")
        tg = _ten_god(day_master, stem)
        xj = _xi_ji(stem, branch, yongshen)
        rels = _branch_relations(branch, four_pillars)
        ss = _shensha(branch, day_master, year_stem, year_branch)
        months.append({
            "label": label, "stem": stem, "branch": branch,
            "wuxing": wx, "ten_god": tg, "xi_ji": xj,
            "relations": rels, "shensha": ss,
        })

    # ── AI 批量解读 ──
    prompt = _build_liuyue_prompt(day_master, target_year, months, yongshen)
    ai_text = await call_deepseek(prompt, system_prompt="你是专业八字命理师，请用简洁中文回答。",
                                   temperature=0.5, max_tokens=2000)

    # 解析 AI 返回的逐月解读（期望格式 "丙寅月：…\n丁卯月：…"）
    interpretations = _parse_ai_batch(ai_text, [m["label"] for m in months])

    result_months = []
    for m in months:
        result_months.append(MonthItem(
            **m, interpretation=interpretations.get(m["label"], "")
        ))

    return LiuYueResponse(year=target_year, months=result_months)


def _build_liuyue_prompt(day_master: str, year: int, months: list[dict], yongshen: dict) -> str:
    lines = [
        f"日主{day_master}，用神{yongshen.get('primary','')}，喜神{yongshen.get('secondary','')}，忌神{yongshen.get('ji_shen','')}",
        f"以下是{year}年逐月干支，请为每个月写一句运势解读（20字以内），结合当月十神和喜忌：",
    ]
    for m in months:
        ss = "、".join(m["shensha"][:2]) if m["shensha"] else "无"
        rel = "、".join(m["relations"][:2]) if m["relations"] else "无"
        lines.append(
            f"{m['label']} 天干{m['stem']}({m['wuxing']}) 十神{m['ten_god']} "
            f"喜忌:{m['xi_ji']} 神煞:{ss} 地支关系:{rel}"
        )
    lines.append("\n请逐月回复，格式：丙寅月：…(解读)")
    return "\n".join(lines)


def _parse_ai_batch(text: str, labels: list[str]) -> dict[str, str]:
    """解析 AI 返回的逐月解读"""
    result: dict[str, str] = {}
    for label in labels:
        for line in text.split("\n"):
            if line.strip().startswith(label):
                result[label] = line.strip()[len(label):].lstrip("：: ").strip()
                break
    return result
