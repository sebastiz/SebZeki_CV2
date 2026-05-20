#!/usr/bin/env python3
"""
Reads site_content.md and generates Hugo Academic content files.
Also generates static/cv/index.html — a print-ready medical CV.

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
from datetime import date

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


def parse_about(body: str) -> dict:
    """Parse the About section into structured fields."""
    lines = body.splitlines()
    role = ""
    organisation = ""
    bio_lines = []
    interests: list[str] = []
    education: list[tuple[str, str, str]] = []
    mode = "bio"

    for line in lines:
        stripped = line.strip()
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

    return {
        "role": role,
        "organisation": organisation,
        "bio": " ".join(bio_lines).strip(),
        "interests": interests,
        "education": education,
    }


def parse_experience_entries(body: str) -> list[dict]:
    lines = body.splitlines()
    entries = []
    current_h2 = None
    current_body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_h2:
                e = parse_experience_entry(current_h2, current_body)
                if e:
                    entries.append(e)
            current_h2 = line
            current_body = []
        else:
            if current_h2:
                current_body.append(line)
    if current_h2:
        e = parse_experience_entry(current_h2, current_body)
        if e:
            entries.append(e)
    return entries


def _toml_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _fmt_date(d: str) -> str:
    """Format YYYY-MM-DD to 'Month YYYY' for display."""
    if not d:
        return "Present"
    try:
        y, m, _ = d.split("-")
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{months[int(m)-1]} {y}"
    except Exception:
        return d


def _h(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# ORCID data readers (reads generated files, no network call)
# ---------------------------------------------------------------------------

def read_publications() -> list[dict]:
    """Read all orcid_* publication index.md files and return sorted list."""
    pubs = []
    pub_dir = REPO / "content" / "publication"
    for folder in sorted(pub_dir.glob("orcid_*")):
        index = folder / "index.md"
        if not index.exists():
            continue
        text = index.read_text(encoding="utf-8")
        # Parse YAML frontmatter between --- markers
        fm_match = re.search(r"^---\n(.+?)\n---", text, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)

        def _yaml_val(key: str) -> str:
            m = re.search(rf'^{key}:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
            return m.group(1).strip().strip('"') if m else ""

        featured = "featured: true" in fm
        pubs.append({
            "title": _yaml_val("title"),
            "date": _yaml_val("date")[:10],
            "doi": _yaml_val("doi"),
            "publication": _yaml_val("publication").strip("*"),
            "url": _yaml_val("url_source"),
            "featured": featured,
        })

    pubs.sort(key=lambda p: p["date"], reverse=True)
    return pubs


def read_fundings() -> list[dict]:
    """Read funding entries from the generated accomplishments.md."""
    path = REPO / "content" / "home" / "accomplishments.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    fundings = []
    for block in re.finditer(
        r'\[\[item\]\](.*?)(?=\[\[item\]\]|\+\+\+\s*$)', text, re.DOTALL
    ):
        chunk = block.group(1)
        def _val(key):
            m = re.search(rf'{key}\s*=\s*"([^"]*)"', chunk)
            return m.group(1) if m else ""
        fundings.append({
            "title": _val("title"),
            "organization": _val("organization"),
            "date_start": _val("date_start"),
            "date_end": _val("date_end"),
            "type": _val("description"),
        })
    return fundings


def read_talks() -> list[dict]:
    """Read talk index.md files."""
    talks = []
    talk_dir = REPO / "content" / "talk"
    for folder in sorted(talk_dir.iterdir()):
        index = folder / "index.md"
        if not index.exists():
            continue
        text = index.read_text(encoding="utf-8")
        fm_match = re.search(r"^---\n(.+?)\n---", text, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)
        def _yaml_val(key):
            m = re.search(rf'^{key}:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
            return m.group(1).strip().strip('"') if m else ""
        title = _yaml_val("title")
        event = _yaml_val("event")
        dt = _yaml_val("date")[:10] if _yaml_val("date") else ""
        if title:
            talks.append({"title": title, "event": event, "date": dt})
    talks.sort(key=lambda t: t["date"], reverse=True)
    return talks


# ---------------------------------------------------------------------------
# CV HTML generator
# ---------------------------------------------------------------------------

CV_CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    color: #1a1a1a;
    background: #f4f4f4;
    padding: 2rem 1rem;
  }

  .cv-page {
    background: #fff;
    max-width: 820px;
    margin: 0 auto;
    padding: 3cm 2.5cm 3cm 2.5cm;
    box-shadow: 0 2px 24px rgba(0,0,0,0.10);
  }

  /* Print button — hidden when printing */
  .print-bar {
    max-width: 820px;
    margin: 0 auto 1.5rem auto;
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
  }
  .print-bar button {
    font-family: -apple-system, sans-serif;
    font-size: 0.95rem;
    padding: 0.5rem 1.5rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-print { background: #1a237e; color: #fff; }
  .btn-back  { background: #e0e0e0; color: #333; text-decoration: none;
               display: inline-flex; align-items: center;
               padding: 0.5rem 1.5rem; border-radius: 4px; font-weight: 600;
               font-family: -apple-system, sans-serif; font-size: 0.95rem; }

  /* ---- Header ---- */
  .cv-header { text-align: center; border-bottom: 2.5px solid #1a237e; padding-bottom: 1.2rem; margin-bottom: 1.8rem; }
  .cv-header h1 { font-size: 26pt; font-weight: bold; letter-spacing: 1px; color: #1a237e; }
  .cv-header .role { font-size: 13pt; color: #444; margin-top: 0.3rem; }
  .cv-header .org  { font-size: 11pt; color: #666; margin-top: 0.15rem; }
  .cv-header .links { margin-top: 0.6rem; font-size: 9.5pt; color: #555; }
  .cv-header .links a { color: #1a237e; text-decoration: none; margin: 0 0.4rem; }

  /* ---- Sections ---- */
  .cv-section { margin-bottom: 1.8rem; }
  .cv-section h2 {
    font-size: 12pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #1a237e;
    border-bottom: 1px solid #c5cae9;
    padding-bottom: 0.25rem;
    margin-bottom: 0.8rem;
  }

  /* Biography */
  .bio-text { line-height: 1.6; }

  /* Interests two-column */
  .interests-list {
    columns: 2;
    column-gap: 2rem;
    list-style: disc;
    padding-left: 1.2rem;
    line-height: 1.7;
  }

  /* Education table */
  .edu-table { width: 100%; border-collapse: collapse; }
  .edu-table td { padding: 0.2rem 0.4rem; vertical-align: top; }
  .edu-table td:first-child { font-weight: bold; width: 55%; }
  .edu-table td:last-child  { color: #555; text-align: right; white-space: nowrap; }

  /* Experience */
  .exp-entry { margin-bottom: 0.9rem; }
  .exp-header { display: flex; justify-content: space-between; align-items: baseline; }
  .exp-title  { font-weight: bold; }
  .exp-dates  { font-size: 9.5pt; color: #666; white-space: nowrap; margin-left: 1rem; }
  .exp-org    { color: #444; font-style: italic; font-size: 10pt; }
  .exp-desc   { margin-top: 0.2rem; font-size: 10pt; color: #333; }

  /* Publications */
  .pub-entry  { margin-bottom: 0.65rem; padding-left: 1rem; border-left: 3px solid #c5cae9; }
  .pub-title  { font-weight: bold; font-size: 10.5pt; }
  .pub-title a { color: #1a237e; text-decoration: none; }
  .pub-title a:hover { text-decoration: underline; }
  .pub-meta   { font-size: 9.5pt; color: #555; margin-top: 0.1rem; }

  /* Funding */
  .fund-entry { margin-bottom: 0.75rem; }
  .fund-header { display: flex; justify-content: space-between; }
  .fund-title  { font-weight: bold; font-size: 10.5pt; }
  .fund-org    { font-style: italic; color: #555; font-size: 10pt; }
  .fund-dates  { font-size: 9.5pt; color: #666; white-space: nowrap; margin-left: 1rem; }
  .fund-type   { font-size: 9.5pt; color: #888; }

  /* Talks */
  .talk-entry { margin-bottom: 0.55rem; display: flex; justify-content: space-between; }
  .talk-title { font-size: 10.5pt; }
  .talk-date  { font-size: 9.5pt; color: #666; white-space: nowrap; margin-left: 1rem; }

  /* Custom sections */
  .custom-body { line-height: 1.7; }
  .custom-body ul { padding-left: 1.2rem; }
  .custom-body li { margin-bottom: 0.2rem; }

  /* Footer */
  .cv-footer { text-align: center; margin-top: 2rem; font-size: 9pt; color: #aaa; border-top: 1px solid #eee; padding-top: 0.8rem; }

  /* ===== PRINT STYLES ===== */
  @media print {
    body { background: #fff; padding: 0; }
    .print-bar { display: none !important; }
    .cv-page { box-shadow: none; max-width: 100%; padding: 1.5cm 1.8cm; }
    a { color: #1a237e !important; }
    .cv-section { page-break-inside: avoid; }
    .pub-entry  { page-break-inside: avoid; }
    .exp-entry  { page-break-inside: avoid; }
  }
"""


