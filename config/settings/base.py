from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

PRODUCT_NAME = "QuadraNaMão!"

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "apps.estabelecimentos",
    "apps.contas",
    "apps.espacos",
    "apps.clientes",
    "apps.agenda",
    "apps.financeiro",
    "apps.estoque",
    "apps.pdv",
    "apps.whatsapp",
    "apps.relatorios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.estabelecimentos.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.estabelecimentos.context_processors.product",
                "apps.financeiro.context_processors.open_register",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "contas.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "contas:login"
# Link de "esqueci a senha": vale por 2 horas e só funciona uma vez.
PASSWORD_RESET_TIMEOUT = 2 * 60 * 60
LOGIN_REDIRECT_URL = "relatorios:dashboard"
LOGOUT_REDIRECT_URL = "contas:login"

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BEAT_SCHEDULE = {
    "gerar-contas-recorrentes": {
        "task": "apps.financeiro.tasks.generate_all_recurring_accounts",
        "schedule": 60 * 60 * 24,
    },
    "gerar-reservas-de-mensalistas": {
        "task": "apps.agenda.tasks.generate_mensalista_reservations",
        "schedule": 60 * 60 * 24,
    },
    "expirar-sinais-vencidos": {"task": "apps.agenda.tasks.expire_pending", "schedule": 60 * 5},
    "enviar-lembretes": {"task": "apps.whatsapp.tasks.send_due_reminders", "schedule": 60 * 10},
}

# Endereço público do sistema, usado nos links mandados por WhatsApp (pagamento do sinal).
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")

# Pix: "estatico" gera o copia e cola com a chave do estabelecimento; a equipe confirma o pagamento.
PIX_PROVIDER = env("PIX_PROVIDER", default="estatico")

# Módulo de WhatsApp automático (Fase 5). Em espera: desligado, some do menu e não manda nada.
WHATSAPP_ENABLED = env.bool("WHATSAPP_ENABLED", default=False)
# WhatsApp: "console" só registra no histórico; "cloud" usa a Cloud API da Meta (docs/whatsapp.md).
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="console")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_API_VERSION = env("WHATSAPP_API_VERSION", default="v21.0")

# Cache: em memória por padrão. Em produção com vários processos, aponte para o Redis em CACHE_URL,
# para o limite de tentativas valer entre todos eles.
CACHES = {"default": env.cache_url("CACHE_URL", default="locmemcache://")}

# Quantos proxies reversos (nginx, balanceador) ficam na frente do Django. Com 0, vale o REMOTE_ADDR.
# Usado no limite de tentativas: errar aqui faz todo mundo dividir o mesmo limite ou permite burlá-lo.
NUM_PROXIES = env.int("NUM_PROXIES", default=0)

# E-mail (recuperação de senha). EMAIL_URL no formato do django-environ, por exemplo
# smtp+tls://usuario:senha@smtp.provedor.com:587 (caracteres especiais da senha codificados, como %40).
# Sem EMAIL_URL, o e-mail aparece no terminal do servidor.
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=f"{PRODUCT_NAME} <nao-responda@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_TIMEOUT = 15
