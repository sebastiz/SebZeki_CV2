#!/usr/bin/env python3
"""
Fetches works and funding from ORCID for Sebastian Zeki (0000-0003-1673-2663)
and generates Hugo Academic content files.

Full author lists are resolved in priority order:
  1. CrossRef (for any work with a DOI) — most complete
  2. ORCID full-work record (put-code endpoint) — fallback for non-DOI works

Abstracts (conference poster/oral codes), errata, and replies are excluded.
Publications are classified into one of five categories via keyword matching.
"""

import re
import time
import requests
from pathlib import Path

ORCID_ID   = "0000-0003-1673-2663"
BASE_URL   = f"https://pub.orcid.org/v3.0/{ORCID_ID}"
ORCID_HDR  = {"Accept": "application/json"}
CROSSREF_HDR = {
    "User-Agent": "SebZekiCV/1.0 (https://github.com/sebastiz/SebZeki_CV2; mailto:s.zeki@gstt.nhs.uk)"
}

REPO_ROOT      = Path(__file__).parent.parent
FEATURED_COUNT = 6

# ── Categories ───────────────────────────────────────────────────────────────
# Order matters — first match wins in categorize().
CATEGORIES = [
    "Cancer Clinical",
    "Cancer Basic Science",
    "Eosinophilic Oesophagitis",
    "Inflammatory Bowel Disease",
    "Natural Language Processing",
    "Oesophageal Physiology",
    "Endoscopy",
    "Other",
]

# Keyword sets — matched against the lowercased title via re.search.
# Cancer Clinical — staging, chemotherapy response, perioperative care, symptoms after surgery
_CANCER_CLINICAL_KW = {
    "prehabilitation",
    "pre-empt",
    "symptom response to treatment questionnaire",
    "oesophago-gastrectomy",
    "resolution of symptoms after",
    r"\brestored\b",
    "dynamic contrast-enhanced mri",
    r"fdg pet",
    "metabolic tumour",
    "lymph node regression",
    "staging investigations",
    r"laur[eé]n",
    r"flot.*magic|magic.*flot",
    "peri-operative chemotherapy regimen",
    "patient perspectives.*symptoms.*cancer",
    "patient perspectives.*follow-up.*cancer",
    r"pet.?mri.*staging|staging.*pet.?mri",
    "mandard score",
    "adjuvant therapy.*oesophagectomy",
    "circumferential resection margin",
    "neoadjuvant.*adenocarcinoma.*survival|survival.*neoadjuvant.*adenocarcinoma",
    "neoadjuvant chemotherapy.*predict",
    "neoadjuvant.*response.*survival",
    "machine learning.*recurrence.*oesophageal",
}

# Cancer Basic Science — genomics, clonal dynamics, molecular biology
_CANCER_BASIC_KW = {
    "clonal", "genomic", "whole genome", "stem cell", "molecular marker",
    "biomarker.*predict", "carcinogenesis", "field cancerization",
    "transcriptomic", "copy number", "dna mutation", "ordering of mutation",
    "preinvasive", "epithelial cell lineage", "precancerous niche",
    "monoclonal", "clonal diaspora", "clonal selection", "clonal interaction",
    "senescent barrett", "crypt dysplasia",
}

# Eosinophilic Oesophagitis
_EOE_KW = {
    "eosinophilic oesophagitis", "eosinophilic esophagitis",
    r"\beoe\b", "eosinophilic", "lymphocytic esophagitis",
    "six-food elimination", "pollen.*esophagitis",
}

# Inflammatory Bowel Disease
_IBD_KW = {
    "inflammatory bowel disease", r"\bibd\b", "crohn",
    "ulcerative colitis", r"\bcolitis\b", "stride-ii", "stride ii",
    "intestinal ultrasound.*ibd|ibd.*intestinal ultrasound",
    "covid.*ibd|ibd.*covid",
}

# Natural Language Processing / AI / data science
_NLP_KW = {
    "natural language", "machine learning", "artificial intelligence",
    "language model", r"\bllm\b", "endominer", "argent", "synthetic report",
    "entity.*relation", "information extract", "text extract", "text mining",
    "automated.*algorithm", "open-ended text", "differential privacy",
    "generation and evaluation", "structured extraction", "biomedical language",
    "reference-free evaluation",
}

# Oesophageal Physiology
_PHYSIOLOGY_KW = {
    "ph monitoring", "ph-impedance", "ph impedance", "impedance transit",
    "manometry", r"\bgerd\b", r"\bgord\b", "reflux", "dysphagia",
    "swallowing", "motility", "aperistalsis", "achalasia", "lyon",
    "wireless ph", "oesophageal physiology", "intraoesophageal",
    "oesophageal transit", "ph sensor", "bravo", "mad-reflux",
    "oesophageal aperistalsis",
}