def _md_to_html_simple(text: str) -> str:
    """Convert a small subset of markdown to HTML for the custom sections."""
    lines = text.splitlines()
    out = []
    in_ul = False
    for line in lines:
        if line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"  <li>{_h(line[2:])}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if line.strip():
                out.append(f"<p>{_h(line)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def generate_cv_html(about: dict, experience: list[dict],
                     publications: list[dict], fundings: list[dict],
                     talks: list[dict], custom_sections: list[tuple[str, str]]) -> str:

    today = date.today().strftime("%-d %B %Y")

    # ---- Header ----
    header = f"""
    <div class="cv-header">
      <h1>{_h("Sebastian Zeki")}</h1>
      <div class="role">{_h(about.get('role', ''))}</div>
      <div class="org">{_h(about.get('organisation', ''))}</div>
      <div class="links">
        <a href="https://orcid.org/0000-0003-1673-2663">ORCID</a> &middot;
        <a href="https://scholar.google.co.uk/citations?user=bNKITLsAAAAJ">Google Scholar</a> &middot;
        <a href="https://github.com/sebastiz">GitHub</a> &middot;
        <a href="https://www.sebastianzeki.co.uk">sebastianzeki.co.uk</a>
      </div>
    </div>"""

    # ---- Biography ----
    bio_html = f"""
    <div class="cv-section">
      <h2>Biography</h2>
      <p class="bio-text">{_h(about.get('bio', ''))}</p>
    </div>"""

    # ---- Interests ----
    interests = about.get("interests", [])
    if interests:
        items = "".join(f"<li>{_h(i)}</li>" for i in interests)
        interests_html = f"""
    <div class="cv-section">
      <h2>Research &amp; Clinical Interests</h2>
      <ul class="interests-list">{items}</ul>
    </div>"""
    else:
        interests_html = ""

    # ---- Education ----
    education = about.get("education", [])
    if education:
        rows = ""
        for course, institution, year in education:
            inst_yr = f"{institution}, {year}" if institution else year
            rows += f"<tr><td>{_h(course)}</td><td>{_h(inst_yr)}</td></tr>"
        edu_html = f"""
    <div class="cv-section">
      <h2>Education &amp; Qualifications</h2>
      <table class="edu-table"><tbody>{rows}</tbody></table>
    </div>"""
    else:
        edu_html = ""

    # ---- Experience ----
    if experience:
        entries_html = ""
        for e in experience:
            dates = _fmt_date(e["date_start"]) + " – " + (
                _fmt_date(e["date_end"]) if e["date_end"] else "Present")
            desc = f'<div class="exp-desc">{_h(e["description"])}</div>' if e["description"] else ""
            entries_html += f"""
        <div class="exp-entry">
          <div class="exp-header">
            <span class="exp-title">{_h(e['title'])}</span>
            <span class="exp-dates">{dates}</span>
          </div>
          <div class="exp-org">{_h(e['company'])}</div>
          {desc}
        </div>"""
        exp_html = f"""
    <div class="cv-section">
      <h2>Experience</h2>
      {entries_html}
    </div>"""
    else:
        exp_html = ""

    # ---- Publications (all, sorted newest first) ----
    if publications:
        pubs_html_items = ""
        for p in publications:
            year = p["date"][:4] if p["date"] else ""
            journal = p["publication"].strip("*")
            doi_link = (f'<a href="{_h(p["url"])}" target="_blank">{_h(p["title"])}</a>'
                        if p["url"] else _h(p["title"]))
            pubs_html_items += f"""
        <div class="pub-entry">
          <div class="pub-title">{doi_link}</div>
          <div class="pub-meta"><em>{_h(journal)}</em>{(', ' + year) if year else ''}</div>
        </div>"""
        pubs_html = f"""
    <div class="cv-section">
      <h2>Publications</h2>
      {pubs_html_items}
    </div>"""
    else:
        pubs_html = ""

    # ---- Funding ----
    if fundings:
        fund_items = ""
        for f in fundings:
            dates = _fmt_date(f["date_start"]) + " – " + (
                _fmt_date(f["date_end"]) if f["date_end"] else "Present")
            fund_items += f"""
        <div class="fund-entry">
          <div class="fund-header">
            <span class="fund-title">{_h(f['title'])}</span>
            <span class="fund-dates">{dates}</span>
          </div>
          <div class="fund-org">{_h(f['organization'])}</div>
          <div class="fund-type">{_h(f['type'])}</div>
        </div>"""
        fund_html = f"""
    <div class="cv-section">
      <h2>Grants &amp; Funding</h2>
      {fund_items}
    </div>"""
    else:
        fund_html = ""

    # ---- Talks ----
    if talks:
        talk_items = ""
        for t in talks:
            talk_items += f"""
        <div class="talk-entry">
          <span class="talk-title">{_h(t['title'])}</span>
          <span class="talk-date">{_fmt_date(t['date'])}</span>
        </div>"""
        talks_html = f"""
    <div class="cv-section">
      <h2>Talks &amp; Presentations</h2>
      {talk_items}
    </div>"""
    else:
        talks_html = ""

    # ---- Custom sections ----
    custom_html = ""
    for heading, body in custom_sections:
        custom_html += f"""
    <div class="cv-section">
      <h2>{_h(heading)}</h2>
      <div class="custom-body">{_md_to_html_simple(body)}</div>
    </div>"""

    # ---- Footer ----
    footer = f"""
    <div class="cv-footer">
      Generated {today} &middot; Auto-updated from <a href="https://orcid.org/0000-0003-1673-2663">ORCID</a>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CV — Sebastian Zeki</title>
  <style>{CV_CSS}</style>
</head>
<body>
  <div class="print-bar">
    <a class="btn-back" href="/">&larr; Back to site</a>
    <button class="btn-print" onclick="window.print()">&#128438; Print / Save PDF</button>
  </div>
  <div class="cv-page">
    {header}
    {bio_html}
    {interests_html}
    {edu_html}
    {exp_html}
    {fund_html}
    {pubs_html}
    {talks_html}
    {custom_html}
    {footer}
  </div>
</body>
</html>
"""


