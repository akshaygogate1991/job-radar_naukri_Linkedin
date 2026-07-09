# Job Radar — automated job application assistant

Scrapes Naukri, LinkedIn and Hirist for matching roles, tailors a resume to each
job description with AI, auto-applies where possible, and surfaces everything it
couldn't auto-apply to in a **Streamlit dashboard** — with the job link, a ready
cover letter, and a one-click "Mark Applied" so nothing is applied to twice.

## How it works

- **Scraper (laptop only):** `run_agent.py` runs the LinkedIn / Naukri / Hirist
  bots (Playwright). Jobs it can't auto-apply to are pushed to the dashboard.
- **Dashboard:** `dashboard.py` (Streamlit) shows those jobs. Runs locally, or on
  Streamlit Cloud backed by Supabase so it works on your phone anywhere.

## Run locally

```bash
pip install -r requirements-bot.txt
playwright install chromium
cp secret_config.example.py secret_config.py   # then fill in your values
python run_agent.py          # scrape + apply
python -m streamlit run dashboard.py   # open the dashboard
```

## Deploy to the cloud (mobile access)

See **[SETUP_CLOUD.md](SETUP_CLOUD.md)** for step-by-step GitHub + Streamlit Cloud
+ Supabase instructions.

## Secrets

All credentials live in `secret_config.py` (gitignored) locally, or in Streamlit
Cloud / Supabase secrets in the cloud. Nothing sensitive is committed.
