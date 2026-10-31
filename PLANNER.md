# PLANNER — QuadraNaMão! (Sistema de Agendamento para Quadras e Campos)

> Documento de planejamento para o Claude Code. Leia inteiro antes de escrever qualquer código.
> Idioma do produto, dos textos de interface e dos nomes de domínio: **português do Brasil**.
> Idioma do código (nomes de variáveis, funções, classes): **inglês**, exceto nomes de domínio muito específicos, que podem ficar em português quando forem mais claros (ex.: `Mensalista`).

---

## 1. Visão do produto

**QuadraNaMão!** é um sistema web (SaaS) de gestão e agendamento para estabelecimentos que alugam espaços esportivos:

- **Campos de Fut7 / society**
- **Quadras de futsal e ginásios poliesportivos**
- **Quadras de areia** (beach tênis, vôlei de praia, futevôlei)

O sistema substitui o caderno e o controle manual pelo WhatsApp. Ele entrega, em um só lugar:

1. Agenda com controle automático de horários e prevenção de conflitos.
2. Controle de caixa automatizado a partir das reservas.
3. Contas a pagar e a receber.
4. PDV simples para venda de produtos do local (bebidas, aluguel de bola, etc.).
5. Controle de estoque intuitivo, ligado ao PDV.
6. Integração com WhatsApp (fase posterior).
7. **Agente de IA** que conversa de forma humanizada com clientes no WhatsApp e faz reservas sozinho (fase posterior, depois do núcleo estável).

**Diferencial:** o dono do espaço não precisa mais responder cliente por cliente. O cliente fala com a IA e a reserva acontece.

**Primeiro cliente piloto:** um proprietário de quadras de areia (contato do Andrey). Todas as decisões de MVP devem priorizar fazer esse piloto funcionar.

---

## 2. Stack e decisões técnicas

| Camada | Escolha | Observação |
|---|---|---|
| Linguagem | Python 3.12+ | |
| Framework | Django 5.x | |
| Banco | PostgreSQL | **Obrigatório** (usaremos constraint de exclusão para evitar reservas duplicadas) |
| Front-end | Django Templates + **Tailwind CSS** | |
| Interatividade | HTMX + Alpine.js (sugestão) | Evitar SPA no MVP; manter simples |
| Tarefas assíncronas | Celery + Redis | Lembretes, geração de cobranças, rotinas |
| API | Django REST Framework | Webhooks do WhatsApp e ferramentas do agente de IA |
| Deploy | Docker + docker-compose | Ambiente local reproduzível |
| Testes | pytest + pytest-django | Cobertura mínima nas regras de agenda e financeiro |
| Qualidade | ruff + black + pre-commit | |

**Decisão importante — multi-tenant:** um único sistema atende vários estabelecimentos. Usar **isolamento por linha** (cada model de negócio tem FK para `Estabelecimento`), com um manager/queryset que filtra automaticamente pelo estabelecimento do usuário logado. Nenhuma consulta pode vazar dados entre estabelecimentos. Escrever testes específicos para isso.

---

## 3. Design e identidade visual

- **Nome do produto:** **QuadraNaMão!** (com o "!" como parte da marca). Usar exatamente essa grafia, com "Q", "N" e "M" maiúsculos e acento em "Mão", em títulos, tela de login, e-mails, mensagens do WhatsApp, rodapé e `<title>` das páginas.
- **Slug técnico** (repositório, pacote Python, banco, containers, domínios): `quadranamao` (minúsculo, sem acento e sem "!").
- A marca deve aparecer no cabeçalho do painel (logo/wordmark) e na página pública de reserva de cada estabelecimento ("Reserva feita com QuadraNaMão!").

- **Paleta fria** (azuis, ciano, verde-azulado, cinzas azulados). Evitar laranja, vermelho e amarelo como cor principal; usar apenas em alertas pontuais.
- **Modo escuro** como padrão, com opção de modo claro.
- **Temas por modalidade.** Cada tipo de espaço tem uma ilustração/representação própria no sistema (cards, cabeçalhos, estados vazios):
  - **Campo (Fut7/society):** campo de grama sintética visto de cima.
  - **Quadra (futsal/poliesportivo):** quadra de piso liso com marcações.
  - **Areia:** quadra de areia com rede.