def write_cv_html(about: dict, experience: list[dict], custom_sections: list[tuple[str, str]]) -> None:
    publications = read_publications()
    fundings = read_fundings()
    talks = read_talks()

    html = generate_cv_html(about, experience, publications, fundings, talks, custom_sections)

    out_dir = REPO / "static" / "cv"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.relative_to(REPO)}  ({len(publications)} pubs, {len(fundings)} grants, {len(talks)} talks)")


# ---------------------------------------------------------------------------
# Hugo section writers
# ---------------------------------------------------------------------------

def write_about(body: str) -> dict:
    about = parse_about(body)
    role = about["role"]
    organisation = about["organisation"]
    bio_text = about["bio"]
    interests = about["interests"]
    education = about["education"]

    interests_yaml = "\n".join(f"- {i}" for i in interests) if interests else "- Gastroenterology"

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
    return about


def write_experience(body: str) -> list[dict]:
    entries = parse_experience_entries(body)

    blocks = []
    for e in entries:
        desc_toml = f'  description = """{e["description"]}"""' if e["description"] else '  description = ""'
        date_end_line = (f'  date_end = "{e["date_end"]}"' if e["date_end"]
                         else '  # date_end = ""  # leave empty = current role')
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
    return entries


def write_skills(body: str) -> None:
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


