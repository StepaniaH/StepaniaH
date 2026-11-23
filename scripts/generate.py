#!/usr/bin/env python3
"""
Generate the full-screen GNU Emacs split-window SVGs (Light & Dark) and README.md
from `profile.toml`.

Usage:
  python3 scripts/generate.py                  # Build using stats in profile.toml
  python3 scripts/generate.py --fetch-github   # Fetch live stats from GitHub API (uses GITHUB_TOKEN if set)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tomllib
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "profile.toml"
ASSETS_DIR = ROOT / "assets"
README_PATH = ROOT / "README.md"


def visual_len(text: str) -> float:
    """Approximate monospace character cell width (CJK = 1.85, ASCII = 1.0)."""
    total = 0.0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 1.85
        else:
            total += 1.0
    return total


def truncate_visual(text: str, max_cells: float) -> str:
    if visual_len(text) <= max_cells:
        return text
    out = []
    acc = 0.0
    for ch in text:
        w = 1.85 if unicodedata.east_asian_width(ch) in ("W", "F") else 1.0
        if acc + w + 1.0 > max_cells:
            break
        out.append(ch)
        acc += w
    return "".join(out).rstrip() + "…"


def fetch_github_stats(username: str, fallback_stats: dict, fallback_langs: list[dict]) -> tuple[dict, list[dict]]:
    """Fetch live GitHub stats & top languages using GitHub GraphQL / REST API (stdlib only)."""
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{username}-emacs-readme-generator",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if token:
        query = """
        query($login: String!) {
          user(login: $login) {
            repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
              totalCount
              nodes {
                stargazerCount
                languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                  edges {
                    size
                    node { name }
                  }
                }
              }
            }
            contributionsCollection {
              totalCommitContributions
              restrictedContributionsCount
              totalPullRequestContributions
              totalRepositoriesWithContributedCommits
            }
            pullRequests(first: 1) {
              totalCount
            }
          }
        }
        """
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": {"login": username}}).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            user = payload.get("data", {}).get("user")
            if user:
                repos_node = user["repositories"]
                cc = user["contributionsCollection"]
                stars = sum(r["stargazerCount"] for r in repos_node["nodes"])
                commits = cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
                prs = user["pullRequests"]["totalCount"]
                contributed = cc["totalRepositoriesWithContributedCommits"]

                lang_totals: dict[str, int] = {}
                for r in repos_node["nodes"]:
                    for edge in r.get("languages", {}).get("edges", []):
                        lname = edge["node"]["name"]
                        lang_totals[lname] = lang_totals.get(lname, 0) + edge["size"]

                stats = {
                    "commits": str(commits),
                    "repos": str(repos_node["totalCount"]),
                    "stars": str(stars),
                    "prs": str(prs),
                    "contributed": str(contributed),
                }
                total_bytes = sum(lang_totals.values())
                if total_bytes > 0:
                    sorted_langs = sorted(lang_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
                    top_sum = sum(v for _, v in sorted_langs)
                    langs = [
                        {"name": k, "percent": round(v * 100.0 / top_sum, 1)}
                        for k, v in sorted_langs
                    ]
                else:
                    langs = fallback_langs
                return stats, langs
        except Exception as exc:
            print(f"[warn] GraphQL fetch failed ({exc}), falling back to profile.toml stats.", file=sys.stderr)

    # Public REST fallback (no token required for repos/stars/languages)
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{username}/repos?per_page=100&type=owner",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            repos = json.loads(resp.read().decode("utf-8"))
        own_repos = [r for r in repos if not r.get("fork")]
        stars = sum(r.get("stargazers_count", 0) for r in own_repos)
        lang_counts: dict[str, int] = {}
        for r in own_repos:
            lang = r.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
        stats = {
            **fallback_stats,
            "repos": str(len(own_repos)),
            "stars": str(stars),
        }
        if lang_counts:
            sorted_langs = sorted(lang_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_sum = sum(v for _, v in sorted_langs)
            langs = [{"name": k, "percent": round(v * 100.0 / top_sum, 1)} for k, v in sorted_langs]
        else:
            langs = fallback_langs
        return stats, langs
    except Exception as exc:
        print(f"[warn] REST fetch failed ({exc}), using profile.toml stats.", file=sys.stderr)
        return fallback_stats, fallback_langs


THEMES = {
    "light": {
        "frame_bg": "#ffffff",
        "frame_border": "#c9cdd4",
        "right_bg": "#faf9fc",
        "split_line": "#dfdce8",
        "tabbar_bg": "#eceaf2",
        "tabbar_border": "#d0cadc",
        "tab_active_bg": "#ffffff",
        "tab_active_fg": "#241b35",
        "tab_inactive_fg": "#6e6a7c",
        "badge_bg": "#6c46a8",
        "badge_fg": "#ffffff",
        "directive": "#858b96",
        "title": "#191970",
        "subtitle": "#24292f",
        "heading": "#6c46a8",
        "bullet": "#858b96",
        "proj_name": "#191970",
        "proj_desc": "#4b535d",
        "proj_tag": "#6c46a8",
        "prop_key": "#6c46a8",
        "prop_val": "#3a5fcd",
        "stat_lbl": "#24292f",
        "stat_val": "#241b35",
        "leader": "#dcd8e6",
        "bar_track": "#edeaf5",
        "bar_fills": ["#6c46a8", "#815ec0", "#9879d2", "#b097e0", "#c7b6ec"],
        "pct": "#6e7781",
        "ml_active_bg": "#e4dff0",
        "ml_active_border": "#c3bad6",
        "ml_active_fg": "#473f59",
        "ml_active_bold": "#1f1630",
        "ml_inactive_bg": "#eff1f4",
        "ml_inactive_border": "#d5d9e0",
        "ml_inactive_fg": "#767d87",
        "mini_prompt": "#6c46a8",
        "mini_cmd": "#1f2328",
        "mini_hint": "#8c959f",
        "cursor": "#6c46a8",
    },
    "dark": {
        "frame_bg": "#0d1117",
        "frame_border": "#30363d",
        "right_bg": "#10141c",
        "split_line": "#252136",
        "tabbar_bg": "#161b22",
        "tabbar_border": "#2d333b",
        "tab_active_bg": "#0d1117",
        "tab_active_fg": "#f0ecff",
        "tab_inactive_fg": "#7d8590",
        "badge_bg": "#9a7ee6",
        "badge_fg": "#0d1117",
        "directive": "#6e7681",
        "title": "#79c0ff",
        "subtitle": "#c9d1d9",
        "heading": "#b69df8",
        "bullet": "#6e7681",
        "proj_name": "#79c0ff",
        "proj_desc": "#9ca3af",
        "proj_tag": "#9a7ee6",
        "prop_key": "#b69df8",
        "prop_val": "#58a6ff",
        "stat_lbl": "#c9d1d9",
        "stat_val": "#f0ecff",
        "leader": "#282438",
        "bar_track": "#1d1a29",
        "bar_fills": ["#b69df8", "#9c80e8", "#8266d0", "#6850b0", "#523f8e"],
        "pct": "#8b949e",
        "ml_active_bg": "#241e36",
        "ml_active_border": "#3d3459",
        "ml_active_fg": "#b8b0cc",
        "ml_active_bold": "#ffffff",
        "ml_inactive_bg": "#161b22",
        "ml_inactive_border": "#2b3139",
        "ml_inactive_fg": "#6e7681",
        "mini_prompt": "#b69df8",
        "mini_cmd": "#e6edf3",
        "mini_hint": "#6e7681",
        "cursor": "#b69df8",
    },
}


def render_svg(data: dict, stats: dict, languages: list[dict], theme_name: str) -> str:
    t = THEMES[theme_name]
    prof = data["profile"]
    ios_apps = data.get("ios_apps", [])
    open_source = data.get("open_source", [])

    width = 880
    split_x = 564
    tabbar_h = 32
    ml_h = 26
    mini_h = 28

    # Calculate Left Buffer layout (README.org)
    left_elems: list[str] = []
    ly = tabbar_h + 28
    left_elems.append(
        f'  <text x="22" y="{ly}" class="mono" font-size="14">'
        f'<tspan fill="{t["directive"]}">#+title: </tspan>'
        f'<tspan fill="{t["title"]}" font-weight="700">{html.escape(prof["title"])}</tspan></text>'
    )
    ly += 22
    left_elems.append(
        f'  <text x="22" y="{ly}" class="mono" font-size="12.5">'
        f'<tspan fill="{t["directive"]}">#+subtitle: </tspan>'
        f'<tspan fill="{t["subtitle"]}">{html.escape(prof["subtitle"])}</tspan></text>'
    )

    def add_project_section(heading_text: str, items: list[dict], start_y: int) -> int:
        y = start_y + 32
        left_elems.append(
            f'  <text x="22" y="{y}" class="mono" font-size="13" fill="{t["heading"]}" font-weight="700">'
            f"{html.escape(heading_text)}</text>"
        )
        for item in items:
            y += 24
            name_str = truncate_visual(item["name"], 16)
            desc_str = truncate_visual(item["desc"], 38)
            tag_raw = item.get("tag", "").strip()
            tag_str = f":{tag_raw}:" if tag_raw else ""

            left_elems.append(
                f'  <text x="22" y="{y}" class="mono" font-size="12.5">'
                f'<tspan fill="{t["bullet"]}">- </tspan>'
                f'<tspan fill="{t["proj_name"]}" font-weight="600">{html.escape(name_str)}</tspan></text>'
            )
            left_elems.append(
                f'  <text x="162" y="{y}" class="mono" font-size="12" fill="{t["proj_desc"]}">'
                f"{html.escape(desc_str)}</text>"
            )
            if tag_str:
                left_elems.append(
                    f'  <text x="{split_x - 20}" y="{y}" class="mono" font-size="11.5" fill="{t["proj_tag"]}" text-anchor="end">'
                    f"{html.escape(tag_str)}</text>"
                )
        return y

    if ios_apps:
        ly = add_project_section("* iOS Apps", ios_apps, ly)
    if open_source:
        ly = add_project_section("* Open Source", open_source, ly)

    # Subtle Org-style site/blog properties at bottom of README.org buffer
    ly += 32
    site_clean = prof.get("website", "").replace("https://", "").replace("http://", "").rstrip("/")
    blog_clean = prof.get("blog", "").replace("https://", "").replace("http://", "").rstrip("/")
    left_elems.append(
        f'  <text x="22" y="{ly}" class="mono" font-size="12">'
        f'<tspan fill="{t["prop_key"]}">:SITE: </tspan>'
        f'<tspan fill="{t["prop_val"]}">{html.escape(site_clean)}</tspan>'
        f'<tspan fill="{t["directive"]}">   </tspan>'
        f'<tspan fill="{t["prop_key"]}">:BLOG: </tspan>'
        f'<tspan fill="{t["prop_val"]}">{html.escape(blog_clean)}</tspan></text>'
    )

    # Calculate Right Buffer layout (*github-stats*)
    rx_left = split_x + 20
    rx_right = width - 20
    right_elems: list[str] = []
    ry = tabbar_h + 28
    right_elems.append(
        f'  <text x="{rx_left}" y="{ry}" class="mono" font-size="13" fill="{t["heading"]}" font-weight="700">* GitHub Stats</text>'
    )

    stat_rows = [
        ("Total Commits", stats.get("commits", "-")),
        ("Public Repos", stats.get("repos", "-")),
        ("Total Stars", stats.get("stars", "-")),
        ("Pull Requests", stats.get("prs", "-")),
        ("Contributed To", stats.get("contributed", "-")),
    ]
    for label, val in stat_rows:
        ry += 23
        lbl_end = rx_left + int(len(label) * 7.5) + 8
        val_start = rx_right - int(len(str(val)) * 7.8) - 8
        right_elems.append(
            f'  <text x="{rx_left}" y="{ry}" class="mono" font-size="12.5" fill="{t["stat_lbl"]}">{html.escape(label)}</text>'
        )
        if val_start > lbl_end + 8:
            right_elems.append(
                f'  <line x1="{lbl_end}" y1="{ry - 4}" x2="{val_start}" y2="{ry - 4}" '
                f'stroke="{t["leader"]}" stroke-width="1" stroke-dasharray="1.5 4.5"/>'
            )
        right_elems.append(
            f'  <text x="{rx_right}" y="{ry}" class="mono" font-size="12.5" fill="{t["stat_val"]}" '
            f'font-weight="600" text-anchor="end">{html.escape(str(val))}</text>'
        )

    ry += 32
    right_elems.append(
        f'  <text x="{rx_left}" y="{ry}" class="mono" font-size="13" fill="{t["heading"]}" font-weight="700">* Top Languages</text>'
    )

    bar_x = rx_left + 92
    bar_w = rx_right - bar_x - 54
    for idx, lang in enumerate(languages[:5]):
        ry += 23
        lname = truncate_visual(lang["name"], 11)
        pct = float(lang["percent"])
        fill_w = max(4, round(bar_w * min(pct, 100.0) / 100.0))
        bar_color = t["bar_fills"][idx % len(t["bar_fills"])]

        right_elems.append(
            f'  <text x="{rx_left}" y="{ry}" class="mono" font-size="12.5" fill="{t["stat_lbl"]}">{html.escape(lname)}</text>'
        )
        right_elems.append(
            f'  <rect x="{bar_x}" y="{ry - 7.5}" width="{bar_w}" height="6" rx="2" fill="{t["bar_track"]}"/>'
        )
        right_elems.append(
            f'  <rect x="{bar_x}" y="{ry - 7.5}" width="{fill_w}" height="6" rx="2" fill="{bar_color}"/>'
        )
        right_elems.append(
            f'  <text x="{rx_right}" y="{ry}" class="mono" font-size="11.5" fill="{t["pct"]}" text-anchor="end">{pct:.1f}%</text>'
        )

    # Dynamic height so adding projects never overflows!
    ml_y = max(ly, ry) + 24
    mini_y = ml_y + ml_h
    total_h = mini_y + mini_h
    clip_id = f"frame-clip-{theme_name}"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_h}" width="100%" role="img" aria-label="{html.escape(prof['title'])} — GNU Emacs GitHub Profile">
  <defs>
    <clipPath id="{clip_id}">
      <rect x="0.5" y="0.5" width="{width - 1}" height="{total_h - 1}" rx="7"/>
    </clipPath>
    <style>
      .mono {{
        font-family: ui-monospace, "SF Mono", "Noto Sans Mono", "JetBrains Mono", Menlo, Consolas, "Noto Sans CJK SC", monospace;
      }}
      .cursor-{theme_name} {{
        fill: {t["cursor"]};
        animation: blink 1.06s step-end infinite;
      }}
      @keyframes blink {{
        0%, 49% {{ opacity: 1; }}
        50%, 100% {{ opacity: 0; }}
      }}
    </style>
  </defs>

  <!-- Clipped Inner Surfaces -->
  <g clip-path="url(#{clip_id})">
    <!-- Left Active Buffer Background -->
    <rect x="0" y="0" width="{width}" height="{total_h}" fill="{t["frame_bg"]}"/>

    <!-- Right Inactive Split Buffer Background -->
    <rect x="{split_x}" y="{tabbar_h}" width="{width - split_x}" height="{ml_y - tabbar_h}" fill="{t["right_bg"]}"/>

    <!-- Emacs tab-bar-mode Top Bar -->
    <rect x="0" y="0" width="{width}" height="{tabbar_h}" fill="{t["tabbar_bg"]}"/>
    <line x1="0" y1="{tabbar_h}" x2="{width}" y2="{tabbar_h}" stroke="{t["tabbar_border"]}" stroke-width="1"/>

    <!-- Active Tab: README.org (merges seamlessly into buffer) -->
    <path d="M 10 {tabbar_h} L 10 9 Q 10 5 14 5 L 142 5 Q 146 5 146 9 L 146 {tabbar_h} Z" fill="{t["tab_active_bg"]}"/>
    <path d="M 10 {tabbar_h} L 10 9 Q 10 5 14 5 L 142 5 Q 146 5 146 9 L 146 {tabbar_h}" fill="none" stroke="{t["tabbar_border"]}" stroke-width="1"/>

    <!-- Emacs E Badge in Active Tab -->
    <g transform="translate(20, 11)">
      <circle cx="7.5" cy="7.5" r="7" fill="{t["badge_bg"]}"/>
      <path d="M 10.6 4.5 C 8.6 3.9 6.0 4.3 5.1 5.6 C 4.5 6.5 5.6 7.3 7.8 7.5 C 5.8 7.9 4.5 9.0 5.1 10.2 C 6.0 11.4 8.8 11.4 10.7 10.3" fill="none" stroke="{t["badge_fg"]}" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <text x="41" y="23" class="mono" font-size="12" fill="{t["tab_active_fg"]}" font-weight="600">README.org</text>

    <!-- Inactive Tab: *github-stats* -->
    <text x="164" y="23" class="mono" font-size="12" fill="{t["tab_inactive_fg"]}">*github-stats*</text>
    <text x="{width - 16}" y="22" class="mono" font-size="11.5" fill="{t["tab_inactive_fg"]}" text-anchor="end">GNU Emacs</text>

    <!-- Left Buffer Content (README.org) -->
{chr(10).join(left_elems)}

    <!-- Right Buffer Content (*github-stats*) -->
{chr(10).join(right_elems)}

    <!-- Left Active Mode-line -->
    <rect x="0" y="{ml_y}" width="{split_x}" height="{ml_h}" fill="{t["ml_active_bg"]}"/>
    <line x1="0" y1="{ml_y}" x2="{split_x}" y2="{ml_y}" stroke="{t["ml_active_border"]}" stroke-width="1"/>
    <line x1="0" y1="{ml_y + ml_h}" x2="{split_x}" y2="{ml_y + ml_h}" stroke="{t["ml_active_border"]}" stroke-width="1"/>
    <text x="16" y="{ml_y + 17}" class="mono" font-size="11.5" fill="{t["ml_active_fg"]}">
      <tspan>-UUU:---  </tspan><tspan fill="{t["ml_active_bold"]}" font-weight="700">README.org</tspan><tspan>   All L1   (Org)</tspan>
    </text>

    <!-- Right Inactive Mode-line (mode-line-inactive) -->
    <rect x="{split_x}" y="{ml_y}" width="{width - split_x}" height="{ml_h}" fill="{t["ml_inactive_bg"]}"/>
    <line x1="{split_x}" y1="{ml_y}" x2="{width}" y2="{ml_y}" stroke="{t["ml_inactive_border"]}" stroke-width="1"/>
    <line x1="{split_x}" y1="{ml_y + ml_h}" x2="{width}" y2="{ml_y + ml_h}" stroke="{t["ml_inactive_border"]}" stroke-width="1"/>
    <text x="{split_x + 16}" y="{ml_y + 17}" class="mono" font-size="11.5" fill="{t["ml_inactive_fg"]}">-UUU:%%-  *github-stats*   All   (Special)</text>

    <!-- Vertical Split-Window Divider (C-x 3) -->
    <line x1="{split_x}" y1="{tabbar_h}" x2="{split_x}" y2="{ml_y + ml_h}" stroke="{t["split_line"]}" stroke-width="1"/>

    <!-- Shared Minibuffer / Echo Area -->
    <text x="16" y="{mini_y + 18}" class="mono" font-size="12">
      <tspan fill="{t["mini_prompt"]}" font-weight="600">M-x </tspan><tspan fill="{t["mini_cmd"]}">open-project</tspan>
    </text>
    <rect x="134" y="{mini_y + 7}" width="7.5" height="13.5" class="cursor-{theme_name}"/>
    <text x="{width - 16}" y="{mini_y + 18}" class="mono" font-size="11.5" fill="{t["mini_hint"]}" text-anchor="end">C-x C-f {html.escape(site_clean)}</text>
  </g>

  <!-- Outer Window Border -->
  <rect x="0.5" y="0.5" width="{width - 1}" height="{total_h - 1}" rx="7" fill="none" stroke="{t["frame_border"]}"/>
</svg>
"""
    return svg


