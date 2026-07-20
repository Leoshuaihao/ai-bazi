"""AI八字排盘引擎 - FastAPI 入口"""

from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager

from orm.db import init_db
import orm.models  # 必须在 init_db() 前导入，确保所有 ORM 模型注册到 Base.metadata
from bazi_engine import calculate_bazi
from models import BirthInfo, FeedbackItem, TrueSolarInfo, FeedbackReviewRequest
from rules.yongshen import calculate_strength_detail
from services.deepseek_client import call_deepseek
from services.rag_retriever import (
    retrieve_relevant_texts, extract_keywords_from_chart, retrieve_by_keywords,
    retrieve_all_stages, merge_stage_results, _extract_keywords,
)
from services.feedback_weights import review_feedback, get_user_weights, reset_weights
from services.ai_explainer import generate_strength_explanation
from services.classical_judge import judge_from_classics, mock_classical_judge, judge_wangshuai_from_classics
from services.predictions import (
    generate_predictions,
    generate_mock_predictions,
    judge_info_sufficient,
    run_ai_judge_sufficient,
    generate_single_prediction,
    MAX_PREDICTIONS,
)
from services.forecast import generate_forecast, generate_mock_forecast
from services.calibration import run_calibration
from services.reanalysis import reanalyze_chart, apply_ai_fix_to_analysis
from services.correction import (
    try_candidate_hours,
    apply_correction,
    run_ai_fix,
    get_shichen_name,
    generate_candidate_hours,
    run_correction_round,
    init_correction_state,
    take_before_snapshot,
    build_correction_comparison,
    get_correction_status,
    MAX_CORRECTION_ROUNDS,
)
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP
from true_solar_time import (
    calculate_true_solar_time,
    resolve_birthplace,
    CITY_COORDINATES,
    PROVINCE_TO_CAPITAL,
    CITY_LIST,
)
from api.routes.auth import router as auth_router
from api.routes.payment import router as payment_router
from api.routes.points import router as points_router
from api.routes.invite import router as invite_router
from api.routes.chat import router as chat_router
from api.routes.liuyue import router as liuyue_router
from api.routes.liunian import router as liunian_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_test_user()
    yield

async def _seed_test_user():
    """Ensure test user leo exists with full entitlements."""
    from sqlalchemy import select
    from orm.db import async_session
    from orm.user import User
    from services.auth import hash_password
    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "leo"))
        if result.scalars().first():
            return
        user = User(username="leo", password_hash=hash_password("123456"))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        from orm.points import Points
        from orm.entitlement import Entitlement
        db.add(Points(user_id=user.id, balance=10000))
        for feat in ("liuyue", "liunian", "hepan", "dayun_chat", "classical"):
            db.add(Entitlement(user_id=user.id, feature=feat))
        await db.commit()
        print(f"[seed] created leo (id={user.id})")

app = FastAPI(
    title="AI八字排盘引擎",
    description="基于 lunar-python 的八字排盘 API（精度到分钟）",
    version="2.0.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else [
    "https://ai-bazi-production.up.railway.app",
    "https://ai-bazi.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers middleware (REQ-P1-02)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com https://beacon.cdn.qq.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://api.deepseek.com"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ── Production error handling (hide Pydantic validation details) ──
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # In production, return generic error to avoid leaking internal data model details
    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数格式错误，请检查输入数据"},
    )

# ============================================================
# Rate Limiting (simple in-memory)
# ============================================================
import time
from collections import defaultdict

_rate_limits = defaultdict(list)
_rate_limits_max_window = 3600  # 最大限流窗口（秒），用于清理

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < window_seconds]
    if len(_rate_limits[key]) >= max_requests:
        return False
    _rate_limits[key].append(now)
    # Periodic cleanup: remove empty or stale keys to prevent memory leak
    if len(_rate_limits) > 1000:
        stale = [k for k, v in _rate_limits.items()
                 if not v or all(now - t > _rate_limits_max_window for t in v)]
        for k in stale:
            del _rate_limits[k]
    return True

# 时辰对照表（供前端使用）
SHICHEN_TABLE = [
    {"index": 0, "name": "子时", "time": "23:00-01:00", "branch": "子", "hour": 0, "minute": 0},
    {"index": 1, "name": "丑时", "time": "01:00-03:00", "branch": "丑", "hour": 1, "minute": 0},
    {"index": 2, "name": "寅时", "time": "03:00-05:00", "branch": "寅", "hour": 3, "minute": 0},
    {"index": 3, "name": "卯时", "time": "05:00-07:00", "branch": "卯", "hour": 5, "minute": 0},
    {"index": 4, "name": "辰时", "time": "07:00-09:00", "branch": "辰", "hour": 7, "minute": 0},
    {"index": 5, "name": "巳时", "time": "09:00-11:00", "branch": "巳", "hour": 9, "minute": 0},
    {"index": 6, "name": "午时", "time": "11:00-13:00", "branch": "午", "hour": 11, "minute": 0},
    {"index": 7, "name": "未时", "time": "13:00-15:00", "branch": "未", "hour": 13, "minute": 0},
    {"index": 8, "name": "申时", "time": "15:00-17:00", "branch": "申", "hour": 15, "minute": 0},
    {"index": 9, "name": "酉时", "time": "17:00-19:00", "branch": "酉", "hour": 17, "minute": 0},
    {"index": 10, "name": "戌时", "time": "19:00-21:00", "branch": "戌", "hour": 19, "minute": 0},
    {"index": 11, "name": "亥时", "time": "21:00-23:00", "branch": "亥", "hour": 21, "minute": 0},
]


@app.get("/api/health")
def health():
    """健康检查"""
    return {"status": "ok", "service": "AI八字排盘引擎", "version": "2.0.0"}


@app.get("/api/shichen")
def get_shichen():
    """获取时辰对照表"""
    return SHICHEN_TABLE


@app.get("/api/cities")
def get_cities():
    """获取支持的城市列表（用于真太阳时校正）"""
    cities = []
    for province, capital in PROVINCE_TO_CAPITAL.items():
        coords = CITY_COORDINATES.get(capital)
        cities.append({
            "province": province,
            "city": capital,
            "longitude": coords[0] if coords else 0,
            "latitude": coords[1] if coords else 0,
        })
    # 按省份排序
    cities.sort(key=lambda x: x["province"])
    return cities


def process_birth_info(birth: BirthInfo) -> tuple[dict, dict | None]:
    """处理出生信息：农历转公历、真太阳时校正

    Args:
        birth: 出生信息

    Returns:
        (processed_params, true_solar_info_dict)
        processed_params: dict with year, month, day, hour, minute, gender
        true_solar_info_dict: dict or None
    """
    from lunar_python import Lunar

    year = birth.year
    month = birth.month
    day = birth.day
    hour = birth.hour
    minute = birth.minute
    calendar_type = birth.calendar_type
    true_solar_info = None

    # 1. 农历转公历
    if calendar_type == "lunar":
        try:
            lunar = Lunar.fromYmd(year, month, day)
            solar = lunar.getSolar()
            year = solar.getYear()
            month = solar.getMonth()
            day = solar.getDay()
        except Exception:
            # 如果转换失败，认为用户输入的已经是阳历
            pass

    # 2. 真太阳时校正
    if birth.use_true_solar and (birth.city or birth.province):
        longitude, city_name = resolve_birthplace(
            province=birth.province,
            city=birth.city,
        )
        if longitude is not None:
            corrected_hour, corrected_minute = calculate_true_solar_time(
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                longitude=longitude,
            )

            # 计算各项时差用于显示
            BEIJING_MERIDIAN = 120.0
            longitude_offset = (BEIJING_MERIDIAN - longitude) * 4.0
            from true_solar_time import calculate_equation_of_time
            eot = calculate_equation_of_time(year, month, day)
            total_offset = longitude_offset - eot

            offset_dir = "早于" if total_offset > 0 else "晚于"
            desc_parts = [
                f"出生地：{city_name}（东经{longitude:.2f}°）",
                f"经度时差：{(BEIJING_MERIDIAN - longitude) * 4:.1f}分钟（东经120°为基准）",
                f"均时差：{eot:.1f}分钟",
                f"总校正：{abs(total_offset):.0f}分钟（真太阳时{offset_dir}北京时间）",
                f"校正后时间：{corrected_hour:02d}:{corrected_minute:02d}",
            ]

            true_solar_info = {
                "enabled": True,
                "original_hour": hour,
                "original_minute": minute,
                "corrected_hour": corrected_hour,
                "corrected_minute": corrected_minute,
                "city": city_name,
                "longitude": round(longitude, 2),
                "longitude_offset_minutes": round(longitude_offset, 1),
                "eot_minutes": round(eot, 1),
                "total_offset_minutes": round(total_offset, 1),
                "description": "；".join(desc_parts),
            }

            hour = corrected_hour
            minute = corrected_minute

    params = {
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
        "gender": birth.gender,
    }

    return params, true_solar_info


def _validate_birth_info(birth: BirthInfo):
    """校验出生信息参数"""
    if birth.year < 1900 or birth.year > 2100:
        raise HTTPException(status_code=400, detail="年份范围：1900-2100")
    if birth.month < 1 or birth.month > 12:
        raise HTTPException(status_code=400, detail="月份范围：1-12")
    if birth.day < 1 or birth.day > 31:
        raise HTTPException(status_code=400, detail="日期范围：1-31")
    if birth.hour < 0 or birth.hour > 23:
        raise HTTPException(status_code=400, detail="小时范围：0-23")
    if birth.minute < 0 or birth.minute > 59:
        raise HTTPException(status_code=400, detail="分钟范围：0-59")
    if birth.gender not in ("male", "female"):
        raise HTTPException(status_code=400, detail="性别：male 或 female")


