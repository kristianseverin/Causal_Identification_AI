"""Build the three links stored for every paper."""

from __future__ import annotations


def build_links(paper: dict, proxy_prefix: str) -> dict:
    doi_url = f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""
    publisher_url = doi_url or paper.get("landing_url", "")
    oa_url = paper.get("oa_url", "")
    # A proxied link only makes sense for paywalled publisher pages, not for free copies.
    proxy_url = ""
    if proxy_prefix and publisher_url and "arxiv.org" not in publisher_url:
        proxy_url = proxy_prefix + publisher_url
    return {"doi_url": doi_url or publisher_url, "oa_url": oa_url, "proxy_url": proxy_url}
