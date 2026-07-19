"""RAG 检索模块 - 从 classical_corpus 典籍原文库检索相关章节

V2.3: 支持 SQLite + FTS5 全文检索（优先），文件系统为后备。
"""

import json
import os
import sqlite3
from collections import defaultdict

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_DB_PATH = os.path.join(_DATA_DIR, "classical_corpus.db")

CORPUS_PATHS = {
    "ziping": os.path.join(_DATA_DIR, "classical_corpus", "ziping"),
    "dishui": os.path.join(_DATA_DIR, "classical_corpus", "dishui"),
    "qiongtong": os.path.join(_DATA_DIR, "classical_corpus", "qiongtong"),
    "sanming": os.path.join(_DATA_DIR, "classical_corpus", "sanming"),
    "yuanhai": os.path.join(_DATA_DIR, "classical_corpus", "yuanhai"),
    "dishui_chanwei": os.path.join(_DATA_DIR, "classical_corpus", "dishui_chanwei"),
    "dishui_ren": os.path.join(_DATA_DIR, "classical_corpus", "dishui_ren"),
    "ziping_yuanben": os.path.join(_DATA_DIR, "classical_corpus", "ziping_yuanben"),
}

# ============================================================
# 分析阶段 → 典籍权重映射
# ============================================================
# 每个分析阶段指定：
#   primary: 第一权威典籍（权重×2.0）
#   supplementary: 辅助参考典籍（权重×1.5）
#   不在列表中的典籍：权重×1.0（不提升，进入竞争）
#
# 原则：
#   定格局 → 子平真诠第一（"用神专求月令"体系最完整）
#   取用神 → 子平真诠 + 穷通宝鉴并列（格局+调候互补）
#   断旺衰 → 滴天髓第一（"能知衰旺之真机"最精深）
#   基 础 → 三命通会、渊海子平（先不挂载）
# ============================================================

STAGE_PRIORITY = {
    "basics": {        # 基础理论（五行干支特性）— V2.4 新增
        "primary": ["sanming"],
        "supplementary": ["ziping", "dishui"],
    },
    "shishen": {       # 十神解读（比肩劫财食神...）— V2.4 新增
        "primary": ["yuanhai"],
        "supplementary": ["ziping"],
    },
    "pattern": {       # 定格局
        "primary": ["ziping"],
        "supplementary": ["dishui"],
    },
    "yongshen": {      # 取用神
        "primary": ["ziping", "qiongtong"],
        "supplementary": ["dishui"],
    },
    "wangshuai": {     # 断旺衰
        "primary": ["dishui"],
        "supplementary": ["ziping", "sanming"],
    },
}

# 穷通宝鉴月令映射（用于按日主过滤噪声）
QIONGTONG_MONTH_MAP = {
    "寅": "正月", "卯": "二月", "辰": "三月", "巳": "四月",
    "午": "五月", "未": "六月", "申": "七月", "酉": "八月",
    "戌": "九月", "亥": "十月", "子": "十一月", "丑": "十二月",
}

# Keyword groups for extracting search terms from strength_detail
DELING_KEYWORDS = ["得令", "月令", "旺衰", "提纲", "当令", "失令"]
DEDI_KEYWORDS = ["通根", "根气", "地支", "天干", "本气", "中气", "余气"]
DESHENG_KEYWORDS = ["印绶", "印星", "生扶", "正印", "偏印", "生我"]
DEZHU_KEYWORDS = ["比劫", "比肩", "劫财", "帮身", "同类"]
KE_XIE_HAO_KEYWORDS = ["官杀", "食伤", "财星", "正官", "七杀", "伤官", "食神", "正财", "偏财"]

STRENGTH_KEYWORD_MAP = {
    "太旺": ["旺衰", "从强", "从旺"],
    "偏强": ["旺衰", "身旺"],
    "中和": ["旺衰", "中和"],
    "偏弱": ["身弱", "用神", "扶抑"],
    "太弱": ["身弱", "从格", "无根"],
    "极弱": ["从格", "无根", "弃命"],
    "极强": ["从强", "从旺"],
}

