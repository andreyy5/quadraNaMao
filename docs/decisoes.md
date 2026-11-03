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

**Painel de reserva.** Quem clica em um horário livre vê só o horário em destaque e os dados do cliente; o resto abre em "Alterar" ou quando há erro de horário. A lista de horários livres (`free_starts`) e o aviso de conflito (`slot_problem`) só consultam: quem garante é a constraint ao gravar. Horários passados ficam fora da lista, mas continuam possíveis em "Outro horário", porque o painel permite passar o caderno a limpo.

**Sem arrastar para remarcar, por enquanto.** Mover uma reserva para outra faixa de preço exige decidir se o valor muda ou se mantém, e essa regra não está no planner. A remarcação continua pelo formulário, que recalcula o valor à vista de quem edita.

**Admin restrito.** O admin do Django cobre apenas `Usuario` e `Estabelecimento`, porque o superusuário não tem tenant e os dados de negócio são operados no painel.

**PDV antes do financeiro.** O PDV e o estoque entraram antes da Fase 3 a pedido do Andrey. As vendas feitas antes da Fase 3 ficaram sem caixa e sem lançamento: aparecem nas vendas do dia, mas não nos fechamentos nem nos relatórios.

**Financeiro (Fase 3).** Todo dinheiro passa por um `Lancamento` em um `Caixa` aberto. Lançamento não se edita nem se apaga: a correção é um estorno, que entra no caixa de quem estorna e aponta para o original. Faturamento é o que entrou por reservas, vendas e contas a receber, menos os estornos desses valores; dinheiro colocado ou retirado da gaveta é movimento de caixa, não faturamento.

**Pagamento de reserva sem a Fase 2.** Para o fechamento bater com as reservas, o recebimento manual da reserva entrou agora: toda reserva gera uma `ContaReceber`, e o pagamento (inteiro ou parcial) baixa essa conta com um lançamento no caixa. O modelo `Pagamento` do planner fica para a Fase 2, quando o Pix trouxer pagamentos pendentes e identificador externo; até lá o lançamento já registra quem recebeu, quanto, como e quando. `Reserva.valor_pago` é uma cópia mantida pelo financeiro.

**Atraso calculado na hora.** Conta "atrasada" é a que está em aberto com o vencimento no passado, calculada a cada consulta, sem status gravado. Assim não depende de uma tarefa agendada para ficar certa.

**Recorrência.** A conta original guarda a repetição e as próximas são criadas até 31 dias à frente, sempre a partir da data original (dia 31 volta a ser 31 depois de fevereiro). Quem cria é uma tarefa diária do Celery e, como garantia, as telas de contas e a tela Hoje; a criação não duplica.

**Cor dos gráficos.** O ciano dos botões é claro demais para área de dados e reprovou no validador de paleta no modo escuro. Os gráficos usam o token `chart` (`#0e9eb8` no escuro, `#006c9e` no claro), que passa nas checagens de faixa de claridade e contraste.

**Saldo de estoque.** `Produto.estoque_atual` é uma cópia do saldo para consulta rápida e só muda em `estoque/services.py`, sempre com uma `MovimentacaoEstoque`. Os locks seguem uma ordem fixa (estabelecimento, venda, produtos por `pk`), para vendas simultâneas não venderem o mesmo item nem se bloquearem.

**Estoque simplificado.** Quantidades inteiras, sem unidade de medida, lotes ou validade. O planner cita `unidade` em `Produto`; ficou de fora até um piloto precisar. Entrada por compra não gera `ContaPagar`, porque depende da Fase 3.

**Apps adiados.** `whatsapp` e `agente` não foram criados, nem o Django REST Framework instalado, conforme a regra de não adiantar fases. O campo `Reserva.mensalista` entra na Fase 2. `Reserva.valor_pago` e `TabelaPreco.valor_sinal` já existem, mas ainda não têm uso.

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
11. Perfis: só o **dono** configura espaços, preços, estabelecimento e equipe. **Dono e gerente** cuidam do estoque. Todos usam a agenda e o PDV.
12. A venda sem estoque é **recusada** por padrão. Em Ajustes, cada estabelecimento pode liberar a venda com saldo negativo. Perda também respeita essa opção; a contagem nunca é recusada, porque é o saldo real.
13. O **preço vem sempre do cadastro**. Se ele mudar com o carrinho aberto, a venda é recusada para o total ser conferido. O item guarda o preço do momento da venda.
14. **Comanda:** no máximo uma aberta por reserva. O estoque baixa ao lançar o consumo e o pagamento fica para o fechamento. Só cobre o consumo, porque o pagamento da própria reserva entra na Fase 2. Cancelar a reserva não mexe na comanda, que continua aberta até alguém receber ou cancelar.
15. **Cancelamento:** devolve os itens ao estoque e mantém o registro. Comanda em aberto qualquer pessoa corrige ou cancela; venda já paga, só dono ou gerente. Não há estorno automático, já que o sistema ainda não movimenta dinheiro.
16. **Sem desconto por venda** por enquanto.
17. **Caixa por operador**, como no planner ("caixa próprio"): cada pessoa abre o seu, e o que ela recebe entra nele. Para receber qualquer coisa é preciso ter o caixa aberto; lançar consumo na comanda não precisa.
18. **Fechamento às cegas para o atendente:** ele conta o dinheiro sem ver o valor esperado. Dono e gerente veem o esperado e a diferença, e podem fechar o caixa de outra pessoa.
19. Só **dinheiro** entra na conferência da gaveta. Pix e cartão aparecem no resumo do fechamento, para conferir com o extrato.
20. **Reserva cancelada** cancela a conta dela, mas o que já foi recebido continua registrado: a devolução é um estorno feito por dono ou gerente. **Não compareceu** mantém a conta em aberto, e o dono decide se cobra.
21. **Conta a pagar** pode sair do caixa (vira lançamento e reduz a gaveta) ou ser paga no banco (só dá baixa).
22. Compra de estoque pode gerar uma **conta a pagar** com quantidade × custo.

## O que ainda não foi executado

- **`Dockerfile` e `docker-compose.yml`:** escritos, mas não executados, porque a máquina de desenvolvimento não tem Docker.
- **`.github/workflows/ci.yml`:** escrito, mas não executado, porque o repositório ainda não tem remoto.
- **Celery com Redis:** configurado, sem tarefas ainda e sem Redis local. Em desenvolvimento roda em modo imediato.

## Pendências conhecidas

- **Limite de tentativas de login:** o planner pede rate limiting em endpoints públicos. Precisa estar pronto antes de expor o sistema na internet.
- **Reset de senha por e-mail:** depende de escolher um provedor de e-mail. Por enquanto é feito pelo admin.
- **Aviso aos clientes em bloqueios:** a tela lista as reservas afetadas e o telefone, mas o aviso é manual até a Fase 5.
- **Política de cancelamento e expiração de pendentes:** entram com o sinal, na Fase 2.
