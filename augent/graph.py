"""
Augent Graph — Obsidian graph view integration

Generates [[wikilinks]], MOC (Map of Content) files, and related links
to power Obsidian's graph view as a knowledge network.

Features:
- compute_related_links: Find semantically similar transcriptions → [[wikilinks]]
- generate_mocs: Create Map of Content hub files for tag clusters
- migrate_markdown_files: Update existing .md files to YAML frontmatter format
- rebuild_graph: Full rebuild orchestrator (migrate + related + MOCs)
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _wikilink_name(md_path: str) -> str:
    """Extract the wikilink name from an .md file path (filename without extension)."""
    return Path(md_path).stem


def compute_related_links(
    memory,
    cache_key: str,
    top_k: int = 5,
    similarity_threshold: float = 0.3,
) -> List[dict]:
    """
    Compute semantically related transcriptions and write [[wikilinks]] to the .md file.

    Uses document-level embedding cosine similarity + shared tag count as a combined
    relevance signal. Writes a ## Related section with [[wikilinks]] to the target file.

    Args:
        memory: TranscriptionMemory instance
        cache_key: Target transcription cache_key
        top_k: Maximum number of related links
        similarity_threshold: Minimum combined score to include

    Returns:
        List of related entries: [{title, md_path, similarity, shared_tags, combined_score}]
    """
    try:
        import numpy as np
        from .embeddings import EMBEDDING_MODEL, _cosine_similarity
    except ImportError:
        return []

    # Get target transcription info
    with sqlite3.connect(memory.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT audio_hash, md_path, title FROM transcriptions WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row or not row["md_path"]:
            return []

        target_hash = row["audio_hash"]
        target_md = row["md_path"]

    # Get target embeddings
    target_emb_data = memory.get_embeddings(target_hash, EMBEDDING_MODEL)
    if target_emb_data is None:
        return []
    target_embeddings = target_emb_data["embeddings"]
    # Document-level embedding: mean of all segment embeddings
    target_doc_emb = np.mean(target_embeddings, axis=0)

    # Get all transcriptions with embeddings
    entries = memory.get_all_with_embeddings(EMBEDDING_MODEL)
    if len(entries) < 2:
        return []

    # Get target tags for shared-tag scoring
    target_tags = set(t["name"] for t in memory.get_tags(cache_key))

    # Build a lookup: audio_hash → (cache_key, md_path, title, tags)
    hash_to_info = {}
    with sqlite3.connect(memory.db_path) as conn:
        conn.row_factory = sqlite3.Row
        for entry in entries:
            if entry["audio_hash"] == target_hash:
                continue
            rows = conn.execute(
                "SELECT cache_key, md_path, title FROM transcriptions WHERE audio_hash = ?",
                (entry["audio_hash"],),
            ).fetchall()
            if rows:
                r = rows[0]
                entry_tags = set(
                    t["name"] for t in memory.get_tags(r["cache_key"])
                )
                hash_to_info[entry["audio_hash"]] = {
                    "cache_key": r["cache_key"],
                    "md_path": r["md_path"] or "",
                    "title": r["title"] or entry["title"],
                    "tags": entry_tags,
                }

    # Compute similarity for each other transcription
    candidates = []
    for entry in entries:
        if entry["audio_hash"] == target_hash:
            continue
        if entry["embeddings"] is None:
            continue
        info = hash_to_info.get(entry["audio_hash"])
        if not info or not info["md_path"]:
            continue

        doc_emb = np.mean(entry["embeddings"], axis=0)
        sim = float(
            _cosine_similarity(
                target_doc_emb.reshape(1, -1), doc_emb.reshape(1, -1)
            )[0]
        )

        shared = target_tags & info["tags"]
        # Combined score: cosine similarity + 0.1 bonus per shared tag
        combined = sim + len(shared) * 0.1

        candidates.append(
            {
                "title": info["title"],
                "md_path": info["md_path"],
                "similarity": round(sim, 4),
                "shared_tags": sorted(shared),
                "combined_score": round(combined, 4),
                "cache_key": info["cache_key"],
            }
        )

    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
    related = [
        c for c in candidates[:top_k] if c["combined_score"] >= similarity_threshold
    ]

    # Write related section to target file
    if related:
        _write_related_section(target_md, related)

    return related


def _write_related_section(md_path: str, related: List[dict]) -> None:
    """Write or replace the ## Related section in an .md file."""
    path = Path(md_path)
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")

    # Build related section
    lines = ["", "## Related", ""]
    for r in related:
        if r["md_path"]:
            link_name = _wikilink_name(r["md_path"])
            tag_note = ""
            if r.get("shared_tags"):
                tag_note = f" — {', '.join(r['shared_tags'])}"
            lines.append(f"- [[{link_name}]]{tag_note}")
    lines.append("")
    related_section = "\n".join(lines)

    # Replace existing Related section or append
    pattern = r"\n## Related\n.*?(?=\n## |\Z)"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, related_section, content, flags=re.DOTALL)
    else:
        content = content.rstrip() + "\n" + related_section

    path.write_text(content, encoding="utf-8")