@app.post("/api/chart")
def create_chart(birth: BirthInfo):
    """
    八字排盘接口

    参数：
    - year: 出生年
    - month: 出生月
    - day: 出生日
    - hour: 出生小时（0-23，24小时制）
    - minute: 出生分钟（0-59，默认 0）
    - gender: 性别（"male" 或 "female"）
    - calendar_type: "solar"（阳历，默认）或 "lunar"（农历）
    - province: 出生省份（可选，用于真太阳时校正）
    - city: 出生城市（可选，用于真太阳时校正）
    - use_true_solar: 是否启用真太阳时校正（默认 false）
    """
    _validate_birth_info(birth)

    try:
        params, true_solar_info = process_birth_info(birth)
        chart = calculate_bazi(**params)

        result = chart.model_dump()
        result["true_solar_info"] = true_solar_info if true_solar_info else None
        # 附带回显出生信息
        result["birth_display"] = _build_birth_display(birth, params, true_solar_info)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"排盘计算错误: {str(e)}")


def _build_birth_display(birth: BirthInfo, params: dict, true_solar_info: dict | None) -> dict:
    """构建出生信息展示文本"""
    cal_label = "农历" if birth.calendar_type == "lunar" else "阳历"
    lines = []
    lines.append(f"出生时间：{params['year']}年{params['month']}月{params['day']}日 "
                 f"{params['hour']:02d}:{params['minute']:02d}（{cal_label}）")

    if birth.city:
        loc = birth.city
        if birth.province:
            loc = f"{birth.province}{birth.city}"
        lines.append(f"出生地点：{loc}")

    if true_solar_info and true_solar_info.get("enabled"):
        orig = f"{true_solar_info['original_hour']:02d}:{true_solar_info['original_minute']:02d}"
        corr = f"{true_solar_info['corrected_hour']:02d}:{true_solar_info['corrected_minute']:02d}"
        lines.append(f"真太阳时校正：已启用（北京时间 {orig} → 真太阳时 {corr}）")

    return {"text": "\n".join(lines), "lines": lines}


@app.post("/api/chart/analyze")
async def analyze_chart(request: dict):
    """AI 命盘初判：直接传入 chart JSON + 可选 feedbacks。不依赖 session。"""
    chart_data = request.get("chart")
    if not chart_data:
        # fallback: try session_id
        session_id = request.get("session_id", "")
        if not session_id:
            raise HTTPException(status_code=400, detail="缺少 chart 数据或 session_id")
        session = _prediction_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="未找到会话")
        chart_data = session.get("chart_data", {})
    if not chart_data:
        raise HTTPException(status_code=404, detail="无排盘数据")
    feedbacks = request.get("feedbacks") or []
    import os as _os
    predictions = request.get("predictions") or []
    if not _os.getenv("DEEPSEEK_API_KEY"):
        return {"method": "unavailable", "message": "AI 服务未配置"}
    try:
        from services.correction import _ai_fix_unified
        result = await _ai_fix_unified(chart_data, feedbacks, predictions)
        if result:
            return {
                "method": "ai",
                "ri_zhu_strength": result.get("ri_zhu_strength", ""),
                "pattern": result.get("pattern", ""),
                "yongshen": result.get("yongshen", ""),
                "auxiliary": result.get("suggested_auxiliary", ""),
                "secondary": result.get("suggested_secondary", ""),
                "ji_shen": result.get("suggested_ji_shen", ""),
                "analysis": result.get("analysis", ""),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 分析失败: {str(e)}")
    return {"method": "unavailable", "message": "AI 分析返回空"}


@app.post("/api/analysis")
async def get_analysis(birth: BirthInfo, session_id: str = ""):
    """
    完整的八字分析接口（排盘 + 旺衰 + RAG检索 + AI解释）

    可选 query 参数：
    - session_id: 会话ID，用于应用用户反馈后的活权重（V2.2）

    参数：
    - year: 出生年
    - month: 出生月
    - day: 出生日
    - hour: 出生小时（0-23，24小时制）
    - minute: 出生分钟（0-59，默认 0）
    - gender: 性别（"male" 或 "female"）
    - calendar_type: "solar"（阳历，默认）或 "lunar"（农历）
    - province: 出生省份（可选）
    - city: 出生城市（可选）
    - use_true_solar: 是否启用真太阳时校正（默认 false）

    返回：
    - chart: 排盘数据
    - strength_detail: 旺衰分析的详细数据（每一步的分值和原因）
    - relevant_texts: RAG 检索到的相关原文
    - explanation: AI 生成的通俗解释（引用原文）
    """
    _validate_birth_info(birth)

    try:
        # 处理出生信息
        params, true_solar_info = process_birth_info(birth)

        # 1. 排盘
        chart = calculate_bazi(**params)

        # 2. 构建四柱原始数据（供旺衰分析使用）
        four_pillars_raw = {}
        all_hidden_stems = []
        for pos in ["year", "month", "day", "hour"]:
            pillar = chart.four_pillars[pos]
            four_pillars_raw[pos] = {
                "stem": pillar.stem,
                "branch": pillar.branch,
            }
            for hs in pillar.hidden_stems:
                all_hidden_stems.append({"stem": hs.stem, "weight": hs.weight})

        # 3. 旺衰分析
        strength_detail = calculate_strength_detail(
            day_master_stem=chart.day_master,
            four_pillars=four_pillars_raw,
            hidden_stems_list=all_hidden_stems,
        )

        # 4. RAG 检索相关原文（按阶段加权 + 用户活权重）
        keywords = _extract_keywords(strength_detail)
        user_weights = get_user_weights(session_id) if session_id else None
        stage_results = retrieve_all_stages(
            keywords,
            ri_zhu_wuxing=WUXING_MAP.get(chart.day_master, ""),
            month_branch=chart.four_pillars["month"].branch,
            ri_zhu_stem=chart.day_master,
            per_stage_k=3,
            user_weights=user_weights,
        )
        relevant_texts = merge_stage_results(stage_results, top_k=8)


        # 5. AI 解释（有 API Key 调 DeepSeek，否则用 Mock 模板）
        explanation = await generate_strength_explanation(strength_detail, relevant_texts)

        result = {
            "chart": chart.model_dump(),
            "strength_detail": strength_detail,
            "relevant_texts": [
                {
                    "id": t["id"],
                    "source": t["source"],
                    "chapter": t["chapter"],
                    "text": t["text"],
                    "topic": t["topic"],
                    "context": t.get("context", ""),
                    "score": t.get("score", 0),
                }
                for t in relevant_texts
            ],
            "explanation": explanation,
        }

        if true_solar_info:
            result["true_solar_info"] = true_solar_info
        result["birth_display"] = _build_birth_display(birth, params, true_solar_info)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析计算错误: {str(e)}")


@app.post("/api/classical-analysis")
async def classical_analysis(birth: BirthInfo, session_id: str = ""):
    """
    基于典籍原文的八字分析（子平派体系）

    可选 query 参数：
    - session_id: 会话ID，用于应用用户反馈后的活权重（V2.2）

    流程：
    1. 排盘（calculate_bazi）
    2. 旺衰分析（calculate_strength_detail）
    3. RAG检索（从 classical_corpus 检索相关原文）
    4. AI判断（基于原文判断得令、格局、用神）
    5. 返回结果（含原文引用）

    参数：
    - year: 出生年
    - month: 出生月
    - day: 出生日
    - hour: 出生小时（0-23，24小时制）
    - minute: 出生分钟（0-59，默认 0）
    - gender: 性别（"male" 或 "female"）
    - calendar_type: "solar"（阳历，默认）或 "lunar"（农历）
    - province: 出生省份（可选）
    - city: 出生城市（可选）
    - use_true_solar: 是否启用真太阳时校正（默认 false）

    返回：
    - chart: 排盘数据
    - strength_detail: 规则引擎旺衰分析
    - classical_analysis: AI/模板 典籍原文分析（含得令、格局、用神判断及原文引用）
    - sources: 检索到的典籍原文出典列表
    """
    _validate_birth_info(birth)

    try:
        # 处理出生信息
        params, true_solar_info = process_birth_info(birth)

        # 1. 排盘
        chart = calculate_bazi(**params)

        # 2. 构建四柱原始数据
        four_pillars_raw = {}
        all_hidden_stems = []
        for pos in ["year", "month", "day", "hour"]:
            pillar = chart.four_pillars[pos]
            four_pillars_raw[pos] = {
                "stem": pillar.stem,
                "branch": pillar.branch,
            }
            for hs in pillar.hidden_stems:
                all_hidden_stems.append({"stem": hs.stem, "weight": hs.weight})

        # 3. 旺衰分析（规则引擎）
        strength_detail = calculate_strength_detail(
            day_master_stem=chart.day_master,
            four_pillars=four_pillars_raw,
            hidden_stems_list=all_hidden_stems,
        )

        # 4. 构建 chart_data 供典籍判断使用（包含完整四柱信息）
        year_pillar = chart.four_pillars["year"]
        month_pillar = chart.four_pillars["month"]
        day_pillar = chart.four_pillars["day"]
        hour_pillar = chart.four_pillars["hour"]

        month_hidden = HIDDEN_STEMS_MAP.get(month_pillar.branch, [])
        month_hidden_stems = [
            {"stem": hs.get("stem", ""), "ten_god": hs.get("ten_god", "")}
            for hs in month_hidden
        ]

        chart_data = {
            "ri_zhu": chart.day_master,
            "ri_zhu_wuxing": WUXING_MAP.get(chart.day_master, ""),
            "month_branch": month_pillar.branch,
            "month_stem": month_pillar.stem,
            "month_hidden_stems": month_hidden_stems,
            "ri_zhu_strength": strength_detail["ri_zhu_strength"],
            "pattern": strength_detail["pattern"],
            "yongshen_rule": strength_detail["yongshen"],
            # Full four pillars for wangshuai judgment
            "year_stem": year_pillar.stem,
            "year_branch": year_pillar.branch,
            "day_branch": day_pillar.branch,
            "hour_stem": hour_pillar.stem,
            "hour_branch": hour_pillar.branch,
        }

        # 5. RAG 检索（按阶段加权 + 用户活权重）
        keywords = extract_keywords_from_chart(chart_data)
        user_weights = get_user_weights(session_id) if session_id else None
        stage_results = retrieve_all_stages(
            keywords,
            ri_zhu_wuxing=chart_data["ri_zhu_wuxing"],
            month_branch=chart_data["month_branch"],
            ri_zhu_stem=chart_data.get("ri_zhu", ""),
            per_stage_k=4,
            user_weights=user_weights,
        )
        rag_results = merge_stage_results(stage_results, top_k=10)

        # 6. AI/模板 典籍判断（旺衰 + 格局 + 用神三角度）
        analysis = await judge_from_classics(chart_data, rag_results)

        # 7. 构建出典列表
        sources = [
            {
                "source": r.get("source", ""),
                "chapter": r.get("chapter", ""),
                "chapter_id": r.get("id", ""),
                "topic": r.get("topic", ""),
                "context": r.get("context", ""),
                "excerpt": " ".join(str(r.get("full_text") or r.get("text") or "").split())[:260],
                "score": r.get("score", 0),
                "keywords_matched": r.get("keywords_matched", []),
            }
            for r in rag_results
        ]

        result = {
            "chart": chart.model_dump(),
            "strength_detail": strength_detail,
            "classical_analysis": analysis,
            "sources": sources,
        }

        if true_solar_info:
            result["true_solar_info"] = true_solar_info
        result["birth_display"] = _build_birth_display(birth, params, true_solar_info)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"典籍分析计算错误: {str(e)}")


