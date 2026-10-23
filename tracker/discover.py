"""Find recent papers on OpenAlex and arXiv. Returns plain dicts; no full text is fetched."""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

OPENALEX = "https://api.openalex.org/works"
ARXIV = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "genai-causal-tracker (literature alert; github.com)"


def normalise_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def paper_key(p: dict) -> str:
    """Stable id used for de-duplication across sources and runs."""
    if p.get("doi"):
        return "doi:" + p["doi"]
    if p.get("arxiv_id"):
        return "arxiv:" + p["arxiv_id"]
    title = re.sub(r"[^a-z0-9]+", " ", (p.get("title") or "").lower()).strip()
    return "title:" + title[:120]


def _abstract_from_index(inv: dict | None) -> str:
    if not inv:
        return ""
    words = sorted((pos, w) for w, positions in inv.items() for pos in positions)
    return " ".join(w for _, w in words)


def search_openalex(query: str, since: date, limit: int) -> list[dict]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{since.isoformat()}",
        "per-page": min(limit, 200),
        "sort": "publication_date:desc",
    }
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.getenv("CONTACT_EMAIL"):
        params["mailto"] = os.environ["CONTACT_EMAIL"]
    r = SESSION.get(OPENALEX, params=params, timeout=30)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        primary = w.get("primary_location") or {}
        source = primary.get("source") or {}
        oa = w.get("best_oa_location") or {}
        arxiv_id = None
        for loc in w.get("locations") or []:
            url = (loc or {}).get("landing_page_url") or ""
            m = re.search(r"arxiv\.org/abs/([\w.\-/]+?)(v\d+)?$", url)
            if m:
                arxiv_id = m.group(1)
        out.append({
            "source": "openalex",
            "openalex_id": w.get("id"),
            "doi": normalise_doi(w.get("doi")),
            "arxiv_id": arxiv_id,
            "title": (w.get("title") or "").strip(),
            "authors": "; ".join(
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])[:8]
            ),
            "year": w.get("publication_year"),
            "date": w.get("publication_date"),
            "venue": source.get("display_name") or "",
            "type": w.get("type") or "",
            "abstract": _abstract_from_index(w.get("abstract_inverted_index")),
            "landing_url": primary.get("landing_page_url") or "",
            "oa_url": oa.get("pdf_url") or oa.get("landing_page_url") or "",
        })
    return out


def search_arxiv(query: str, categories: list[str], since: date, limit: int) -> list[dict]:
    terms = " AND ".join(f'all:"{t}"' if " " in t else f"all:{t}" for t in query.split())
    cats = " OR ".join(f"cat:{c}" for c in categories)
    q = f"({terms}) AND ({cats})" if cats else terms
    params = {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending",
              "max_results": limit}
    r = SESSION.get(ARXIV, params=params, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        published = (e.findtext(f"{ATOM}published") or "")[:10]
        if published and published < since.isoformat():
            continue
        abs_url = e.findtext(f"{ATOM}id") or ""
        m = re.search(r"abs/([\w.\-/]+?)(v\d+)?$", abs_url)
        arxiv_id = m.group(1) if m else None
        out.append({
            "source": "arxiv",
            "openalex_id": None,
            "doi": normalise_doi(e.findtext(f"{ARXIV_NS}doi")),
            "arxiv_id": arxiv_id,
            "title": " ".join((e.findtext(f"{ATOM}title") or "").split()),
            "authors": "; ".join(
                a.findtext(f"{ATOM}name") or "" for a in e.findall(f"{ATOM}author")[:8]
            ),
            "year": int(published[:4]) if published else None,
            "date": published,
            "venue": "arXiv",
            "type": "preprint",
            "abstract": " ".join((e.findtext(f"{ATOM}summary") or "").split()),
            "landing_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else abs_url,
            "oa_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else abs_url,
        })
    return out


def discover(cfg: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    since = today - timedelta(days=int(cfg.get("lookback_days", 14)))
    limit = int(cfg.get("max_results_per_query", 50))
    found: dict[str, dict] = {}
    attempts = failures = 0
    for q in cfg["queries"]:
        for fetch in (
            lambda: search_openalex(q, since, limit),
            lambda: search_arxiv(q, cfg.get("arxiv_categories", []), since, limit),
        ):
            attempts += 1
            try:
                results = fetch()
            except Exception as exc:  # one failing source shouldn't sink the run
                failures += 1
                print(f"  ! search failed for {q!r}: {exc}")
                continue
            for p in results:
                k = paper_key(p)
                if k in found:
                    # keep the richer record; fill gaps from the other source
                    for field, val in p.items():
                        if val and not found[k].get(field):
                            found[k][field] = val
                else:
                    found[k] = p
            time.sleep(1)  # be polite to both APIs (arXiv asks for ~3s between bursts)
    if attempts and failures == attempts:
        # Every search failed: an outage or network problem, not a quiet week.
        raise RuntimeError("all searches failed; see messages above")
    for k, p in found.items():
        p["key"] = k
    return list(found.values())