PATTERN_KEYWORD_MAP = {
    "从弱格": ["从格", "真从", "假从", "从财", "从杀", "弃命"],
    "从强格": ["从格", "从强", "从旺"],
    "正格": ["用神", "扶抑", "格局"],
}

YONGSHEN_WUXING_KEYWORDS = {
    "金": ["金", "庚", "辛"],
    "木": ["木", "甲", "乙"],
    "水": ["水", "壬", "癸"],
    "火": ["火", "丙", "丁"],
    "土": ["土", "戊", "己"],
}


# ============================================================
# Index Loading (lazy + cached)
# ============================================================

_index_cache: dict[str, dict] | None = None


def _load_all_indexes() -> dict[str, dict]:
    """Load all corpus index.json files (cached).

    只加载有完整结构化索引的典籍（dict 格式，含 source/chapters）。
    list 格式的新典籍（sanming/yuanhai 等）仅通过 FTS5 检索，不参与 fallback。
    """
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    indexes = {}
    for name, path in CORPUS_PATHS.items():
        index_path = os.path.join(path, "index.json")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        # 只保留 dict 格式且有 chapters 字段的索引（兼容 fallback 检索）
        if isinstance(index, dict) and "chapters" in index:
            indexes[name] = index
        # list 格式的新典籍跳过（仅通过 FTS5 检索）

    _index_cache = indexes
    return indexes


# ============================================================
# Keyword extraction
# ============================================================

def _extract_keywords(strength_detail: dict) -> list[str]:
    """Extract search keywords from strength_detail dict."""
    keywords: list[str] = []

    for dimension in ["deling", "dedi", "desheng", "dezhu", "ke_xie_hao"]:
        section = strength_detail.get(dimension, {})
        conclusion = section.get("conclusion", "")
        if "令" in conclusion:
            keywords.extend(DELING_KEYWORDS)
        if "根" in conclusion or "地" in conclusion:
            keywords.extend(DEDI_KEYWORDS)
        if "印" in conclusion or "生" in conclusion:
            keywords.extend(DESHENG_KEYWORDS)
        if "比" in conclusion or "助" in conclusion:
            keywords.extend(DEZHU_KEYWORDS)
        if "克" in conclusion or "泄" in conclusion or "耗" in conclusion:
            keywords.extend(KE_XIE_HAO_KEYWORDS)

    ri_zhu_strength = strength_detail.get("ri_zhu_strength", "")
    if ri_zhu_strength in STRENGTH_KEYWORD_MAP:
        keywords.extend(STRENGTH_KEYWORD_MAP[ri_zhu_strength])

    pattern = strength_detail.get("pattern", "")
    for key, kws in PATTERN_KEYWORD_MAP.items():
        if key in pattern:
            keywords.extend(kws)
            break

    yongshen = strength_detail.get("yongshen", {})
    for field in ["primary", "secondary"]:
        wuxing = yongshen.get(field, "")
        if wuxing in YONGSHEN_WUXING_KEYWORDS:
            keywords.extend(YONGSHEN_WUXING_KEYWORDS[wuxing])

    ri_zhu_wuxing = strength_detail.get("ri_zhu_wuxing", "")
    if ri_zhu_wuxing in YONGSHEN_WUXING_KEYWORDS:
        keywords.extend(YONGSHEN_WUXING_KEYWORDS[ri_zhu_wuxing])

    keywords.extend(["旺衰", "用神"])
    return keywords


