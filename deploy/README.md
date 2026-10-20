# Deploying to Vercel (dashboard + live scenario builder + dashboard assistant)

What you get: the dashboard at `/` and two functions: `POST /api/scenario` (natural-language scenario builder) and `POST /api/ask` (the "Ask" panel, D34: answers only from `ask_facts.json`, every number checked). The Ask button appears only where `/api/ask` exists. The Anthropic key exists
only as an environment variable on Vercel, never in the page. The function is untested on Vercel itself
until the first deploy; it is tested locally over HTTP with a fake LLM client (`tests/test_deploy_function.py`).

## Before you deploy: protect your money

1. Create an API key in the Anthropic Console for this project only (not your main one).
2. Set a **monthly spend limit of $10** on that account/workspace in the Console (look under the
   billing/limits settings). This is the hard cap; nothing in the code can replace it.
3. At the default model (`claude-haiku-5-5`, $0.10 / $0.50 per million tokens) one request costs a
   small fraction of a cent, so $10 covers tens of thousands of requests. Verify on the Console's
   usage page after the first few calls.

## Deploy

```bash
python run.py                  # builds outputs/dashboard.html and outputs/shock_basis.json
python deploy/prepare.py       # copies them (and two source files) into deploy/
cd deploy
npx vercel login               # once
npx vercel --prod              # answer the prompts; root directory = deploy/
```

Then in the Vercel dashboard: Project → Settings → Environment Variables → add
`ANTHROPIC_API_KEY` (Production). Redeploy once so the function sees it. Do not paste the key anywhere else.

Optional variables: `HICP_NL_MODEL` (default `claude-haiku-5-5`), `HICP_NL_PER_MINUTE` (default 6),
`HICP_NL_PER_DAY_INSTANCE` (default 200).

## Limits to know

- The per-IP rate limit is in memory, per serverless instance: it slows one client down, it does not
  guarantee a ceiling. The spend limit is the ceiling.
- If the function or the key is down, the site still works: the simulator, presets and recorded
  examples do not need the LLM. `outputs/dashboard.html` also works offline by double-click.
- The page is public to anyone with the link. It contains only public Eurostat data and our results.