- Implementar o tema por **CSS variables** em um atributo (`data-theme="campo" | "quadra" | "areia"`), de modo que trocar o tema não exija reescrever componentes.
- Definir tokens no `tailwind.config.js`: `background`, `surface`, `primary`, `accent`, `text`, `muted`, `success`, `warning`, `danger`.
- Mobile-first. Dono e cliente vão usar bastante pelo celular.
- Componentes reutilizáveis: card de quadra, grade de horários, badge de status da reserva, modal de confirmação, tabela com filtros.
- Acessibilidade básica: contraste adequado no modo escuro, foco visível, labels em formulários.

> Ilustrações: usar SVGs simples e originais feitos para o projeto. Não usar imagens de terceiros com direitos autorais.

---

## 4. Estrutura de apps Django

```
config/                # settings, urls, celery
apps/
  contas/              # usuários, perfis, autenticação, permissões
  estabelecimentos/    # Estabelecimento (tenant), configurações, horário de funcionamento
  espacos/             # Espaco (campo/quadra/areia), tipos, preços, tema
  agenda/              # Reserva, Mensalista, Bloqueio, regras de horário
  clientes/            # Cliente, histórico, contatos
  financeiro/          # Caixa, Lancamento, ContaReceber, ContaPagar, formas de pagamento
  pdv/                 # Venda, ItemVenda, comanda simples
  estoque/             # Produto, Movimentacao, alertas de estoque mínimo
  whatsapp/            # (fase 5) integração com a API, webhook, templates
  agente/              # (fase 6) agente de IA, ferramentas, guardrails, logs
  relatorios/          # dashboards e relatórios
```

---

## 5. Modelagem de dados (rascunho)

Todos os models de negócio herdam de um `TenantModel` abstrato com `estabelecimento` (FK), `criado_em`, `atualizado_em`.

**Estabelecimento**: nome, slug, documento (CNPJ/CPF), telefone, endereço, fuso horário, ativo.

**Espaco**: estabelecimento, nome, `tipo` (`CAMPO`, `QUADRA`, `AREIA`), modalidades aceitas, capacidade, ativo, ordem de exibição.

**HorarioFuncionamento**: espaco, dia da semana, abre, fecha.

**TabelaPreco**: espaco, dia da semana (ou faixa), faixa de horário, duração do slot (minutos), valor, valor do sinal (opcional).

**Cliente**: estabelecimento, nome, telefone (WhatsApp, único por estabelecimento, normalizado em E.164), e-mail opcional, observações, aceite de contato por WhatsApp.

**Reserva**: espaco, cliente, `inicio`, `fim` (ou `DateTimeRangeField`), status (`PENDENTE`, `CONFIRMADA`, `CANCELADA`, `CONCLUIDA`, `NAO_COMPARECEU`), origem (`PAINEL`, `WHATSAPP`, `IA`, `MENSALISTA`), valor total, valor pago, observações, mensalista (FK opcional).
- **Constraint de exclusão no PostgreSQL** (`ExclusionConstraint` com `btree_gist`) impedindo dois intervalos sobrepostos no mesmo espaço quando o status não for `CANCELADA`.

**Mensalista**: cliente, espaco, dia da semana, horário, vigência (início/fim), valor mensal ou por sessão, forma de cobrança. Gera reservas futuras automaticamente (rotina agendada).

**Bloqueio**: espaco, intervalo, motivo (`MANUTENCAO`, `CHUVA`, `EVENTO`, `OUTRO`). Impede novas reservas e dispara fluxo de remarcação.

**Pagamento**: reserva (ou venda), valor, forma (`PIX`, `DINHEIRO`, `CARTAO_DEBITO`, `CARTAO_CREDITO`, `OUTRO`), status, data, identificador externo (Pix).

