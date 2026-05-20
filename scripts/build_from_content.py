#!/usr/bin/env python3
"""
Reads site_content.md and generates Hugo Academic content files.

Supported sections (case-insensitive H1 headings):
  # About        → content/authors/admin/_index.md  (bio, role, interests, education)
  # Experience   → content/home/experience.md        (H2 = ## Title | Org | date - date)
  # Skills       → content/home/skills.md            (free text + link to commercial site)
  # Projects     → left as-is (note-only section)
  # Talks        → left as-is (note-only section)
  # Featured...  → left as-is (auto from ORCID)
  # Funding      → left as-is (auto from ORCID)
  # All Pub...   → left as-is (auto from ORCID)

  Any OTHER heading → creates a new blank widget section at the end of the page,
  rendered as formatted HTML from the markdown content beneath it.

Run:  python scripts/build_from_content.py
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
CONTENT_FILE = REPO / "site_content.md"

# Sections that are auto-managed by the ORCID script — skip silently
AUTO_SECTIONS = {"featured publications", "funding", "all publications"}

# Sections that are managed per-file in content/ subdirs — skip silently
NOTE_ONLY_SECTIONS = {"projects", "talks"}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown on H1 headings. Returns [(heading, body), ...]."""
    parts = re.split(r"^# (.+)$", text, flags=re.MULTILINE)
    # parts[0] is pre-first-heading content (ignored)
    sections = []
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections.append((heading, body))
    return sections


def parse_experience_entry(h2_line: str, body_lines: list[str]) -> dict | None:
    """
    Parse:  ## Title | Organisation | YYYY-MM-DD - YYYY-MM-DD
    Optional body lines:
        Description: some text
        URL: https://...
    Trailing '-' means current position (no end date).
    """
    m = re.match(
        r"^##\s+(.+?)\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2}|\s*)$",
        h2_line,
    )
    if not m:
        return None

    title, org, date_start, date_end = m.group(1), m.group(2), m.group(3), m.group(4).strip()
    description = ""
    url = ""
    for line in body_lines:
        if line.lower().startswith("description:"):
            description = line.split(":", 1)[1].strip()
        elif line.lower().startswith("url:"):
            url = line.split(":", 1)[1].strip()

    return {
        "title": title.strip(),
        "company": org.strip(),
        "url": url,
        "date_start": date_start,
        "date_end": date_end,
        "description": description,
    }


def _toml_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _yaml_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Section writers
# ---------------------------------------------------------------------------

def write_about(body: str) -> None:
    lines = body.splitlines()

    role = ""
    organisation = ""
    bio_lines = []
    interests: list[str] = []
    education: list[tuple[str, str, str]] = []  # (course, institution, year)

    mode = "bio"
    for line in lines:
        stripped = line.strip()

        # Detect field-value pairs at the top
        if stripped.lower().startswith("**role:**"):
            role = re.sub(r"\*\*role:\*\*\s*", "", stripped, flags=re.IGNORECASE).strip()
            continue
        if stripped.lower().startswith("**organisation:**"):
            organisation = re.sub(r"\*\*organisation:\*\*\s*", "", stripped, flags=re.IGNORECASE).strip()
            continue
        if stripped.lower().startswith("**interests:**"):
            mode = "interests"
            continue
        if stripped.lower().startswith("**education:**"):
            mode = "education"
            continue

        if mode == "interests":
            if stripped.startswith("- "):
                interests.append(stripped[2:].strip())
        elif mode == "education":
            if stripped.startswith("- "):
                # Format: Course | Institution | Year  OR  Course | Year
                parts = [p.strip() for p in stripped[2:].split("|")]
                if len(parts) == 3:
                    education.append((parts[0], parts[1], parts[2]))
                elif len(parts) == 2:
                    education.append((parts[0], "", parts[1]))
                else:
                    education.append((parts[0], "", ""))
        elif mode == "bio":
            if stripped and not stripped.startswith("**"):
                bio_lines.append(stripped)

    bio_text = " ".join(bio_lines).strip()

    # Build YAML for interests
    interests_yaml = "\n".join(f"- {i}" for i in interests) if interests else "- Gastroenterology"

    # Build YAML for education
    edu_yaml_parts = []
    for course, institution, year in education:
        edu_yaml_parts.append(f"  - course: {course}")
        if institution:
            edu_yaml_parts.append(f"    institution: {institution}")
        if year:
            edu_yaml_parts.append(f"    year: {year}")
    edu_yaml = "\n".join(edu_yaml_parts)

    org_entry = f"- name: {organisation}\n  url: \"\"" if organisation else ""

    content = f"""---
title: Sebastian Zeki
authors:
- admin
superuser: true
role: {role}
organizations:
{org_entry}
bio: {bio_text}
interests:
{interests_yaml}
education:
  courses:
{edu_yaml}
social:
- icon: twitter
  icon_pack: fab
  link: https://twitter.com/gastroDS
- icon: google-scholar
  icon_pack: ai
  link: https://scholar.google.co.uk/citations?user=bNKITLsAAAAJ
- icon: github
  icon_pack: fab
  link: https://github.com/sebastiz
- icon: researchgate
  icon_pack: ai
  link: https://www.researchgate.net/profile/Sebastian_Zeki
email: ""
user_groups:
- Researchers
- Visitors
---

{bio_text}
"""

    path = REPO / "content" / "authors" / "admin" / "_index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO)}")


