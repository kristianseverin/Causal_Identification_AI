"""Weekly run: discover -> screen new papers -> store accepted ones -> write a digest.

Usage:  python -m tracker.run [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import yaml

from .discover import discover
from .links import build_links
from .screen import screen
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def _md(text: str) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def write_digest(new_rows: list[dict], screened: int, today: date) -> Path:
    out_dir = ROOT / "digests"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{today.isoformat()}.md"
    lines = [
        f"# GenAI causal-evidence digest — {today.isoformat()}",
        "",
        f"Screened {screened} new candidate papers; {len(new_rows)} passed "
        "(on-topic and a causal design).",
        "",
    ]
    if not new_rows:
        lines.append("Nothing new this week.")
    else:
        lines += ["| Paper | Design | Setting | Finding | Links |", "|---|---|---|---|---|"]
        for r in sorted(new_rows, key=lambda r: -int(r.get("relevance") or 0)):
            links = []
            if r.get("oa_url"):
                links.append(f"[free]({r['oa_url']})")
            if r.get("proxy_url"):
                links.append(f"[CBS]({r['proxy_url']})")
            if r.get("doi_url"):
                links.append(f"[DOI]({r['doi_url']})")
            paper = f"**{_md(r['title'])}**<br>{_md(r['authors'])[:80]} · {_md(r['venue'])} {r.get('year') or ''}"
            lines.append(
                f"| {paper} | {_md(r['design'])} | {_md(r['setting'])} | "
                f"{_md(r['finding'] or r['summary'])} | {' · '.join(links)} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="discover only; no Claude calls, no writes")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    today = date.today()
    store = Store(ROOT / "data")

    print("Searching…")
    candidates = [p for p in discover(cfg, today) if not store.is_seen(p["key"])]
    print(f"{len(candidates)} new candidates")
    if args.dry_run:
        for p in candidates[:30]:
            print(f"  - {p['title'][:100]}  ({p['venue']})")
        return 0

    import anthropic
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1
    client = anthropic.Anthropic()

    new_rows, screened = [], 0
    for p in candidates:
        try:
            s = screen(p, cfg, client)
        except Exception as exc:
            # leave unseen so it is retried next week
            print(f"  ! screening failed for {p['title'][:60]!r}: {exc}")
            continue
        screened += 1
        store.mark_seen(p["key"])
        if s["causal"] and s["relevance"] >= int(cfg.get("min_relevance", 2)):
            row = {**p, **s, **build_links(p, cfg.get("proxy_prefix", "")), "added": today.isoformat()}
            store.add(row)
            new_rows.append(row)
            print(f"  + {p['title'][:90]}  [{s['design']}]")

    store.save()
    digest = write_digest(new_rows, screened, today)
    print(f"Added {len(new_rows)} papers. Digest: {digest.relative_to(ROOT)}")

    # Tell the GitHub workflow whether to open an issue.
    if gh_out := os.getenv("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            f.write(f"new_count={len(new_rows)}\n")
            f.write(f"digest={digest.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