def write_print_cv_button() -> None:
    """Add a 'Print CV' button widget at the very bottom of the home page."""
    content = """+++
widget = "blank"
headless = true
active = true
weight = 200

title = ""
subtitle = ""

[design]
  columns = "1"

[design.background]
  color = "#f8f8f8"

[advanced]
 css_style = ""
 css_class = ""
+++

<div style="text-align:center; padding: 2rem 0 1rem;">
  <a href="/cv/"
     style="display:inline-block; padding:0.9rem 2.5rem; background:#1a237e; color:#fff;
            border-radius:4px; font-size:1.1rem; text-decoration:none; font-weight:700;
            font-family:-apple-system,sans-serif; letter-spacing:0.5px;">
    &#128438;&nbsp; Print / Download CV
  </a>
  <p style="margin-top:0.75rem; font-size:0.9rem; color:#888; font-family:-apple-system,sans-serif;">
    Opens a print-ready version of this CV &mdash; use your browser's Print or Save as PDF.
  </p>
</div>
"""
    path = REPO / "content" / "home" / "cv_button.md"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO)}")


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

    custom_weight = 120
    about_data: dict = {}
    experience_data: list[dict] = []
    custom_sections: list[tuple[str, str]] = []

    for heading, body in sections:
        key = heading.lower().strip()

        if key == "about":
            print("[About]")
            about_data = write_about(body)

        elif key == "experience":
            print("[Experience]")
            experience_data = write_experience(body)

        elif key == "skills":
            print("[Skills]")
            write_skills(body)

        elif any(key.startswith(s) for s in AUTO_SECTIONS):
            print(f"[{heading}] — auto-managed by ORCID script, skipping.")

        elif any(key.startswith(s) for s in NOTE_ONLY_SECTIONS):
            print(f"[{heading}] — managed per-file in content/, skipping.")

        else:
            print(f"[{heading}] — creating custom section (weight={custom_weight})")
            write_custom_section(heading, body, custom_weight)
            custom_sections.append((heading, body))
            custom_weight += 10

    print("\n[CV button]")
    write_print_cv_button()

    print("\n[CV HTML]")
    write_cv_html(about_data, experience_data, custom_sections)

    print("\nDone.")


if __name__ == "__main__":
    main()
