# GenAI causal-evidence tracker

Every Monday this repo searches OpenAlex and arXiv for new papers on the effects of
generative AI in organisations, asks Claude to screen each one for topic fit and a
credible causal design (RCT, natural experiment, DiD, IV, RDD, synthetic control…),
and adds the ones that pass to `data/papers.csv`. When there are new papers it opens a
GitHub issue with a digest table, so you get a notification.

No PDFs are downloaded. Each paper gets up to three links:

| Column | What it is |
|---|---|
| `oa_url` | Free copy (arXiv, SSRN, NBER, author or OA journal version), when one exists |
| `proxy_url` | Publisher page via the CBS Library proxy; you log in with your CBS account |
| `doi_url` | Permanent DOI link to the publisher version |

The repo stores only metadata, links and Claude's own one-line summaries, never
publishers' abstracts, so it can be public or private.

## Setup (about 10 minutes)

1. **Create the repo.** Make a new GitHub repository and push these files to it.
2. **Add secrets.** In the repo: *Settings → Secrets and variables → Actions → New repository secret*.
   - `ANTHROPIC_API_KEY` (required): from console.anthropic.com. Screening uses Claude Haiku
     with one short call per new abstract, so a weekly run is cheap; check current pricing
     on the Anthropic site.
   - `CONTACT_EMAIL` (recommended): sent to OpenAlex so you get its faster "polite pool".
   - `OPENALEX_API_KEY` (optional): only needed if OpenAlex requires a key for your usage.
3. **Allow the workflow to write.** *Settings → Actions → General → Workflow permissions*:
   choose "Read and write permissions".
4. **Turn on issue notifications.** Click *Watch* on the repo (Custom → Issues) to get the
   digest by email.
5. **Run it once.** *Actions → Weekly literature check → Run workflow*. The first run
   looks back `lookback_days` (14). For a one-off backfill, set it higher (e.g. 365) in
   `config.yaml`, run once, then set it back.

## Test the CBS link

Open any `proxy_url` from the CSV. You should land on the CBS login and then the article.
If the link fails, CBS may have changed its proxy: find the current prefix on the CBS
Library website (look for "remote access" or a library browser extension) and update
`proxy_prefix` in `config.yaml`. Links already in the CSV are not rewritten automatically;
a find-and-replace on the CSV fixes them.

## Tuning

Everything lives in `config.yaml`:

- `queries`: add or remove search phrases. Broad queries cost more screening calls.
- `causal_designs`: what counts as causal. Add "structural model" if you want those too.
- `min_relevance`: raise to 3 for only core papers.
- `topic`: the description Claude screens against. Make it specific.

Papers Claude rejects are recorded in `data/seen.txt`, so they aren't screened again.
Delete a line there to have a paper re-screened.

## Run locally

```bash
pip install -r requirements.txt
python -m tracker.run --dry-run         # just list what the searches find
ANTHROPIC_API_KEY=sk-... python -m tracker.run
```

## Coverage notes

OpenAlex indexes most journals, SSRN and NBER working papers, and many institutional
repositories, but new working papers can appear there with a delay of days to weeks.
The 14-day lookback overlaps weekly runs to catch late arrivals. For anything that must
not be missed, keep NBER and SSRN email alerts alongside this.

Screening is done from title and abstract only, so treat the design label as a first
pass: always check the paper before citing it.