# ============================================================
# P1 Phase 1: 断前事 + 逐条反馈
# ============================================================

# 简易内存会话（生产环境应替换为 Redis）
_prediction_sessions: dict[str, dict] = {}


@app.post("/api/predictions/generate")
async def generate_predictions_endpoint(birth: BirthInfo):
    """
    断前事生成接口

    流程：
    1. 排盘
    2. 生成 7 条断前事推断
    3. 返回 chart + predictions

    请求参数同 /api/chart
    """
    _validate_birth_info(birth)

    try:
        # 处理出生信息
        params, true_solar_info = process_birth_info(birth)

        # 1. 排盘
        chart = calculate_bazi(**params)

        # 2. 生成断事，包含当前年龄信息
        chart_data = chart.model_dump()
        import datetime
        current_year = datetime.datetime.now().year
        chart_data["current_year"] = current_year
        chart_data["current_age"] = current_year - params["year"]
        chart_data["birth_year"] = params["year"]
        predictions = await generate_predictions(chart, chart_data)

        # 3. 创建会话记录（含出生信息用于后续修正）
        session_id = f"{params['year']}{params['month']:02d}{params['day']:02d}_{params['hour']:02d}{params['minute']:02d}_{params['gender']}"
        # 保存原始 birth 信息（用于修正流程中的重新排盘）
        session_birth_info = birth.model_dump()
        # 同时保存处理后的参数
        session_birth_info["_processed_hour"] = params["hour"]
        session_birth_info["_processed_minute"] = params["minute"]
        _prediction_sessions[session_id] = {
            "predictions": [p.model_dump() for p in predictions],
            "feedbacks": [],
            "birth_info": session_birth_info,
            "chart_data": chart_data,  # 保存排盘数据供修正使用
        }

        core_count = sum(1 for p in predictions if p.is_core)

        result = {
            "session_id": session_id,
            "chart": chart_data,
            "predictions": [p.model_dump() for p in predictions],
            "total": len(predictions),
            "core_count": core_count,
        }

        if true_solar_info:
            result["true_solar_info"] = true_solar_info
        result["birth_display"] = _build_birth_display(birth, params, true_solar_info)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"断事生成错误: {str(e)}")


@app.post("/api/predictions/feedback")
def submit_feedback(feedback: FeedbackItem):
    """
    提交单条断事反馈

    请求参数：
    - prediction_id: 推断 ID（如 "pred_01"）
    - status: "accurate" | "partial" | "inaccurate" | "supplement"
    - note: 补充说明（可选）
    """
    # 优先按 session_id 定位，避免多个会话都存在 pred_01 时反馈写入旧会话。
    found_session = None
    if feedback.session_id:
        found_session = _prediction_sessions.get(feedback.session_id)
        if found_session is None:
            raise HTTPException(status_code=404, detail=f"未找到会话: {feedback.session_id}")

        all_preds = found_session.get("predictions", []) + found_session.get("_dynamic_predictions", [])
        if not any(p["id"] == feedback.prediction_id for p in all_preds):
            raise HTTPException(status_code=404, detail=f"当前会话未找到推断记录: {feedback.prediction_id}")
    else:
        # 向后兼容旧前端：未传 session_id 时仍按 prediction_id 查找。
        for sid, session in _prediction_sessions.items():
            all_preds = session.get("predictions", []) + session.get("_dynamic_predictions", [])
            for p in all_preds:
                if p["id"] == feedback.prediction_id:
                    found_session = session
                    break
            if found_session:
                break

    if found_session is None:
        raise HTTPException(status_code=404, detail=f"未找到推断记录: {feedback.prediction_id}")

    # 添加反馈
    found_session["feedbacks"].append(feedback.model_dump())

    # 计数时使用动态预测或总预测
    dynamic_preds = found_session.get("_dynamic_predictions", [])
    total = len(dynamic_preds) if dynamic_preds else len(found_session.get("predictions", []))
    progress = len(found_session["feedbacks"])

    return {
        "accepted": True,
        "prediction_id": feedback.prediction_id,
        "status": feedback.status,
        "progress": f"{progress}/{total}" if total > 0 else f"{progress}/?",
    }


@app.post("/api/predictions/next")
async def predictions_next(request: dict):
    """
    动态题量：获取下一条断事推断

    逐条获取，AI 动态判断何时信息充足。

    请求参数：
    - session_id: 会话ID
    - feedbacks: 当前轮次所有已完成的反馈列表 [{"prediction_id": "...", "status": "...", "note": "..."}]

    返回：
    - done: true（信息已充足，可以提交）/ false（继续回答下一条）
    - next_prediction: 下一条推断（done=false 时）
    - message: 提示文案
    - asked_count: 已问条数
    - sufficient_reason: 信息充足的原因（done=true 时）
    """
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    # 获取当前 session 中通过 /next 已服务过的预测（动态题量）
    # 使用独立 key "_dynamic_predictions" 与 /generate 的 predictions 分开
    if "_dynamic_predictions" not in session:
        # 首次调用：初始化动态预测列表为空
        session["_dynamic_predictions"] = []
    dynamic_predictions = session["_dynamic_predictions"]

    # 合并反馈
    incoming_feedbacks = request.get("feedbacks", [])
    existing_feedbacks = session.get("feedbacks", [])
    existing_ids = {f.get("prediction_id") for f in existing_feedbacks}
    for fb in incoming_feedbacks:
        if fb.get("prediction_id") not in existing_ids:
            existing_feedbacks.append(fb)
    session["feedbacks"] = existing_feedbacks

    # 当前已问条数和类别（只看动态预测）
    asked_categories = {p.get("category", "") for p in dynamic_predictions}

    # 1. 判断信息是否充足
    sufficiency = judge_info_sufficient(
        chart_data=session.get("chart_data", {}),
        asked_predictions=dynamic_predictions,
        feedbacks=existing_feedbacks,
    )

    # 如果标注需要AI判断（有API Key且>=3条），执行异步判断
    if sufficiency.get("_needs_ai"):
        ai_result = await run_ai_judge_sufficient(dynamic_predictions, existing_feedbacks)
        sufficiency = ai_result

    # 2. 如果信息充足且不是首次调用（至少有一条），返回 done=true
    if sufficiency.get("sufficient") and len(dynamic_predictions) > 0:
        session["predictions"] = dynamic_predictions  # 同步
        return {
            "done": True,
            "message": "信息已充足，可以生成校准分析了",
            "asked_count": len(dynamic_predictions),
            "sufficient_reason": sufficiency.get("reason", ""),
        }

    # 3. 信息不足，生成下一条推断
    birth_info = session.get("birth_info", {})
    chart_data = session.get("chart_data", {})

    # 重建 BaziChart 对象
    try:
        hour = birth_info.get("_processed_hour", birth_info.get("hour", 12))
        minute = birth_info.get("_processed_minute", birth_info.get("minute", 0))
        chart = calculate_bazi(
            year=birth_info.get("year", 1990),
            month=birth_info.get("month", 6),
            day=birth_info.get("day", 15),
            hour=hour,
            minute=minute,
            gender=birth_info.get("gender", "male"),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="重新排盘失败")

    next_pred = await generate_single_prediction(
        chart, chart_data,
        asked_categories=asked_categories,
        feedbacks=existing_feedbacks,
    )

    if next_pred is None:
        # 无法生成新推断，直接判定充足
        return {
            "done": True,
            "message": "信息已充足，可以生成校准分析了",
            "asked_count": len(dynamic_predictions),
            "sufficient_reason": "所有类别已覆盖",
        }

    # 将新推断加入动态预测列表，并同步到主 predictions（兼容其他端点）
    pred_dict = next_pred.model_dump()
    dynamic_predictions.append(pred_dict)
    session["predictions"] = dynamic_predictions  # 同步，确保 downstream 端点读到正确数据

    return {
        "done": False,
        "next_prediction": pred_dict,
        "asked_count": len(dynamic_predictions),
        "message": sufficiency.get("next_suggestion", ""),
    }


# ============================================================
# P1 Phase 2: 校验判定 + 双路径修正
# ============================================================

# ── 新流程端点：逐步验证收敛 ──

from services.verification import init_verification, process_verification, get_session as get_verification_session
from services.gate import require_auth
from services.user_data import (
    save_chart_record,
    save_verification_record,
    get_user_charts,
    get_user_verifications,
)


