"""Weekly literature check.

Subscription mode (what the GitHub workflow uses; no API key needed):
    python -m tracker.run discover   # search; write data/candidates.json + data/screening_task.md
    (Claude Code GitHub Action screens them and writes data/screened.json)
    python -m tracker.run finalize   # store accepted papers, write the digest, clean up

API mode (local use, needs ANTHROPIC_API_KEY):
    python -m tracker.run api

Search only, no screening:
    python -m tracker.run dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

from .discover import discover
from .links import build_links
from .screen import normalise, screen, task_instructions
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = "data/candidates.json"
TASK = "data/screening_task.md"
SCREENED = "data/screened.json"


def _md(text: str) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def _gh_output(**values) -> None:
    """Pass values to later steps of the GitHub workflow."""
    if gh_out := os.getenv("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


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


def _accept(store: Store, cfg: dict, today: date, papers_and_verdicts) -> tuple[list[dict], int]:
    new_rows, screened = [], 0
    for p, s in papers_and_verdicts:
        screened += 1
        store.mark_seen(p["key"])
        if s["causal"] and s["relevance"] >= int(cfg.get("min_relevance", 2)):
            row = {**p, **s, **build_links(p, cfg.get("proxy_prefix", "")), "added": today.isoformat()}
            store.add(row)
            new_rows.append(row)
            print(f"  + {p['title'][:90]}  [{s['design']}]")
    return new_rows, screened


def _finish(store: Store, new_rows: list[dict], screened: int, today: date) -> None:
    store.save()
    digest = write_digest(new_rows, screened, today)
    print(f"Added {len(new_rows)} papers. Digest: {digest.relative_to(ROOT)}")
    _gh_output(new_count=len(new_rows), digest=digest.relative_to(ROOT))


def cmd_discover(cfg: dict, store: Store, today: date, dry: bool = False) -> int:
    print("Searching…")
    candidates = [p for p in discover(cfg, today) if not store.is_seen(p["key"])]
    cap = int(cfg.get("max_screen_per_run", 150))
    if len(candidates) > cap:
        print(f"{len(candidates)} new candidates; screening the {cap} most recent, the rest next run")
        candidates = sorted(candidates, key=lambda p: p.get("date") or "", reverse=True)[:cap]
    print(f"{len(candidates)} new candidates")
    if dry:
        for p in candidates[:30]:
            print(f"  - {p['title'][:100]}  ({p['venue']})")
        return 0
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / CANDIDATES).write_text(json.dumps(candidates, indent=1, ensure_ascii=False), encoding="utf-8")
    (ROOT / TASK).write_text(task_instructions(cfg, len(candidates)), encoding="utf-8")
    (ROOT / SCREENED).unlink(missing_ok=True)
    _gh_output(candidate_count=len(candidates))
    return 0


def cmd_finalize(cfg: dict, store: Store, today: date) -> int:
    cand_path, screened_path = ROOT / CANDIDATES, ROOT / SCREENED
    candidates = json.loads(cand_path.read_text()) if cand_path.exists() else []
    verdicts = {}
    if screened_path.exists():
        try:
            verdicts = json.loads(screened_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"  ! data/screened.json is not valid JSON ({exc}); nothing stored this run")
    if candidates and not verdicts:
        print("  ! no screening results; candidates will be retried next run")

    pairs = []
    for p in candidates:
        v = verdicts.get(p["key"])
        if isinstance(v, dict):
            pairs.append((p, normalise(v)))
        # missing verdicts stay unseen, so they're retried next run
    missing = len(candidates) - len(pairs)
    if missing:
        print(f"  ! {missing} candidates had no verdict; retrying them next run")

    new_rows, screened = _accept(store, cfg, today, pairs)
    _finish(store, new_rows, screened, today)
    for f in (CANDIDATES, TASK, SCREENED):
        (ROOT / f).unlink(missing_ok=True)
    return 0


def cmd_api(cfg: dict, store: Store, today: date) -> int:
    import anthropic
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1
    client = anthropic.Anthropic()
    print("Searching…")
    candidates = [p for p in discover(cfg, today) if not store.is_seen(p["key"])]
    print(f"{len(candidates)} new candidates")

    def verdicts():
        for p in candidates:
            try:
                yield p, screen(p, cfg, client)
            except Exception as exc:  # leave unseen so it is retried next run
                print(f"  ! screening failed for {p['title'][:60]!r}: {exc}")

    new_rows, screened = _accept(store, cfg, today, verdicts())
    _finish(store, new_rows, screened, today)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["discover", "finalize", "api", "dry-run"])
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    today = date.today()
    store = Store(ROOT / "data")
    if args.mode == "discover":
        return cmd_discover(cfg, store, today)
    if args.mode == "dry-run":
        return cmd_discover(cfg, store, today, dry=True)
    if args.mode == "finalize":
        return cmd_finalize(cfg, store, today)
    return cmd_api(cfg, store, today)


if __name__ == "__main__":
    sys.exit(main())
