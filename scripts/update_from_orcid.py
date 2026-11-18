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

import html
import json
import re
import time
from difflib import SequenceMatcher

import requests
from pathlib import Path

ORCID_ID   = "0000-0003-1673-2663"
BASE_URL   = f"https://pub.orcid.org/v3.0/{ORCID_ID}"
ORCID_HDR  = {"Accept": "application/json"}
CROSSREF_HDR = {
    "User-Agent": "SebZekiCV/1.0 (https://github.com/sebastiz/SebZeki_CV2; mailto:sebastiz@hotmail.com)"
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


# ── HTTP helper ──────────────────────────────────────────────────────────────

SESSION = requests.Session()
MAILTO  = "sebastiz@hotmail.com"


def get_json(url: str, params=None, headers=None, timeout: int = 20,
             retries: int = 3, method: str = "GET", json_body=None):
    """GET/POST returning parsed JSON, retrying on rate limits and 5xx."""
    for attempt in range(retries):
        try:
            r = SESSION.request(method, url, params=params, headers=headers,
                                json=json_body, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    return None


def clean_title(title: str) -> str:
    """Fix mojibake/HTML in titles (e.g. 'Barrett�s' -> 'Barrett’s')."""
    title = html.unescape(title or "")
    title = re.sub(r"<[^>]+>", "", title)            # strip <i>, <sub> etc.
    title = title.replace("�", "’")
    return re.sub(r"\s+", " ", title).strip()


def _norm(title: str) -> str:
    """Normalise a title for deduplication — strips punctuation and leading codes."""
    t = re.sub(_ABSTRACT_RE, "", clean_title(title))
    t = re.sub(r"[^\w\s]", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def norm_doi(doi: str) -> str:
    doi = (doi or "").strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.rstrip(".").strip()


def _initials(given: str) -> str:
    return "".join(p[0] for p in re.split(r"[\s.\-]+", given or "") if p)


def author_from_full_name(name: str) -> str:
    """'Rebecca C. Fitzgerald' -> 'Fitzgerald RC' (matches CrossRef style)."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        return ""
    if "," in name:                                  # 'Fitzgerald, Rebecca C.'
        family, given = [p.strip() for p in name.split(",", 1)]
    else:
        parts = name.split(" ")
        if len(parts) == 1:
            return name
        family, given = parts[-1], " ".join(parts[:-1])
    return f"{family} {_initials(given)}".strip()


# ── Publication date helpers ─────────────────────────────────────────────────

def _date_from_parts(parts) -> str:
    """CrossRef date-parts [[y, m, d]] -> 'YYYY-MM-DD' (missing parts -> 01)."""
    try:
        p = parts["date-parts"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    if not p or not p[0]:
        return ""
    y = str(p[0])
    m = str(p[1]) if len(p) > 1 and p[1] else "1"
    d = str(p[2]) if len(p) > 2 and p[2] else "1"
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def _date_precision(date_str: str) -> int:
    """Rough precision score: 3 = full date, 2 = month known, 1 = year only."""
    if not date_str:
        return 0
    if date_str.endswith("-01-01"):
        return 1
    if date_str.endswith("-01"):
        return 2
    return 3


# ── CrossRef ─────────────────────────────────────────────────────────────────

def crossref_record(doi: str) -> dict | None:
    """Full metadata for one DOI from CrossRef (authors, venue, volume, date…)."""
    doi = norm_doi(doi)
    if not doi:
        return None
    data = get_json(f"https://api.crossref.org/works/{requests.utils.quote(doi)}",
                    headers=CROSSREF_HDR)
    if not data:
        return None
    msg = data.get("message", {})

    authors = []
    for a in msg.get("author", []) or []:
        family = (a.get("family") or "").strip()
        given  = (a.get("given") or "").strip()
        if family:
            authors.append(f"{family} {_initials(given)}".strip())
        elif a.get("name"):                          # consortium / group author
            authors.append(a["name"].strip())

    date = ""
    for key in ("published-print", "published-online", "issued", "published"):
        if msg.get(key):
            cand = _date_from_parts(msg[key])
            if _date_precision(cand) > _date_precision(date):
                date = cand
            if _date_precision(date) == 3:
                break

    titles = msg.get("container-title") or []
    return {
        "doi":       msg.get("DOI", "") or doi,
        "title":     clean_title((msg.get("title") or [""])[0]),
        "authors":   authors,
        "journal":   titles[0] if titles else "",
        "volume":    msg.get("volume", "") or "",
        "issue":     msg.get("issue", "") or "",
        "pages":     msg.get("page", "") or msg.get("article-number", "") or "",
        "publisher": msg.get("publisher", "") or "",
        "cr_type":   msg.get("type", "") or "",
        "date":      date,
    }


def crossref_find_doi(title: str, year: str) -> str:
    """Search CrossRef by title; only accept a near-identical title match."""
    data = get_json(
        "https://api.crossref.org/works",
        params={"query.bibliographic": title, "rows": 5,
                "select": "DOI,title,issued,type"},
        headers=CROSSREF_HDR,
    )
    if not data:
        return ""
    for item in data.get("message", {}).get("items", []):
        cand_title = (item.get("title") or [""])[0]
        if title_similarity(title, cand_title) < 0.93:
            continue
        if item.get("type") in ("peer-review", "component"):
            continue
        cand_year = _date_from_parts(item.get("issued") or {})[:4]
        if year and cand_year and abs(int(year) - int(cand_year)) > 1:
            continue
        return item.get("DOI", "")
    return ""


# ── OpenAlex (one bulk call for everything linked to the ORCID) ──────────────

def fetch_openalex_index() -> tuple[dict, dict]:
    """Return ({doi: work}, {norm_title: work}) for all OpenAlex works by ORCID."""
    by_doi, by_title = {}, {}
    cursor = "*"
    while cursor:
        data = get_json(
            "https://api.openalex.org/works",
            params={"filter": f"author.orcid:{ORCID_ID}", "per-page": 200,
                    "cursor": cursor, "mailto": MAILTO},
        )
        if not data:
            break
        for w in data.get("results", []):
            rec = _openalex_to_record(w)
            if rec["doi"]:
                by_doi[rec["doi"].lower()] = rec
            if rec["title"]:
                by_title.setdefault(_norm(rec["title"]), rec)
        cursor = (data.get("meta") or {}).get("next_cursor")
    return by_doi, by_title


def _openalex_to_record(w: dict) -> dict:
    biblio = w.get("biblio") or {}
    first, last = biblio.get("first_page") or "", biblio.get("last_page") or ""
    pages = f"{first}-{last}" if first and last and first != last else first
    source = ((w.get("primary_location") or {}).get("source") or {})
    authors = [author_from_full_name((a.get("author") or {}).get("display_name", ""))
               for a in w.get("authorships") or []]
    return {
        "doi":       norm_doi(w.get("doi") or ""),
        "title":     clean_title(w.get("title") or w.get("display_name") or ""),
        "authors":   [a for a in authors if a],
        "journal":   source.get("display_name") or "",
        "volume":    biblio.get("volume") or "",
        "issue":     biblio.get("issue") or "",
        "pages":     pages,
        "date":      w.get("publication_date") or "",
        "citations": w.get("cited_by_count"),
    }


def openalex_lookup(doi: str, title: str, by_doi: dict, by_title: dict) -> dict | None:
    if doi and doi.lower() in by_doi:
        return by_doi[doi.lower()]
    rec = by_title.get(_norm(title))
    if rec:
        return rec
    # fuzzy fallback for small wording differences
    best, best_score = None, 0.0
    for key, cand in by_title.items():
        s = SequenceMatcher(None, _norm(title), key).ratio()
        if s > best_score:
            best, best_score = cand, s
    return best if best_score >= 0.93 else None


# ── Semantic Scholar ─────────────────────────────────────────────────────────

S2_AUTHOR_ID = "49975042"  # Sebastian Zeki on Semantic Scholar
S2_HDR = {"User-Agent": "SebZekiCV/1.0 (mailto:sebastiz@hotmail.com)"}


def fetch_s2_author_metrics() -> dict:
    """Return h-index, citationCount, paperCount from Semantic Scholar."""
    data = get_json(
        f"https://api.semanticscholar.org/graph/v1/author/{S2_AUTHOR_ID}",
        params={"fields": "hIndex,citationCount,paperCount"},
        headers=S2_HDR, retries=5,
    ) or {}
    return {
        "hIndex":        data.get("hIndex"),
        "citationCount": data.get("citationCount"),
        "paperCount":    data.get("paperCount"),
    }


def fetch_s2_citation_counts(dois: list[str]) -> dict:
    """Batch lookup {doi_lower: citationCount} — one request instead of ~70."""
    out = {}
    dois = [d for d in dict.fromkeys(dois) if d]
    for i in range(0, len(dois), 400):
        chunk = dois[i:i + 400]
        data = get_json(
            "https://api.semanticscholar.org/graph/v1/paper/batch",
            params={"fields": "citationCount"}, headers=S2_HDR, retries=5,
            method="POST", json_body={"ids": [f"DOI:{d}" for d in chunk]},
        )
        if not isinstance(data, list):
            continue
        for doi, paper in zip(chunk, data):
            if paper and paper.get("citationCount") is not None:
                out[doi.lower()] = paper["citationCount"]
    return out


def write_metrics_widget(metrics: dict) -> None:
    """Update the allpubs_heading.md widget with fresh citation metrics."""
    h      = metrics.get("hIndex")
    cites  = metrics.get("citationCount")
    papers = metrics.get("paperCount")

    if h is None or cites is None:
        return  # API unavailable — leave existing file untouched

    path = REPO_ROOT / "content" / "home" / "allpubs_heading.md"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")

    def _replace_val(label: str, value) -> None:
        nonlocal text
        pattern = r'(<strong>)[^<]*(</strong>\s*' + re.escape(label) + r')'
        text = re.sub(pattern, rf'\g<1>{value}\2', text)

    _replace_val("h-index", h)
    _replace_val("citations", f"{cites:,}")
    if papers is not None:
        _replace_val("papers indexed", papers)

    path.write_text(text, encoding="utf-8")
    print(f"  Updated allpubs_heading.md metrics: h={h}, citations={cites}, papers={papers}")


# ── Manual overrides ─────────────────────────────────────────────────────────

def load_overrides() -> dict:
    """scripts/publication_overrides.json: {normalised title: {field: value}}.
    Use for anything the APIs get wrong (missing DOI, wrong date, exclude)."""
    path = Path(__file__).parent / "publication_overrides.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {_norm(k): v for k, v in raw.items() if not k.startswith("_")}
    out["__add_dois__"] = raw.get("_add_dois", [])
    return out


def read_previous_citations() -> dict:
    """Citation counts from the files currently on disk, keyed by DOI and title,
    so a temporary API outage doesn't wipe the numbers from the site."""
    prev = {}
    for f in (REPO_ROOT / "content" / "publication").glob("orcid_*/index.md"):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"Cited (\d+) time", text)
        if not m:
            continue
        n = int(m.group(1))
        d = re.search(r'^doi:\s*"([^"]*)"', text, re.M)
        t = re.search(r'^title:\s*"(.*)"\s*$', text, re.M)
        if d and d.group(1):
            prev[d.group(1).lower()] = n
        if t:
            prev[_norm(t.group(1).replace('\\"', '"'))] = n
    return prev


# ── ORCID ──────

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



# ── Fetchers ─────────────────────────────────────────────────────────────────

def _orcid_group_candidates(group: dict) -> tuple[dict, list[str]]:
    """Pick the best summary in an ORCID group and collect every DOI it lists."""
    summaries = group.get("work-summary", [])
    best = summaries[0]
    for s in summaries:
        src = _str((s.get("source") or {}).get("source-name")).lower()
        if "crossref" in src or "scopus" in src:
            best = s
            break
    dois = []
    for s in [best] + summaries:                     # best summary's DOI first
        for eid in (s.get("external-ids") or {}).get("external-id", []) or []:
            if (eid.get("external-id-type") or "").lower() == "doi":
                d = norm_doi(eid.get("external-id-value") or "")
                if d and d not in dois:
                    dois.append(d)
    return best, dois


def _richness(w: dict) -> int:
    return (100 if w["doi"] else 0) + (10 if w["volume"] else 0) + len(w["authors"])


def fetch_works() -> list[dict]:
    """Return deduplicated, non-abstract, enriched works sorted newest-first."""
    data = get_json(f"{BASE_URL}/works", headers=ORCID_HDR, timeout=30)
    if not data:
        raise RuntimeError("ORCID API unavailable — aborting without changes")

    overrides = load_overrides()
    print("      Loading OpenAlex index…")
    oa_by_doi, oa_by_title = fetch_openalex_index()
    print(f"      OpenAlex: {len(oa_by_doi)} works with DOI, {len(oa_by_title)} titles")

    works   = []
    groups  = data.get("group", [])
    skipped = 0
    stats   = {"doi_from_search": 0, "doi_from_openalex": 0, "authors_from_openalex": 0}

    for idx, group in enumerate(groups, 1):
        if not group.get("work-summary"):
            continue
        best, dois = _orcid_group_candidates(group)
        title = clean_title(_str((best.get("title") or {}).get("title")))
        if not title or is_abstract(title):
            skipped += 1
            continue

        ov = overrides.get(_norm(title), {})
        if ov.get("exclude"):
            skipped += 1
            continue

        pub_date = best.get("publication-date") or {}
        year  = _str(pub_date.get("year"))
        month = _str(pub_date.get("month")) or "01"
        day   = _str(pub_date.get("day"))   or "01"
        date_str = f"{year}-{_zpad(month)}-{_zpad(day)}" if year else ""

        work = {
            "title": title, "date": date_str, "year": year,
            "journal": _str(best.get("journal-title")),
            "doi": "", "authors": [], "volume": "", "issue": "", "pages": "",
            "type": best.get("type", "JOURNAL_ARTICLE"), "publisher": "",
            "citation_count": None, "citation_source": "",
        }

        # ── 1. DOI: ORCID (any record in group) → override → OpenAlex → CrossRef search
        doi_candidates = ([norm_doi(ov["doi"])] if ov.get("doi") else []) + dois
        oa = openalex_lookup("", title, oa_by_doi, oa_by_title)
        if not doi_candidates and oa and oa["doi"]:
            doi_candidates = [oa["doi"]]
            stats["doi_from_openalex"] += 1
        if not doi_candidates:
            found = crossref_find_doi(title, year)
            time.sleep(0.1)
            if found:
                doi_candidates = [found]
                stats["doi_from_search"] += 1

        # ── 2. CrossRef metadata for the first DOI that resolves to a real venue
        cr = None
        for d in doi_candidates:
            rec = crossref_record(d)
            time.sleep(0.1)
            if rec and title_similarity(title, rec["title"] or title) < 0.6:
                continue                              # DOI belongs to something else
            if rec and (rec["journal"] or rec["cr_type"] in ("book", "monograph")):
                cr = rec
                break
            if rec and not cr:
                cr = rec                              # e.g. repository DOI — keep as fallback
        if cr and not cr["journal"] and cr["cr_type"] not in ("book", "monograph"):
            # repository/preprint DOI — look for the published version
            alt = crossref_find_doi(title, year)
            time.sleep(0.1)
            if alt and alt.lower() != cr["doi"].lower():
                alt_rec = crossref_record(alt)
                if alt_rec and alt_rec["journal"]:
                    cr = alt_rec

        if cr:
            work["doi"] = cr["doi"]
            for k in ("journal", "volume", "issue", "pages", "publisher"):
                if cr[k]:
                    work[k] = cr[k]
            work["authors"] = cr["authors"]
            if _date_precision(cr["date"]) > _date_precision(work["date"]):
                work["date"] = cr["date"]
        elif doi_candidates:
            work["doi"] = doi_candidates[0]

        # ── 3. OpenAlex fills remaining gaps (non-CrossRef venues, e.g. ACL, CEUR)
        oa = openalex_lookup(work["doi"], title, oa_by_doi, oa_by_title) or oa
        if oa:
            if len(oa["authors"]) > len(work["authors"]):
                work["authors"] = oa["authors"]
                stats["authors_from_openalex"] += 1
            for k in ("journal", "volume", "issue", "pages"):
                if not work[k] and oa[k]:
                    work[k] = oa[k]
            if not work["doi"] and oa["doi"]:
                work["doi"] = oa["doi"]
            if _date_precision(oa["date"]) > _date_precision(work["date"]):
                work["date"] = oa["date"]
            work["_oa_citations"] = oa["citations"]

        # ── 4. ORCID contributor list as last resort
        if len(work["authors"]) <= 1:
            orcid_authors = authors_from_orcid_work(str(best.get("put-code", "")))
            if len(orcid_authors) > len(work["authors"]):
                work["authors"] = [author_from_full_name(a) for a in orcid_authors]
            time.sleep(0.05)

        # Manual overrides win over everything
        for k, v in ov.items():
            if k in work and k != "exclude":
                work[k] = norm_doi(v) if k == "doi" else v

        if not work["date"]:
            work["date"] = "2000-01-01"
        work["year"]     = work["date"][:4]
        work["url"]      = f"https://doi.org/{work['doi']}" if work["doi"] else ""
        work["category"] = ov.get("category") or categorize(title)
        works.append(work)

        if idx % 10 == 0:
            print(f"      … processed {idx}/{len(groups)} ({skipped} skipped so far)")

    # ── Papers missing from ORCID, listed by DOI in the overrides file
    for extra in overrides.get("__add_dois__", []):
        rec = crossref_record(extra)
        if not rec:
            print(f"      WARNING: could not resolve extra DOI {extra}")
            continue
        oa = openalex_lookup(rec["doi"], rec["title"], oa_by_doi, oa_by_title)
        works.append({
            "title": rec["title"], "date": rec["date"] or "2000-01-01",
            "year": (rec["date"] or "2000")[:4], "journal": rec["journal"],
            "doi": rec["doi"], "authors": rec["authors"], "volume": rec["volume"],
            "issue": rec["issue"], "pages": rec["pages"], "publisher": rec["publisher"],
            "type": "JOURNAL_ARTICLE", "citation_count": None, "citation_source": "",
            "url": f"https://doi.org/{rec['doi']}", "category": categorize(rec["title"]),
            "_oa_citations": oa["citations"] if oa else None,
        })

    # ── Deduplicate on DOI and on (near-)identical titles, keeping the richest
    works.sort(key=_richness, reverse=True)
    kept, seen_doi, seen_titles = [], set(), []
    for w in works:
        d = w["doi"].lower()
        n = _norm(w["title"])
        if d and d in seen_doi:
            skipped += 1
            continue
        if any(n == t or SequenceMatcher(None, n, t).ratio() > 0.95 for t in seen_titles):
            skipped += 1
            continue
        if d:
            seen_doi.add(d)
        seen_titles.append(n)
        kept.append(w)

    # ── Citation counts: Semantic Scholar (batch) → OpenAlex → previous value
    s2 = fetch_s2_citation_counts([w["doi"] for w in kept if w["doi"]])
    prev = read_previous_citations()
    for w in kept:
        d = w["doi"].lower()
        if d and d in s2:
            w["citation_count"], w["citation_source"] = s2[d], "Semantic Scholar"
        elif w.get("_oa_citations") is not None:
            w["citation_count"], w["citation_source"] = w["_oa_citations"], "OpenAlex"
        elif (d and d in prev) or _norm(w["title"]) in prev:
            w["citation_count"] = prev.get(d, prev.get(_norm(w["title"])))
            w["citation_source"] = "Semantic Scholar"

    kept.sort(key=lambda w: w["date"], reverse=True)
    print(f"      Skipped {skipped} abstracts/duplicates/errata in total")
    print(f"      DOIs found via OpenAlex: {stats['doi_from_openalex']}, "
          f"via CrossRef title search: {stats['doi_from_search']}; "
          f"author lists from OpenAlex: {stats['authors_from_openalex']}; "
          f"S2 citation counts: {len(s2)}")
    return kept


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
    authors  = work.get("authors") or ["Zeki S"]
    authors_yaml = "\n".join(f"- \"{_q(a)}\"" for a in authors)

    journal = work["journal"] or work.get("publisher", "")
    vol_str = ""
    if work.get("volume"):
        vol_str = f", {work['volume']}"
        if work.get("issue"):
            vol_str += f"({work['issue']})"
        if work.get("pages"):
            vol_str += f":{work['pages']}"
    elif work.get("pages"):
        vol_str = f", {work['pages']}"

    publication_str = f"*{_q(journal)}*{_q(vol_str)}" if journal else ""
    category        = work.get("category", "Other")
    citation_count  = work.get("citation_count", "")
    doi             = work["doi"]

    # Build content body: Altmetric badge + citation count
    body_parts = []
    if doi:
        body_parts.append(
            f'<div class="altmetric-embed" data-badge-type="donut" '
            f'data-badge-popover="right" data-doi="{doi}"></div>'
        )
    if citation_count != "" and citation_count is not None:
        body_parts.append(
            f'<p style="font-size:0.85rem;color:#666;margin-top:0.5rem;">'
            f'📖 Cited {citation_count} time{"s" if citation_count != 1 else ""} '
            f'({work.get("citation_source") or "Semantic Scholar"})</p>'
        )
    body = "\n".join(body_parts)

    content = f"""---
title: "{_q(work['title'])}"
authors:
{authors_yaml}
date: "{work['date']}T00:00:00Z"
doi: "{doi}"
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

{body}
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

    print("\n[3/3] Fetching author metrics from Semantic Scholar…")
    metrics = fetch_s2_author_metrics()
    if metrics.get("hIndex") is not None:
        print(f"      h-index={metrics['hIndex']}, citations={metrics['citationCount']}, papers={metrics['paperCount']}")
        write_metrics_widget(metrics)
    else:
        print("      Semantic Scholar unavailable — skipping metrics widget")

    print("\nDone.")


if __name__ == "__main__":
    main()
