<div align="center">

# QuadraNaMão!

**Agendamento e gestão para quadras e campos esportivos.**
Agenda, clientes, PDV, estoque e financeiro em um só lugar, no lugar do caderno e das conversas soltas no WhatsApp.

[![CI](https://github.com/andreyy5/quadraNaMao/actions/workflows/ci.yml/badge.svg)](https://github.com/andreyy5/quadraNaMao/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-0e9eb8)
![Django 5.2](https://img.shields.io/badge/django-5.2-0e9eb8)
![PostgreSQL](https://img.shields.io/badge/postgresql-13%2B-0e9eb8)

<img src="docs/screenshots/agenda.png" alt="Agenda do dia com os espaços lado a lado" width="860">

</div>

---

## Sumário

- [Sobre](#sobre)
- [Funcionalidades](#funcionalidades)
- [Telas](#telas)
- [Tecnologias](#tecnologias)
- [Como rodar localmente](#como-rodar-localmente)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Uso](#uso)
- [Testes e qualidade](#testes-e-qualidade)
- [Arquitetura](#arquitetura)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Roadmap](#roadmap)
- [Deploy e operação](#deploy-e-operação)
- [Contribuindo](#contribuindo)
- [Licença](#licença)

## Sobre

O QuadraNaMão! é um sistema web (SaaS) para estabelecimentos que alugam espaços esportivos: campos de society, quadras de futsal e quadras de areia. Um mesmo sistema atende vários estabelecimentos, cada um vendo apenas os próprios dados.

O foco é a rotina de quem atende no balcão e pelo celular: marcar um horário em poucos toques, saber o que está livre, receber, vender uma água e fechar o caixa no fim do dia com o valor batendo.

O planejamento completo, com modelagem e fases, está em [PLANNER.md](PLANNER.md). As decisões técnicas e as regras de negócio assumidas estão em [docs/decisoes.md](docs/decisoes.md).

## Funcionalidades

**Agenda**
- Grade do dia e da semana, com todos os espaços lado a lado e a hora atual sempre à vista.
- Reserva em um clique a partir do horário livre, com a lista dos horários realmente livres e aviso de conflito antes de salvar.
- Conflito de horário impedido pelo próprio banco de dados, inclusive com reservas feitas ao mesmo tempo.
- Bloqueios (chuva, manutenção, evento) com a lista das reservas afetadas para remarcar e avisar.

**Reserva online e mensalistas**
- Link público para o cliente reservar sozinho pelo celular, sem login, vendo só os horários livres.
- Sinal por Pix (QR Code e copia e cola): o horário fica reservado pelo prazo do pagamento e é liberado sozinho se o sinal não for pago.
- Política de cancelamento com antecedência configurável.
- Mensalistas com horário fixo semanal: as reservas são criadas sozinhas semanas à frente, com cobrança por jogo ou mensalidade, e as semanas sem vaga viram aviso para o dono.

**WhatsApp**
- Confirmação, lembrete antes do jogo, cancelamento e aviso de chuva ou manutenção, só para quem aceitou (LGPD).
- Histórico de conversas com status de entrega e leitura, e resposta da equipe pelo próprio sistema.
- Cliente sai da lista respondendo SAIR.

**Clientes**
- Cadastro automático na primeira reserva, busca por nome ou telefone e histórico.
- Atalho para conversar pelo WhatsApp e anonimização dos dados pessoais (LGPD).

**PDV e estoque**
- Tela de venda pensada para toque e leitor de código de barras, com troco calculado.
- Comanda vinculada à reserva para cobrar o consumo no fim do jogo.
- Estoque com histórico de entradas, perdas e contagens, estoque mínimo e venda bloqueada sem saldo (configurável).

**Financeiro**
- Caixa por operador, com abertura, retirada de dinheiro e fechamento com conferência da gaveta.
- Cada reserva gera sua conta a receber, com recebimento total ou parcial.
- Contas a receber e a pagar com repetição semanal, mensal ou anual e alertas de vencimento.
- Estorno em vez de edição: todo lançamento fica no histórico.
- Relatórios de faturamento, formas de pagamento, espaços, ocupação e inadimplência.

**Uso no dia a dia**
- Modo escuro (padrão) e claro, layout pensado primeiro para o celular.
- Busca rápida (`Ctrl` + `K`) e atalhos de teclado.
- Perfis de dono, gerente e atendente, cada um com o que precisa.

## Telas

| Tela Hoje | Nova reserva |
|---|---|
| <img src="docs/screenshots/hoje.png" alt="Tela Hoje com o próximo jogo, números do dia, contas e vendas" width="420"> | <img src="docs/screenshots/nova-reserva.png" alt="Painel de nova reserva aberto a partir de um horário livre" width="420"> |

| PDV | PDV no celular |
|---|---|
| <img src="docs/screenshots/pdv.png" alt="PDV com produtos e carrinho" width="420"> | <img src="docs/screenshots/pdv-celular.png" alt="PDV no celular com a barra do carrinho" width="220"> |

As telas usam os dados de demonstração gerados pelo comando `seed_demo`.

## Tecnologias

| Camada | Escolha |
|---|---|
| Back-end | Python 3.13, Django 5.2 (somente views baseadas em classe) |
| Banco | PostgreSQL 13+ (constraint de exclusão para conflito de horário) |
| Front-end | Templates do Django, Tailwind CSS 3, HTMX 2 e Alpine.js 3 |
| Tarefas | Celery com Redis |
| Testes | pytest e pytest-django |
| Qualidade | ruff, black e pre-commit |
| Entrega | Docker, docker-compose e GitHub Actions |

As bibliotecas de front-end e as fontes são servidas pelo próprio sistema, sem CDN.

## Como rodar localmente

### Pré-requisitos

- Python 3.13
- Node.js 20 ou mais recente
- PostgreSQL 13 ou mais recente, em execução
- Redis é opcional em desenvolvimento: as tarefas rodam no próprio processo

### Passo a passo

Os comandos abaixo são para o PowerShell, no Windows. No Linux ou macOS, troque `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

```powershell
# 1. Clonar o repositório
git clone https://github.com/andreyy5/quadraNaMao.git
cd quadraNaMao

# 2. Ambiente Python e dependências
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt

# 3. Front-end (CSS, HTMX, Alpine e fontes)
npm install
npm run build

# 4. Banco e .env: cria o usuário e o banco "quadranamao" e gera o .env.
#    Pede a senha do usuário postgres.
.\.venv\Scripts\python.exe scripts\setup_db.py

# 5. Tabelas e dados de demonstração
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo

# 6. Servidor
.\.venv\Scripts\python.exe manage.py runserver
```

Abra http://127.0.0.1:8000. O `seed_demo` mostra no terminal o e-mail e a senha do dono e do atendente de demonstração.

Para preparar o `.env` à mão, copie o [.env.example](.env.example) e preencha os valores. Durante o desenvolvimento do CSS, deixe `npm run dev` rodando em outro terminal.

### Dados de demonstração

| Comando | O que faz |
|---|---|
| `manage.py seed_demo` | Cria a Arena Demo com espaços, clientes, reservas, produtos, vendas e contas. |
| `manage.py seed_demo --reset` | Apaga e recria a demonstração (gera uma senha nova). |
| `manage.py seed_demo --produtos` | Só acrescenta produtos e vendas a uma demonstração antiga. |
| `manage.py seed_demo --financeiro` | Só acrescenta contas e recebimentos de exemplo. |
| `manage.py seed_demo --online` | Só liga o link público, o Pix, o WhatsApp (em modo de teste) e cria mensalistas numa demonstração antiga. |

O comando só roda em desenvolvimento (`config.settings.dev`). O link público da demonstração é http://127.0.0.1:8000/r/arena-demo/. Em desenvolvimento, a página do Pix tem um botão que simula o pagamento, e as mensagens de WhatsApp ficam só no histórico do sistema.

## Variáveis de ambiente

| Variável | Obrigatória | Uso |
|---|---|---|
| `SECRET_KEY` | sim | Chave do Django. Em produção, gere uma longa e aleatória. |
| `DATABASE_URL` | sim | Conexão com o PostgreSQL, como `postgres://usuario:senha@localhost:5432/quadranamao`. |
| `DJANGO_SETTINGS_MODULE` | não | `config.settings.dev` (padrão, modo de depuração ligado) ou `config.settings.prod` (desligado). |
| `ALLOWED_HOSTS` | em produção | Domínios aceitos, separados por vírgula. |
| `CSRF_TRUSTED_ORIGINS` | em produção | Origens HTTPS confiáveis, separadas por vírgula. |
| `CELERY_BROKER_URL` | em produção | Redis do Celery. |
| `CACHE_URL` | em produção | Cache compartilhado do limite de tentativas, como `redis://localhost:6379/1`. Sem ele, cada processo conta separado. |
| `NUM_PROXIES` | atrás de proxy | Quantos proxies reversos ficam na frente do Django (nginx, balanceador). Padrão `0`. |
| `SITE_URL` | em produção | Endereço público do sistema, usado nos links mandados por WhatsApp. |
| `PIX_PROVIDER` | não | `estatico` (padrão: a equipe confirma o Pix) ou `simulado` (só desenvolvimento). Veja [docs/integracoes.md](docs/integracoes.md). |
| `WHATSAPP_PROVIDER` | não | `console` (padrão: só registra no histórico) ou `cloud` (Cloud API da Meta). |
| `WHATSAPP_ACCESS_TOKEN` | com `cloud` | Token permanente do usuário do sistema na Meta. |
| `WHATSAPP_APP_SECRET` | com `cloud` | Chave secreta do app da Meta, para conferir a assinatura do webhook. |
| `WHATSAPP_VERIFY_TOKEN` | com `cloud` | Frase inventada por você e repetida no cadastro do webhook na Meta. |
| `WHATSAPP_API_VERSION` | não | Versão da Graph API. Padrão `v21.0`. |
| `POSTGRES_PASSWORD` | só no Docker | Senha do banco criado pelo `docker-compose`. |

Como conseguir as chaves da Meta e cadastrar os modelos de mensagem: [docs/whatsapp.md](docs/whatsapp.md).

O `.env` nunca vai para o repositório: o `.gitignore` já cuida disso.

## Uso

### Perfis

| Perfil | Acesso |
|---|---|
| Dono | Tudo: espaços, preços, equipe e ajustes do estabelecimento, além do resto. |
| Gerente | Agenda, clientes, PDV, estoque, financeiro e relatórios. |
| Atendente | Agenda, clientes, PDV e o próprio caixa. Fecha o caixa sem ver o valor esperado. |

### Cadastrar um estabelecimento real

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Em `/admin/`, crie o estabelecimento e um usuário com perfil **Dono** vinculado a ele. Ao entrar, o dono vê os primeiros passos: espaço, horários, preços e primeira reserva. O superusuário só acessa o admin, porque não pertence a nenhum estabelecimento.

### Atalhos de teclado

| Tecla | Ação |
|---|---|
| `Ctrl` + `K` ou `/` | Busca rápida de clientes e ações |
| `N` | Nova reserva, no dia aberto na agenda |
| `B` | Bloquear horário, na agenda |
| `←` e `→` | Dia ou semana anterior e seguinte, na agenda |
| `T` | Voltar para hoje, na agenda |

## Testes e qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\black.exe --check .
```

Os testes criam um banco temporário no próprio PostgreSQL. As regras críticas têm cobertura específica:

| Regra | Onde |
|---|---|
| Conflito de horário e reservas simultâneas | `apps/agenda/tests/` |
| Venda, comanda e concorrência no estoque | `apps/pdv/tests/` |
| Caixa, fechamento, estornos e contas | `apps/financeiro/tests/` |
| Link público, Pix, expiração do sinal e pagamento atrasado | `apps/agenda/tests/test_online.py` |
| Mensalistas, avisos e mensalidade | `apps/agenda/tests/test_mensalistas.py` |
| WhatsApp: aceite, webhook assinado, status, SAIR, janela de 24 horas | `apps/whatsapp/tests/` |
| Limite de tentativas no login | `apps/contas/tests/` e `apps/estabelecimentos/tests/test_ratelimit.py` |
| Isolamento entre estabelecimentos | `apps/estabelecimentos/tests/test_isolation.py` e os testes de cada app |

O GitHub Actions roda lint, formatação, checagem de migrações e testes a cada push e pull request. Para rodar ruff e black antes de cada commit:

```powershell
.\.venv\Scripts\pre-commit.exe install
```

## Arquitetura

- **Multi-tenant por linha.** Todo modelo de negócio herda de `TenantModel`, cujo gerenciador filtra pelo estabelecimento da requisição e não devolve nada sem ele (falha fechado).
- **Regras em `services.py`.** Views só recebem a requisição e chamam os serviços; templates não têm regra de negócio.
- **O banco garante o essencial.** Conflito de horário é uma `ExclusionConstraint` do PostgreSQL; vendas e recebimentos usam transações e travas em ordem fixa.
- **Dinheiro em `Decimal`**, horários em UTC no banco e no fuso do estabelecimento na tela.
- **Histórico imutável.** Movimentações de estoque e lançamentos financeiros não se editam: a correção é um novo registro.

Os detalhes e os porquês estão em [docs/decisoes.md](docs/decisoes.md).

## Estrutura do projeto

```
config/                 settings por ambiente, urls e Celery
apps/
  contas/               usuário (login por e-mail), perfis e equipe
  estabelecimentos/     tenant, TenantModel, middleware e mixins das views
  espacos/              espaços, horários de funcionamento e tabela de preços
  clientes/             clientes, busca e anonimização (LGPD)
  agenda/               reservas, bloqueios, mensalistas, link público e grade de horários
  estoque/              produtos, movimentações e estoque mínimo
  pdv/                  vendas, comanda na reserva e cancelamento
  financeiro/           caixa, lançamentos, contas a receber e a pagar e Pix
  whatsapp/             mensagens, modelos, webhook da Meta e conversas
  relatorios/           tela Hoje e relatórios
templates/              layout base e componentes compartilhados
assets/css/app.css      fonte do CSS (compilado em static/css/app.css)
static/js/app.js        comportamento da interface (HTMX e Alpine)
scripts/                criação do banco local e cópia das bibliotecas de front-end
docs/                   decisões técnicas, guias do WhatsApp e do Pix e capturas de tela
```

## Roadmap

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Fundação: autenticação, multi-tenant, layout e CI | Pronta |
| 1 | Cadastros e agenda | Pronta |
| 2 | Mensalistas, sinal com Pix e link público de reserva | Pronta. Confirmação automática do Pix depende de escolher o provedor |
| 3 | Financeiro: caixa, contas e relatórios | Pronta |
| 4 | PDV e estoque | Pronta |
| 5 | WhatsApp: lembretes e confirmações automáticas | Pronta. Envio real depende de configurar a conta na Meta |
| 6 | Agente de IA para reservas pelo WhatsApp | Planejada |
| 7 | Lista de espera, cupons, planos e app | Planejada |

## Deploy e operação

### Docker

Defina `SECRET_KEY` e `POSTGRES_PASSWORD` no `.env` e rode:

```bash
docker compose up --build
```

O `Dockerfile` e o `docker-compose.yml` ainda não foram executados de ponta a ponta (ver [decisões](docs/decisoes.md)).

### Tarefas agendadas

| Rotina | Frequência |
|---|---|
| Expirar reservas com sinal vencido | a cada 5 minutos |
| Lembretes pelo WhatsApp | a cada 10 minutos |
| Reservas das próximas semanas dos mensalistas | diária |
| Contas que se repetem | diária |

Em produção, rode o worker (que também manda as mensagens de WhatsApp) e o agendador:

```bash
celery -A config worker -l info
celery -A config beat -l info
```

Sem Celery, agende `manage.py rotinas` no cron a cada 5 minutos; ele roda todas as rotinas uma vez. Como garantia, a agenda e o link público expiram os sinais vencidos ao serem abertos, e as telas de contas e a tela Hoje criam as repetições.

### Backup

```bash
pg_dump -U quadranamao -h localhost -Fc quadranamao -f backup.dump
pg_restore -U quadranamao -h localhost -d quadranamao --clean backup.dump
```

Em produção, agende o `pg_dump` diariamente e guarde as cópias fora do servidor. Arquivos `.dump` e `.sql` ficam fora do repositório, porque contêm dados de clientes.

### Antes de expor na internet

- `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY` própria e `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` preenchidos.
- HTTPS e backup diário configurados.
- `CACHE_URL` apontando para o Redis e `NUM_PROXIES` de acordo com o proxy, para o limite de tentativas valer.
- `SITE_URL` com o endereço público, para os links do WhatsApp funcionarem.
- Worker e agendador do Celery rodando (ou o cron do `manage.py rotinas`).

## Contribuindo

1. Crie uma branch a partir da `main`.
2. Mantenha as regras de negócio em `services.py`, com testes junto.
3. Rode `pytest`, `ruff check .` e `black --check .` antes do commit.
4. Use mensagens no padrão `tipo: descrição` em português, como `feat: adiciona lista de espera` ou `fix: corrige troco em dinheiro`.
5. Registre decisões técnicas relevantes em [docs/decisoes.md](docs/decisoes.md).

## Licença

O projeto ainda não tem licença definida. Até que uma seja escolhida, todos os direitos são reservados ao autor.
