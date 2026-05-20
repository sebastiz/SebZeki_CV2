#!/usr/bin/env python3
"""
Fetches works and funding from ORCID for Sebastian Zeki (0000-0003-1673-2663)
and generates Hugo Academic content files.

Full author lists are resolved in priority order:
  1. CrossRef (for any work with a DOI) — most complete
  2. ORCID full-work record (put-code endpoint) — fallback for non-DOI works

Run manually:  python scripts/update_from_orcid.py
Auto-run:      GitHub Actions (.github/workflows/update_orcid.yml) runs this daily.
"""

import re
import time
import requests
from pathlib import Path

ORCID_ID   = "0000-0003-1673-2663"
BASE_URL   = f"https://pub.orcid.org/v3.0/{ORCID_ID}"
ORCID_HDR  = {"Accept": "application/json"}
# CrossRef asks for a polite User-Agent with contact info
CROSSREF_HDR = {
    "User-Agent": "SebZekiCV/1.0 (https://github.com/sebastiz/SebZeki_CV2; mailto:s.zeki@gstt.nhs.uk)"
}

REPO_ROOT     = Path(__file__).parent.parent
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
    if isinstance(obj, dict):
        return obj.get("value", "") or ""
    return str(obj) if obj else ""


def _zpad(val: str, width: int = 2) -> str:
    return val.zfill(width) if val else "01"