def generate_mocs(memory, min_members: int = 3) -> List[str]:
    """
    Generate/update MOC (Map of Content) files for tags with enough members.

    Creates one .md file per qualifying tag in the transcriptions directory.
    MOC files serve as hub nodes in the Obsidian graph, clustering related
    transcriptions around shared topics.

    Args:
        memory: TranscriptionMemory instance
        min_members: Minimum number of transcriptions to generate a MOC

    Returns:
        List of MOC file paths created/updated
    """
    all_tags = memory.get_all_tags_with_counts()
    moc_paths = []

    for tag_info in all_tags:
        if tag_info["count"] < min_members:
            continue

        tag_name = tag_info["name"]
        members = memory.filter_by_tag(tag_name)

        if len(members) < min_members:
            continue

        # Batch-fetch md_paths for all members
        member_links = []
        with sqlite3.connect(memory.db_path) as conn:
            for m in members:
                row = conn.execute(
                    "SELECT md_path, title FROM transcriptions WHERE cache_key = ?",
                    (m["cache_key"],),
                ).fetchone()
                if row and row[0]:
                    link_name = _wikilink_name(row[0])
                    title = row[1] or link_name
                    member_links.append((link_name, title))

        if not member_links:
            continue

        # Build MOC content with YAML frontmatter
        date_str = datetime.now().strftime("%Y-%m-%d")
        frontmatter = memory._build_frontmatter(
            title=tag_name,
            tags=[tag_name],
            date=date_str,
            type_="moc",
        )

        body_lines = [
            "",
            f"# {tag_name}",
            "",
        ]

        for link_name, title in sorted(member_links, key=lambda x: x[1]):
            body_lines.append(f"- [[{link_name}]]")
        body_lines.append("")

        content = frontmatter + "\n".join(body_lines)

        safe_name = memory._sanitize_filename(f"MOC_{tag_name}")
        moc_path = memory.md_dir / f"{safe_name}.md"
        moc_path.write_text(content, encoding="utf-8")
        moc_paths.append(str(moc_path))

    return moc_paths


