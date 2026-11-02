# QuadraNaMão!

Sistema de agendamento e gestão para quadras e campos esportivos. Substitui o caderno e o controle pelo WhatsApp.

**Estado atual:** Fases 0 e 1 do [planner](PLANNER.md), mais o PDV e o estoque da Fase 4, sem o caixa da Fase 3. Login e perfis, multi-tenant, espaços, horários, preços, clientes, agenda visual, bloqueios, PDV com comanda na reserva e estoque.

## Stack

Python 3.13, Django 5.2 (views em CBV), PostgreSQL, Tailwind CSS, HTMX e Alpine.js, Celery e Redis, pytest.

## Como rodar localmente (Windows)

Pré-requisitos: Python 3.13, Node 20+ e PostgreSQL 13+ em execução.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
npm install
npm run build

# Cria o usuário e o banco "quadranamao" e gera o .env. Pede a senha do usuário postgres.
.\.venv\Scripts\python.exe scripts\setup_db.py

.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Abra http://127.0.0.1:8000. O `seed_demo` mostra no terminal os acessos do dono e do atendente de demonstração. Para recriar esses dados, use `seed_demo --reset`. Para só acrescentar produtos e vendas a uma demonstração criada antes do PDV, use `seed_demo --produtos`.

No Linux ou macOS, troque `.\.venv\Scripts\python.exe` por `.venv/bin/python`. Durante o desenvolvimento do CSS, deixe `npm run dev` rodando.

### Atalhos de teclado

| Tecla | Ação |
|---|---|
| `Ctrl` + `K` ou `/` | Busca rápida de clientes e ações |
| `N` | Nova reserva, no dia aberto na agenda |
| `B` | Bloquear horário, na agenda |
| `←` e `→` | Dia ou semana anterior e seguinte, na agenda |
| `T` | Voltar para hoje, na agenda |

### Cadastrar um estabelecimento real

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Em `/admin/`, crie o estabelecimento e depois um usuário com perfil **Dono** vinculado a ele. Ao entrar, o dono vê os primeiros passos: espaço, horários, preços e primeira reserva. O reset de senha também é feito pelo admin nesta fase.

### Com Docker

Defina `SECRET_KEY` e `POSTGRES_PASSWORD` no `.env` e rode `docker compose up --build`. Esses arquivos ainda não foram executados de ponta a ponta (ver [decisões](docs/decisoes.md)).

## Testes e qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\black.exe --check .
```

Os testes usam um banco temporário criado no próprio PostgreSQL. As regras críticas têm cobertura específica: conflito de horário e concorrência em `apps/agenda/tests/`, venda, comanda e concorrência de estoque em `apps/pdv/tests/`, e isolamento entre estabelecimentos em `apps/estabelecimentos/tests/test_isolation.py` e `apps/pdv/tests/`.

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `SECRET_KEY` | Chave do Django. Obrigatória. |
| `DATABASE_URL` | Conexão com o PostgreSQL. Obrigatória. |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` ou `config.settings.prod`. |
| `ALLOWED_HOSTS` | Domínios aceitos em produção, separados por vírgula. |
| `CSRF_TRUSTED_ORIGINS` | Origens HTTPS confiáveis em produção. |
| `CELERY_BROKER_URL` | Redis do Celery. Em desenvolvimento as tarefas rodam no próprio processo. |
| `POSTGRES_PASSWORD` | Somente para o `docker-compose`. |

## Estrutura

```
config/              settings por ambiente, urls, celery
apps/
  contas/            usuário (login por e-mail), perfis, equipe
  estabelecimentos/  tenant, TenantModel, middleware, mixins das CBVs
  espacos/           espaços, horários de funcionamento, tabela de preços
  clientes/          clientes, busca, anonimização (LGPD)
  agenda/            reservas, bloqueios, auditoria e grade de horários
  estoque/           produtos, movimentações e estoque mínimo
  pdv/               vendas, comanda na reserva e cancelamento
  relatorios/        tela "Hoje"
templates/           layout base e componentes
assets/css/app.css   fonte do CSS (compilado em static/css/app.css)
```

As regras de negócio ficam em `services.py`, e as views são somente CBVs. Os demais apps do planner (financeiro, PDV, estoque, WhatsApp, agente) entram nas suas fases.

## Backup

Backup e restauração do banco:

```powershell
pg_dump -U quadranamao -h localhost -Fc quadranamao -f backup.dump
pg_restore -U quadranamao -h localhost -d quadranamao --clean backup.dump
```

Em produção, agende o `pg_dump` diariamente e guarde as cópias fora do servidor.
