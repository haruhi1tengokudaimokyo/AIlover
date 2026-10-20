"""Opt-in cloud settings. Desktop launcher continues to use backend.settings."""
import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

DEBUG = False
if not os.getenv('SECRET_KEY') or len(os.environ['SECRET_KEY']) < 32:
    raise ImproperlyConfigured('Production requires a SECRET_KEY of at least 32 characters')
ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', '').split(',') if host.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Production requires explicit ALLOWED_HOSTS')
ASGI_APPLICATION = 'backend.asgi.application'
STATIC_ROOT = DATA_DIR / 'static-collected'  # noqa: F405
WHITENOISE_USE_FINDERS = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_TRUSTED_ORIGINS = [url for url in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if url]
CORS_ALLOWED_ORIGINS = [url for url in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if url]
REST_FRAMEWORK = {**REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'anon': '60/min', 'user': '120/min', 'chat': '12/min'},
}
if os.getenv('POSTGRES_DB'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['POSTGRES_DB'], 'USER': os.environ['POSTGRES_USER'],
        'PASSWORD': os.environ['POSTGRES_PASSWORD'], 'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'), 'CONN_MAX_AGE': 0,
        'OPTIONS': {'sslmode': os.getenv('POSTGRES_SSLMODE', 'require')},
    }}
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'formatters': {'event': {'format': '{asctime} level={levelname} logger={name} message={message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'event'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