def render_readme(data: dict) -> str:
    prof = data["profile"]
    ios_apps = data.get("ios_apps", [])
    open_source = data.get("open_source", [])

    def fmt_links(items: list[dict]) -> str:
        return " · ".join(f'<a href="{html.escape(it["url"])}">{html.escape(it["name"])}</a>' for it in items)

    lines = [
        '<picture>',
        '  <source media="(prefers-color-scheme: dark)" srcset="./assets/emacs-frame-dark.svg">',
        '  <source media="(prefers-color-scheme: light)" srcset="./assets/emacs-frame-light.svg">',
        f'  <img alt="{html.escape(prof["title"])} — GNU Emacs GitHub Profile" src="./assets/emacs-frame-light.svg" width="100%">',
        '</picture>',
        '',
        '<sub>',
    ]

    site_links = []
    if prof.get("website"):
        site_clean = prof["website"].replace("https://", "").replace("http://", "").rstrip("/")
        site_links.append(f'<a href="{html.escape(prof["website"])}">{html.escape(site_clean)}</a>')
    if prof.get("blog"):
        blog_clean = prof["blog"].replace("https://", "").replace("http://", "").rstrip("/")
        site_links.append(f'<a href="{html.escape(prof["blog"])}">{html.escape(blog_clean)}</a>')
    if prof.get("email"):
        site_links.append(f'<a href="mailto:{html.escape(prof["email"])}">Email</a>')

    footer_rows = []
    if ios_apps:
        footer_rows.append(f'<b>iOS Apps:</b> {fmt_links(ios_apps)}')
    if open_source:
        footer_rows.append(f'<b>Open Source:</b> {fmt_links(open_source)}')
    if site_links:
        footer_rows.append(f'<b>Links:</b> {" · ".join(site_links)}')

    lines.append("<br>\n".join(footer_rows))
    lines.append('</sub>')
    lines.append('')
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Emacs-style GitHub Profile SVGs and README.md")
    parser.add_argument("--fetch-github", action="store_true", help="Fetch live stats from GitHub API")
    args = parser.parse_args()

    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    stats = data.get("stats", {})
    languages = data.get("languages", [])
    if args.fetch_github:
        username = data["profile"].get("github_user", data["profile"]["title"])
        stats, languages = fetch_github_stats(username, stats, languages)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "emacs-frame-light.svg").write_text(render_svg(data, stats, languages, "light"), encoding="utf-8")
    (ASSETS_DIR / "emacs-frame-dark.svg").write_text(render_svg(data, stats, languages, "dark"), encoding="utf-8")
    README_PATH.write_text(render_readme(data), encoding="utf-8")
    print("Generated assets/emacs-frame-light.svg, assets/emacs-frame-dark.svg, and README.md")


if __name__ == "__main__":
    main()
