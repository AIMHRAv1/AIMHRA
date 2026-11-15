# AIMHRA

AI-based Maternal Health Risk Assessment and decision-support system
(Django REST backend + React frontend).

---

## Getting Started (new device)

### 0. Prerequisites — system installs

| Tool | Version | Why | Notes |
| --- | --- | --- | --- |
| Git | any | clone the repo | |
| Python | 3.12 recommended (3.10+ required) | Django backend + ML | [python.org](https://www.python.org/downloads/) — tick "Add to PATH" on Windows |
| Node.js | 20.19+ or 22+ (Vite 8) | React frontend | [nodejs.org](https://nodejs.org) |
| Tesseract OCR | 5.x | report-card scanning (pytesseract wraps it) | Windows: [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki); if `tesseract` is not on PATH set `TESSERACT_CMD` in `backend/.env` |
| Ollama | latest | offline AI chat/advisory (optional) | see step 4 — app degrades gracefully without it |

GPU (optional, **NVIDIA only**): the repo ships `torch>=2.0` which installs the
**CPU** wheel by default — that works on every machine. For EasyOCR on an
NVIDIA GPU install the CUDA build matching your card:

```bash
# RTX 20/30/40 series (e.g. RTX 3050, driver >= 551.61):
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
# RTX 50 series / Blackwell (e.g. RTX 5060, torch >= 2.7, driver >= 572):
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

AMD/Intel GPUs and Apple Silicon should keep the default CPU wheels.
Verify any install with:
`python -c "import torch; print(torch.cuda.is_available())"`

### 1. Clone the repository

```bash
git clone <repo-url>
cd AIMHRA/v1
```

### 2. Backend (Django)

```bash
# from the repo root
python -m venv .venv
.venv\Scripts\activate            # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r backend/requirements.txt
```

Environment file — defaults are safe for local development:

```bash
cp backend/.env.example backend/.env
```

Create the database (SQLite by default; `DATABASE_URL` switches to Postgres)
and the first admin account — `createsuperuser` assigns the `ADMIN` role
automatically:

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
```

There is **no public self-registration** — additional staff accounts are
created by an admin via the frontend **Admin → Users** page, the API
(`POST /api/auth/users/`), or Django admin. They start as
`HEALTHCARE_WORKER`s.

**Train the ML models** — trained model files (`backend/ml_artifacts/`) are
gitignored, so a fresh clone has none. The dataset is included
(`backend/data/Mathernal_Risk.csv`):

```bash
python manage.py train_models --quick   # fast smoke run, nothing registered
python manage.py train_models           # full training, registers model versions
```

Run the API:

```bash
python manage.py runserver             # http://localhost:8000
```

### 3. Frontend (React + Vite)

```bash
# in a second terminal, from the repo root
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

The Vite dev server proxies `/api` and `/media` to `http://localhost:8000`
(override with `VITE_API_PROXY_TARGET`). To point the app at a different API
host entirely, set `VITE_API_BASE_URL` in `frontend/.env`.

### 4. Offline AI (Ollama)

1. Install [Ollama](https://ollama.com) and pull a small model:
   `ollama pull llama3.2:3b`
2. Keep Ollama running (`ollama serve`, or the desktop app). The app talks to
   `http://localhost:11434/v1` by default (`LLM_BASE_URL`).

Without Ollama nothing crashes: chat and care advisory degrade to an
extractive knowledge-base fallback. OCR also uses a local Ollama model to
rescue fields the regex parser missed (`OCR_LLM_MODEL`, default `llama3.2:3b`).

### 5. Verify the setup

1. Open `http://localhost:8000/admin` and log in with the superuser.
2. Open `http://localhost:5173`, register/log in, and submit a risk
   assessment — the dashboard charts and the Care Advisory tab should work.
3. Knowledge base (RAG) starts empty on a new device: upload trusted documents
   via Django admin → Knowledge documents (they are chunked and indexed
   automatically; embeddings are local TF-IDF, fully offline).
4. OCR smoke check (optional): start from the frontend's report-scan page, or
   `python manage.py ocr_eval` with a generated sample card.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `tesseract is not installed` | install Tesseract or set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` |
| Chat answers are extractive/marked `rag_only_fallback` | Ollama not running or wrong `LLM_BASE_URL` |
| Assessment endpoint returns engine unavailable | run `python manage.py train_models` |
| CORS errors in browser | backend `CORS_ALLOWED_ORIGINS` must include `http://localhost:5173` (default in `.env.example`) |
| EasyOCR slow on CPU | expected without the CUDA torch build; see GPU install above |

---

## Offline AI (local LLM)

The AI assistant (chat) and the care advisory system run **completely offline** —
no cloud API is ever contacted. Answers are generated by a locally-running
OpenAI-compatible model server, grounded in the trusted knowledge base (RAG).

### Configuration (optional, via environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible local server (e.g. llama.cpp `--host`/vLLM) |
| `LLM_MODEL` | `llama3.2:3b` | Model tag the server should use |
| `LLM_TIMEOUT_SECONDS` | `120` | Local CPU inference can be slow |
| `LLM_API_KEY` | *(empty)* | Only needed if your local server requires a key |
| `EMBEDDING_BACKEND` | `local` | Keep `local` (TF-IDF) for offline embeddings |

### Care Advisory

After a risk assessment is submitted, open the **Care Advisory** tab (or the
advisory card in the assessment result) and press "Generate care advice".
For dangerous situations (e.g. heavy bleeding, convulsions) the advisory leads
with a strong warning to go to the nearest hospital/doctor **and** still gives
practical advice on what to do while arranging care.
