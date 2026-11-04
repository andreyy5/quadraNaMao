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

**WhatsApp em espera.** O módulo automático (Fase 5) ficou pronto, mas foi desligado por decisão do Andrey, por causa do custo da Meta. `WHATSAPP_ENABLED` (padrão desligado) esconde o menu, a aba de Ajustes, as conversas e o webhook, e impede qualquer envio, inclusive lembretes. Nada foi apagado: ligar a variável traz tudo de volta. O link público também deixa de pedir o aceite de WhatsApp, para não colher um consentimento que não vai ser usado.

**Reserva por modalidade (organização automática).** Quem reserva escolhe a modalidade, o dia e a hora; o sistema escolhe o espaço. As modalidades saem do campo de texto do espaço (separadas por vírgula, sem diferença de acento ou maiúscula), e espaços com a mesma modalidade são tratados como equivalentes. Espaço sem modalidade cadastrada vale pelo tipo ("Areia"). Entre os livres, a escolha segue, nesta ordem: não deixar sobra menor que um horário da grade (ninguém compra meia hora solta); ocupar a menor janela livre que comporta o jogo (encaixe justo, que cola nos jogos existentes e preserva os blocos grandes nos outros espaços); e a ordem de exibição. Se o escolhido for ocupado no meio do caminho, tenta o seguinte. A reserva guarda a modalidade, para a equipe preparar o espaço (rede de beach tênis ou de vôlei, por exemplo).

**Painel com "Automático".** A escolha de modalidade e o cartão "Automático" só aparecem quando alguma modalidade tem mais de um espaço; sem isso, o painel fica como antes. O botão "Nova reserva" abre no automático; clicar num horário da grade continua escolhendo aquele espaço, porque quem clicou já decidiu.

**Esqueci minha senha.** Usa o fluxo do Django com token de uso único, válido por 2 horas. A tela é a mesma exista ou não a conta, e o e-mail sai pelo Celery, para o tempo de resposta não revelar quais e-mails existem. Limites: 3 e-mails por hora para o mesmo endereço (os excedentes não saem, sem aviso) e 10 pedidos por hora do mesmo IP. Redefinir a senha libera o bloqueio de login daquele e-mail.

**Dois jeitos de falar pelo WhatsApp.** Os botões de conversa abrem o `wa.me` e quem envia é o atendente, pelo próprio celular. As mensagens automáticas (Fase 5) saem pela Cloud API da Meta, só para quem aceitou, e ficam no histórico do sistema. O passo a passo da Meta está em [whatsapp.md](whatsapp.md).

**Painel de reserva.** Quem clica em um horário livre vê só o horário em destaque e os dados do cliente; o resto abre em "Alterar" ou quando há erro de horário. A lista de horários livres (`free_starts`) e o aviso de conflito (`slot_problem`) só consultam: quem garante é a constraint ao gravar. Horários passados ficam fora da lista, mas continuam possíveis em "Outro horário", porque o painel permite passar o caderno a limpo.

**Sem arrastar para remarcar, por enquanto.** Mover uma reserva para outra faixa de preço exige decidir se o valor muda ou se mantém, e essa regra não está no planner. A remarcação continua pelo formulário, que recalcula o valor à vista de quem edita.

**Admin restrito.** O admin do Django cobre apenas `Usuario` e `Estabelecimento`, porque o superusuário não tem tenant e os dados de negócio são operados no painel.

**PDV antes do financeiro.** O PDV e o estoque entraram antes da Fase 3 a pedido do Andrey. As vendas feitas antes da Fase 3 ficaram sem caixa e sem lançamento: aparecem nas vendas do dia, mas não nos fechamentos nem nos relatórios.

**Financeiro (Fase 3).** Todo dinheiro passa por um `Lancamento` em um `Caixa` aberto. Lançamento não se edita nem se apaga: a correção é um estorno, que entra no caixa de quem estorna e aponta para o original. Faturamento é o que entrou por reservas, vendas e contas a receber, menos os estornos desses valores; dinheiro colocado ou retirado da gaveta é movimento de caixa, não faturamento.

