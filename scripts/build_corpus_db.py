"""构建 SQLite + FTS5 典籍库

从 classical_corpus/ 目录读取8本典籍的 .txt 文件和 index.json，
输出 data/classical_corpus.db（SQLite + FTS5 全文索引）。

用法: python scripts/build_corpus_db.py
"""

import json
import os
import re
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(PROJECT_ROOT, "data", "classical_corpus")
DB_PATH = os.path.join(PROJECT_ROOT, "data", "classical_corpus.db")

# Corpus metadata
CORPUS_META = {
    "ziping":         {"source": "子平真诠",       "author": "沈孝瞻", "dynasty": "清", "school": "子平派"},
    "dishui":         {"source": "滴天髓",           "author": "刘伯温", "dynasty": "明", "school": "子平派"},
    "qiongtong":      {"source": "穷通宝鉴",         "author": "余春台", "dynasty": "清", "school": "子平派"},
    "sanming":        {"source": "三命通会",         "author": "万民英", "dynasty": "明", "school": "子平派"},
    "yuanhai":        {"source": "渊海子平",         "author": "徐大升", "dynasty": "宋", "school": "子平派"},
    "dishui_chanwei": {"source": "滴天髓阐微",       "author": "任铁樵", "dynasty": "清", "school": "子平派"},
    "dishui_ren":     {"source": "滴天髓征义",       "author": "任铁樵", "dynasty": "清", "school": "子平派"},
    "ziping_yuanben": {"source": "子平真诠原本",     "author": "沈孝瞻", "dynasty": "清", "school": "子平派"},
}

_CJK_RE = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af])')


def _space_cjk(text: str) -> str:
    """在 CJK 字符之间插入空格，用于 FTS5 索引（弥补 unicode61 tokenizer 对中文的不足）"""
    return _CJK_RE.sub(r' \1 ', text)


def parse_existing_index(corpus_id: str, index_path: str) -> list[dict]:
    """解析已有的结构化 index.json（ziping/dishui/qiongtong）"""
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    chapters = []
    source_name = index.get("source", CORPUS_META.get(corpus_id, {}).get("source", corpus_id))
    for i, ch in enumerate(index.get("chapters", []), 1):
        file_path = os.path.join(CORPUS_DIR, corpus_id, ch["file"])
        if not os.path.exists(file_path):
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            full_text = f.read()

        chapters.append({
            "corpus_id": corpus_id,
            "source": source_name,
            "chapter_no": i,
            "title": ch.get("title", ""),
            "topic": ch.get("topic", ""),
            "keywords": ", ".join(ch.get("keywords", [])),
            "summary": ch.get("summary", full_text[:200] if full_text else ""),
            "full_text": full_text,
            "full_text_spaced": _space_cjk(full_text),
            "file_path": ch["file"],
        })
    return chapters


def parse_raw_corpus(corpus_id: str) -> list[dict]:
    """解析无结构化索引的典籍（sanming/yuanhai/dishui_chanwei/dishui_ren/ziping_yuanben）"""
    corpus_path = os.path.join(CORPUS_DIR, corpus_id)
    if not os.path.exists(corpus_path):
        return []

    meta = CORPUS_META.get(corpus_id, {})
    source_name = meta.get("source", corpus_id)

    # Try index.json for file list
    index_path = os.path.join(corpus_path, "index.json")
    file_list = []
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            if isinstance(idx, list):
                file_list = [e.get("file", "") for e in idx]
            elif isinstance(idx, dict):
                file_list = [ch.get("file", "") for ch in idx.get("chapters", [])]
        except json.JSONDecodeError:
            pass

    # Fallback: list all .txt files
    if not file_list:
        file_list = sorted([
            f for f in os.listdir(corpus_path)
            if f.endswith(".txt") and f != "index.json"
        ])

    chapters = []
    for i, filename in enumerate(file_list, 1):
        file_path = os.path.join(corpus_path, filename)
        if not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                full_text = f.read()
        except UnicodeDecodeError:
            continue

        # Extract title from first line
        lines = full_text.strip().split("\n")
        title = filename.replace(".txt", "")
        for line in lines[:5]:
            line = line.strip().lstrip("#").strip()
            if line and len(line) < 100:
                title = line
                break

        chapters.append({
            "corpus_id": corpus_id,
            "source": source_name,
            "chapter_no": i,
            "title": title,
            "topic": "",       # 待标注
            "keywords": "",    # 待标注
            "summary": full_text[:200] if full_text else "",
            "full_text": full_text,
            "full_text_spaced": _space_cjk(full_text),
            "file_path": filename,
        })
    return chapters


