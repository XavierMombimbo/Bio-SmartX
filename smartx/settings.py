"""
Django settings for smartx project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]

# Security
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-for-local-development")
DEBUG = env_bool("DJANGO_DEBUG", True)

# AJOUTEZ CES DOMAINES :
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", [
    '127.0.0.1', 
    'localhost', 
    '192.168.11.101', 
    'bio-smartx.duckdns.org',
    'smartx.bio-smartx.com',      # NOUVEAU
    'app.bio-smartx.com',         # NOUVEAU
    'www.bio-smartx.com',         # NOUVEAU
    'bio-smartx.com',             # NOUVEAU
])

# AJOUTEZ CES LIGNES POUR CSRF :
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [
    'https://smartx.bio-smartx.com',
    'https://app.bio-smartx.com',
    'https://www.bio-smartx.com',
    'https://bio-smartx.com',
])

# AJOUTEZ POUR LES COOKIES SECURES (HTTPS) :
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SAMESITE = 'Lax'

# Authentication
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'
LOGIN_URL = '/login/'
AUTH_USER_MODEL = 'core.User'

# Applications
INSTALLED_APPS = [
    'core',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

# Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# URLs
ROOT_URLCONF = 'smartx.urls'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "core/templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]  # tes fichiers source
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')            # dossier cible pour collectstatic
# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / "media"

# Database
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.mysql'),
        'NAME': os.getenv('DB_NAME', 'smartx_db'),
        'USER': os.getenv('DB_USER', 'SmartX'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '3306'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

# NBIS Configuration
NBIS_BIN = os.getenv('NBIS_BIN', '/home/Dell_Latitude_5400/nbis_build/Rel_5.0.0')
MINDTCT_PATH = os.path.join(NBIS_BIN, 'mindtct/bin/mindtct')
BOZORTH3_PATH = os.path.join(NBIS_BIN, 'bozorth3/bin/bozorth3')

# Biometric thresholds
SEUIL_VISAGE = 0.4  # Facial recognition threshold (0-1)
SEUIL_EMPREINTE = 40  # Fingerprint score threshold (0-100)

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AJOUTEZ CETTE SECTION POUR LE SECURE PROXY :
# Important pour Django derrière Cloudflare
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

APPEND_SLASH = True

# Security recommendations for production
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
else:
    # En développement avec Cloudflare, on garde ces sécurités
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
