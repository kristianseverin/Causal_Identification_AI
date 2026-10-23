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

## How a run works

1. `python -m tracker.run discover` searches and writes the new candidates to
   `data/candidates.json`, with instructions in `data/screening_task.md`.
2. The Claude Code GitHub Action screens them **using your Claude subscription**
   (no API key, no separate billing) and writes `data/screened.json`. It is only allowed
   to read and write files: no shell, no web, no GitHub access.
3. `python -m tracker.run finalize` stores the accepted papers, writes the digest and
   deletes the temporary files.

Each run screens at most `max_screen_per_run` papers (150) with Claude Haiku, so it uses
a small share of your subscription's usage limits.

## Setup (about 15 minutes)

1. **Create the repo.** Make a new GitHub repository and push these files to it.
2. **Get a subscription token** (on a computer where you can install Claude Code):
   - Install Claude Code. Windows PowerShell: `irm https://claude.ai/install.ps1 | iex`
     · macOS/Linux: `curl -fsSL https://claude.ai/install.sh | bash`
   - Open a **new** terminal and run `claude setup-token`. Approve in the browser that opens
     (log in with the Claude account that has your paid plan).
   - The token is printed in the terminal. Copy it now; it isn't saved anywhere.
     It is valid for one year (see *Renewing the token*).
3. **Add secrets.** In the repo: *Settings → Secrets and variables → Actions → New repository secret*.
   - `CLAUDE_CODE_OAUTH_TOKEN` (required): the token from step 2.
   - `OPENALEX_API_KEY` (required): free key from openalex.org. Since early 2026 OpenAlex
     needs a key for search calls; the free daily allowance is far more than the
     8 searches this makes per week.
   - `CONTACT_EMAIL` (optional): your email, sent to OpenAlex as a courtesy contact.
4. **Allow the workflow to write.** *Settings → Actions → General → Workflow permissions*:
   choose "Read and write permissions".
5. **Turn on issue notifications.** Click *Watch* on the repo (Custom → Issues) to get the
   digest by email.
6. **Run it once.** *Actions → Weekly literature check → Run workflow*. The first run
   looks back `lookback_days` (14). For a backfill, set it higher (e.g. 365) in
   `config.yaml` and run it a few times: each run screens up to 150 papers and the rest
   wait for the next run. Then set it back to 14.

If the "Screen with Claude" step fails with a message about the Claude GitHub App,
install the app on the repo from github.com/apps/claude and run again.

## Renewing the token

The subscription token lasts one year. When it expires, the "Screen with Claude" step
fails with an authentication error. Run `claude setup-token` again and replace the
`CLAUDE_CODE_OAUTH_TOKEN` secret. Nothing is lost: unscreened papers are retried on the
next run.

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
export OPENALEX_API_KEY=...
python -m tracker.run dry-run           # just list what the searches find
```

If you ever get a Claude API key, `python -m tracker.run api` does the whole run
locally (search, screen, store) without Claude Code.

## Coverage notes

OpenAlex indexes most journals, SSRN and NBER working papers, and many institutional
repositories, but new working papers can appear there with a delay of days to weeks.
The 14-day lookback overlaps weekly runs to catch late arrivals. For anything that must
not be missed, keep NBER and SSRN email alerts alongside this.

Screening is done from title and abstract only, so treat the design label as a first
pass: always check the paper before citing it.
