"""RAG 检索模块 - 从 classical_corpus 典籍原文库检索相关章节"""

import json
import os
from collections import defaultdict

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

CORPUS_PATHS = {
    "ziping": os.path.join(_DATA_DIR, "classical_corpus", "ziping"),
    "dishui": os.path.join(_DATA_DIR, "classical_corpus", "dishui"),
    "qiongtong": os.path.join(_DATA_DIR, "classical_corpus", "qiongtong"),
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
    """Load all corpus index.json files (cached)."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    indexes = {}
    for name, path in CORPUS_PATHS.items():
        index_path = os.path.join(path, "index.json")
        with open(index_path, "r", encoding="utf-8") as f:
            indexes[name] = json.load(f)
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
# Main retrieval
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
# Public API
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