**Pagamento de reserva.** Toda reserva gera uma `ContaReceber`, e o pagamento (inteiro ou parcial) baixa essa conta com um lançamento no caixa. `Reserva.valor_pago` é uma cópia mantida pelo financeiro. O modelo `Pagamento` (Fase 2) existe só para a cobrança Pix do link público: guarda o `txid`, o copia e cola, o prazo e o status, e aponta para o lançamento quando é pago. Recebimento no balcão continua sendo só o lançamento.

**Pix com provedor plugável.** O provedor de cobrança Pix não foi escolhido (decisão em aberto no planner). O padrão é o Pix estático, gerado com a chave do estabelecimento no formato BR Code do Banco Central: funciona com qualquer banco, mas a equipe confirma o pagamento pelo botão Receber. Um provedor simulado prova o fluxo automático em desenvolvimento e nos testes, e o sistema se recusa a subir em produção com ele. As opções e o que falta para a confirmação automática estão em [integracoes.md](integracoes.md).

**Caixa "Pix online".** Pagamento confirmado pelo provedor não tem operador. Ele entra num caixa do tipo online, um por estabelecimento, aberto sozinho na primeira confirmação, para o faturamento e os relatórios continuarem saindo dos lançamentos.

**Expiração sem depender do agendador.** As pendentes vencidas são canceladas pela tarefa a cada 5 minutos e também ao abrir a agenda ou o link público. Assim o horário nunca fica preso se o Celery parar.

**Mensalista vira reservas de verdade.** A regra semanal gera reservas comuns, 8 semanas à frente, renovadas por uma tarefa diária. A agenda, o conflito de horário e o financeiro tratam o jogo do mensalista como qualquer reserva. Semana que não pode ser reservada (outra reserva, bloqueio, espaço fechado) vira um aviso para o dono, em vez de falhar calada, e não é tentada de novo. Ao mudar horário, espaço, datas ou valor, os jogos futuros são cancelados e refeitos; os cancelados pela mudança saem do mensalista, para a semana ser refeita no horário novo, e um jogo que a equipe cancelou antes continua pulado.

**WhatsApp assíncrono e idempotente.** O envio sai de uma tarefa do Celery depois que a transação confirma, para uma falha da Meta não desfazer a reserva. O webhook confere a assinatura `X-Hub-Signature-256` com o segredo do app, ignora mensagens repetidas pelo `wa_id` e não deixa um status atrasado ("entregue") desfazer um mais novo ("lida"). O estabelecimento é identificado pelo `phone_number_id` do aviso, que é único entre os estabelecimentos. Sem a Meta configurada, o provedor `console` só registra no histórico.

**Limite de tentativas.** Login (5 por e-mail e IP, 30 por IP, a cada 15 minutos) e reservas pelo link público (10 por hora por IP) usam o cache do Django. Em produção com mais de um processo, o cache precisa ser compartilhado (`CACHE_URL` no Redis), e atrás de proxy reverso `NUM_PROXIES` diz quantos proxies são confiáveis no `X-Forwarded-For`.

**Atraso calculado na hora.** Conta "atrasada" é a que está em aberto com o vencimento no passado, calculada a cada consulta, sem status gravado. Assim não depende de uma tarefa agendada para ficar certa.

**Recorrência.** A conta original guarda a repetição e as próximas são criadas até 31 dias à frente, sempre a partir da data original (dia 31 volta a ser 31 depois de fevereiro). Quem cria é uma tarefa diária do Celery e, como garantia, as telas de contas e a tela Hoje; a criação não duplica.

**Cor dos gráficos.** O ciano dos botões é claro demais para área de dados e reprovou no validador de paleta no modo escuro. Os gráficos usam o token `chart` (`#0e9eb8` no escuro, `#006c9e` no claro), que passa nas checagens de faixa de claridade e contraste. As saídas do fluxo de caixa usam `chart-out` (laranja: `#d95926` no escuro, `#eb6834` no claro); o par ciano e laranja passou em todas as checagens nos dois modos, inclusive para daltonismo (ΔE 19,4). O mapa de calor usa só o ciano, mais forte onde a ocupação é maior, e todo gráfico tem a tabela com os mesmos números.