**Caixa**: estabelecimento, operador, abertura, fechamento, saldo inicial, saldo final conferido.
**Lancamento**: caixa, tipo (`ENTRADA`/`SAIDA`), categoria, valor, origem (reserva, venda PDV, manual), data.

**ContaReceber / ContaPagar**: descrição, valor, vencimento, status (`ABERTA`, `PAGA`, `ATRASADA`, `CANCELADA`), categoria, fornecedor/cliente, recorrência opcional.

**Produto**: nome, SKU/código de barras opcional, preço de venda, custo, unidade, estoque mínimo, ativo.
**MovimentacaoEstoque**: produto, tipo (`ENTRADA`, `SAIDA`, `AJUSTE`, `PERDA`), quantidade, origem (venda, compra, ajuste manual), data, usuário.

**Venda (PDV)**: caixa, cliente opcional, reserva opcional (para lançar consumo na reserva), itens, total, forma de pagamento, status.
**ItemVenda**: venda, produto, quantidade, preço unitário.

---

## 6. Regras de negócio essenciais

### 6.1 Agenda
- A grade de horários é calculada a partir de `HorarioFuncionamento` + `TabelaPreco` + reservas e bloqueios existentes.
- **Nunca** confiar só na validação em Python: a unicidade de horário é garantida por constraint no banco. A camada de serviço trata o erro e devolve mensagem amigável.
- Criar reserva e registrar pagamento/lançamento dentro de **transação atômica**.
- Reserva `PENDENTE` com sinal não pago expira após um prazo configurável (ex.: 15 min) e libera o horário (tarefa Celery).
- Política de cancelamento configurável por estabelecimento (ex.: até X horas antes sem multa).
- Mensalistas: rotina gera reservas das próximas N semanas; conflitos com bloqueios geram aviso para o dono, não falha silenciosa.
- **Chuva (espaços de areia/abertos):** o dono pode bloquear uma faixa e o sistema lista as reservas afetadas, permitindo remarcação em lote com aviso aos clientes.
- Lista de espera (pós-MVP): se um horário for cancelado, avisar quem estava na fila.

### 6.2 Financeiro
- Toda reserva confirmada gera automaticamente um `ContaReceber` (ou lançamento direto, se paga na hora).
- Pagamento registrado → baixa da conta a receber → lançamento no caixa aberto.
- Caixa: abertura com saldo inicial, movimentação automática, fechamento com conferência e diferença.
- Contas a pagar com recorrência (aluguel do ponto, energia, água, internet) e alerta de vencimento.
- Relatórios: faturamento por período, por espaço, por forma de pagamento, inadimplência, ocupação.

### 6.3 PDV e estoque
- PDV simples e rápido (touch-friendly): busca de produto, carrinho, forma de pagamento, finalizar.
- Opção de **lançar o consumo na reserva** (ex.: mesa que consumiu durante o jogo) e cobrar tudo junto.
- Venda concluída gera `MovimentacaoEstoque` de saída e `Lancamento` no caixa.
- Estoque: entrada por compra (podendo gerar `ContaPagar`), ajuste, perda, alerta de estoque mínimo, histórico por produto.
- Impedir venda com estoque negativo (configurável).

### 6.4 Permissões (perfis)
- **Dono/Admin:** tudo do estabelecimento.
- **Gerente:** agenda, financeiro, estoque, relatórios.
- **Atendente/Operador:** agenda, PDV, caixa próprio.
- Cliente final não tem login no MVP (interage via link público de reserva e, depois, via WhatsApp).

---

## 7. Integração com WhatsApp (fase posterior)

- Usar a **API oficial (WhatsApp Business Cloud API)**, direto ou via provedor. **Não** usar bibliotecas não oficiais: risco de banimento do número do cliente.
- Criar uma **camada de abstração** (`WhatsAppProvider`) para trocar de provedor sem reescrever o resto.
- Webhook recebe mensagens e status de entrega; responder rápido (200) e processar em Celery.
- Lembretes e avisos fora da janela de 24h exigem **templates aprovados**. Mapear os templates necessários: confirmação de reserva, lembrete, cobrança de sinal, cancelamento, aviso de chuva/remarcação.
- Guardar histórico de conversas e status de cada mensagem.
- Respeitar opt-in/opt-out do cliente (LGPD).
- Considerar custo por mensagem e refletir isso no plano do produto.

