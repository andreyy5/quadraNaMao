# Decisões técnicas

## Arquitetura

**Isolamento entre estabelecimentos.** `TenantModel.objects` filtra pelo estabelecimento da requisição e, sem tenant definido, não devolve nada (falha fechado). `all_tenants` é a saída explícita para serviços, comandos e testes. O estabelecimento atual fica em um `ContextVar`, definido e limpo pelo `TenantMiddleware`.

Consequências a lembrar:

- Nunca escreva `queryset = Model.objects.all()` no corpo de uma classe de view ou de formulário, porque isso é avaliado sem tenant. Use `model = Model` ou `get_queryset()`.
- Os `ModelChoiceField` são criados ao importar o módulo, então `TenantFormMixin` refaz as opções a cada instância.
- Gerenciadores reversos (`espaco.reservas`) também passam pelo filtro. Fora de uma requisição, use `all_tenants` com filtro explícito, como fazem os serviços.
- `Usuario` não é `TenantModel`: as views de equipe filtram por `request.tenant`.

**Conflito de horário.** Quem garante é a `ExclusionConstraint` do PostgreSQL em `Reserva`. Os serviços travam a linha do espaço com `select_for_update` para enfileirar quem grava reservas e bloqueios, porque um bloqueio não pode entrar na constraint de outra tabela.

**Nomes.** Models e campos em português, como na seção 5 do planner. Funções, serviços e classes utilitárias em inglês.

**Tailwind 3.4.** Mantido em vez do 4 porque o planner define os tokens em `tailwind.config.js`, que é o formato nativo dessa versão.

**Sem CDN.** HTMX, Alpine e as fontes são servidos pelo próprio sistema, para funcionar em redes ruins e não enviar dados de navegação a terceiros.

**Visual neon com parcimônia.** A base é quase preta e o brilho fica reservado ao que importa: ação principal, item ativo, foco, hora atual e reservas. A variável `--glow` controla a força do brilho e quase o desliga no modo claro, onde neon sobre branco não se lê. As sombras usam `var(--color-primary)` em cada regra, para seguir o `data-theme` do espaço mais próximo. Toda animação respeita `prefers-reduced-motion`.

**Fontes.** Space Grotesk só em tamanhos grandes (títulos de página, números de destaque), sem `tabular-nums`, porque o "1" tabular dela parece riscado. O restante usa Inter.

**Classes do Tailwind nos templates.** Duas armadilhas: classes montadas a partir de dados do banco (`badge-{{ status }}`) precisam entrar no `safelist`, e classes com valor arbitrário não podem ficar coladas em `{% if %}` (`{% if x %}md:max-h-[...]{% endif %}` não é gerada; com espaços, é).

**Link do WhatsApp em vez de integração.** Os botões abrem uma conversa em `wa.me` e quem envia é o atendente. Não depende de aceite nem de API, que continuam para a Fase 5.

**Sem arrastar para remarcar, por enquanto.** Mover uma reserva para outra faixa de preço exige decidir se o valor muda ou se mantém, e essa regra não está no planner. A remarcação continua pelo formulário, que recalcula o valor à vista de quem edita.

**Admin restrito.** O admin do Django cobre apenas `Usuario` e `Estabelecimento`, porque o superusuário não tem tenant e os dados de negócio são operados no painel.

**Apps adiados.** `financeiro`, `pdv`, `estoque`, `whatsapp` e `agente` não foram criados, nem o Django REST Framework instalado, conforme a regra de não adiantar fases. O campo `Reserva.mensalista` entra na Fase 2. `Reserva.valor_pago` e `TabelaPreco.valor_sinal` já existem, mas ainda não têm uso.

## Regras de negócio assumidas (validar com o piloto)

Estas regras não estão definidas no planner:

1. A reserva pelo painel nasce **confirmada**. O status pendente entra com o sinal, na Fase 2.
2. Reserva **fora do horário de funcionamento** é recusada, sem exceção pelo painel.
3. Reserva em **horário passado** é permitida, para o dono passar o caderno a limpo.
4. Telefone é **obrigatório** para todo cliente, porque identifica a pessoa e será usado no WhatsApp. Cliente novo nasce sem aceite de WhatsApp registrado.
5. Se o telefone digitado já existe, a reserva usa o cliente existente e **mantém o nome cadastrado**.
6. Um bloqueio **pode ser criado sobre reservas existentes**. Elas continuam na agenda, marcadas como "Em bloqueio", até serem remarcadas ou canceladas.
7. Horário em que **fechar é menor ou igual a abrir** significa fechar no dia seguinte. As horas após a meia-noite pertencem ao expediente do dia em que abriu, inclusive para o preço.
8. Duração diferente do horário padrão é cobrada **proporcionalmente** aos minutos.
9. Um **único intervalo de funcionamento** por dia e por espaço. Pausa para almoço pode ser feita com um bloqueio.
10. Reserva cancelada não pode ser editada nem reativada: cria-se outra.
11. Perfis: só o **dono** configura espaços, preços, estabelecimento e equipe. Gerente e atendente têm o mesmo acesso até a Fase 3, quando o financeiro os diferencia.

## O que ainda não foi executado

- **`Dockerfile` e `docker-compose.yml`:** escritos, mas não executados, porque a máquina de desenvolvimento não tem Docker.
- **`.github/workflows/ci.yml`:** escrito, mas não executado, porque o repositório ainda não tem remoto.
- **Celery com Redis:** configurado, sem tarefas ainda e sem Redis local. Em desenvolvimento roda em modo imediato.

## Pendências conhecidas

- **Limite de tentativas de login:** o planner pede rate limiting em endpoints públicos. Precisa estar pronto antes de expor o sistema na internet.
- **Reset de senha por e-mail:** depende de escolher um provedor de e-mail. Por enquanto é feito pelo admin.
- **Aviso aos clientes em bloqueios:** a tela lista as reservas afetadas e o telefone, mas o aviso é manual até a Fase 5.
- **Política de cancelamento e expiração de pendentes:** entram com o sinal, na Fase 2.