def extract_keywords_from_chart(chart: dict) -> list[str]:
    """
    Extract search keywords directly from chart data (for new endpoint).

    Args:
        chart: {
            "ri_zhu": "己",
            "ri_zhu_wuxing": "土",
            "month_branch": "卯",
            "month_hidden_stems": [...],
            ...
        }
    """
    keywords: list[str] = []
    ri_zhu_wx = chart.get("ri_zhu_wuxing", "")
    month_branch = chart.get("month_branch", "")

    # Day master keywords
    if ri_zhu_wx in YONGSHEN_WUXING_KEYWORDS:
        keywords.extend(YONGSHEN_WUXING_KEYWORDS[ri_zhu_wx])

    # Month branch keywords
    BRANCH_TO_PINYIN = {
        "子": "zi", "丑": "chou", "寅": "yin", "卯": "mao",
        "辰": "chen", "巳": "si", "午": "wu", "未": "wei",
        "申": "shen", "酉": "you", "戌": "xu", "亥": "hai",
    }
    branch_pinyin = BRANCH_TO_PINYIN.get(month_branch, "")
    if branch_pinyin:
        keywords.append(branch_pinyin + "月")

    # General megalithic keywords
    keywords.extend(["月令", "旺衰", "用神", "格局", "调候"])
    return keywords


# ============================================================
# Chapter scoring
# ============================================================

def _score_chapter(chapter: dict, keywords: list[str]) -> float:
    """
    Score a chapter entry from index.json against keywords.

    Scoring rules:
    - topic matches a keyword: +3
    - each keyword match in chapter's keywords list: +2
    - chapter title contains a query keyword: +2
    - summary contains a query keyword: +1
    """
    score = 0.0

    topic = chapter.get("topic", "")
    if topic in keywords:
        score += 3

    chapter_keywords = chapter.get("keywords", [])
    for kw in chapter_keywords:
        if kw in keywords:
            score += 2

    title = chapter.get("title", "")
    for kw in keywords:
        if kw and kw in title:
            score += 2

    summary = chapter.get("summary", "")
    for kw in keywords:
        if kw and kw in summary:
            score += 1

    return score


# ============================================================
# Chapter file reading
# ============================================================

