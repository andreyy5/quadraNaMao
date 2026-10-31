"""Prepara o PostgreSQL local e gera o .env do projeto.

Uso: python scripts/setup_db.py

Pede a senha do superusuario "postgres" no terminal (ela nao fica salva), cria o
usuario e o banco "quadranamao" e grava a senha gerada apenas no .env. Pode ser
executado de novo: um .env existente nao e sobrescrito e a senha dele e mantida.
"""

import getpass
import os
import re
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
APP_NAME = "quadranamao"


def read_existing_password():
    if not ENV_PATH.exists():
        return None
    match = re.search(
        r"^DATABASE_URL=postgres://[^:]+:([^@]+)@",
        ENV_PATH.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None


def write_env(host, port, password):
    secret_key = secrets.token_urlsafe(50)
    content = (
        "DJANGO_SETTINGS_MODULE=config.settings.dev\n"
        f"SECRET_KEY={secret_key}\n"
        "DEBUG=True\n"
        "ALLOWED_HOSTS=localhost,127.0.0.1\n"
        f"DATABASE_URL=postgres://{APP_NAME}:{password}@{host}:{port}/{APP_NAME}\n"
        "CELERY_BROKER_URL=redis://localhost:6379/0\n"
    )
    # newline="\n" e sem BOM: o leitor de .env nao aceita BOM no inicio do arquivo.
    with ENV_PATH.open("w", encoding="utf-8", newline="\n") as env_file:
        env_file.write(content)


def main():
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    admin_user = os.environ.get("PGUSER", "postgres")

    admin_password = getpass.getpass(f"Senha do usuario '{admin_user}' do PostgreSQL ({host}:{port}): ")

    # token_hex evita caracteres que precisariam de escape na DATABASE_URL.
    existing_password = read_existing_password()
    password = existing_password or secrets.token_hex(24)

    try:
        admin = psycopg.connect(
            host=host,
            port=port,
            user=admin_user,
            password=admin_password,
            dbname="postgres",
            autocommit=True,
        )
    except psycopg.OperationalError as exc:
        sys.exit(f"Nao consegui conectar no PostgreSQL: {exc}")

    with admin:
        role_exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_NAME,)).fetchone()
        statement = (
            "ALTER ROLE {} WITH LOGIN CREATEDB PASSWORD {}"
            if role_exists
            else "CREATE ROLE {} WITH LOGIN CREATEDB PASSWORD {}"
        )
        admin.execute(sql.SQL(statement).format(sql.Identifier(APP_NAME), sql.Literal(password)))

        db_exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_NAME,)).fetchone()
        if not db_exists:
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                    sql.Identifier(APP_NAME), sql.Identifier(APP_NAME)
                )
            )

    if existing_password:
        print(".env ja existia e foi mantido.")
    else:
        write_env(host, port, password)
        print(".env criado.")
    print(f"Pronto: usuario e banco '{APP_NAME}' disponiveis em {host}:{port}.")


if __name__ == "__main__":
    main()
