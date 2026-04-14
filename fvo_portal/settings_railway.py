from .settings import *
import os
import dj_database_url

DEBUG = False

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

railway_public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
if railway_public_domain:
    ALLOWED_HOSTS.append(railway_public_domain)

CSRF_TRUSTED_ORIGINS = []
if railway_public_domain:
    CSRF_TRUSTED_ORIGINS.append(f"https://{railway_public_domain}")

DATABASES = {
    "default": dj_database_url.config(
        conn_max_age=600,
        ssl_require=False,
    )
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