**Relatórios pelo regime de caixa.** Dinheiro conta na data em que entrou ou saiu, e um estorno conta na data dele (não muda o passado). Despesa é conta paga: pelo caixa, vale o lançamento; pelo banco, a data da baixa, só quando não há lançamento de caixa em vigor para a conta, para um pagamento estornado e refeito no banco não contar duas vezes. Dinheiro colocado ou retirado da gaveta é movimento interno e fica fora do fluxo. O previsto soma as contas em aberto que vencem nos próximos 30 dias, por semana; as reservas futuras entram pela conta a receber de cada uma.

**Período dos relatórios.** Até um ano. A ocupação monta a grade de cada dia de cada espaço, então olha no máximo os últimos 92 dias do período e avisa quando corta. A comparação da visão geral é com o período anterior de mesmo tamanho.

**Conferência do caixa (revisão de novembro de 2026).** Três correções: o valor de uma reserva não pode mais ficar abaixo do que já foi recebido (antes a conta ficava paga com sobra escondida; agora é preciso estornar antes); o caixa "Pix online" fecha conferindo com o extrato, sem pedir dinheiro contado; e caixa de operador aberto desde outro dia aparece em "Pedem atenção" para dono e gerente. O restante do fluxo (abertura, sangria, recebimento parcial, estorno no caixa de quem estorna, fechamento às cegas) foi revisado e está coberto por testes, inclusive a conta que cruza fechamentos, fluxo e visão geral.

**Celular.** Todas as telas foram conferidas em 360 e 390 px de largura e em tablet, sem rolagem para os lados fora das tabelas e gráficos que rolam de propósito. Links de texto têm área de toque maior que o desenho, e campos ficam com 16 px de letra, porque no iPhone um campo menor dá zoom ao tocar.

**Saldo de estoque.** `Produto.estoque_atual` é uma cópia do saldo para consulta rápida e só muda em `estoque/services.py`, sempre com uma `MovimentacaoEstoque`. Os locks seguem uma ordem fixa (estabelecimento, venda, produtos por `pk`), para vendas simultâneas não venderem o mesmo item nem se bloquearem.

**Estoque simplificado.** Quantidades inteiras, sem unidade de medida, lotes ou validade. O planner cita `unidade` em `Produto`; ficou de fora até um piloto precisar. Entrada por compra não gera `ContaPagar`, porque depende da Fase 3.

**Apps adiados.** `agente` (Fase 6) não foi criado, nem o Django REST Framework instalado, conforme a regra de não adiantar fases.

## Regras de negócio assumidas (validar com o piloto)

Estas regras não estão definidas no planner:

