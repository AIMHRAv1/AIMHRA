"""
Django settings for the AIMHRA project
(Hybrid AI-Based Maternal Health Risk Analysis and Decision-Support System).

All secrets and deployment-specific values come from environment variables
(see .env.example). Defaults are safe for local development only.
"""
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.getenv("DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
if DEBUG:
    ALLOWED_HOSTS.append("testserver")  # Django test client host

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    # project apps
    "core",
    "audit",
    "accounts",
    "patients",
    "assessments",
    "mlcore",
    "kb",
    "chat",
    "reports",
    "advisory",
    "ocr",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.StructuredErrorMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: SQLite by default; DATABASE_URL respected when provided
# (postgres://user:pass@host:port/name or mysql://...). Parse manually to avoid
# an extra dependency.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
    import dj_database_url  # optional, only needed for postgres deployments

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
elif DATABASE_URL.startswith("mysql://"):
    from urllib.parse import urlparse

    p = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": p.path.lstrip("/"),
            "USER": p.username or "",
            "PASSWORD": p.password or "",
            "HOST": p.hostname or "",
            "PORT": p.port or 3306,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_RATES": {"ocr_extract": "60/hour"},
    "EXCEPTION_HANDLER": "core.exceptions.structured_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AIMHRA API",
    "DESCRIPTION": "Hybrid AI-Based Maternal Health Risk Analysis and Healthcare Decision-Support System",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER": "accounts.serializers.CustomTokenObtainPairSerializer",
    "TOKEN_REFRESH_SERIALIZER": "accounts.serializers.CustomTokenRefreshSerializer",
}

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# ML configuration
# ---------------------------------------------------------------------------
DATASET_PATH = os.getenv("DATASET_PATH", "data/Mathernal_Risk.csv")
ML_ARTIFACTS_DIR = BASE_DIR / os.getenv("ML_ARTIFACTS_DIR", "ml_artifacts")
MODEL_SELECTION_CRITERION = os.getenv("MODEL_SELECTION_CRITERION", "high_risk_recall_then_f1")

# ---------------------------------------------------------------------------
# LLM / RAG configuration
# ---------------------------------------------------------------------------
# Completely offline: answers come from a locally-running OpenAI-compatible
# model server (Ollama by default; a llama.cpp server works via LLM_BASE_URL).
# No cloud API is ever contacted. If the local server is down, the chat and
# advisory features degrade to an extractive knowledge-base fallback.
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()  # optional; local servers need none
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b").strip()
# OCR (report-card scanning) — optional feature; engine probed lazily.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
# OCR engine selection: "tesseract" (default) | "easyocr" (fallback to
# tesseract when EasyOCR is not installed). Engines load lazily on first use.
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract").strip().lower()
OCR_ALLOW_GPU = os.getenv("OCR_ALLOW_GPU", "0") == "1"
# LLM-assisted extraction of fields the regex parser missed (local Ollama;
# temperature 0; keep_alive=0 so it never stays resident beside another model).
OCR_LLM_MODEL = os.getenv("OCR_LLM_MODEL", "").strip()
# Optional vision-model stage — DISABLED by default; small models only.
OCR_VISION_ENABLED = os.getenv("OCR_VISION_ENABLED", "0") == "1"
OCR_VISION_MODEL = os.getenv("OCR_VISION_MODEL", "qwen2.5vl:3b").strip()
# Optional hard-threshold variant pass (usually hurts decimals; off by default).
OCR_THRESHOLD_PASS = os.getenv("OCR_THRESHOLD_PASS", "0") == "1"
# Step 3: cross-engine voting with a second OCR engine (EasyOCR), per-field.
OCR_SECOND_ENGINE = os.getenv("OCR_SECOND_ENGINE", "1") == "1"
# Fine-tuned EasyOCR recognition network produced by `manage.py ocr_train`
# (trained on the report/reports corpus). OPT-IN: measured page-level field
# accuracy was 96.7% vs 98.4% for the stock model on the held-out corpus
# (2026-11-15 eval), so the stock recognizer stays the default. Set e.g.
# OCR_EASYOCR_RECOG_NETWORK=aimhra_report to use the fine-tuned model.
OCR_EASYOCR_RECOG_NETWORK = os.getenv("OCR_EASYOCR_RECOG_NETWORK", "").strip()
# Directory that holds EasyOCR models (detector + custom .pth). Empty = the
# easyocr default (~/.EasyOCR).
OCR_EASYOCR_MODEL_DIR = os.getenv("OCR_EASYOCR_MODEL_DIR", "").strip()
# Step 3: capture-quality gate (min width, blur) — hard gate with a retake message.
OCR_MIN_WIDTH = int(os.getenv("OCR_MIN_WIDTH", "1200"))
OCR_MIN_BLUR_VAR = float(os.getenv("OCR_MIN_BLUR_VAR", "40"))
OCR_ALLOW_LOW_QUALITY = os.getenv("OCR_ALLOW_LOW_QUALITY", "0") == "1"
# Step 3: per-fix toggles used by the ablation evaluation.
OCR_ENABLE_UPSCALE = os.getenv("OCR_ENABLE_UPSCALE", "1") == "1"
OCR_ENABLE_CLAHE = os.getenv("OCR_ENABLE_CLAHE", "1") == "1"
OCR_ENABLE_FUZZY = os.getenv("OCR_ENABLE_FUZZY", "1") == "1"
OCR_ENABLE_SUGGESTIONS = os.getenv("OCR_ENABLE_SUGGESTIONS", "1") == "1"
# Step 3: QR-code fast path (decode fields from a QR before falling back to OCR).
OCR_ENABLE_QR = os.getenv("OCR_ENABLE_QR", "1") == "1"
# Use the packaged tessdata_best LSTM data (better digits/decimals).
OCR_TESSDATA_BEST = os.getenv("OCR_TESSDATA_BEST", "1") == "1"

LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").strip().lower()
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "local").strip().lower()
VECTOR_DB_URL = os.getenv("VECTOR_DB_URL", "").strip()
VECTOR_DB_API_KEY = os.getenv("VECTOR_DB_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# Email (password reset architecture)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "webmaster@aimhra.local")

# ---------------------------------------------------------------------------
# Logging (structured, avoids sensitive medical payloads)
# ---------------------------------------------------------------------------
BASE_DIR.joinpath("logs").mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "aimhra.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "mlcore": {"level": "INFO"},
        "chat": {"level": "INFO"},
        "kb": {"level": "INFO"},
    },
}