def _q(text: str) -> str:
    """Escape for YAML double-quoted scalars."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def map_work_type(orcid_type: str) -> str:
    mapping = {
        "JOURNAL_ARTICLE": "2", "journal-article": "2",
        "CONFERENCE_PAPER": "1", "conference-paper": "1",
        "BOOK": "5", "book": "5",
        "BOOK_CHAPTER": "6", "book-chapter": "6",
        "PREPRINT": "3", "preprint": "3",
        "REPORT": "4", "report": "4",
        "DISSERTATION": "7", "dissertation": "7",
        "WORKING_PAPER": "3",
        "SUPERVISED_STUDENT_PUBLICATION": "2",
    }
    return mapping.get(orcid_type, "2")


def format_authors(authors: list[str], max_before_et_al: int = 6) -> str:
    """Return 'A, B, C et al.' style string."""
    if not authors:
        return "Zeki S"
    if len(authors) <= max_before_et_al:
        return ", ".join(authors)
    return ", ".join(authors[:max_before_et_al]) + " et al."


# ---------------------------------------------------------------------------
# Author resolution
# ---------------------------------------------------------------------------

def authors_from_crossref(doi: str) -> list[str]:
    """
    Query CrossRef for a DOI and return a list of 'Surname I' formatted authors.
    Returns [] on any failure.
    """
    if not doi:
        return []
    url = f"https://api.crossref.org/works/{doi.strip()}"
    try:
        r = requests.get(url, headers=CROSSREF_HDR, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json().get("message", {})
        raw_authors = data.get("author", [])
        authors = []
        for a in raw_authors:
            family = a.get("family", "").strip()
            given  = a.get("given", "").strip()
            if family:
                initials = "".join(p[0] for p in given.split() if p) if given else ""
                authors.append(f"{family} {initials}".strip())
        return authors
    except Exception:
        return []


def authors_from_orcid_work(put_code: str) -> list[str]:
    """
    Fetch the full ORCID work record by put-code and extract contributors.
    Returns [] on any failure.
    """
    if not put_code:
        return []
    url = f"{BASE_URL}/work/{put_code}"
    try:
        r = requests.get(url, headers=ORCID_HDR, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        contributors = (
            (data.get("contributors") or {}).get("contributor") or []
        )
        authors = []
        for c in contributors:
            role = _str((c.get("contributor-attributes") or {}).get("contributor-role"))
            if role and role.upper() not in ("AUTHOR", ""):
                continue  # skip editors etc.
            cn = c.get("credit-name") or {}
            name = _str(cn).strip()
            if name:
                authors.append(name)
        return authors
    except Exception:
        return []


def crossref_extra(doi: str) -> dict:
    """
    Fetch volume, issue, pages, and full journal name from CrossRef.
    Returns a dict with keys: volume, issue, pages, journal (may be empty strings).
    """
    result = {"volume": "", "issue": "", "pages": "", "journal": ""}
    if not doi:
        return result
    url = f"https://api.crossref.org/works/{doi.strip()}"
    try:
        r = requests.get(url, headers=CROSSREF_HDR, timeout=15)
        if r.status_code != 200:
            return result
        msg = r.json().get("message", {})
        result["volume"] = msg.get("volume", "") or ""
        result["issue"]  = msg.get("issue",  "") or ""
        result["pages"]  = msg.get("page",   "") or ""
        titles = msg.get("container-title", [])
        result["journal"] = titles[0] if titles else ""
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# ORCID works fetcher
# ---------------------------------------------------------------------------

def fetch_works() -> list[dict]:
    """Return deduplicated works sorted newest-first, with full author lists."""
    r = requests.get(f"{BASE_URL}/works", headers=ORCID_HDR, timeout=30)
    r.raise_for_status()
    data = r.json()

    works      = []
    seen_titles: set[str] = set()
    total      = len(data.get("group", []))

    for idx, group in enumerate(data.get("group", []), 1):
        summaries = group.get("work-summary", [])
        if not summaries:
            continue

        # Prefer Crossref/Scopus summary
        best = summaries[0]
        best_put_code = str(best.get("put-code", ""))
        for s in summaries:
            src = _str((s.get("source") or {}).get("source-name")).lower()
            if "crossref" in src or "scopus" in src:
                best = s
                best_put_code = str(s.get("put-code", ""))
                break

        title = _str((best.get("title") or {}).get("title"))
        if not title:
            continue

        norm = re.sub(r"[^\w\s]", "", title.lower())
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Date
        pub_date = best.get("publication-date") or {}
        year  = _str(pub_date.get("year"))
        month = _str(pub_date.get("month")) or "01"
        day   = _str(pub_date.get("day"))   or "01"
        date_str = f"{year}-{_zpad(month)}-{_zpad(day)}" if year else "2000-01-01"

        # DOI
        doi = ""
        for eid in (best.get("external-ids") or {}).get("external-id", []):
            if eid.get("external-id-type") == "doi":
                doi = (eid.get("external-id-value") or "").strip()
                break

        # Journal from summary (may be improved by CrossRef below)
        journal = _str(best.get("journal-title"))

        # ---- Resolve full authors + extra metadata ----
        authors = []
        volume = issue = pages = ""

        if doi:
            authors = authors_from_crossref(doi)
            extra   = crossref_extra(doi)
            if not journal and extra["journal"]:
                journal = extra["journal"]
            elif extra["journal"]:
                journal = extra["journal"]   # prefer CrossRef journal name
            volume = extra["volume"]
            issue  = extra["issue"]
            pages  = extra["pages"]
            time.sleep(0.12)   # polite rate-limit (~8 req/s max)

        if not authors:
            authors = authors_from_orcid_work(best_put_code)
            time.sleep(0.05)

        works.append({
            "title":   title,
            "date":    date_str,
            "year":    year,
            "journal": journal,
            "doi":     doi,
            "url":     f"https://doi.org/{doi}" if doi else "",
            "type":    best.get("type", "JOURNAL_ARTICLE"),
            "authors": authors,
            "volume":  volume,
            "issue":   issue,
            "pages":   pages,
        })

        if idx % 10 == 0:
            print(f"      … processed {idx}/{total}")

    works.sort(key=lambda w: w["date"], reverse=True)
    return works


# ---------------------------------------------------------------------------
# ORCID funding fetcher
# ---------------------------------------------------------------------------

def fetch_fundings() -> list[dict]:
    r = requests.get(f"{BASE_URL}/fundings", headers=ORCID_HDR, timeout=30)
    r.raise_for_status()
    data = r.json()

    fundings = []
    for group in data.get("group", []):
        summaries = group.get("funding-summary", [])
        if not summaries:
            continue
        s = summaries[0]

        title = _str(((s.get("title") or {}).get("title") or {}))
        org   = _str((s.get("organization") or {}).get("name"))

        start = s.get("start-date") or {}
        end   = s.get("end-date")   or {}

        sy = _str(start.get("year"));  sm = _str(start.get("month")) or "01"
        ey = _str(end.get("year"));    em = _str(end.get("month"))   or "01"

        date_start = f"{sy}-{_zpad(sm)}-01" if sy else ""
        date_end   = f"{ey}-{_zpad(em)}-01" if ey else ""

        fundings.append({
            "title":        title,
            "organization": org,
            "date_start":   date_start,
            "date_end":     date_end,
            "type":         (s.get("type") or "Grant").replace("_", " ").title(),
        })

    fundings.sort(key=lambda f: f["date_start"], reverse=True)
    return fundings


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def create_publication_file(work: dict, featured: bool = False) -> None:
    slug    = f"orcid_{slugify(work['title'])}"
    pub_dir = REPO_ROOT / "content" / "publication" / slug
    pub_dir.mkdir(parents=True, exist_ok=True)

    pub_type = map_work_type(work["type"])

    # Build authors YAML list
    authors = work.get("authors") or ["Sebastian Zeki"]
    authors_yaml = "\n".join(f"- {_q(a)}" for a in authors)

    # Build citation string for display (volume/issue/pages)
    journal = work["journal"]
    vol_str = ""
    if work.get("volume"):
        vol_str = f", {work['volume']}"
        if work.get("issue"):
            vol_str += f"({work['issue']})"
        if work.get("pages"):
            vol_str += f":{work['pages']}"

    publication_str = f"*{_q(journal)}*{_q(vol_str)}" if journal else ""

    content = f"""---
title: "{_q(work['title'])}"
authors:
{authors_yaml}
date: "{work['date']}T00:00:00Z"
doi: "{work['doi']}"
publication: "{publication_str}"
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


def update_funding_widget(fundings: list) -> None:
    items = []
    for f in fundings:
        items.append(f"""
[[item]]
  title = "{_q(f['title'])}"
  organization = "{_q(f['organization'])}"
  organization_url = ""
  date_start = "{f['date_start']}"
  date_end = "{f['date_end']}"
  description = "{f['type']}"
  certificate_url = ""
  url = ""
""")

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
    print(f"  Wrote {path.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== ORCID → Hugo Academic updater ===")
    print("    (fetching full author lists from CrossRef — this takes ~2 min)")

    print("\n[1/2] Fetching works + resolving authors…")
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
