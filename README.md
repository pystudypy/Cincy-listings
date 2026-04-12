# CincyListings — Cincinnati Real Estate Aggregator

All Cincinnati listings in one place — Zillow, Redfin, Sibcy Cline, Huff Realty, Comey & Shepherd, and more.

**Zero hosting cost.** Scrapers run free on GitHub Actions. Frontend is a static site on GitHub Pages.

---

## Quick start (local)

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Run all scrapers (writes data/listings.json)
python run_scrapers.py

# 3. Open the frontend
open frontend/index.html
# or serve it:
python -m http.server 8000 --directory frontend
# → http://localhost:8000
```

## Deploying for free (GitHub Pages)

1. Push this repo to GitHub
2. Go to **Settings → Pages → Source**: deploy from branch `main`, folder `/frontend`
3. GitHub Pages will serve `frontend/index.html` at `https://yourusername.github.io/repo-name/`
4. The scraper runs daily via `.github/workflows/scrape.yml` and commits fresh data automatically

> **Note:** GitHub Pages serves static files. The frontend reads `../data/listings.json` relative to the page.
> Make sure `data/listings.json` is committed to your repo.

---

## Scrapers

| Source | File | Notes |
|--------|------|-------|
| Zillow | `scrapers/zillow.py` | Extracts from `__NEXT_DATA__` JSON blob |
| Redfin | `scrapers/redfin.py` | Uses Redfin's internal GIS/stingray API |
| Sibcy Cline | `scrapers/local_sites.py` | Largest Cincinnati brokerage |
| Huff Realty | `scrapers/local_sites.py` | Local IDX feed |
| Comey & Shepherd | `scrapers/local_sites.py` | Local IDX feed |
| CABR | `scrapers/local_sites.py` | Cincinnati Area Board of Realtors |

## Run options

```bash
# Run a single source only
python run_scrapers.py --source zillow
python run_scrapers.py --source redfin
python run_scrapers.py --source local

# Merge new listings with existing (don't replace)
python run_scrapers.py --merge

# Dry run (print stats, don't write)
python run_scrapers.py --dry-run
```

## Project structure

```
AgenticRealtor/
├── scrapers/
│   ├── zillow.py          # Zillow scraper
│   ├── redfin.py          # Redfin scraper
│   └── local_sites.py     # Sibcy Cline, Huff, Comey, CABR
├── utils/
│   └── deduplicator.py    # Dedup + Cincinnati geo filter
├── data/
│   └── listings.json      # Output — committed to repo
├── frontend/
│   ├── index.html         # Single-page app
│   ├── style.css
│   └── app.js
├── .github/workflows/
│   └── scrape.yml         # Daily GitHub Actions job
├── run_scrapers.py         # Main entry point
└── requirements.txt
```

## Legal note

Zillow and Redfin's ToS prohibit automated data collection. This project is for **personal use only**.
Local brokerage sites may have similar restrictions — check their ToS before use.
