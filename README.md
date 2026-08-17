# Cloth — Clothing Search Application

A web application that lets you describe a clothing item in plain English and instantly see matching products from real retailers.

## Quick start

### Prerequisites
- Python 3.11+

### Setup

1. Clone the repository and navigate to the `cloth/` directory
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate      # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env and add your SERPAPI_KEY
   ```
5. Run the development server:
   ```bash
   uvicorn main:app --reload
   ```
6. Open http://localhost:8000 in your browser.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SERPAPI_KEY` | Yes | — | Your SerpAPI API key. Get one at serpapi.com |
| `PORT` | No | `8000` | Port to listen on |
| `ENVIRONMENT` | No | `development` | Set to `production` to disable debug output |

## Deployment: single-worker constraint

The application uses in-process state for caching and rate limiting. **Always run with a single worker:**

```bash
uvicorn main:app --workers 1 --host 0.0.0.0 --port $PORT
```

Running with `--workers N` (N > 1) or setting `WEB_CONCURRENCY > 1` causes independent per-worker counters — rate limits and the SerpAPI budget tracker multiply silently. The application emits a `startup_warning` log event and console warning if multiple workers are detected. See OPERATIONS.md for details.

## Deploying to Render.com

Render's free tier works well for this app. A cold-start after 15 minutes of inactivity takes ~30 seconds — see UptimeRobot below to avoid this.

### 1. Push to GitHub

```bash
# From the repo root (not cloth/)
git remote add origin https://github.com/whiteyoh/cloth.git
git push -u origin main
```

### 2. Create a Render Web Service

1. Sign in at [render.com](https://render.com) and click **New → Web Service**.
2. Connect your GitHub account and select the `whiteyoh/cloth` repository.
3. Configure the service:

| Setting | Value |
|---------|-------|
| **Name** | `cloth` (or your choice) |
| **Root Directory** | *(leave blank)* |
| **Environment** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | Free |

> Do **not** set `--workers` or `WEB_CONCURRENCY > 1` — the app requires a single worker.

### 3. Set environment variables

In **Environment → Environment Variables**, add:

| Key | Value | Required |
|-----|-------|----------|
| `SERPAPI_KEY` | Your SerpAPI key from [serpapi.com](https://serpapi.com) | Yes |
| `ENVIRONMENT` | `production` | Recommended |
| `ANTHROPIC_API_KEY` | Your Anthropic key (enables AI query expansion) | Optional |
| `FASHN_API_KEY` | Your Fashn.ai key (enables virtual try-on) | Optional |

### 4. Deploy

Click **Create Web Service**. Render will build and deploy automatically. The URL appears in the dashboard — it looks like `https://cloth-xxxx.onrender.com`.

### 5. Prevent free-tier cold starts (recommended)

Free tier services spin down after 15 minutes of inactivity. Use [UptimeRobot](https://uptimerobot.com) (free) to ping the app every 5 minutes and keep it warm:

1. Sign in at uptimerobot.com → **+ Add New Monitor**.
2. Monitor Type: **HTTP(S)**.
3. URL: your Render URL, e.g. `https://cloth-xxxx.onrender.com/health`.
4. Monitoring Interval: **5 minutes**.
5. Click **Create Monitor**.

### 6. Post-deploy smoke test

```bash
# Replace with your actual Render URL
export BASE=https://cloth-xxxx.onrender.com

# Health check
curl -sf "$BASE/health" | python3 -m json.tool

# Search (first call may take 30s on a cold-start free tier)
curl -sf "$BASE/search?q=navy+chinos&format=json" | python3 -m json.tool | head -20
```

### Subsequent deploys

Render redeploys automatically on every push to `main`. You can also trigger a manual deploy from the Render dashboard.

---

## Running tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

## Project structure

```
cloth/
├── main.py          # FastAPI app — routes and startup
├── search.py        # SerpAPI integration and product mapping
├── cache.py         # In-memory LRU+TTL cache
├── models.py        # Canonical Product model
├── templates/       # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   └── results.html
├── static/
│   ├── css/style.css
│   └── js/app.js
└── tests/
    ├── test_search.py
    ├── test_cache.py
    └── test_models.py
```