@app.post("/api/predictions/start")
async def predictions_start(birth: BirthInfo, authorization: str = Header(None)):
    """新的断前事入口：排盘 + 格局分类 + 返回第一条验证问题

    替代旧的 /api/predictions/generate（固定7题），
    改为逐步对话式验证，收敛后锁定格局和用神。
    """
    _validate_birth_info(birth)
    try:
        params, true_solar_info = process_birth_info(birth)
        chart = calculate_bazi(**params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"排盘失败: {str(e)}")

    chart_data = chart.model_dump() if hasattr(chart, "model_dump") else chart

    # 提取登录用户 ID（可选）
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        try:
            from services.auth import verify_jwt
            uid = verify_jwt(authorization[7:])
            if uid:
                user_id = uid
        except Exception:
            pass

    result = init_verification(chart_data, user_id=user_id)

    # 生成 prediction session（兼容旧校准流程）
    import uuid
    session_id = str(uuid.uuid4())
    _prediction_sessions[session_id] = {
        "chart_data": chart_data,
        "predictions": [],
        "feedbacks": [],
        "verification_session_id": result["session_id"],
    }

    return {
        "session_id": session_id,
        "chart_data": chart_data,
        "stage": result.get("stage", "pattern"),
        "sub_stage": result.get("sub_stage", "L1"),
        "hypotheses": [],
        "question": result["question"],
        "step_results": result.get("step_results", {}),
    }


@app.post("/api/predictions/verify")
async def predictions_verify(request: dict):
    """验证反馈接口：提交对当前问题的回答，返回下一条问题或锁定结果

    请求: {"session_id": str, "answer": "accurate|partial|inaccurate", "note": str}
    未锁定: {"locked": false, "question": {...}, "hypotheses": [...]}
    已锁定: {"locked": true, "result": {pattern, yong_shen, five_element, gong_way, confidence}, "hypotheses": [...]}
    """
    prediction_session_id = request.get("session_id", "")
    answer = request.get("answer", "")
    note = request.get("note", "")

    if not prediction_session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    # 将中文选项标准化为英文枚举（兼容前端直接返回中文选项文本）
    _ANSWER_NORMALIZE = {
        "很像": "accurate", "有点出入": "partial", "完全不像": "inaccurate",
        "是的": "accurate", "不太确定": "partial", "不是": "inaccurate",
    }
    answer = _ANSWER_NORMALIZE.get(answer, answer)

    if answer not in ("accurate", "partial", "inaccurate"):
        raise HTTPException(status_code=400, detail="answer 必须是 accurate/partial/inaccurate")

    # 从 prediction session 中获取 verification session
    pred_session = _prediction_sessions.get(prediction_session_id)
    if not pred_session:
        raise HTTPException(status_code=404, detail="未找到会话")

    verification_sid = pred_session.get("verification_session_id", "")
    if not verification_sid:
        raise HTTPException(status_code=400, detail="请先调用 /api/predictions/start")

    result = await process_verification(verification_sid, answer, note)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    if result.get("locked"):
        # 锁定后，将结果写入 prediction session 供后续校准使用
        pred_session["locked_result"] = result["result"]
        pred_session["hypotheses"] = result.get("hypotheses") or result.get("xiangshen_candidates") or []
        pred_session["locked_quality"] = result.get("quality")
        pred_session["locked_purity"] = result.get("purity")
        pred_session["locked_source"] = result.get("pattern_source")

    return result


# ── 旧端点保留（兼容） ──


@app.post("/api/calibrate")
def calibrate(request: dict):
    """
    校验判定接口

    接收 session_id，执行校验判定，返回结果。

    请求参数：
    - session_id: 会话ID（从 /api/predictions/generate 返回）

    返回：
    - core: 核心三关判定结果
    - auxiliary: 辅助项判定结果
    - verdict: 最终判定（passed / ai_fix / hour_fix / ai_fix_first）
    """
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])

    if not feedbacks or not predictions:
        raise HTTPException(status_code=400, detail="会话中没有反馈或预测数据")

    if len(feedbacks) < len(predictions):
        raise HTTPException(
            status_code=400,
            detail=f"反馈未完成：{len(feedbacks)}/{len(predictions)}，请完成所有反馈后再提交",
        )

    result = run_calibration(feedbacks, predictions)
    return result


@app.post("/api/calibrate/compare")
async def calibrate_compare(request: dict):
    """
    时钟修正对比接口

    对原始时钟 ±1, ±2 共4个候选时钟重新排盘、生成断事，
    与用户原有反馈进行对比，返回多时钟对比结果。

    请求参数：
    - session_id: 会话ID

    返回：
    - original_hour: 原始小时
    - comparisons: 候选时钟对比列表
    - recommended: 推荐时辰
    - all_failed: 是否所有候选都不如原始
    """
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    birth_info = session.get("birth_info")
    if not birth_info:
        raise HTTPException(status_code=400, detail="会话中缺少出生信息")

    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])

    if not feedbacks:
        raise HTTPException(status_code=400, detail="会话中缺少反馈数据")

    result = await try_candidate_hours(birth_info, feedbacks, predictions)
    return result


@app.post("/api/calibrate/apply")
async def calibrate_apply(request: dict):
    """
    应用修正接口（Phase 3 增强版：支持轮数控制 + 双路径切换 + 对比数据）

    用户确认修正方案后，用新参数重跑P0全链路（排盘 + 旺衰 + 断事）。

    请求参数：
    - session_id: 会话ID
    - correction_type: "hour_fix" | "ai_fix" | "ai_fix_first"
    - new_hour: 新时钟小时值（仅 hour_fix 时需要）
    - fix_stage: AI修正阶段 1/2/3（仅 ai_fix 时需要）
    - correction_round: 当前修正轮数（可选，0=自动）
    - force_correction: 强制执行修正（跳过轮数检查，可选）

    返回：
    - round: 当前修正轮数
    - correction_type: 执行的修正类型
    - verdict: 修正后的校验结果
    - comparison: 修正前后对比数据（Phase 3 新增）
    - correction_result: 修正执行结果
    - can_continue: 是否可以继续修正
    - need_degrade: 是否需要降级
    - degrade_reason: 降级原因（如有）
    - message: 用户提示信息
    """
    session_id = request.get("session_id", "")
    correction_type = request.get("correction_type", "")
    new_hour = request.get("new_hour")
    fix_stage = request.get("fix_stage", 1)
    force_correction = request.get("force_correction", False)

    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    birth_info = session.get("birth_info")
    chart_data = session.get("chart_data", {})
    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])

    if not birth_info:
        raise HTTPException(status_code=400, detail="会话中缺少出生信息")

    # 初始化修正状态
    cs = init_correction_state(session)

    # 检查轮数限制
    if not force_correction and cs.get("round", 0) >= MAX_CORRECTION_ROUNDS:
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs.get(
                "degraded_reason",
                f"已达到最大修正轮数（{MAX_CORRECTION_ROUNDS}轮），"
                "系统无法在当前条件下给出可靠推断，建议确认出生时辰。",
            ),
            "next_path": None,
            "message": cs.get("degraded_reason", "已达到最大修正轮数"),
        }

    # 如果已降级
    if not force_correction and cs.get("degraded"):
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs.get("degraded_reason", "系统已降级"),
            "next_path": None,
            "message": "系统已降级，无法继续修正。" + cs.get("degraded_reason", ""),
        }

    # 在修正开始前保存快照（第1轮时）
    if cs["round"] == 0 and cs.get("before_snapshot") is None:
        cs["before_snapshot"] = take_before_snapshot(session)

    # 递增轮数
    cs["round"] += 1
    current_round = cs["round"]

    comparison = None
    correction_result = None

    # 路径一：时钟修正
    if correction_type == "hour_fix":
        if new_hour is None:
            # 自动选择：先做时钟对比
            birth_info_data = birth_info  # dict 类型的 birth_info
            candidate_result = await try_candidate_hours(birth_info_data, feedbacks, predictions)
            if candidate_result.get("all_failed", True):
                correction_result = {
                    "candidate_result": candidate_result,
                    "any_improvement": False,
                    "all_candidates_failed": True,
                }
                # 候选全失败，记录到状态
                cs["current_path"] = "hour_fix"
            else:
                new_hour = candidate_result.get("recommended_hour")
                correction_result = {
                    "candidate_result": candidate_result,
                    "any_improvement": True,
                    "all_candidates_failed": False,
                }
        elif new_hour < 0 or new_hour > 23:
            raise HTTPException(status_code=400, detail="new_hour 范围：0-23")

        if new_hour is not None:
            result = await apply_correction(birth_info, new_hour, feedbacks)

            # 更新会话数据
            session["chart_data"] = result["chart"]
            session["predictions"] = result["predictions"]
            session["birth_info"]["hour"] = new_hour

            # 构建修正前后对比
            if cs.get("before_snapshot"):
                comparison = build_correction_comparison(session, cs["before_snapshot"])

            if correction_result is None:
                correction_result = {
                    "applied_result": result,
                    "any_improvement": True,
                    "all_candidates_failed": False,
                }
            else:
                correction_result["applied_result"] = result
                correction_result["any_improvement"] = True

        cs["current_path"] = "hour_fix"

    # 路径二：AI修正
    elif correction_type in ("ai_fix", "ai_fix_first"):
        ai_result = await run_ai_fix(chart_data, feedbacks, predictions, fix_stage=fix_stage)

        # 判断是否触发任何修正
        any_triggered = False
        if ai_result.get("wangshuai_fix", {}).get("triggered"):
            any_triggered = True
        if ai_result.get("pattern_fix", {}).get("triggered"):
            any_triggered = True
        if ai_result.get("yongshen_fix", {}).get("triggered"):
            any_triggered = True

        correction_result = {
            "ai_fix_result": ai_result,
            "any_improvement": any_triggered,
        }

        # 构建对比（AI修正场景）
        if cs.get("before_snapshot"):
            comparison = build_correction_comparison(session, cs["before_snapshot"])
            if ai_result.get("wangshuai_fix", {}).get("triggered"):
                comparison["wangshuai_changed"] = True
                comparison["any_changed"] = True
                wf = ai_result["wangshuai_fix"]
                comparison["changes"].append(
                    f"AI建议旺衰调整：{wf['current_strength']} → {wf['suggested_strength']}"
                )
            if ai_result.get("pattern_fix", {}).get("triggered"):
                comparison["pattern_changed"] = True
                comparison["any_changed"] = True
                pf = ai_result["pattern_fix"]
                comparison["changes"].append(
                    f"AI建议格局调整：{pf['current_pattern']} → {pf['suggested_pattern']}"
                )

        cs["current_path"] = "ai_fix"

    else:
        raise HTTPException(status_code=400, detail=f"无效的修正类型: {correction_type}")

    # 重新校验
    new_verdict = run_calibration(feedbacks, predictions)

    # 判断是否改善
    verdict_key = new_verdict.get("verdict", {}).get("verdict", "")
    improved = verdict_key == "passed" or correction_result.get("any_improvement", False)

    # 记录历史
    history_entry = {
        "round": current_round,
        "path": correction_type,
        "verdict": new_verdict,
        "improved": improved,
    }
    cs.setdefault("history", []).append(history_entry)

    # 如果校验通过
    if verdict_key == "passed":
        return {
            "round": current_round,
            "correction_type": correction_type,
            "verdict": new_verdict,
            "comparison": comparison,
            "correction_result": correction_result,
            "can_continue": False,
            "need_degrade": False,
            "degrade_reason": "",
            "next_path": None,
            "message": f"第{current_round}轮修正后校验通过，命盘准确度达标。",
        }

    # 决定下一步
    if not improved:
        if correction_type in ("ai_fix", "ai_fix_first"):
            if current_round < MAX_CORRECTION_ROUNDS:
                next_path = "hour_fix"
                message = (
                    f"第{current_round}轮AI修正未能改善校验结果。"
                    f"建议切换到时修修正（路径一）。"
                )
                can_continue = True
                need_degrade = False
            else:
                next_path = None
                cs["degraded"] = True
                cs["degraded_reason"] = (
                    f"已完成{MAX_CORRECTION_ROUNDS}轮修正，"
                    f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
                )
                message = cs["degraded_reason"]
                can_continue = False
                need_degrade = True
        elif correction_type == "hour_fix":
            if correction_result.get("all_candidates_failed"):
                # 候选时钟全失败
                if current_round < MAX_CORRECTION_ROUNDS:
                    next_path = "ai_fix"
                    message = (
                        f"第{current_round}轮时钟修正中所有候选时钟均未改善结果。"
                        f"建议尝试AI修正（路径二）。"
                    )
                    can_continue = True
                    need_degrade = False
                else:
                    next_path = None
                    cs["degraded"] = True
                    cs["degraded_reason"] = (
                        f"已完成{MAX_CORRECTION_ROUNDS}轮修正，"
                        f"所有候选时钟和修正方案均无效。"
                        f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
                    )
                    message = cs["degraded_reason"]
                    can_continue = False
                    need_degrade = True
            else:
                if current_round >= MAX_CORRECTION_ROUNDS:
                    next_path = None
                    cs["degraded"] = True
                    cs["degraded_reason"] = (
                        f"已完成{MAX_CORRECTION_ROUNDS}轮修正，"
                        f"时钟修正未能产生有效改善。"
                        f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
                    )
                    message = cs["degraded_reason"]
                    can_continue = False
                    need_degrade = True
                else:
                    next_path = "hour_fix"
                    message = "时钟修正有效果，可继续下一轮。"
                    can_continue = True
                    need_degrade = False
        else:
            next_path = None
            can_continue = current_round < MAX_CORRECTION_ROUNDS
            need_degrade = not can_continue
            message = "修正效果不明显。"
    else:
        if current_round < MAX_CORRECTION_ROUNDS:
            next_path = correction_type
            message = f"第{current_round}轮修正有改善，可继续下一轮优化。"
            can_continue = True
            need_degrade = False
        else:
            next_path = None
            message = f"已完成{MAX_CORRECTION_ROUNDS}轮修正。"
            can_continue = False
            need_degrade = False

    return {
        "round": current_round,
        "correction_type": correction_type,
        "verdict": new_verdict,
        "comparison": comparison,
        "correction_result": correction_result,
        "can_continue": can_continue,
        "need_degrade": need_degrade,
        "degrade_reason": cs.get("degraded_reason", ""),
        "next_path": next_path,
        "message": message,
    }