---

## 8. Agente de IA (fase posterior)

**Objetivo:** conversar de forma natural e humanizada com o cliente pelo WhatsApp e concluir reservas sem intervenção humana.

**Princípios de design:**
1. **A IA conversa, o sistema decide.** O modelo nunca "acha" que um horário está livre. Ele chama **ferramentas (tool calling)** que consultam o sistema.
2. Ferramentas mínimas: `consultar_horarios_disponiveis`, `criar_reserva`, `cancelar_reserva`, `remarcar_reserva`, `consultar_minhas_reservas`, `gerar_cobranca_sinal`, `transferir_para_humano`.
3. A disponibilidade final é sempre validada pela constraint do banco. A IA só confirma ao cliente depois do retorno de sucesso.
4. **Confirmação explícita** antes de criar ou cancelar: a IA resume (espaço, dia, hora, valor) e pede o "ok".
5. **Guardrails:** não inventar preço, política ou horário; não falar de assuntos fora do escopo; não expor dados de outros clientes; limitar o que pode ser feito por mensagem.
6. **Handoff para humano:** quando não entender, quando o cliente pedir, ou em caso de reclamação, transferir para o dono/atendente com o resumo da conversa.
7. Tom configurável por estabelecimento (mais formal/descontraído), sempre em português do Brasil.
8. **Logs completos:** guardar mensagens, ferramentas chamadas e resultados para auditoria e melhoria.
9. Memória curta por conversa (contexto da reserva em andamento) e identificação do cliente pelo número.
10. Testar com um conjunto de conversas de exemplo (casos felizes e casos difíceis: cliente muda de ideia, horário ocupado, pede desconto, manda áudio, escreve errado).

**Provedor de LLM:** abstrair em uma interface (`LLMClient`) para permitir trocar de modelo/provedor. Definir limites de custo por estabelecimento.

---

## 9. Roadmap por fases

### Fase 0 — Fundação
- Repositório, Docker, Postgres, Redis, Celery, settings por ambiente.
- Autenticação, usuários, perfis, multi-tenant (`TenantModel` + manager).
- Tailwind configurado, layout base, modo escuro, sistema de temas.
- CI básico (lint + testes).
- **Pronto quando:** consigo logar, ver um dashboard vazio no tema escuro e rodar testes.

### Fase 1 — Cadastros e agenda (MVP núcleo)
- Estabelecimento, Espaços, horários de funcionamento, tabela de preços.
- Clientes.
- Agenda visual (grade por dia/semana e por espaço), criação/edição/cancelamento de reservas.
- Constraint anti-conflito e testes de concorrência.
- Bloqueios (manutenção/chuva).
- **Pronto quando:** o dono consegue operar a agenda de um dia inteiro sem erro de conflito.

### Fase 2 — Mensalistas e pagamentos de reserva
- Mensalistas com geração automática de reservas.
- Sinal e pagamento da reserva, expiração de reservas pendentes.
- Link público de reserva (cliente escolhe espaço/horário).
- Integração de Pix (escolher provedor: ver "Decisões em aberto").
- **Pronto quando:** reserva pública com sinal Pix confirma sozinha após o pagamento.

### Fase 3 — Financeiro
- Caixa (abertura/fechamento), lançamentos automáticos.
- Contas a receber e a pagar, recorrências, alertas.
- Relatórios básicos (faturamento, ocupação, inadimplência).
- **Pronto quando:** o fechamento do caixa bate com as reservas e vendas do dia.

### Fase 4 — PDV e estoque
- Cadastro de produtos, movimentações, estoque mínimo.
- PDV com carrinho, formas de pagamento, vínculo opcional à reserva.
- **Pronto quando:** uma venda baixa estoque e entra no caixa automaticamente.