def migrate_markdown_files(memory) -> dict:
    """
    Migrate all existing .md files to the new YAML frontmatter format.

    For each transcription in the DB:
    1. If .md exists without frontmatter → rewrite with frontmatter (preserving body)
    2. If .md exists with frontmatter → sync tags
    3. If .md is missing → recreate from DB data

    Returns:
        Migration stats: {migrated, synced, recreated, errors}
    """
    stats = {"migrated": 0, "synced": 0, "recreated": 0, "errors": 0}

    with sqlite3.connect(memory.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT cache_key, audio_hash, title, file_path, source_url, "
            "duration, language, created_at, md_path, text, segments "
            "FROM transcriptions"
        ).fetchall()

    for row in rows:
        try:
            cache_key = row["cache_key"]
            md_path_str = row["md_path"] or ""
            md_path = Path(md_path_str) if md_path_str else None

            tags = memory.get_tags(cache_key)
            tag_names = sorted([t["name"] for t in tags])

            duration = row["duration"] or 0
            mins = int(duration // 60)
            secs = int(duration % 60)
            title = row["title"] or ""
            source_url = row["source_url"] or ""
            language = row["language"] or "unknown"
            created = row["created_at"]
            date_str = (
                datetime.fromtimestamp(created).strftime("%Y-%m-%d")
                if created
                else datetime.now().strftime("%Y-%m-%d")
            )

            frontmatter = memory._build_frontmatter(
                title=title,
                tags=tag_names,
                source=os.path.basename(row["file_path"] or ""),
                source_url=source_url,
                duration=f"{mins}:{secs:02d}",
                language=language,
                date=date_str,
                type_="transcription",
            )

            if md_path and md_path.exists():
                content = md_path.read_text(encoding="utf-8")

                if content.startswith("---\n"):
                    # Has frontmatter — just sync tags
                    memory._sync_markdown_tags(cache_key)
                    stats["synced"] += 1
                else:
                    # Old format — extract body, prepend frontmatter
                    # Find the transcription body (## Transcription or after ---)
                    body_start = content.find("## Transcription")
                    if body_start == -1:
                        # Look for --- separator
                        sep_idx = content.find("\n---\n")
                        if sep_idx != -1:
                            body_start = sep_idx + 5
                        else:
                            body_start = 0

                    body = content[body_start:]

                    # Ensure body has title heading
                    if not body.strip().startswith("# "):
                        body = f"\n# {title}\n\n{body}"
                    else:
                        body = f"\n{body}"

                    new_content = frontmatter + body
                    md_path.write_text(new_content, encoding="utf-8")
                    stats["migrated"] += 1
            else:
                # .md missing — recreate from DB data
                segments = json.loads(row["segments"]) if row["segments"] else []
                text = row["text"] or ""

                body_lines = [
                    "",
                    f"# {title}",
                    "",
                    "## Transcription",
                    "",
                ]
                for seg in segments:
                    start = seg.get("start", 0)
                    m = int(start // 60)
                    s = int(start % 60)
                    seg_text = seg.get("text", "").strip()
                    body_lines.append(f"**[{m}:{s:02d}]** {seg_text}")
                    body_lines.append("")
                if not segments and text:
                    body_lines.append(text)
                    body_lines.append("")

                content = frontmatter + "\n".join(body_lines)

                sanitized = memory._sanitize_filename(title) if title else "untitled"
                new_md_path = memory.md_dir / f"{sanitized}.md"
                new_md_path.write_text(content, encoding="utf-8")

                # Update DB with new md_path
                with sqlite3.connect(memory.db_path) as update_conn:
                    update_conn.execute(
                        "UPDATE transcriptions SET md_path = ? WHERE cache_key = ?",
                        (str(new_md_path), cache_key),
                    )
                    update_conn.commit()

                stats["recreated"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


def rebuild_graph(memory) -> dict:
    """
    Full rebuild: migrate all files, compute related links, generate MOCs.

    This is the one-shot command to bring the entire memory directory
    up to date for Obsidian graph view. Safe to run repeatedly.

    Args:
        memory: TranscriptionMemory instance

    Returns:
        Stats: {migration: {...}, related_computed: int, mocs_generated: int}
    """
    # Phase 1: Migrate all files to new format
    migration_stats = migrate_markdown_files(memory)

    # Phase 2: Compute related links for all transcriptions with embeddings
    related_count = 0
    with sqlite3.connect(memory.db_path) as conn:
        cache_keys = [
            row[0]
            for row in conn.execute(
                "SELECT cache_key FROM transcriptions"
            ).fetchall()
        ]

    for ck in cache_keys:
        try:
            related = compute_related_links(memory, ck)
            if related:
                related_count += 1
        except Exception:
            pass

    # Phase 3: Generate MOCs
    moc_paths = generate_mocs(memory)

    return {
        "migration": migration_stats,
        "related_computed": related_count,
        "mocs_generated": len(moc_paths),
    }