@app.post("/api/calibrate/correct")
async def calibrate_correct(request: dict):
    """
    修正闭环接口（Phase 3 新增）

    执行完整的修正闭环流程：
    1. 初始化/获取修正状态
    2. 检查轮数限制和降级状态
    3. 自动决定修正路径（ai_fix -> hour_fix 自动切换）
    4. 执行修正并返回对比数据

    请求参数：
    - session_id: 会话ID
    - new_hour: 新时钟小时值（可选手动指定，未指定时自动选择最佳候选）

    返回：
    - 完整的修正结果，包含轮数、对比、降级状态等
    """
    session_id = request.get("session_id", "")
    new_hour = request.get("new_hour")

    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    birth_info = session.get("birth_info", {})
    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])

    if not birth_info:
        raise HTTPException(status_code=400, detail="会话中缺少出生信息")
    if not feedbacks:
        raise HTTPException(status_code=400, detail="会话中缺少反馈数据")

    # 初始化修正状态
    cs = init_correction_state(session)

    # 检查降级
    if cs.get("degraded"):
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs.get("degraded_reason", "系统已降级"),
            "next_path": None,
            "message": "系统已降级，无法继续修正。" + cs.get("degraded_reason", ""),
        }

    # 检查轮数
    if cs.get("round", 0) >= MAX_CORRECTION_ROUNDS:
        cs["degraded"] = True
        cs["degraded_reason"] = (
            f"已达到最大修正轮数（{MAX_CORRECTION_ROUNDS}轮），"
            "系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
        )
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs["degraded_reason"],
            "next_path": None,
            "message": cs["degraded_reason"],
        }

    # 决定修正路径
    history = cs.get("history", [])
    if history:
        last_round = history[-1]
        if last_round.get("path") in ("ai_fix", "ai_fix_first") and not last_round.get("improved"):
            correction_type = "hour_fix"
        elif last_round.get("path") == "hour_fix" and not last_round.get("improved"):
            # 双路径都无效 -> 降级
            cs["degraded"] = True
            cs["degraded_reason"] = (
                "双路径修正均未产生有效改善，"
                "系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
            )
            return {
                "round": cs["round"],
                "correction_type": None,
                "verdict": None,
                "comparison": None,
                "correction_result": None,
                "can_continue": False,
                "need_degrade": True,
                "degrade_reason": cs["degraded_reason"],
                "next_path": None,
                "message": cs["degraded_reason"],
            }
        else:
            correction_type = last_round.get("path", "ai_fix_first")
    else:
        # 没有历史，根据最新校验结果决定
        last_calibration = cs.get("last_calibration", {})
        verdict_key = last_calibration.get("verdict", {}).get("verdict", "")
        if verdict_key == "passed":
            return {
                "round": 0,
                "correction_type": None,
                "verdict": last_calibration,
                "comparison": None,
                "correction_result": None,
                "can_continue": False,
                "need_degrade": False,
                "degrade_reason": "",
                "next_path": None,
                "message": "校验已通过，无需修正。",
            }
        elif verdict_key == "ai_fix_first":
            correction_type = "ai_fix"
        elif verdict_key in ("ai_fix",):
            correction_type = "ai_fix"
        elif verdict_key == "hour_fix":
            correction_type = "hour_fix"
        else:
            correction_type = "ai_fix"

    # 执行修正（委托给 calibrate_apply）
    return await calibrate_apply({
        "session_id": session_id,
        "correction_type": correction_type,
        "new_hour": new_hour,
        "fix_stage": 3,
    })


