"""Ask Claude whether each paper is on-topic and uses a credible causal design."""

from __future__ import annotations

import json
import re

PROMPT = """You screen new research papers for a researcher tracking this topic:

{topic}

Accepted identification strategies:
{designs}

Paper:
Title: {title}
Venue: {venue}
Abstract: {abstract}

Reply with ONLY a JSON object, no other text:
{{
  "relevance": 0-3,          // 0 off-topic, 1 tangential, 2 relevant, 3 core to the topic
  "design": "<one of the accepted strategies, or 'descriptive / correlational', 'theory / review', 'unclear'>",
  "causal": true|false,      // true only if the design is one of the accepted strategies
  "setting": "<who/where was studied, a few words>",
  "sample": "<size and unit if stated, else ''>",
  "outcome": "<main outcome measured, a few words>",
  "finding": "<headline effect in your own words, one sentence, '' if not stated>",
  "summary": "<one-sentence summary in your own words; do not copy the abstract>"
}}"""

FIELDS = ("relevance", "design", "causal", "setting", "sample", "outcome", "finding", "summary")


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    raw = re.sub(r"//[^\n]*", "", m.group(0))  # tolerate comments copied from the template
    data = json.loads(raw)
    out = {f: data.get(f, "") for f in FIELDS}
    out["relevance"] = int(out["relevance"] or 0)
    out["causal"] = bool(out["causal"])
    return out


def screen(paper: dict, cfg: dict, client) -> dict:
    """Return screening fields for one paper. `client` is an anthropic.Anthropic()."""
    if not paper.get("abstract"):
        # Without an abstract we can only judge the title; mark as unclear rather than guess.
        abstract = "(no abstract available; judge from the title only and set design to 'unclear' unless the title states it)"
    else:
        abstract = paper["abstract"][:6000]
    prompt = PROMPT.format(
        topic=cfg["topic"].strip(),
        designs="\n".join(f"- {d}" for d in cfg["causal_designs"]),
        title=paper.get("title", ""),
        venue=paper.get("venue", ""),
        abstract=abstract,
    )
    msg = client.messages.create(
        model=cfg.get("model", "claude-haiku-5-5"),
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _parse(text)