### Fase 5 — WhatsApp
- Webhook, envio de mensagens e templates, histórico.
- Lembretes automáticos de reserva e avisos de remarcação.
- **Pronto quando:** cliente recebe lembrete e confirmação automáticos.

### Fase 6 — Agente de IA
- Ferramentas, guardrails, handoff, logs, tom configurável.
- Bateria de testes de conversa.
- Piloto controlado com o primeiro cliente.
- **Pronto quando:** um cliente reserva do início ao fim só conversando, sem intervenção humana.

### Fase 7 — Evolução
- Lista de espera, avaliações, cupons/promoções, planos de assinatura do SaaS, app/PWA, relatórios avançados.

---

## 10. Requisitos não funcionais

- **Segurança:** HTTPS, senhas com hash forte, proteção CSRF, rate limiting em endpoints públicos e webhooks, validação de assinatura dos webhooks, segredos só em variáveis de ambiente.
- **LGPD:** coletar o mínimo de dados, registrar consentimento de contato, permitir exclusão/anonimização de cliente.
- **Auditoria:** registrar quem criou, alterou ou cancelou reservas e lançamentos financeiros.
- **Desempenho:** índices nas consultas da agenda (espaço + intervalo de tempo); evitar N+1.
- **Fuso horário:** armazenar em UTC, exibir no fuso do estabelecimento.
- **Dinheiro:** usar `DecimalField`, nunca float.
- **Testes:** regras de agenda, concorrência de reservas, isolamento entre tenants, cálculo financeiro, fluxo do PDV.
- **Backups:** rotina de backup do banco documentada.

---

## 11. Instruções de trabalho para o Claude Code

1. Trabalhe **uma fase por vez**, na ordem. Não adiantar fases futuras.
2. Antes de cada fase, escreva um plano curto (arquivos que serão criados/alterados) e aguarde confirmação do Andrey em decisões grandes.
3. Faça commits pequenos, com mensagens claras em português ou inglês (manter um padrão só).
4. Toda regra de negócio fica em **camada de serviços** (`services.py`), não em views nem em templates.
5. Escreva testes junto com a funcionalidade, principalmente para agenda, financeiro e isolamento entre tenants.
6. Mantenha o README atualizado com como rodar, testar e variáveis de ambiente.
7. Registre decisões técnicas relevantes em `docs/decisoes.md`.
8. Nunca coloque chaves de API ou segredos no repositório.
9. Em caso de dúvida de regra de negócio, **pergunte** em vez de inventar.
10. Ao concluir cada fase, entregue um resumo: o que foi feito, como testar, o que ficou pendente.
11. O nome do produto é **QuadraNaMão!** em toda interface voltada ao usuário e `quadranamao` em identificadores técnicos. Defina o nome em um único lugar (ex.: `settings.PRODUCT_NAME`) e reutilize nos templates, e-mails e mensagens.

---

## 12. Decisões em aberto (confirmar com o Andrey)

- Provedor de Pix/cobrança (opções a avaliar: Mercado Pago, Asaas, EfiBank, outros).
- Provedor de WhatsApp (Cloud API direto da Meta ou via provedor/BSP).
- Provedor/modelo de LLM para o agente e limite de custo por estabelecimento.
- Modelo de cobrança do SaaS (mensalidade fixa, por espaço, por reserva).
- Emissão de nota fiscal: entra no escopo ou não?
- Hospedagem de produção (VPS, PaaS, nuvem).
- Quais perguntas validar com o piloto antes da Fase 2 (política de cancelamento, valor de sinal, como tratam mensalistas hoje).
- ~~Nome do produto~~ — **definido: QuadraNaMão!** Falta apenas a identidade visual (logo/wordmark) e verificar disponibilidade de domínio (ex.: quadranamao.com.br) e de registro da marca.

---

## 13. Critérios de sucesso do MVP (Fases 0 a 3)

- O piloto consegue operar a agenda real por pelo menos 2 semanas sem voltar ao caderno.
- Zero reservas duplicadas.
- Fechamento de caixa diário conferindo com o dinheiro/Pix recebido.
- Tempo para criar uma reserva pelo painel: menos de 30 segundos.
