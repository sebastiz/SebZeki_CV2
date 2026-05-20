#!/usr/bin/env python3
"""
Fetches works and funding from ORCID for Sebastian Zeki (0000-0003-1673-2663)
and generates Hugo Academic content files.

Run manually:  python scripts/update_from_orcid.py
Auto-run:      GitHub Actions (.github/workflows/update_orcid.yml) runs this daily.
"""

import re
import sys
import requests
from pathlib import Path

ORCID_ID = "0000-0003-1673-2663"
BASE_URL = f"https://pub.orcid.org/v3.0/{ORCID_ID}"
HEADERS = {"Accept": "application/json"}

# Repo root is one level up from scripts/
REPO_ROOT = Path(__file__).parent.parent

# Number of most-recent works (with DOIs) to mark as "featured"
FEATURED_COUNT = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:60]


def _str(obj) -> str:
    """Safely extract a string value from an ORCID value-object."""
    if isinstance(obj, dict):
        return obj.get("value", "") or ""
    return str(obj) if obj else ""


def _zpad(val: str, width: int = 2) -> str:
    return val.zfill(width) if val else "01"


def map_work_type(orcid_type: str) -> str:
    """Map ORCID work type to Hugo Academic publication_type integer."""
    mapping = {
        "JOURNAL_ARTICLE": "2",
        "journal-article": "2",
        "CONFERENCE_PAPER": "1",
        "conference-paper": "1",
        "BOOK": "5",
        "book": "5",
        "BOOK_CHAPTER": "6",
        "book-chapter": "6",
        "PREPRINT": "3",
        "preprint": "3",
        "REPORT": "4",
        "report": "4",
        "DISSERTATION": "7",
        "dissertation": "7",
        "WORKING_PAPER": "3",
        "SUPERVISED_STUDENT_PUBLICATION": "2",
    }
    return mapping.get(orcid_type, "2")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_works():
    """Return a list of work dicts, deduplicated and sorted newest-first."""
    r = requests.get(f"{BASE_URL}/works", headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    works = []
    seen_titles: set[str] = set()

    for group in data.get("group", []):
        summaries = group.get("work-summary", [])
        if not summaries:
            continue

        # Prefer summaries from Crossref or Scopus over self-submitted
        best = summaries[0]
        for s in summaries:
            source_name = _str(
                (s.get("source") or {}).get("source-name")
            ).lower()
            if "crossref" in source_name or "scopus" in source_name:
                best = s
                break

        title = _str((best.get("title") or {}).get("title"))
        if not title:
            continue

        # Normalise title for deduplication (strip punctuation differences)
        norm = re.sub(r"[^\w\s]", "", title.lower())
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Date
        pub_date = best.get("publication-date") or {}
        year = _str(pub_date.get("year"))
        month = _str(pub_date.get("month")) or "01"
        day = _str(pub_date.get("day")) or "01"
        date_str = (
            f"{year}-{_zpad(month)}-{_zpad(day)}" if year else "2000-01-01"
        )

        # Journal
        journal = _str(best.get("journal-title"))

        # DOI
        doi = ""
        for eid in (best.get("external-ids") or {}).get("external-id", []):
            if eid.get("external-id-type") == "doi":
                doi = eid.get("external-id-value", "") or ""
                break

        works.append(
            {
                "title": title,
                "date": date_str,
                "year": year,
                "journal": journal,
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else "",
                "type": best.get("type", "JOURNAL_ARTICLE"),
            }
        )

    works.sort(key=lambda w: w["date"], reverse=True)
    return works


def fetch_fundings():
    """Return a list of funding dicts, sorted newest-first."""
    r = requests.get(f"{BASE_URL}/fundings", headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    fundings = []
    for group in data.get("group", []):
        summaries = group.get("funding-summary", [])
        if not summaries:
            continue
        s = summaries[0]

        title = _str(((s.get("title") or {}).get("title") or {}))
        org = _str((s.get("organization") or {}).get("name"))

        start = s.get("start-date") or {}
        end = s.get("end-date") or {}

        sy = _str(start.get("year"))
        sm = _str(start.get("month")) or "01"
        ey = _str(end.get("year"))
        em = _str(end.get("month")) or "01"

        date_start = f"{sy}-{_zpad(sm)}-01" if sy else ""
        date_end = f"{ey}-{_zpad(em)}-01" if ey else ""

        fundings.append(
            {
                "title": title,
                "organization": org,
                "date_start": date_start,
                "date_end": date_end,
                "type": (s.get("type") or "Grant").replace("_", " ").title(),
            }
        )

    fundings.sort(key=lambda f: f["date_start"], reverse=True)
    return fundings


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _q(text: str) -> str:
    """Escape a string for use inside YAML double-quoted scalars."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def create_publication_file(work: dict, featured: bool = False) -> str:
    slug = f"orcid_{slugify(work['title'])}"
    pub_dir = REPO_ROOT / "content" / "publication" / slug
    pub_dir.mkdir(parents=True, exist_ok=True)

    pub_type = map_work_type(work["type"])

    content = f"""---
title: "{_q(work['title'])}"
authors:
- Sebastian Zeki
date: "{work['date']}T00:00:00Z"
doi: "{work['doi']}"
publication: "*{_q(work['journal'])}*"
publication_short: ""
publication_types:
- "{pub_type}"
abstract: ""
featured: {str(featured).lower()}
tags: []
url_pdf: ""
url_source: "{work['url']}"
---
"""
    (pub_dir / "index.md").write_text(content, encoding="utf-8")
    return slug


def update_funding_widget(fundings: list) -> None:
    items = []
    for f in fundings:
        items.append(
            f"""
[[item]]
  title = "{_q(f['title'])}"
  organization = "{_q(f['organization'])}"
  organization_url = ""
  date_start = "{f['date_start']}"
  date_end = "{f['date_end']}"
  description = "{f['type']}"
  certificate_url = ""
  url = ""
"""
        )

    content = (
        "+++\n"
        "# Funding — auto-generated from ORCID. Do not edit manually.\n"
        'widget = "accomplishments"\n'
        "headless = true\n"
        "active = true\n"
        "weight = 90\n\n"
        'title = "Funding"\n'
        'subtitle = "Research grants and awards"\n\n'
        'date_format = "Jan 2006"\n'
        + "".join(items)
        + "+++\n"
    )

    path = REPO_ROOT / "content" / "home" / "accomplishments.md"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== ORCID → Hugo Academic updater ===")

    print("\n[1/2] Fetching works…")
    works = fetch_works()
    print(f"      {len(works)} unique works found")

    featured_so_far = 0
    for work in works:
        mark_featured = featured_so_far < FEATURED_COUNT and bool(work["doi"])
        if mark_featured:
            featured_so_far += 1
        create_publication_file(work, featured=mark_featured)

    print(f"      {len(works)} publication files written ({featured_so_far} marked featured)")

    print("\n[2/2] Fetching fundings…")
    fundings = fetch_fundings()
    print(f"      {len(fundings)} funding entries found")
    update_funding_widget(fundings)

    print("\nDone.")


if __name__ == "__main__":
    main()