def _read_chapter_file(corpus_name: str, file_name: str) -> str:
    """Read the full text of a chapter .txt file."""
    file_path = os.path.join(CORPUS_PATHS[corpus_name], file_name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"[原文缺失: {corpus_name}/{file_name}]"


# ============================================================
# V2.3: SQLite + FTS5 全文检索
# ============================================================

def _fts5_available() -> bool:
    """检查 SQLite FTS5 数据库是否可用"""
    return os.path.exists(_DB_PATH)


def search_corpus_fts(
    query: str,
    stage: str | None = None,
    corpus_ids: list[str] | None = None,
    ri_zhu_wuxing: str = "",
    month_branch: str = "",
    ri_zhu_stem: str = "",
    top_k: int = 10,
) -> list[dict]:
    """
    使用 FTS5 全文搜索引擎检索典籍。

    Args:
        query: 自然语言查询（空格分隔的关键词）
        stage: 可选，过滤 analysis_layer
        corpus_ids: 可选，限制典籍范围
        ri_zhu_wuxing: 日主五行（用于穷通宝鉴后过滤）
        month_branch: 月令
        ri_zhu_stem: 日干（用于穷通宝鉴精准匹配，如"丁"）
        top_k: 返回条数

    Returns:
        同 retrieve_by_stage 格式的结果列表
    """
    if not _fts5_available():
        return []

    # FTS5 查询语法：关键词用 OR 连接
    keywords = [kw for kw in query.split() if len(kw) >= 2]
    if not keywords:
        return []

    fts_query = " OR ".join(keywords)

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    # 基础 SQL
    where_clauses = [f"chapters_fts MATCH ?"]
    params = [fts_query]

    if corpus_ids:
        placeholders = ",".join("?" * len(corpus_ids))
        where_clauses.append(f"c.corpus_id IN ({placeholders})")
        params.extend(corpus_ids)

    if stage:
        where_clauses.append("c.analysis_layer = ?")
        params.append(stage)

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT c.*,
               rank AS fts_rank,
               snippet(chapters_fts, 1, '<b>', '</b>', '...', 40) AS fts_snippet
        FROM chapters_fts f
        JOIN chapters c ON f.rowid = c.id
        WHERE {where_sql}
        ORDER BY rank
        LIMIT ?
    """
    params.append(top_k)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)

        # 穷通宝鉴后过滤（如果日主/月令提供了，进一步过滤）
        qiongtong_quality = 1.0
        if r["corpus_id"] == "qiongtong" and ri_zhu_wuxing and month_branch:
            qiongtong_quality = _filter_qiongtong_noise(
                r["corpus_id"], {"title": r["title"]}, ri_zhu_wuxing, month_branch,
                ri_zhu_stem=ri_zhu_stem,
            )
            if qiongtong_quality == 0.0:
                continue

        base_score = (20.0 - len(results) * 2) * qiongtong_quality
        results.append({
            "id": str(r["id"]),
            "source": CORPUS_META_SOURCE.get(r["corpus_id"], r["corpus_id"]),
            "chapter": r["title"],
            "text": r["full_text"],
            "topic": r["topic"] or "",
            "context": r["summary"] or "",
            "score": base_score,
            "weighted_score": base_score,
            "authority": "fts_match",
            "full_text": r["full_text"],
            "file": r["file_path"] or "",
            "corpus": r["corpus_id"],
            "keywords_matched": keywords,
            "fts_rank": r["fts_rank"],
        })

    # 精准匹配后加权：穷通宝鉴精准日干+月令匹配直接注入
    if ri_zhu_stem and month_branch:
        target_month = QIONGTONG_MONTH_MAP.get(month_branch, "")
        if target_month and ri_zhu_stem:
            # 在 chapters 表中直接查找精准匹配章节
            exact_title = f"{target_month}{ri_zhu_stem}"
            try:
                conn = sqlite3.connect(_DB_PATH)
                conn.row_factory = sqlite3.Row
                exact_rows = conn.execute(
                    "SELECT * FROM chapters WHERE corpus_id='qiongtong' AND title LIKE ?",
                    (f"%{exact_title}%",)
                ).fetchall()
                conn.close()

                for er in exact_rows:
                    er_dict = dict(er)
                    # 检查是否已在结果中
                    already_in = any(
                        r["corpus"] == "qiongtong" and er_dict["title"] in r["chapter"]
                        for r in results
                    )
                    if already_in:
                        # 已在结果中，加分即可
                        for r in results:
                            if r["corpus"] == "qiongtong" and er_dict["title"] in r["chapter"]:
                                r["score"] += 15.0
                                r["weighted_score"] += 15.0
                    else:
                        # 不在结果中，直接注入
                        results.append({
                            "id": str(er_dict["id"]),
                            "source": CORPUS_META_SOURCE.get("qiongtong", "穷通宝鉴"),
                            "chapter": er_dict["title"],
                            "text": er_dict["full_text"],
                            "topic": er_dict["topic"] or "",
                            "context": er_dict.get("summary", "") or "",
                            "score": 25.0,  # 高分注入
                            "weighted_score": 25.0,
                            "authority": "fts_match",
                            "full_text": er_dict["full_text"],
                            "file": er_dict.get("file_path", ""),
                            "corpus": "qiongtong",
                            "keywords_matched": keywords,
                            "fts_rank": 0,
                        })
            except Exception:
                pass

    # 按分重排
    results.sort(key=lambda x: x["weighted_score"], reverse=True)

    return results


# corpus_id → source name 映射
CORPUS_META_SOURCE = {
    "ziping": "子平真诠",
    "dishui": "滴天髓",
    "qiongtong": "穷通宝鉴",
    "sanming": "三命通会",
    "yuanhai": "渊海子平",
    "dishui_chanwei": "滴天髓阐微",
    "dishui_ren": "滴天髓征义",
    "ziping_yuanben": "子平真诠原本",
}


# ============================================================
# Main retrieval (legacy file-system, kept as fallback)
# ============================================================

def _retrieve_chapters(keywords: list[str], top_k: int = 5) -> list[dict]:
    """
    Match keywords against all corpus chapters, return top_k with full text.

    Returns list of dicts with:
        id, source, chapter, text, topic, context, score, full_text, file
    """
    indexes = _load_all_indexes()
    scored = []

    for corpus_name, index in indexes.items():
        source_name = index["source"]
        for chapter in index["chapters"]:
            score = _score_chapter(chapter, keywords)
            if score > 0:
                full_text = _read_chapter_file(corpus_name, chapter["file"])
                scored.append({
                    "id": chapter["id"],
                    "source": source_name,
                    "chapter": chapter["title"],
                    "text": full_text,
                    "topic": chapter.get("topic", ""),
                    "context": chapter.get("summary", ""),
                    "score": score,
                    "full_text": full_text,
                    "file": chapter["file"],
                    "corpus": corpus_name,
                    "keywords_matched": [
                        kw for kw in keywords
                        if kw in chapter.get("keywords", [])
                        or kw in chapter.get("title", "")
                        or kw in chapter.get("topic", "")
                        or kw in chapter.get("summary", "")
                    ],
                })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate: same source + topic keeps highest score
    seen = set()
    unique = []
    for entry in scored:
        key = (entry["source"], entry["topic"])
        if key not in seen:
            seen.add(key)
            unique.append(entry)

    return unique[:top_k]


# ============================================================
# Stage-aware retrieval (NEW)
# ============================================================

def _filter_qiongtong_noise(
    corpus_name: str, chapter: dict, ri_zhu_wuxing: str, month_branch: str,
    ri_zhu_stem: str = "",
) -> float:
    """
    穷通宝鉴噪声过滤：检查章节是否匹配当前日主和月令。

    返回质量乘数：
    - 1.0: 精准日干+月令匹配（如 丁火+丑月→"十二月丁火"）
    - 0.8: 同五行日干+月令匹配（如 丁火+丑月→"十二月丙火"，调候规律相近）
    - 0.5: 精准日干但月令不匹配（如 丁火+丑月→"六月丁火"）
    - 0.3: 同五行但月令不匹配
    - 0.0: 无关
    """
    if corpus_name != "qiongtong":
        return 1.0  # 其他典籍不过滤

    title = chapter.get("title", "")
    if not title:
        return 1.0

    # 解析"正月甲木"格式的标题
    target_month = QIONGTONG_MONTH_MAP.get(month_branch, "")
    if not target_month:
        return 0.5

    # 月令匹配
    month_match = target_month in title

    # 日干→章节文本映射
    GAN_TO_TEXT = {
        "甲": "甲木", "乙": "乙木", "丙": "丙火", "丁": "丁火",
        "戊": "戊土", "己": "己土", "庚": "庚金", "辛": "辛金",
        "壬": "壬水", "癸": "癸水",
    }

    # 同五行日干（降级匹配用）
    SAME_ELEMENT_GAN = {
        "木": ["甲木", "乙木"], "火": ["丙火", "丁火"],
        "土": ["戊土", "己土"], "金": ["庚金", "辛金"],
        "水": ["壬水", "癸水"],
    }

    # 精准日干匹配（如果提供了日干）
    exact_stem_text = GAN_TO_TEXT.get(ri_zhu_stem, "")
    exact_stem_match = exact_stem_text and exact_stem_text in title

    # 同五行匹配（降级）
    day_gan_texts = SAME_ELEMENT_GAN.get(ri_zhu_wuxing, [])
    same_element_match = any(gan_text in title for gan_text in day_gan_texts)

    if month_match and exact_stem_match:
        return 1.0   # 精准匹配：日干+月令都对
    elif month_match and same_element_match:
        return 0.8   # 同五行+月令匹配（调候规律相近）
    elif exact_stem_match:
        return 0.5   # 精准日干但月令不对（调候规律相同五行有参考性）
    elif same_element_match:
        return 0.3   # 仅同五行
    else:
        return 0.0   # 无关


def retrieve_by_stage(
    stage: str,
    keywords: list[str],
    ri_zhu_wuxing: str = "",
    month_branch: str = "",
    ri_zhu_stem: str = "",
    top_k: int = 5,
    user_weights: dict[str, float] | None = None,
) -> list[dict]:
    """
    按分析阶段加权检索典籍。

    V2.3: 优先使用 FTS5 全文检索，回退到文件系统关键词检索。

    Args:
        stage: 分析阶段 ("pattern" | "yongshen" | "wangshuai")
        keywords: 检索关键词列表
        ri_zhu_wuxing: 日主五行（用于穷通宝鉴过滤）
        month_branch: 月令地支（用于穷通宝鉴过滤）
        ri_zhu_stem: 日干（用于穷通宝鉴精准日干匹配）
        top_k: 返回结果数量
        user_weights: 用户活权重表 {"pattern:ziping": 1.0, ...}，None 则只用固定权重

    Returns:
        加权后的典籍条目列表，优先典籍排在前面
    """
    # --- V2.3: FTS5 优先 ---
    if _fts5_available():
        query = " ".join(keywords)
        fts_results = search_corpus_fts(
            query,
            stage=None,
            corpus_ids=None,
            ri_zhu_wuxing=ri_zhu_wuxing,
            month_branch=month_branch,
            ri_zhu_stem=ri_zhu_stem,
            top_k=top_k * 3,
        )

        if fts_results:
            # 对FTS5结果应用阶段权重 + 用户权重
            priority = STAGE_PRIORITY.get(stage, {})
            primary = priority.get("primary", [])
            supplementary = priority.get("supplementary", [])

            for r in fts_results:
                corpus_name = r["corpus"]
                base = r["score"]

                if corpus_name in primary:
                    stage_mult = 2.0
                    r["authority"] = "primary"
                elif corpus_name in supplementary:
                    stage_mult = 1.5
                    r["authority"] = "supplementary"
                else:
                    stage_mult = 1.0
                    r["authority"] = "general"

                user_mult = 1.0
                if user_weights:
                    user_mult = user_weights.get(f"{stage}:{corpus_name}", 1.0)

                r["weighted_score"] = base * stage_mult * user_mult

            # 按加权分排序
            fts_results.sort(key=lambda x: x["weighted_score"], reverse=True)

            # 去重
            seen = set()
            unique = []
            for r in fts_results:
                key = (r["source"], r["topic"])
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            return unique[:top_k]

    # --- Fallback: 文件系统关键词检索 ---
    priority = STAGE_PRIORITY.get(stage, {})
    primary_corpuses = priority.get("primary", [])
    supplementary_corpuses = priority.get("supplementary", [])

    indexes = _load_all_indexes()
    scored = []

    for corpus_name, index in indexes.items():
        source_name = index["source"]

        for chapter in index["chapters"]:
            base_score = _score_chapter(chapter, keywords)

            # 穷通宝鉴噪声过滤
            if corpus_name == "qiongtong" and ri_zhu_wuxing and month_branch:
                quality = _filter_qiongtong_noise(
                    corpus_name, chapter, ri_zhu_wuxing, month_branch,
                    ri_zhu_stem=ri_zhu_stem,
                )
                if quality == 0.0:
                    continue
                base_score *= quality

            if base_score <= 0:
                continue

            # 固定权重
            if corpus_name in primary_corpuses:
                stage_mult = 2.0
                authority = "primary"
            elif corpus_name in supplementary_corpuses:
                stage_mult = 1.5
                authority = "supplementary"
            else:
                stage_mult = 1.0
                authority = "general"

            # 用户活权重（叠加在固定权重之上）
            user_mult = 1.0
            if user_weights:
                weight_key = f"{stage}:{corpus_name}"
                user_mult = user_weights.get(weight_key, 1.0)

            weighted_score = base_score * stage_mult * user_mult

            full_text = _read_chapter_file(corpus_name, chapter["file"])
            scored.append({
                "id": chapter["id"],
                "source": source_name,
                "chapter": chapter["title"],
                "text": full_text,
                "topic": chapter.get("topic", ""),
                "context": chapter.get("summary", ""),
                "score": base_score,
                "weighted_score": weighted_score,
                "authority": authority,
                "full_text": full_text,
                "file": chapter["file"],
                "corpus": corpus_name,
                "keywords_matched": [
                    kw for kw in keywords
                    if kw in chapter.get("keywords", [])
                    or kw in chapter.get("title", "")
                    or kw in chapter.get("topic", "")
                    or kw in chapter.get("summary", "")
                ],
            })

    # 按加权分数排序，同分时优先权威度高的
    scored.sort(key=lambda x: (x["weighted_score"], x["authority"] == "primary"), reverse=True)

    # 去重：同一来源+主题只保留最高分
    seen = set()
    unique = []
    for entry in scored:
        key = (entry["source"], entry["topic"])
        if key not in seen:
            seen.add(key)
            unique.append(entry)

    return unique[:top_k]


def retrieve_all_stages(
    keywords: list[str],
    ri_zhu_wuxing: str = "",
    month_branch: str = "",
    ri_zhu_stem: str = "",
    per_stage_k: int = 4,
    user_weights: dict[str, float] | None = None,
) -> dict[str, list[dict]]:
    """
    一次性为所有分析阶段检索典籍。
    返回 {stage_name: [检索结果列表]}，按去重后的综合结果合并。

    Args:
        keywords: 检索关键词
        ri_zhu_wuxing: 日主五行
        month_branch: 月令地支
        ri_zhu_stem: 日干（穷通精准匹配）
        per_stage_k: 每个阶段取多少条
        user_weights: 用户活权重表

    Returns:
        {"pattern": [...], "yongshen": [...], "wangshuai": [...]}
    """
    results = {}
    all_seen = set()

    for stage_name in ["basics", "shishen", "pattern", "yongshen", "wangshuai"]:
        stage_results = retrieve_by_stage(
            stage_name, keywords,
            ri_zhu_wuxing=ri_zhu_wuxing,
            month_branch=month_branch,
            ri_zhu_stem=ri_zhu_stem,
            top_k=per_stage_k,
            user_weights=user_weights,
        )
        results[stage_name] = stage_results

        # 记录全局已见
        for r in stage_results:
            all_seen.add((r["source"], r["topic"]))

    return results


def merge_stage_results(
    stage_results: dict[str, list[dict]], top_k: int = 10
) -> list[dict]:
    """
    将分阶段检索结果合并为统一列表（去重，按加权分排序）。

    Args:
        stage_results: retrieve_all_stages 的返回值
        top_k: 最终取多少条

    Returns:
        合并后的统一结果列表
    """
    seen = set()
    merged = []

    for entries in stage_results.values():
        for entry in entries:
            key = (entry["source"], entry["topic"])
            if key not in seen:
                seen.add(key)
                merged.append(entry)

    merged.sort(key=lambda x: x["weighted_score"], reverse=True)
    return merged[:top_k]


# ============================================================
# Public API (backward-compatible)
# ============================================================

def retrieve_relevant_texts(strength_detail: dict, top_k: int = 5) -> list[dict]:
    """
    Retrieve relevant classical texts from the corpus based on strength analysis.

    Backward-compatible with the old classical_texts.json API.

    Args:
        strength_detail: strength analysis data from rules/yongshen.py
        top_k: number of results to return

    Returns:
        list of dicts with: id, source, chapter, text, topic, context, score
    """
    keywords = _extract_keywords(strength_detail)
    return _retrieve_chapters(keywords, top_k=top_k)


def retrieve_by_keywords(keywords: list[str], top_k: int = 10) -> list[dict]:
    """
    Retrieve relevant texts from the corpus using explicit keywords.

    Args:
        keywords: list of search keywords
        top_k: number of results to return

    Returns:
        list of dicts with: id, source, chapter, text, topic, context, score
    """
    return _retrieve_chapters(keywords, top_k=top_k)


# ============================================================
# Utility: get all source names for attribution
# ============================================================

def get_corpus_sources() -> list[dict]:
    """Return metadata about all available corpus sources."""
    indexes = _load_all_indexes()
    sources = []
    for corpus_name, index in indexes.items():
        sources.append({
            "corpus": corpus_name,
            "source": index["source"],
            "author": index.get("author", ""),
            "dynasty": index.get("dynasty", ""),
            "school": index.get("school", ""),
            "total_chapters": index.get("total_chapters", 0),
        })
    return sources