def write_experience(body: str) -> None:
    lines = body.splitlines()

    # Split into H2 blocks
    entries = []
    current_h2 = None
    current_body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_h2:
                entry = parse_experience_entry(current_h2, current_body)
                if entry:
                    entries.append(entry)
            current_h2 = line
            current_body = []
        else:
            if current_h2:
                current_body.append(line)
    if current_h2:
        entry = parse_experience_entry(current_h2, current_body)
        if entry:
            entries.append(entry)

    blocks = []
    for e in entries:
        desc_toml = f'  description = """{e["description"]}"""' if e["description"] else '  description = ""'
        date_end_line = f'  date_end = "{e["date_end"]}"' if e["date_end"] else "  # date_end = \"\"  # leave empty = current role"
        blocks.append(
            f"""[[experience]]
  title = "{_toml_str(e['title'])}"
  company = "{_toml_str(e['company'])}"
  company_url = "{e['url']}"
  location = "London"
  date_start = "{e['date_start']}"
{date_end_line}
{desc_toml}
"""
        )

    content = (
        "+++\n"
        'widget = "experience"\n'
        "headless = true\n"
        "active = true\n"
        "weight = 40\n\n"
        'title = "Experience"\n'
        'subtitle = ""\n'
        'date_format = "Jan 2006"\n\n'
        + "\n".join(blocks)
        + "+++\n"
    )

    path = REPO / "content" / "home" / "experience.md"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO)}")


def write_skills(body: str) -> None:
    # Convert markdown link syntax to HTML for the button, keep rest as-is
    # Replace [text](url) with an HTML anchor for the commercial site
    html_body = re.sub(
        r"\[([^\]]+)\]\((https?://[^\)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        body,
    )

    content = f"""+++
widget = "blank"
headless = true
active = true
weight = 50

title = "Skills"
subtitle = ""

[design]
  columns = "1"

[design.background]
  color = "white"

[advanced]
 css_style = ""
 css_class = ""
+++

{html_body}

<div style="text-align:center; margin-top:1.5rem;">
  <a href="https://www.sebastianzeki.co.uk" target="_blank" rel="noopener"
     style="display:inline-block; padding:0.75rem 2rem; background:#2962ff; color:#fff;
            border-radius:4px; font-size:1.1rem; text-decoration:none; font-weight:600;">
    Visit sebastianzeki.co.uk &rarr;
  </a>
</div>
"""
    path = REPO / "content" / "home" / "skills.md"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO)}")


def write_custom_section(heading: str, body: str, weight: int) -> None:
    """Create a new blank widget section for any unrecognised heading."""
    slug = re.sub(r"[^\w]+", "-", heading.lower()).strip("-")
    path = REPO / "content" / "home" / f"custom_{slug}.md"

    content = f"""+++
widget = "blank"
headless = true
active = true
weight = {weight}

title = "{_toml_str(heading)}"
subtitle = ""

[design]
  columns = "1"

[advanced]
 css_style = ""
 css_class = ""
+++

{body}
"""
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO)}  [new custom section]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not CONTENT_FILE.exists():
        print(f"ERROR: {CONTENT_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    text = CONTENT_FILE.read_text(encoding="utf-8")
    sections = parse_sections(text)

    if not sections:
        print("No H1 sections found in site_content.md — nothing to do.")
        return

    print(f"=== build_from_content: {len(sections)} sections found ===\n")

    # Custom sections start after the last known widget weight
    custom_weight = 120

    for heading, body in sections:
        key = heading.lower().strip()

        if key == "about":
            print(f"[About]")
            write_about(body)

        elif key == "experience":
            print(f"[Experience]")
            write_experience(body)

        elif key == "skills":
            print(f"[Skills]")
            write_skills(body)

        elif any(key.startswith(s) for s in AUTO_SECTIONS):
            print(f"[{heading}] — auto-managed by ORCID script, skipping.")

        elif any(key.startswith(s) for s in NOTE_ONLY_SECTIONS):
            print(f"[{heading}] — managed per-file in content/, skipping.")

        else:
            print(f"[{heading}] — creating custom section (weight={custom_weight})")
            write_custom_section(heading, body, custom_weight)
            custom_weight += 10

    print("\nDone.")


if __name__ == "__main__":
    main()
