"""CSV database of accepted papers, plus a list of every paper already screened."""

from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = [
    "added", "date", "year", "title", "authors", "venue", "type",
    "design", "setting", "sample", "outcome", "finding", "summary", "relevance",
    "doi_url", "oa_url", "proxy_url", "key",
]


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.papers_path = self.dir / "papers.csv"
        self.seen_path = self.dir / "seen.txt"
        self.papers = self._load_papers()
        self.seen = set(self.seen_path.read_text().split("\n")) - {""} if self.seen_path.exists() else set()

    def _load_papers(self) -> list[dict]:
        if not self.papers_path.exists():
            return []
        with self.papers_path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def is_seen(self, key: str) -> bool:
        return key in self.seen

    def mark_seen(self, key: str) -> None:
        self.seen.add(key)

    def add(self, row: dict) -> None:
        self.papers.append({c: row.get(c, "") for c in COLUMNS})

    def save(self) -> None:
        rows = sorted(self.papers, key=lambda r: (r.get("date") or "", r.get("title") or ""), reverse=True)
        with self.papers_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        self.seen_path.write_text("\n".join(sorted(self.seen)) + "\n")
