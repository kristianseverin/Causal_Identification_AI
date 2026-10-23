"""Offline end-to-end test: fake OpenAlex, arXiv and Claude responses."""

import csv
import json
from datetime import date
from types import SimpleNamespace
from unittest import mock

import tracker.run as run
from tracker import discover as disc

OPENALEX_JSON = {"results": [
    {   # causal, paywalled journal article, also on arXiv
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1093/QJE/QJAE044",
        "title": "Generative AI at Work", "publication_year": 2026, "publication_date": "2026-10-15",
        "type": "article",
        "authorships": [{"author": {"display_name": "Ann Smith"}}, {"author": {"display_name": "Bo Lee"}}],
        "primary_location": {"source": {"display_name": "Quarterly Journal of Economics"},
                             "landing_page_url": "https://academic.oup.com/qje/x"},
        "locations": [{"landing_page_url": "https://arxiv.org/abs/2610.00001v2"}],
        "best_oa_location": None,
        "abstract_inverted_index": {"We": [0], "randomize": [1], "AI": [2], "access": [3]},
    },
    {   # descriptive, should be rejected
        "id": "https://openalex.org/W2", "doi": "https://doi.org/10.1/survey",
        "title": "A Survey of Managers' Attitudes to ChatGPT", "publication_year": 2026,
        "publication_date": "2026-10-12", "type": "article", "authorships": [],
        "primary_location": {"source": {"display_name": "Some Journal"}, "landing_page_url": "x"},
        "locations": [], "best_oa_location": {"pdf_url": "https://repo.example/survey.pdf"},
        "abstract_inverted_index": {"Survey": [0]},
    },
]}

ARXIV_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry><id>http://arxiv.org/abs/2610.00001v2</id><published>2026-10-14T00:00:00Z</published>
  <title>Generative AI at Work</title><summary>We randomize AI access.</summary>
  <author><name>Ann Smith</name></author><arxiv:doi>10.1093/qje/qjae044</arxiv:doi></entry>
 <entry><id>http://arxiv.org/abs/2610.00009v1</id><published>2026-10-18T00:00:00Z</published>
  <title>Copilot Rollout and Developer Output: A Staggered DiD</title>
  <summary>Staggered adoption across firms.</summary>
  <author><name>Cy Dorn</name></author></entry>
 <entry><id>http://arxiv.org/abs/2601.00002v1</id><published>2026-01-01T00:00:00Z</published>
  <title>Too old</title><summary>x</summary></entry>
</feed>"""


def fake_get(url, params=None, timeout=None):
    r = mock.Mock()
    r.raise_for_status = lambda: None
    if "openalex" in url:
        r.json = lambda: OPENALEX_JSON
    else:
        r.content = ARXIV_XML
    return r


def fake_create(model, max_tokens, messages):
    text = messages[0]["content"]
    if "Survey" in text:
        verdict = {"relevance": 2, "design": "descriptive / correlational", "causal": False}
    elif "Staggered" in text:
        verdict = {"relevance": 3, "design": "difference-in-differences / event study", "causal": True,
                   "setting": "software firms", "finding": "Output rose about 10%."}
    else:
        verdict = {"relevance": 3, "design": "RCT / field experiment", "causal": True,
                   "setting": "call-centre agents", "sample": "5,000 agents",
                   "finding": "Productivity up 14% | mostly for novices", "summary": "s"}
    reply = "Here you go:\n" + json.dumps(verdict)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])


def test_end_to_end(tmp_path, monkeypatch):
    for f in ("config.yaml",):
        (tmp_path / f).write_text((run.ROOT / f).read_text())
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(disc.SESSION, "get", fake_get)
    monkeypatch.setattr(disc.time, "sleep", lambda s: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    gh_out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    with mock.patch("anthropic.Anthropic", return_value=fake_client), \
         mock.patch.object(run, "date", SimpleNamespace(today=lambda: date(2026, 10, 23))):
        assert run.main([]) == 0

    rows = list(csv.DictReader((tmp_path / "data/papers.csv").open()))
    titles = {r["title"] for r in rows}
    assert titles == {"Generative AI at Work", "Copilot Rollout and Developer Output: A Staggered DiD"}

    qje = next(r for r in rows if r["title"] == "Generative AI at Work")
    assert qje["doi_url"] == "https://doi.org/10.1093/qje/qjae044"
    assert qje["proxy_url"] == "https://esc-web.lib.cbs.dk:8443/login?url=https://doi.org/10.1093/qje/qjae044"
    assert qje["oa_url"] == "https://arxiv.org/abs/2610.00001"   # merged from the arXiv record
    assert qje["venue"] == "Quarterly Journal of Economics"

    copilot = next(r for r in rows if "Copilot" in r["title"])
    assert copilot["proxy_url"] == ""                            # arXiv-only: no proxy link
    assert copilot["oa_url"] == "https://arxiv.org/abs/2610.00009"

    seen = (tmp_path / "data/seen.txt").read_text().split()
    assert len(seen) == 3                                        # survey recorded as seen too
    assert "new_count=2" in gh_out.read_text()

    digest = (tmp_path / "digests/2026-10-23.md").read_text()
    assert "[CBS](https://esc-web.lib.cbs.dk" in digest
    assert "Productivity up 14% / mostly" in digest              # pipe escaped for the table

    # Second run: nothing new should be screened or added.
    with mock.patch("anthropic.Anthropic", return_value=fake_client), \
         mock.patch.object(run, "date", SimpleNamespace(today=lambda: date(2026, 10, 23))):
        assert run.main([]) == 0
    assert len(list(csv.DictReader((tmp_path / "data/papers.csv").open()))) == 2
