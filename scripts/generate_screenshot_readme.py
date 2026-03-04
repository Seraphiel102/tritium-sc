#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Generate docs/screenshots/README.md from the current screenshot inventory.

Run standalone:
    python3 scripts/generate_screenshot_readme.py

Also called automatically by test_doc_screenshots.py after generating new shots.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

# Hero images used in the top-level README.md
HERO_IMAGES = {
    "command-center.jpg": "Command Center — real satellite imagery, AI-controlled units, live tactical panels",
    "game-combat.jpg": "Wave-based Nerf combat — turrets engage hostile intruders with projectile physics and kill streaks",
    "neighborhood-wide.jpg": "Your neighborhood becomes the battlefield — same pipeline monitors real security",
}

# Additional doc images referenced in README.md
DOC_IMAGES = {
    "mission-modal.png": "Mission Initialization — 6 game modes, local model selection, AI or scripted generation",
    "mission-deployment.jpg": "Defenders deployed at real buildings — turrets guarding structures, rovers on street patrols",
    "mission-combat.jpg": "Mid-battle — green friendlies engage red hostiles across the neighborhood",
}

# Combat detail shots from ./test.sh docs
COMBAT_DETAIL = {
    "combat-close.jpg": "Close-up combat — combined arms engagement at tight zoom",
    "combat-satellite.jpg": "Satellite combat — turret defense on satellite imagery with roads",
    "combat-air.jpg": "Air support — drones and turrets engaging hostiles",
}

# UI reference screenshots
UI_REFERENCE = {
    "help-overlay.jpg": "Keyboard shortcuts modal",
    "help-overlay.png": "Keyboard shortcuts modal (PNG)",
    "panels-annotated.png": "Command Center panels annotated",
    "dom-audit-annotated.png": "DOM audit annotated",
    "green-blobs-annotated.png": "Green blobs diagnostic",
    "overlap-annotated.png": "Overlap diagnostic annotated",
    "overlap-diagnostic.png": "Overlap diagnostic",
}

# Audit screenshots
AUDIT_IMAGES = {
    "audit-04-help.png": "Audit: Help overlay",
    "audit-08-setup.png": "Audit: Setup mode",
    "audit-09-combat.png": "Audit: Combat",
    "audit-10-combat-later.png": "Audit: Combat (later)",
}

# Thought closeups
THOUGHT_IMAGES = {
    "thought-closeup-0.png": "Amy thought panel closeup",
    "thought-closeup-1.png": "Amy thought panel closeup",
    "thought-closeup-2.png": "Amy thought panel closeup",
}


def _count_files(directory: Path, extensions: tuple[str, ...] = (".jpg", ".png")) -> int:
    """Count image files in a directory."""
    if not directory.exists():
        return 0
    return sum(1 for f in directory.iterdir() if f.suffix.lower() in extensions)


def _section(name: str, images: dict[str, str], base: str = "") -> str:
    """Generate a markdown section with image thumbnails."""
    lines = [f"### {name}", ""]
    for filename, caption in images.items():
        path = Path(base) / filename if base else Path(filename)
        full_path = SCREENSHOTS_DIR / path
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({path})")
            lines.append(f"*{caption}*")
            lines.append("")
    return "\n".join(lines)


def generate() -> str:
    """Generate the full README.md content."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Count subfolders
    demo_count = _count_files(SCREENSHOTS_DIR / "demo")
    engine_count = _count_files(SCREENSHOTS_DIR / "engine-extraction")
    top_count = _count_files(SCREENSHOTS_DIR)

    lines = [
        "# Screenshots",
        "",
        f"**{top_count + demo_count + engine_count} screenshots** across {top_count} top-level, "
        f"{demo_count} demo captures, and {engine_count} engine extraction frames.",
        "",
        f"*Last updated: {now}*",
        "",
        "---",
        "",
    ]

    # Hero images
    lines.append("## Hero Images (README)")
    lines.append("")
    lines.append("These are referenced directly in the top-level README.md. Regenerate with `./test.sh docs`.")
    lines.append("")
    for filename, caption in HERO_IMAGES.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Mission screenshots
    lines.append("## Mission Generator")
    lines.append("")
    for filename, caption in DOC_IMAGES.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Combat detail
    lines.append("## Combat Detail (from `./test.sh docs`)")
    lines.append("")
    for filename, caption in COMBAT_DETAIL.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # UI Reference
    lines.append("## UI Reference")
    lines.append("")
    for filename, caption in UI_REFERENCE.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Thought closeups
    lines.append("## Amy Thought Closeups")
    lines.append("")
    for filename, caption in THOUGHT_IMAGES.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Audit
    lines.append("## Visual Audit")
    lines.append("")
    for filename, caption in AUDIT_IMAGES.items():
        full_path = SCREENSHOTS_DIR / filename
        if full_path.exists():
            lines.append(f"**{filename}**")
            lines.append(f"![{caption}]({filename})")
            lines.append(f"*{caption}*")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Engine extraction
    lines.append("## Engine Extraction")
    lines.append("")
    ee_dir = SCREENSHOTS_DIR / "engine-extraction"
    if ee_dir.exists():
        for f in sorted(ee_dir.iterdir()):
            if f.suffix.lower() in (".jpg", ".png"):
                rel = f"engine-extraction/{f.name}"
                lines.append(f"**{f.name}**")
                lines.append(f"![{f.stem}]({rel})")
                lines.append("")

    lines.append("---")
    lines.append("")

    # Demo — just summary, too many to embed
    lines.append("## Demo Captures")
    lines.append("")
    if demo_count > 0:
        lines.append(f"**{demo_count} screenshots** in [`demo/`](demo/) from automated demo runs.")
        lines.append("")
        lines.append("Demo captures are organized by timestamp and act:")
        lines.append("")
        lines.append("| Act | Content |")
        lines.append("|-----|---------|")
        lines.append("| Act 1 | Command Center panels, map modes, satellite view |")
        lines.append("| Act 2 | Unit selection, tactical overview, deployment |")
        lines.append("| Act 3 | Battle: countdown, waves, combat bursts, leaderboard |")
        lines.append("| Act 4 | TAK integration: status, clients, geochat, alerts |")
        lines.append("| Act 5 | Escalation: threat detection, alerts, multi-threat |")
        lines.append("| Act 6 | Panels: mesh, audio, events, search, system, scenarios |")
        lines.append("| Act 7 | Camera: neighborhood wide, zoom levels, cinematic |")
        lines.append("")
    else:
        lines.append("No demo captures yet. Run the demo suite to generate.")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Regenerating")
    lines.append("")
    lines.append("```bash")
    lines.append("# Regenerate hero + combat detail screenshots")
    lines.append("./test.sh docs")
    lines.append("")
    lines.append("# Regenerate this README from current inventory")
    lines.append("python3 scripts/generate_screenshot_readme.py")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main():
    content = generate()
    readme_path = SCREENSHOTS_DIR / "README.md"
    readme_path.write_text(content)
    print(f"Generated {readme_path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
