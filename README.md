# Daily Digest

A daily email at 7 AM IST that keeps you current and teaches you something, all inside the email.

## What's in each email

- **TL;DR**: the 3 things that mattered today
- **By the numbers**: the 3 most striking figures from today's stories, as stat tiles
- **Top stories + topic sections** (AI, Tech, Product, Fintech, Global Markets): a real summary, why it matters, and one jargon term explained
- **Quick hits**: one-liners for everything else worth knowing
- **Learn**: a structured lesson that alternates Product and Tech fundamentals (tracks defined per template), with a
  diagram (step flow, bar chart or side-by-side comparison) and progress bars for each track
- **Challenge**: a ~15 minute exercise with a difficulty level. The solution arrives in the next day's email

Stories carry the article's own image when the feed or page provides one. All visuals are built from HTML tables
and inline styles, since Gmail strips SVG and scripts.

## Templates

Each file in `templates/` is one email. The current email is `templates/daily.json`. To create another,
copy `templates/example-markets.json`, rename it (the file name becomes the template id), edit it and set
`"enabled": true`. Every enabled template is sent on each run.

| Field | What it does |
|---|---|
| `name` | Title in the email header and the sender name in the inbox |
| `enabled` | `false` keeps the template in the repo without sending it |
| `recipients_env` | Name of a secret holding comma-separated emails, e.g. `DAILY_RECIPIENTS` = `a@x.com, b@y.com`. Use this on a public repo so addresses never enter git. Each person gets their own copy, so nobody sees the others |
| `recipients` | Optional: emails written directly in the file (comma-separated). Fine in a private repo; combined with `recipients_env` if both are set |
| `days` | Days to send, e.g. `["mon","tue","wed","thu","fri"]`. Defaults to every day |
| `audience` | Who the reader is. Shapes story picks, "why it matters", lessons and challenges |
| `topics` | Map of topic key to `label`, optional `color` (hex), `focus` (what to favour) and `sources` (`name`, `url`, optional `slow: true` for weekly newsletters) |
| `learning.goal` | What the lessons should achieve |
| `learning.tracks` | Learning tracks that rotate daily, each with `key`, `name` and an ordered `lessons` list. Leave empty for challenge-only emails |
| `challenge_types` | Challenge formats, rotated by weekday |

Each template makes about 3 LLM calls a day, so a handful of templates fits comfortably in Gemini's free tier.

Each template keeps its own progress in `state/<id>.json`: sent articles, lesson positions and challenges.
Invalid config (bad email, missing sources) stops the run before anything is sent, with a clear error in the log.

## Challenges

Each email ends with a challenge. The next email opens with its full solution: the original question,
approach, a sample answer, what good looks like and common mistakes. If a day is skipped or the
summarizer is down, the solution still arrives in the next email that goes out, so no challenge goes unanswered.

## How it works

1. `fetch.py` pulls each template's feeds (fetched once per run even when shared), keeps fresh items, and dedupes by URL and title
2. `compose.py` asks a free LLM to pick the best stories, then fetches full article text and writes the summaries
3. A second LLM call writes the lesson and the challenge (with its solution, stored for tomorrow)
4. `render.py` builds a Gmail-safe HTML email plus a plain-text version
5. `state/<id>.json` remembers sent URLs, curriculum progress and challenges. The workflow commits it back after each run

If the LLM is unavailable, you still get a headlines-only edition.

## Setup (all free)

Repo secrets (Settings > Secrets and variables > Actions):

| Secret | Required | Where to get it |
|---|---|---|
| `SENDER_EMAIL` | yes | Gmail address that sends the digest |
| `SENDER_APP_PASSWORD` | yes | Gmail app password |
| `DAILY_RECIPIENTS` | yes | Comma-separated recipient emails for `templates/daily.json` (its `recipients_env`). Add one secret, plus one line in `.github/workflows/daily_digest.yml`, for each extra template that uses `recipients_env` |
| `GEMINI_API_KEY` | yes | Free key from [Google AI Studio](https://aistudio.google.com/apikey), no card needed |
| `GROQ_API_KEY` | no | Optional extra fallback from [console.groq.com](https://console.groq.com) |

GitHub Models is used automatically as a backup through the workflow's built-in token.
Note: Google may use free-tier prompts to improve its models. The digest only sends public news content.

Optional overrides: `GEMINI_MODELS` (comma-separated, default `gemini-flash-latest,gemini-flash-lite-latest`). Recipients live in each template file.

## Exact 7 AM delivery

GitHub's built-in schedule often starts jobs hours late, so the workflow has no GitHub schedule. A free external
scheduler triggers it at 7:00 AM IST instead. The digest also refuses to send twice on the same day.

1. Create a fine-grained token at GitHub > Settings > Developer settings > Fine-grained tokens:
   repository access limited to this repo, permission **Actions: Read and write**, and the longest expiry available
2. At [cron-job.org](https://cron-job.org) (free), create a job:
   - URL: `https://api.github.com/repos/OWNER/REPO/actions/workflows/daily_digest.yml/dispatches`
   - Schedule: every day at 07:00, time zone Asia/Kolkata
   - Advanced > Request method: `POST`
   - Headers: `Authorization: Bearer <your token>`, `Accept: application/vnd.github+json`
   - Request body: `{"ref":"main"}`
3. Click "Test run". A new run should appear under Actions within a few seconds (a 204 response means it worked)

## Running

- **Preview without sending**: Actions > Daily AI Digest > Run workflow > tick "dry run". Download the `digest-preview` artifact (one `preview-<id>.html` per template).
- **Locally**: `pip install -r requirements.txt && GEMINI_API_KEY=... python digest.py --dry-run`, then open `preview-daily.html`
- **Feed health**: Actions > Check Feed Health, or `python evaluate_feeds.py`

## Customizing

- Edit sources, topics, lessons and challenge formats in the template's JSON file
- Run one template only: Actions > Daily AI Digest > Run workflow > set "template" to its id (e.g. `daily`)
