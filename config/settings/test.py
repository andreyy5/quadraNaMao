from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PIX_PROVIDER = "simulado"
WHATSAPP_PROVIDER = "console"
WHATSAPP_APP_SECRET = "segredo-de-teste"
WHATSAPP_VERIFY_TOKEN = "token-de-teste"
SITE_URL = "https://quadranamao.test"