@app.post("/api/calibrate/confirm-time")
async def calibrate_confirm_time(request: dict):
    """
    用户视角确认出生时间接口（P1 重构）

    反馈完成后，不展示技术校验面板，只问用户出生时间是否准确。
    根据用户选择走不同修正路径。

    请求参数：
    - session_id: 会话ID
    - time_accurate: true（准确）/ false（不太确定）

    返回：
    - path: "accurate" | "uncertain"
    - message: 用户看到的确认消息
    - loading_message: 修正过程中显示的消息
    - result_message: 修正完成后口语化展示的消息
    - result_data: 修正后的详细数据（供后续使用）
    """
    session_id = request.get("session_id", "")
    time_accurate = request.get("time_accurate", True)

    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    birth_info = session.get("birth_info", {})
    chart_data = session.get("chart_data", {})
    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])

    if not birth_info:
        raise HTTPException(status_code=400, detail="会话中缺少出生信息")

    # 运行校验判定（内部使用，不暴露给前端）
    calibration = run_calibration(feedbacks, predictions)
    verdict_key = calibration.get("verdict", {}).get("verdict", "passed")

    if time_accurate:
        # 用户确信出生时间准确 → 只走 AI 判断修正（旺衰/格局/用神），不动时辰
        ai_result = await run_ai_fix(chart_data, feedbacks, predictions, fix_stage=3)

        # 生成口语化修正结果
        wf = (ai_result.get("wangshuai_fix") or {})
        pf = (ai_result.get("pattern_fix") or {})
        yf = (ai_result.get("yongshen_fix") or {})

        parts_reviewed = []
        parts_off = []
        reason_parts = []

        # 分析哪些推断准、哪些偏了
        pred_map = {p["id"]: p for p in predictions}
        accurate_cats = set()
        inaccurate_cats = set()
        for fb in feedbacks:
            pred = pred_map.get(fb["prediction_id"])
            if pred:
                cat = pred.get("category", "")
                if fb.get("status") == "accurate":
                    accurate_cats.add(cat)
                elif fb.get("status") == "inaccurate":
                    inaccurate_cats.add(cat)

        if "性格" in accurate_cats or "事业" in accurate_cats:
            parts_reviewed.append("性格和事业")
        if "学历" in accurate_cats:
            parts_reviewed.append("学历")
        if inaccurate_cats:
            if "父母关" in inaccurate_cats:
                parts_off.append("父母")
            if "婚姻关" in inaccurate_cats:
                parts_off.append("婚姻")

        if wf.get("triggered"):
            reason_parts.append(f"日主在强弱边界上（当前{wf.get('current_strength','')}，从反角度看可能是{wf.get('suggested_strength','')}）")
        if pf.get("triggered"):
            reason_parts.append(f"格局{chart_data.get('yongshen',{}).get('pattern','')}处于边界区域")
        if yf.get("triggered"):
            reason_parts.append(f"从《穷通宝鉴》调候角度重新看，用神判断需要调整")

        reviewed_str = "、".join(parts_reviewed) if parts_reviewed else "大部分判断"
        off_str = "和".join(parts_off) if parts_off else "部分解读"
        reason_str = "；".join(reason_parts) if reason_parts else "你这个八字比较特殊，日主在强弱边界上，从不同角度看得出的结论不同"

        yongshen = chart_data.get("yongshen", {})
        current_pattern = yongshen.get("pattern", "正格")

        result_message = (
            f"我重新看了你的命盘，之前的判断中，{reviewed_str}是对的，"
            f"但{off_str}那块我解读偏了。"
            f"主要原因是{reason_str}。"
            f"我这次从《穷通宝鉴》的调候角度重新看，更新了分析。"
        )

        # 重新跑 P0 分析，再叠加 AI 校正层，返回给前端刷新
        updated = apply_ai_fix_to_analysis(reanalyze_chart(chart_data), ai_result)
        corrected_yongshen = {
            **(chart_data.get("yongshen") or {}),
            **(updated["strength_detail"].get("yongshen") or {}),
            "pattern": updated["strength_detail"].get("pattern", ""),
            "ri_zhu_strength": updated["strength_detail"].get("ri_zhu_strength", ""),
        }

        # 更新 session 中的 chart_data，确保断未来读到修正后的数据
        session["chart_data"]["yongshen"] = corrected_yongshen
        session["chart_data"]["strength_detail"] = updated["strength_detail"]
        session["chart_data"]["ri_zhu_strength"] = updated["strength_detail"]["ri_zhu_strength"]
        session["chart_data"]["pattern"] = updated["strength_detail"]["pattern"]

        return {
            "path": "accurate",
            "time_accurate": True,
            "message": "好的，我不动你的出生时间，换个角度重新分析。",
            "loading_message": "正在重新分析，可能需要几秒钟...",
            "result_message": result_message,
            "correction_type": "ai_fix",
            "ai_fix_result": {
                "wangshuai_fix": {
                    "triggered": wf.get("triggered", False),
                    "current_strength": wf.get("current_strength", ""),
                    "suggested_strength": wf.get("suggested_strength", ""),
                    "ai_yongshen": wf.get("ai_yongshen", ""),
                    "suggestion": wf.get("suggestion", ""),
                },
                "pattern_fix": {
                    "triggered": pf.get("triggered", False),
                    "current_pattern": pf.get("current_pattern", ""),
                    "suggested_pattern": pf.get("suggested_pattern", ""),
                    "suggested_yongshen": yf.get("ai_yongshen", ""),
                    "total_score": pf.get("total_score", 50),
                },
                "yongshen_fix": {
                    "triggered": yf.get("triggered", False),
                    "best_angle": yf.get("best_angle", ""),
                    "best_angle_label": yf.get("best_angle_label", ""),
                    "max_difference": yf.get("max_difference", 0),
                    "angle_accuracy": yf.get("angle_accuracy", {}),
                    "ranked_angles": yf.get("ranked_angles", []),
                    "ai_yongshen": yf.get("ai_yongshen", ""),
                    "suggestion": yf.get("suggestion", ""),
                },
            },
            # 修正后重新计算的 P0 分析结果，供前端刷新
            "updated_analysis": {
                "strength_detail": updated["strength_detail"],
                "classical_analysis": updated["classical_analysis"],
                "sources": updated["sources"],
            },
            "updated_chart": {
                "yongshen": corrected_yongshen,
            },
        }
    else:
        # 用户不太确定出生时间 → 尝试相邻4个时辰，找最吻合的
        original_hour = birth_info.get("hour", 12)
        original_shichen = get_shichen_name(original_hour)

        candidate_result = await try_candidate_hours(birth_info, feedbacks, predictions)

        if candidate_result.get("all_failed", True):
            # 所有候选都不如原始
            return {
                "path": "uncertain",
                "time_accurate": False,
                "message": "我帮你试了前后几个时辰，但没有找到更好的匹配。",
                "loading_message": "正在对比前后几个时辰，可能需要几秒钟...",
                "result_message": (
                    f"我试了前后几个时辰的排盘，但你的原始时辰{original_shichen}（{original_hour}时）"
                    f"和反馈情况最吻合。你的出生时间应该没问题，"
                    f"之前的偏差可能是其他原因导致的。让我换个思路重新分析。"
                ),
                "correction_type": "hour_fix_unchanged",
                "all_candidates_failed": True,
                "original_shichen": original_shichen,
                "original_hour": original_hour,
            }

        recommended_shichen = candidate_result.get("recommended", "")
        recommended_hour = candidate_result.get("recommended_hour")
        comparisons = candidate_result.get("comparisons", [])
        best = None
        for c in comparisons:
            if c.get("shichen") == recommended_shichen and not c.get("is_original"):
                best = c
                break

        result_message = (
            f"我试了前后几个时辰，发现把你的出生时间调到{recommended_shichen}"
            f"（{recommended_hour}点前后），之前的偏差就都对上了。"
        )

        return {
            "path": "uncertain",
            "time_accurate": False,
            "message": "我帮你试试前后几个时辰，看哪个和你的情况最吻合。",
            "loading_message": "正在对比前后几个时辰，可能需要几秒钟...",
            "result_message": result_message,
            "correction_type": "hour_fix",
            "all_candidates_failed": False,
            "recommended_shichen": recommended_shichen,
            "recommended_hour": recommended_hour,
            "original_shichen": original_shichen,
            "original_hour": original_hour,
            "best_score": best.get("score") if best else 0,
        }


@app.get("/api/calibrate/status")
def calibrate_status_get(session_id: str = ""):
    """
    获取修正状态接口（Phase 3 新增）

    查询参数：
    - session_id: 会话ID

    返回：
    - round: 当前修正轮数
    - degraded: 是否已降级
    - degraded_reason: 降级原因
    - current_path: 当前修正路径
    - history: 修正历史记录
    - can_continue: 是否可以继续修正
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id 参数")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    return get_correction_status(session)


# ============================================================
# P2: 断未来（基于校准命盘预测未来运势）
# ============================================================


# ============================================================
# V2.2: 反馈复盘 — LLM 分析错误来源 + 调整活权重
# ============================================================

@app.post("/api/feedback/review")
async def feedback_review(request: FeedbackReviewRequest):
    """
    LLM复盘用户反馈，分析错误层面，输出典籍权重调整建议。

    输入：7条预测 + 7条反馈 + 命盘摘要
    输出：错误分析 + 权重调整 + 调整前后的权重对比

    权重调整会自动应用到该 session 的后续分析。
    """
    chart_data = request.chart_data or {}

    chart_summary = {
        "ri_zhu": chart_data.get("ri_zhu", ""),
        "ri_zhu_wx": chart_data.get("ri_zhu_wuxing", ""),
        "month_branch": chart_data.get("month_branch", ""),
        "strength": chart_data.get("ri_zhu_strength", ""),
        "pattern": chart_data.get("pattern", ""),
        "yongshen": str(chart_data.get("yongshen_rule", {})),
    }

    preds = [p.model_dump() if hasattr(p, "model_dump") else p for p in request.predictions]
    fbs = [f.model_dump() if hasattr(f, "model_dump") else f for f in request.feedbacks]

    session_id = request.session_id or (
        fbs[0].get("session_id", "") if fbs else ""
    )

    result = await review_feedback(
        predictions=preds,
        feedbacks=fbs,
        chart_summary=chart_summary,
        session_id=session_id,
    )

    # 如果有权重调整，导出当前用户权重供前端展示
    current_weights = None
    if session_id:
        current_weights = get_user_weights(session_id)

    return {
        "review": result["review"],
        "applied": result.get("applied"),
        "current_weights": current_weights,
        "new_weights": result.get("new_weights", {}),
        "method": result.get("method", "mock_rule"),
        "suggested_actions": result.get("suggested_actions", []),
    }


@app.post("/api/feedback/weights/reset")
async def reset_feedback_weights(request: dict):
    """重置用户典籍权重为默认值"""
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    weights = reset_weights(session_id)
    return {"weights": weights}


@app.get("/api/feedback/weights")
async def get_feedback_weights(session_id: str = ""):
    """获取用户当前的典籍权重"""
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    weights = get_user_weights(session_id)
    return {"session_id": session_id, "weights": weights}


@app.post("/api/forecast")
async def forecast_endpoint(request: dict):
    """
    断未来接口（基于校准命盘预测未来运势）

    在修正确认后调用，基于校准命盘 + 大运流年，预测未来运势趋势。

    请求参数：
    - session_id: 会话ID（从 /api/predictions/generate 返回）
    - calibration_result: 修正结果（可选，包含修正类型和结果）

    返回：
    - forecast: 四维度预测（事业/财运/婚姻/健康）
    - current_dayun: 当前所处的大运信息
    - method: 预测方法（ai_deepseek 或 mock_template）
    - disclaimer: 免责声明
    """

    def _dict_dayun_to_obj(dayun_list):
        """将 dict 格式的大运列表转为 SimpleNamespace 对象列表"""
        from types import SimpleNamespace
        return [SimpleNamespace(
            stem=d.get("stem",""), branch=d.get("branch",""),
            ten_god=d.get("ten_god",""),
            start_age=d.get("start_age",0), end_age=d.get("end_age",0),
            start_year=d.get("start_year",0), end_year=d.get("end_year",0),
        ) for d in dayun_list]

    session_id = request.get("session_id", "")
    calibration_result = request.get("calibration_result")
    dayun_start_age = request.get("dayun_start_age")  # 可选：指定大运
    chart_data_input = request.get("chart_data")  # 兜底：无 session 时直接传 chart_data

    # 尝试从 session 获取数据，否则使用直接传入的 chart_data
    chart_data = {}
    feedbacks = []
    predictions = []
    birth_info = {}

    if session_id:
        session = _prediction_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")
        chart_data = session.get("chart_data", {})
        feedbacks = session.get("feedbacks", [])
        predictions = session.get("predictions", [])
        birth_info = session.get("birth_info", {})
    elif chart_data_input:
        chart_data = chart_data_input
    else:
        raise HTTPException(status_code=400, detail="缺少 session_id 或 chart_data 参数")

    # 重新构建 BaziChart 对象（用于大运分析）
    chart = None
    if birth_info:
        try:
            hour = birth_info.get("_processed_hour", birth_info.get("hour", 12))
            minute = birth_info.get("_processed_minute", birth_info.get("minute", 0))
            chart = calculate_bazi(
                year=birth_info.get("year", 1990),
                month=birth_info.get("month", 6),
                day=birth_info.get("day", 15),
                hour=hour,
                minute=minute,
                gender=birth_info.get("gender", "male"),
            )
        except Exception:
            raise HTTPException(status_code=500, detail="重新排盘失败")
    elif chart_data:
        # 无 session/birth_info：从 chart_data 构造 chart-like 对象
        from types import SimpleNamespace
        chart = SimpleNamespace(
            day_master=chart_data.get("day_master", ""),
            gender=chart_data.get("gender", "male"),
            yongshen=SimpleNamespace(
                primary=chart_data.get("yongshen", {}).get("primary", ""),
                secondary=chart_data.get("yongshen", {}).get("secondary", ""),
                ji_shen=chart_data.get("yongshen", {}).get("ji_shen", ""),
                pattern=chart_data.get("yongshen", {}).get("pattern", ""),
                ri_zhu_strength=chart_data.get("yongshen", {}).get("ri_zhu_strength", ""),
            ),
            dayun=_dict_dayun_to_obj(chart_data.get("dayun", [])),
            four_pillars=chart_data.get("four_pillars", {}),
        )
    else:
        raise HTTPException(status_code=400, detail="缺少出生信息或排盘数据")

    try:
        result = await generate_forecast(
            chart, chart_data,
            calibration_result=calibration_result,
            feedbacks=feedbacks,
            predictions=predictions,
            dayun_start_age=dayun_start_age,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"断未来预测错误: {str(e)}")


@app.post("/api/forecast/by-birth")
async def forecast_by_birth_endpoint(birth: BirthInfo):
    """
    基于出生信息直接预测未来（无需先走断前事流程）

    请求参数同 /api/chart

    返回：
    - forecast: 四维度预测（事业/财运/婚姻/健康）
    - current_dayun: 当前所处的大运信息
    - method: 预测方法
    - disclaimer: 免责声明
    """
    _validate_birth_info(birth)

    try:
        params, true_solar_info = process_birth_info(birth)
        chart = calculate_bazi(**params)
        chart_data = chart.model_dump()
        result = await generate_forecast(chart, chart_data)

        if true_solar_info:
            result["true_solar_info"] = true_solar_info
        result["birth_display"] = _build_birth_display(birth, params, true_solar_info)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"断未来预测错误: {str(e)}")



# ============================================================
# 断未来 — 大运分项 AI 分析
# ============================================================

DAYUN_ASPECTS_PROMPT = """你是一位严格遵循子平派体系的命理师，拥有30年实战经验。

