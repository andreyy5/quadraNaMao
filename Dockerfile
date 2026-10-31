# Etapa 1: compila o CSS e copia as bibliotecas de front-end.
FROM node:24-slim AS assets
WORKDIR /app
COPY package.json package-lock.json tailwind.config.js ./
COPY scripts/copy_vendor.mjs scripts/
COPY assets assets
COPY templates templates
COPY apps apps
COPY static static
RUN npm ci && npm run build

# Etapa 2: aplicação Python.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements requirements
RUN pip install --no-cache-dir -r requirements/prod.txt
COPY . .
COPY --from=assets /app/static static
RUN SECRET_KEY=build DATABASE_URL=postgres://build:build@localhost/build \
    DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