def build_db():
    """构建完整 SQLite + FTS5 典籍库"""
    print(f"Building corpus DB at: {DB_PATH}")
    print(f"Source directory: {CORPUS_DIR}")

    # 删除旧库
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("  Removed old database")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- 建表 ---
    cursor.execute("""
        CREATE TABLE corpus_meta (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            author TEXT,
            dynasty TEXT,
            school TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_id TEXT NOT NULL,
            chapter_no INTEGER,
            title TEXT NOT NULL,
            topic TEXT,
            analysis_layer TEXT,
            keywords TEXT,
            summary TEXT,
            full_text TEXT NOT NULL,
            full_text_spaced TEXT NOT NULL,
            file_path TEXT,
            FOREIGN KEY (corpus_id) REFERENCES corpus_meta(id)
        )
    """)

    # FTS5 全文索引（使用 space-delimited 中文，解决 CJK 分词问题）
    cursor.execute("""
        CREATE VIRTUAL TABLE chapters_fts USING fts5(
            title,
            summary,
            full_text_spaced,
            content='chapters',
            content_rowid='id'
        )
    """)

    # --- 插入元数据 ---
    for cid, meta in CORPUS_META.items():
        cursor.execute(
            "INSERT INTO corpus_meta VALUES (?, ?, ?, ?, ?)",
            (cid, meta["source"], meta["author"], meta["dynasty"], meta["school"]),
        )

    # --- 解析并插入章节 ---
    total_chapters = 0
    for cid in CORPUS_META:
        print(f"  Processing: {CORPUS_META[cid]['source']} ({cid})...")

        # Try structured index first
        index_path = os.path.join(CORPUS_DIR, cid, "index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    idx = json.load(f)
                if isinstance(idx, dict) and "chapters" in idx and idx["chapters"]:
                    chapters = parse_existing_index(cid, index_path)
                else:
                    chapters = parse_raw_corpus(cid)
            except json.JSONDecodeError:
                chapters = parse_raw_corpus(cid)
        else:
            chapters = parse_raw_corpus(cid)

        for ch in chapters:
            cursor.execute(
                """INSERT INTO chapters
                   (corpus_id, chapter_no, title, topic, keywords, summary, full_text, full_text_spaced, file_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ch["corpus_id"], ch["chapter_no"], ch["title"],
                 ch["topic"], ch["keywords"],
                 ch["summary"][:500], ch["full_text"], ch["full_text_spaced"], ch["file_path"]),
            )
            total_chapters += 1

        print(f"    → {len(chapters)} chapters")

    # --- 构建 FTS5 索引 ---
    print(f"\n  Building FTS5 index for {total_chapters} chapters...")
    cursor.execute(
        "INSERT INTO chapters_fts(chapters_fts) VALUES('rebuild')"
    )

    conn.commit()

    # --- 验证 ---
    cursor.execute("SELECT COUNT(*) FROM corpus_meta")
    corpus_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM chapters")
    chapter_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM chapters_fts")
    fts_count = cursor.fetchone()[0]

    print(f"\n✅ Build complete:")
    print(f"   Corpus sources: {corpus_count}")
    print(f"   Chapters: {chapter_count}")
    print(f"   FTS5 indexed: {fts_count}")

    # 显示各典籍分布
    cursor.execute(
        "SELECT corpus_id, COUNT(*) FROM chapters GROUP BY corpus_id ORDER BY COUNT(*) DESC"
    )
    print(f"\n   Per-corpus breakdown:")
    for cid, cnt in cursor.fetchall():
        src = CORPUS_META.get(cid, {}).get("source", cid)
        has_topic = cursor.execute(
            "SELECT COUNT(*) FROM chapters WHERE corpus_id = ? AND topic != ''", (cid,)
        ).fetchone()[0]
        topic_pct = f"({has_topic}/{cnt} labelled)" if has_topic else "(unlabelled)"
        print(f"     {src}: {cnt} chapters {topic_pct}")

    conn.close()

    # 文件大小
    db_size = os.path.getsize(DB_PATH)
    print(f"\n   DB size: {db_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    build_db()