## 命局数据
日主：{day_master}（五行{day_master_wuxing}），{ri_zhu_strength}，{pattern}
四柱：
  年柱：{year_pillar}
  月柱：{month_pillar}
  日柱：{day_pillar}
  时柱：{hour_pillar}
用神：{yongshen_primary}（第二用神：{yongshen_secondary}）
喜神：{xi_shen}
忌神：{ji_shen}
五行力量：{wuxing_balance}

## 规则引擎旺衰分析
{strength_breakdown}

## 典籍原文依据（RAG检索）
{classical_texts}

## 全部大运
{all_dayun}

## 当前选中大运
{dayun_stem}{dayun_branch}（{dayun_ten_god}），{dayun_age}岁，{dayun_years}年
天干{dayun_stem}五行{dayun_stem_wuxing}，地支{dayun_branch}
与命局关系：{dayun_relations}

## 大运内流年
{liunian_list}

请完成两项判断：

1. 为每步大运判断喜忌。**必须结合上述典籍原文和规则引擎分析**，综合考虑：
   - 天干地支五行是否用神/忌神
   - 大运干支与命局的合冲刑害
   - 十神组合对日主的影响
   - 调候角度（寒暖燥湿）
   输出为 all_badges 数组，每项格式：
   {{"stem":"丙","branch":"寅","label":"平","reason":"综合判断理由"}}

2. 从事业/财运/感情/健康/贵人五个维度分析当前选中大运。每条要求：
   - 2-3句具体分析（必须引用大运内至少2个具体流年，如"2024甲辰年食神制杀利于晋升，2026丙午年财星透出宜守不宜攻"）
   - 引用典籍原文一句（注明出处）——**优先使用上面的典籍原文依据**
   - 一条实操建议（基于五行/十神给出具体行动方向，也要提到具体年份的时间建议）
   - 严禁只说"某年注意""某年有机会"等模糊表述，必须写具体年份+干支

