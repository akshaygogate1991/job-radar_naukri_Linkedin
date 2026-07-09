# Deploy to the cloud — mobile access (GitHub + Streamlit Cloud + Supabase)

Do these in order. Total time ~30–40 min. You only do this setup once.

The split you're building:
- **Scraper** stays on your laptop (`run_agent.py`) — it needs your real browser logins.
- **Dashboard** runs on Streamlit Cloud and reads from **Supabase**, so it's live on your phone anywhere.
- After each scrape, your laptop pushes jobs to Supabase automatically.

---

## STEP 0 — Safety check (important)

Your passwords were typed during setup. Before going public, change your
LinkedIn/Naukri/Hirist password and regenerate your Gmail App Password, then
update them in `secret_config.py`. `secret_config.py` is gitignored and will
NOT be uploaded.

---

## STEP 1 — Create the Supabase database

1. Go to https://supabase.com → sign in → **New project**.
   - Name: `job-radar`
   - Region: **Mumbai (ap-south-1)**
   - Set a database password (save it somewhere).
2. Wait ~2 min for it to provision.
3. Left sidebar → **SQL Editor** → **New query** → paste this and click **Run**:

```sql
create table if not exists jobs (
  url          text primary key,
  title        text,
  company      text,
  platform     text,
  score        int default 0,
  cover_letter text,
  summary      text,
  notes        text,
  first_seen   timestamptz default now(),
  status       text default 'pending',
  applied_at   timestamptz
);
```

4. Left sidebar → **Project Settings** → **API**. Copy two things:
   - **Project URL** (e.g. `https://booxshfeikueakgtkqib.supabase.co`)
   - **service_role** key (under "Project API keys" — click reveal). Treat this
     like a password. Never paste it into code or GitHub.

5. Open `secret_config.py` on your laptop and fill in:

```python
SUPABASE_URL = "https://<your-project>.supabase.co"
SUPABASE_KEY = "<your service_role key>"
```

6. Push your existing jobs up once:

```powershell
cd "D:\Naukari CV\job automation"
python sync_to_cloud.py
```

You should see `Synced N jobs to Supabase.`

---

## STEP 2 — Put the code on GitHub

1. Go to https://github.com/new (sign in as `akshaygogate1991`).
   - Repository name: `job-radar`
   - Visibility: **Public** (so you can show interviewers) — or Private, your call.
   - Do **NOT** add a README/.gitignore (you already have them).
   - Click **Create repository**.

2. In VS Code terminal:

```powershell
cd "D:\Naukari CV\job automation"
git init
git add .
git status
```

3. **CHECK THE `git status` OUTPUT.** Confirm these are **NOT** listed (they must be
   ignored): `secret_config.py`, `logs/`, `resumes/`. If any of them appear, stop
   and tell me before pushing.

4. If the check is clean:

```powershell
git commit -m "Job radar: scraper + dashboard"
git branch -M main
git remote add origin https://github.com/akshaygogate1991/job-radar.git
git push -u origin main
```

(If git asks you to sign in, a browser window opens — approve it.)

---

## STEP 3 — Deploy the dashboard on Streamlit Cloud

1. Go to https://share.streamlit.io → **Sign in with GitHub**.
2. **Create app** → **Deploy a public app from GitHub**.
   - Repository: `akshaygogate1991/job-radar`
   - Branch: `main`
   - Main file path: `dashboard.py`
   - (Optional) Custom subdomain: `akshay-job-radar` → URL becomes
     `https://akshay-job-radar.streamlit.app`
3. Click **Advanced settings → Secrets** and paste (TOML format):

```toml
SUPABASE_URL = "https://<your-project>.supabase.co"
SUPABASE_KEY = "<your service_role key>"
```

4. Click **Deploy**. First build takes 1–3 min.
5. Open the app URL on your **phone**. You should see your jobs. The header will
   say **"data source: ☁️ Supabase"**.

---

## Daily use from now on

1. On your laptop: `python run_agent.py`
   (it scrapes, applies, and auto-pushes new jobs to Supabase at the end).
2. On your phone: open `https://akshay-job-radar.streamlit.app`, tap **Reload**.
   Apply, download the resume, tap **Mark Applied** — it updates Supabase, so it's
   marked everywhere.

That's it. The laptop must be run to *fetch* new jobs, but *viewing/applying*
works on your phone anytime, even with the laptop off.

---

## Notes

- The `service_role` key lives only in `secret_config.py` (laptop) and Streamlit
  Cloud Secrets (server-side) — never in the public repo. Keep it that way.
- Resume PDFs aren't uploaded (they're gitignored). On the cloud dashboard, a
  tailored resume is regenerated on the spot from the stored summary.
- To update the deployed app later: `git add . && git commit -m "..." && git push`
  — Streamlit Cloud redeploys automatically.