1. A reserva pelo painel nasce **confirmada**. Só a reserva pelo link público, em horário com sinal, nasce **pendente**.
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
14. **Comanda:** no máximo uma aberta por reserva. O estoque baixa ao lançar o consumo e o pagamento fica para o fechamento, junto com o da reserva. Cancelar a reserva não mexe na comanda, que continua aberta até alguém receber ou cancelar.
15. **Cancelamento:** devolve os itens ao estoque e mantém o registro. Comanda em aberto qualquer pessoa corrige ou cancela; venda já paga, só dono ou gerente. Não há estorno automático, já que o sistema ainda não movimenta dinheiro.
16. **Sem desconto por venda** por enquanto.
17. **Caixa por operador**, como no planner ("caixa próprio"): cada pessoa abre o seu, e o que ela recebe entra nele. Para receber qualquer coisa é preciso ter o caixa aberto; lançar consumo na comanda não precisa.
18. **Fechamento às cegas para o atendente:** ele conta o dinheiro sem ver o valor esperado. Dono e gerente veem o esperado e a diferença, e podem fechar o caixa de outra pessoa.
19. Só **dinheiro** entra na conferência da gaveta. Pix e cartão aparecem no resumo do fechamento, para conferir com o extrato.
20. **Reserva cancelada** cancela a conta dela, mas o que já foi recebido continua registrado: a devolução é um estorno feito por dono ou gerente. **Não compareceu** mantém a conta em aberto, e o dono decide se cobra.
21. **Conta a pagar** pode sair do caixa (vira lançamento e reduz a gaveta) ou ser paga no banco (só dá baixa).
22. Compra de estoque pode gerar uma **conta a pagar** com quantidade × custo.
23. **Sinal:** o valor vem da faixa da tabela de preços em que a reserva começa. Sem chave Pix cadastrada, o link público não cobra sinal e a reserva nasce confirmada.
24. **Prazo do sinal:** 30 minutos por padrão, configurável. Vencido, a reserva é cancelada, a conta dela também, e o cliente é avisado.
25. **Um pedido pendente por cliente** no link público: com um Pix em aberto, o mesmo telefone não reserva outro horário até pagar ou o prazo vencer.
26. Sinal recebido no balcão (parcial ou inteiro) que **alcança o valor do sinal** confirma a reserva pendente. Abaixo disso, ela continua pendente.
27. **Pagamento atrasado** (chegou depois da expiração) não reabre o horário nem entra no caixa: fica marcado para a equipe resolver.
28. **Política de cancelamento:** até X horas antes (24 por padrão), o sinal é devolvido; depois, fica com o estabelecimento. O sistema mostra a regra ao cancelar, mas a devolução é um estorno feito por dono ou gerente.
29. **Link público:** mostra até 30 dias à frente, só horários futuros, livres e dentro do funcionamento, com a duração definida na faixa de preço do dia (uma hora se não houver). O cliente informa nome e telefone; se o telefone já existe, usa o cliente cadastrado.
30. **Mensalista** pode ser cobrado **por jogo** (cada reserva tem o seu valor) ou **por mês** (uma conta a receber que se repete todo mês, no dia de vencimento escolhido entre 1 e 28, e as reservas ficam com valor zero). Encerrar cancela os jogos depois da data e para a repetição da conta; o histórico fica.
31. **WhatsApp automático só para quem aceitou**, nunca sobre jogo que já começou, e sem confirmação para jogos de mensalista. "SAIR", "PARAR" ou "STOP" desligam o aceite na hora; "VOLTAR" religa. Resposta livre da equipe só nas 24 horas seguintes à última mensagem do cliente, como exige a Meta.
32. O **aviso de bloqueio** pelo WhatsApp é disparado pela equipe na tela do bloqueio, e não sozinho, porque às vezes o dono prefere remarcar antes de avisar.
33. Só o **dono** configura o link público, o Pix e o WhatsApp. Toda a equipe vê as conversas e responde.
34. No link público, o cliente **não escolhe o espaço**: vê antes de confirmar onde vai jogar e quanto custa. Escolher um espaço específico ("quero a quadra coberta") fica para depois, se o piloto pedir.
35. Espaços equivalentes podem ter **preços diferentes**: vale o preço do espaço escolhido, mostrado antes de confirmar.

## O que ainda não foi executado

- **`Dockerfile` e `docker-compose.yml`:** escritos, mas não executados, porque a máquina de desenvolvimento não tem Docker.
- **Celery com Redis:** sem Redis local. Em desenvolvimento as tarefas rodam no próprio processo e o agendador não roda; `manage.py rotinas` executa todas as rotinas uma vez.
- **WhatsApp com a Meta:** o envio pela Cloud API foi testado com a API simulada nos testes automatizados, não contra a Meta, porque depende da conta e dos modelos aprovados ([whatsapp.md](whatsapp.md)).

## Pendências conhecidas

- **Confirmação automática do Pix:** depende de escolher o provedor de cobrança ([integracoes.md](integracoes.md)).
- **Provedor de e-mail em produção:** o "esqueci minha senha" está pronto, mas precisa de um servidor SMTP em `EMAIL_URL` para os e-mails saírem de verdade.