输出严格JSON：{{"all_badges":[...], "aspects":[...]}}"""


@app.post("/api/dayun/reading")
async def generate_dayun_reading(request: dict):
    """生成大运分项分析

    请求格式：
    {
        "session_id": "xxx",
        "dayun_index": 0  // 可选，默认当前大运
    }
    """
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    # Rate limit: 5 per minute per session
    if not check_rate_limit(f"dayun:{session_id}", 5, 60):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍候")

    chart_data = session.get("chart_data", {})
    dayun = chart_data.get("dayun", [])
    if not dayun:
        return {"aspects": [], "fallback": True, "reason": "无大运数据"}

    # 选中大运（默认当前）
    from datetime import datetime
    current_year = datetime.now().year
    dayun_index = request.get("dayun_index")
    if dayun_index is not None and 0 <= dayun_index < len(dayun):
        cur = dayun[dayun_index]
    else:
        cur = next((d for d in dayun if d["start_year"] <= current_year <= d["end_year"]), dayun[0])

    # 构建命局摘要
    fp = chart_data.get("four_pillars", {})
    yongshen = chart_data.get("yongshen", {})
    wuxing_score = chart_data.get("wuxing_score", {})
    dm = chart_data.get("day_master", "")
    dm_wuxing = WUXING_MAP.get(dm, "")
    wuxing_label = {"mu": "木", "huo": "火", "tu": "土", "jin": "金", "shui": "水"}

    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}

    def pillar_str(pos):
        p = fp.get(pos, {})
        hs = "、".join([f"{h.get('stem','')}({h.get('ten_god','')})" for h in p.get("hidden_stems", [])])
        return f"{p.get('stem','')}{p.get('branch','')} 天干十神={p.get('stem_ten_god','')} 藏干=[{hs}] 纳音={p.get('nayin','')}"

    # 五行平衡描述
    wx_balance_parts = []
    for wx, score in sorted(wuxing_score.items(), key=lambda x: -x[1]) if wuxing_score else []:
        wx_cn = wuxing_label.get(wx, wx)
        wx_balance_parts.append(f"{wx_cn}{score:.0f}%")
    wx_balance_str = "、".join(wx_balance_parts) if wx_balance_parts else "无数据"

    # 大运与命局关系（完整版：合/冲/刑/害/破）
    dz_relations = []
    # 六合
    branch_combine = {"子":"丑","丑":"子","寅":"亥","亥":"寅","卯":"戌","戌":"卯","辰":"酉","酉":"辰","巳":"申","申":"巳","午":"未","未":"午"}
    # 六冲
    branch_clash = {"子":"午","午":"子","丑":"未","未":"丑","寅":"申","申":"寅","卯":"酉","酉":"卯","辰":"戌","戌":"辰","巳":"亥","亥":"巳"}
    # 六害（穿）
    branch_harm = {"子":"未","未":"子","丑":"午","午":"丑","寅":"巳","巳":"寅","卯":"辰","辰":"卯","申":"亥","亥":"申","酉":"戌","戌":"酉"}
    # 三刑
    branch_punish = {"子":"卯","卯":"子","寅":"巳","巳":"申","申":"寅","丑":"戌","戌":"未","未":"丑"}
    # 六破
    branch_break = {"子":"酉","酉":"子","寅":"亥","亥":"寅","辰":"丑","丑":"辰","午":"卯","卯":"午","申":"巳","巳":"申","戌":"未","未":"戌"}

    db = cur.get("branch", "")
    for pos in ["year", "month", "day", "hour"]:
        nb = fp.get(pos, {}).get("branch", "")
        if not nb: continue
        if branch_clash.get(db) == nb:
            dz_relations.append(f"大运{db}冲{pos}柱{nb}")
        elif branch_combine.get(db) == nb:
            dz_relations.append(f"大运{db}合{pos}柱{nb}")
        elif branch_harm.get(db) == nb:
            dz_relations.append(f"大运{db}害{pos}柱{nb}")
        elif branch_punish.get(db) == nb:
            dz_relations.append(f"大运{db}刑{pos}柱{nb}")
        elif branch_break.get(db) == nb:
            dz_relations.append(f"大运{db}破{pos}柱{nb}")

    # 流年列表（全部10年，每年标注天干地支）
    liunian_parts = []
    for y in range(cur.get("start_year", 2000), cur.get("end_year", 2030) + 1):
        idx = (y - 4) % 60
        s = "甲乙丙丁戊己庚辛壬癸"[idx % 10]
        b = "子丑寅卯辰巳午未申酉戌亥"[idx % 12]
        liunian_parts.append(f"{y}{s}{b}")

    # 全部大运摘要
    all_dayun_parts = []
    for d in dayun:
        all_dayun_parts.append(
            f"{d.get('stem','')}{d.get('branch','')} "
            f"({d.get('ten_god','')}) "
            f"{d.get('start_age','')}-{d.get('end_age','')}岁"
        )

    # 规则引擎旺衰分析
    strength_detail = chart_data.get("strength_detail", {})
    strength_parts = []
    if strength_detail:
        for key in ["deling", "dedi", "desheng", "dezhu", "ke_xie_hao"]:
            d = strength_detail.get(key, {})
            if d and isinstance(d, dict):
                val = d.get("score", 0)
                desc = d.get("description", d.get("detail", ""))
                strength_parts.append(f"  {key}: 分数{val}, {desc}")
        strength_parts.append(f"  综合得分: {strength_detail.get('total_score', 'N/A')}")
    strength_breakdown = "\n".join(strength_parts) if strength_parts else "无数据"

    # 典籍原文（RAG检索 — 按阶段加权 + 用户活权重）
    classical_texts = "无检索数据"
    try:
        keywords = extract_keywords_from_chart(chart_data)
        user_weights = get_user_weights(session_id) if session_id else None
        stage_results = retrieve_all_stages(
            keywords,
            ri_zhu_wuxing=chart_data.get("ri_zhu_wuxing", ""),
            month_branch=chart_data.get("month_branch", ""),
            ri_zhu_stem=chart_data.get("day_master", ""),
            per_stage_k=3,
            user_weights=user_weights,
        )
        rag_results = merge_stage_results(stage_results, top_k=6)
        if rag_results:
            classical_texts = "\n".join([
                f"《{r.get('source','')}》{r.get('chapter','')}：[权威={r.get('authority','一般')}] {r.get('full_text', '')[:200]}"
                for r in rag_results[:5]
            ])
    except Exception:
        pass

    prompt = DAYUN_ASPECTS_PROMPT.format(
        day_master=dm,
        day_master_wuxing=dm_wuxing,
        ri_zhu_strength=yongshen.get("ri_zhu_strength", "未知"),
        pattern=yongshen.get("pattern", "未知"),
        year_pillar=pillar_str("year"),
        month_pillar=pillar_str("month"),
        day_pillar=pillar_str("day"),
        hour_pillar=pillar_str("hour"),
        yongshen_primary=yongshen.get("primary", "未知"),
        yongshen_secondary=yongshen.get("secondary", ""),
        xi_shen=yongshen.get("secondary", ""),
        ji_shen=yongshen.get("ji_shen", ""),
        wuxing_balance=wx_balance_str,
        strength_breakdown=strength_breakdown,
        classical_texts=classical_texts,
        all_dayun="\n".join(all_dayun_parts),
        dayun_stem=cur.get("stem", ""),
        dayun_branch=cur.get("branch", ""),
        dayun_ten_god=cur.get("ten_god", ""),
        dayun_age=f"{cur.get('start_age', '')}-{cur.get('end_age', '')}",
        dayun_years=f"{cur.get('start_year', '')}-{cur.get('end_year', '')}",
        dayun_stem_wuxing=WUXING_MAP.get(cur.get("stem", ""), ""),
        dayun_relations="、".join(dz_relations) if dz_relations else "无特殊关系",
        liunian_list="\n".join(liunian_parts),
    )

    if not os.getenv("DEEPSEEK_API_KEY"):
        return {"aspects": [], "fallback": True, "reason": "AI 服务不可用"}

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是一位严格遵循子平派体系的命理师，拥有30年实战经验。只返回JSON格式的分析结果。",
            timeout=45,
            model="deepseek-chat",
            temperature=0.6,
            max_tokens=3000,
        )
        if content and not content.startswith("[API_"):
            # Parse JSON — handle both dict and list formats
            import json as _json
            try:
                data = _json.loads(content) if isinstance(content, str) else content
            except Exception:
                # Try extracting JSON from text
                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    data = _json.loads(content[start:end])
                else:
                    raise
            aspects = data.get("aspects", []) if isinstance(data, dict) else data
            all_badges = data.get("all_badges", []) if isinstance(data, dict) else []
            return {"aspects": aspects, "all_badges": all_badges, "fallback": False}
    except Exception:
        pass

    return {"aspects": [], "fallback": True, "reason": "生成失败"}


# ============================================================
# AI 对话
# ============================================================

CHAT_PROMPT = """你是一位遵循子平派体系的命理师。用户正在查看命盘中的一个板块：{topic}。

命盘信息：{chart_summary}

用户的问题：{question}

请用口语化的中文回答，1-3句话，直接、有用、不啰嗦。如果问题涉及判断，请简要说明判断依据。"""


# ── Router includes (must be before app.post to give auth routes priority) ──
app.include_router(auth_router)
app.include_router(payment_router)
app.include_router(points_router)
app.include_router(invite_router)
app.include_router(chat_router)       # POST /api/chat — auth + trial + points gating
app.include_router(liuyue_router)
app.include_router(liunian_router)

# ── Legacy session-based chat (deprecated; use auth POST /api/chat instead) ──
@app.post("/api/chat/session")
async def ai_chat_session(request: dict):
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到会话: {session_id}")

    # Rate limit: 10 per minute per session
    if not check_rate_limit(f"chat:{session_id}", 10, 60):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍候")

    question = request.get("question", "").strip()
    topic = request.get("topic", "").strip()
    if not question:
        return {"reply": "请提一个具体的问题。"}

    chart_data = session.get("chart_data", {})
    # Compact chart summary
    dm = chart_data.get("day_master", "未知")
    ys = chart_data.get("yongshen", {})
    fp = chart_data.get("four_pillars", {})
    pillars = " ".join([f"{fp.get(p,{}).get('stem','')}{fp.get(p,{}).get('branch','')}" for p in ["year","month","day","hour"]])
    chart_summary = f"日主{dm}，四柱{pillars}，用神{ys.get('primary','未知')}，{ys.get('pattern','')}，{ys.get('ri_zhu_strength','')}"

    prompt = CHAT_PROMPT.format(topic=topic, chart_summary=chart_summary, question=question[:200])

    if not os.getenv("DEEPSEEK_API_KEY"):
        return {"reply": "AI 服务暂未配置"}

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是命理师。用口语化的中文回答，1-3句话。",
            timeout=20,
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=500,
        )
        if content and not content.startswith("[API_"):
            return {"reply": content.strip()}
    except Exception:
        pass

    return {"reply": "抱歉，暂时无法回答。"}


@app.post("/api/dayun/chat")
async def dayun_chat_endpoint(request: dict):
    """大运问答——结合当前命盘回答用户问题"""
    import datetime
    session_id = request.get("session_id", "")
    question = request.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    session = _prediction_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="未找到会话")
    chart_data = session.get("chart_data", {})
    ys = chart_data.get("yongshen", {})
    dm = chart_data.get("day_master", "")
    dayun = chart_data.get("dayun", [])
    cur, cy = None, datetime.datetime.now().year
    for d in dayun:
        if d.get("start_year",0)<=cy<=d.get("end_year",9999): cur=d; break
    cur = cur or (dayun[0] if dayun else {})
    summary = f"日主{dm}，{ys.get('pattern','')}，{ys.get('ri_zhu_strength','')}。用神{ys.get('primary','')}，忌神{ys.get('ji_shen','')}。"
    if cur: summary += f"当前{cur.get('stem','')}{cur.get('branch','')}大运（{cur.get('ten_god','')}），{cur.get('start_year','')}-{cur.get('end_year','')}年。"
    if not os.getenv("DEEPSEEK_API_KEY"): return {"answer": "AI 服务暂未配置"}
    prompt = f"命盘概要：{summary}\n\n用户提问：{question[:300]}\n\n请基于上述命盘信息，用口语化的中文回答，2-4句话，给出针对性建议。"
    try:
        from services.deepseek_client import call_deepseek
        content = await call_deepseek(prompt=prompt, system_prompt="你是命理师。基于命盘数据，用口语化中文回答。简洁直接有依据。", timeout=25, model="deepseek-chat", temperature=0.7, max_tokens=600)
        if content and not content.startswith("[API_"): return {"answer": content.strip()}
    except Exception: pass
    return {"answer": "抱歉，暂时无法回答，请稍后重试。"}


# ============================================================
# 用户数据持久化 API
# ============================================================

@app.get("/api/user/readings")
async def get_user_readings(user_id: str = Depends(require_auth)):
    """获取当前用户的排盘和验证记录（需要登录）"""
    charts = await get_user_charts(user_id, limit=10)
    verifications = await get_user_verifications(user_id, limit=10)
    return {
        "charts": charts,
        "verifications": verifications,
    }


@app.post("/api/user/save-reading")
async def save_user_reading(
    request: Request,
    user_id: str = Depends(require_auth),
):
    """保存排盘记录和验证结果（需要登录）"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    chart_data = body.get("chart_data")
    birth_info = body.get("birth_info")
    verification_result = body.get("verification_result")
    verification_history = body.get("verification_history", [])

    chart_record_id = None

    # 保存排盘记录
    if chart_data and birth_info:
        try:
            chart_record_id = await save_chart_record(user_id, birth_info, chart_data)
        except Exception as e:
            print(f"[save-reading] chart save failed: {e}")

    # 保存验证结果
    if verification_result:
        try:
            await save_verification_record(
                user_id=user_id,
                chart_record_id=chart_record_id,
                result=verification_result,
                history=verification_history,
            )
        except Exception as e:
            print(f"[save-reading] verification save failed: {e}")

    return {
        "ok": True,
        "chart_record_id": chart_record_id,
    }


# 静态文件服务（放在路由定义之后，避免覆盖 API 路由）
app.mount("/", StaticFiles(directory="public", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8022)