# Endoscopy
_ENDOSCOPY_KW = {
    "endoscopic", "colonoscopy", "adenoma", r"\bpolyp\b", "radiofrequency ablation",
    r"\brfa\b", "barrett.*surveillance", r"\bpoem\b", "haemostatic",
    "mucosal resection", r"\besd\b", "intestinal ultrasound",
    "endoscopic therapy", "transnasal endoscopy", "halo express",
    "endoscopic resection", "trans-nasal",
}

# Abstract title patterns — conference poster/oral abstract codes
_ABSTRACT_RE = re.compile(
    r"^\s*(?:"
    r"\d+\s"                                    # "216 Feasibility …", "54 evaluation …"
    r"|[A-Z]{1,4}-[A-Z]{0,3}\d+"               # PTH-024, OFR-3, P-OGC21
    r"|[A-Z]{1,4}\d+"                           # P44, Mo1623, Su1136, Tu1116
    r"|O\d+"                                    # O26, O32
    r")",
    re.IGNORECASE,
)

# Titles that start with these strings are always excluded
_EXCLUDE_PREFIXES = (
    "erratum",
    "reply",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def is_abstract(title: str) -> bool:
    """Return True if the title looks like a conference abstract."""
    if not title:
        return True
    if _ABSTRACT_RE.match(title):
        return True
    low = title.lower().strip()
    if any(low.startswith(p) for p in _EXCLUDE_PREFIXES):
        return True
    return False


def _kw_match(title: str, kw_set: set) -> bool:
    low = title.lower()
    for kw in kw_set:
        if re.search(kw, low):
            return True
    return False


def categorize(title: str) -> str:
    """Return one of the eight category strings for a publication title."""
    if _kw_match(title, _CANCER_CLINICAL_KW):
        return "Cancer Clinical"
    if _kw_match(title, _CANCER_BASIC_KW):
        return "Cancer Basic Science"
    if _kw_match(title, _EOE_KW):
        return "Eosinophilic Oesophagitis"
    if _kw_match(title, _IBD_KW):
        return "Inflammatory Bowel Disease"
    if _kw_match(title, _NLP_KW):
        return "Natural Language Processing"
    if _kw_match(title, _PHYSIOLOGY_KW):
        return "Oesophageal Physiology"
    if _kw_match(title, _ENDOSCOPY_KW):
        return "Endoscopy"
    return "Other"


def _norm(title: str) -> str:
    """Normalise a title for deduplication — strips punctuation and leading codes."""
    t = re.sub(_ABSTRACT_RE, "", title)   # strip leading abstract code
    t = re.sub(r"[^\w\s]", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── CrossRef helpers ─────────────────────────────────────────────────────────

def authors_from_crossref(doi: str) -> list[str]:
    if not doi:
        return []
    url = f"https://api.crossref.org/works/{doi.strip()}"
    try:
        r = requests.get(url, headers=CROSSREF_HDR, timeout=15)
        if r.status_code != 200:
            return []
        raw = r.json().get("message", {}).get("author", [])
        authors = []
        for a in raw:
            family = a.get("family", "").strip()
            given  = a.get("given", "").strip()
            if family:
                initials = "".join(p[0] for p in given.split() if p) if given else ""
                authors.append(f"{family} {initials}".strip())
        return authors
    except Exception:
        return []


def authors_from_orcid_work(put_code: str) -> list[str]:
    if not put_code:
        return []
    url = f"{BASE_URL}/work/{put_code}"
    try:
        r = requests.get(url, headers=ORCID_HDR, timeout=15)
        if r.status_code != 200:
            return []
        contributors = (r.json().get("contributors") or {}).get("contributor") or []
        authors = []
        for c in contributors:
            role = _str((c.get("contributor-attributes") or {}).get("contributor-role"))
            if role and role.upper() not in ("AUTHOR", ""):
                continue
            name = _str(c.get("credit-name") or {}).strip()
            if name:
                authors.append(name)
        return authors
    except Exception:
        return []


def crossref_extra(doi: str) -> dict:
    result = {"volume": "", "issue": "", "pages": "", "journal": ""}
    if not doi:
        return result
    url = f"https://api.crossref.org/works/{doi.strip()}"
    try:
        r = requests.get(url, headers=CROSSREF_HDR, timeout=15)
        if r.status_code != 200:
            return result
        msg = r.json().get("message", {})
        result["volume"]  = msg.get("volume", "") or ""
        result["issue"]   = msg.get("issue",  "") or ""
        result["pages"]   = msg.get("page",   "") or ""
        titles = msg.get("container-title", [])
        result["journal"] = titles[0] if titles else ""
    except Exception:
        pass
    return result


# ── Fetchers ─────────────────────────────────────────────────────────────────

def fetch_works() -> list[dict]:
    """Return deduplicated, non-abstract works sorted newest-first."""
    r = requests.get(f"{BASE_URL}/works", headers=ORCID_HDR, timeout=30)
    r.raise_for_status()
    data = r.json()

    works      = []
    seen_norms: set[str] = set()
    total      = len(data.get("group", []))
    skipped    = 0

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

        # ── Skip abstracts and errata ──
        if is_abstract(title):
            skipped += 1
            continue

        # ── Deduplicate on normalised title ──
        norm = _norm(title)
        if norm in seen_norms:
            skipped += 1
            continue
        seen_norms.add(norm)

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

        journal = _str(best.get("journal-title"))

        # ── Resolve authors + CrossRef metadata ──
        authors = []
        volume = issue = pages = ""

        if doi:
            authors = authors_from_crossref(doi)
            extra   = crossref_extra(doi)
            if extra["journal"]:
                journal = extra["journal"]
            volume = extra["volume"]
            issue  = extra["issue"]
            pages  = extra["pages"]
            time.sleep(0.12)

        if not authors:
            authors = authors_from_orcid_work(best_put_code)
            time.sleep(0.05)

        works.append({
            "title":    title,
            "date":     date_str,
            "year":     year,
            "journal":  journal,
            "doi":      doi,
            "url":      f"https://doi.org/{doi}" if doi else "",
            "type":     best.get("type", "JOURNAL_ARTICLE"),
            "authors":  authors,
            "volume":   volume,
            "issue":    issue,
            "pages":    pages,
            "category": categorize(title),
        })

        if idx % 10 == 0:
            print(f"      … processed {idx}/{total} ({skipped} skipped so far)")

    works.sort(key=lambda w: w["date"], reverse=True)
    print(f"      Skipped {skipped} abstracts/duplicates/errata in total")
    return works


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
        sy = _str(start.get("year")); sm = _str(start.get("month")) or "01"
        ey = _str(end.get("year"));   em = _str(end.get("month"))   or "01"
        fundings.append({
            "title":        title,
            "organization": org,
            "date_start":   f"{sy}-{_zpad(sm)}-01" if sy else "",
            "date_end":     f"{ey}-{_zpad(em)}-01" if ey else "",
            "type":         (s.get("type") or "Grant").replace("_", " ").title(),
        })

    fundings.sort(key=lambda f: f["date_start"], reverse=True)
    return fundings


# ── Writers ───────────────────────────────────────────────────────────────────

def create_publication_file(work: dict, featured: bool = False) -> None:
    slug    = f"orcid_{slugify(work['title'])}"
    pub_dir = REPO_ROOT / "content" / "publication" / slug
    pub_dir.mkdir(parents=True, exist_ok=True)

    pub_type = map_work_type(work["type"])
    authors  = work.get("authors") or ["Sebastian Zeki"]
    authors_yaml = "\n".join(f"- \"{_q(a)}\"" for a in authors)

    journal = work["journal"]
    vol_str = ""
    if work.get("volume"):
        vol_str = f", {work['volume']}"
        if work.get("issue"):
            vol_str += f"({work['issue']})"
        if work.get("pages"):
            vol_str += f":{work['pages']}"

    publication_str = f"*{_q(journal)}*{_q(vol_str)}" if journal else ""
    category        = work.get("category", "Other")

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
tags:
- "{_q(category)}"
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
        "weight = 40\n\n"
        'title = "Funding"\n'
        'subtitle = "Research grants and awards"\n\n'
        'date_format = "Jan 2006"\n'
        + "".join(items)
        + "+++\n"
    )

    path = REPO_ROOT / "content" / "home" / "accomplishments.md"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path.relative_to(REPO_ROOT)}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== ORCID → Hugo Academic updater ===")
    print("    (fetching full author lists from CrossRef — takes ~2 min)")

    print("\n[1/2] Fetching works + resolving authors…")
    works = fetch_works()
    print(f"      {len(works)} publications kept after filtering")

    # Print category breakdown
    from collections import Counter
    cats = Counter(w["category"] for w in works)
    for cat, n in sorted(cats.items()):
        print(f"        {cat}: {n}")

    # Remove old orcid_ publication folders before writing fresh set
    pub_root = REPO_ROOT / "content" / "publication"
    for old in pub_root.glob("orcid_*"):
        if old.is_dir():
            for f in old.iterdir():
                f.unlink()
            old.rmdir()

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
