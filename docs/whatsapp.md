# WhatsApp: como ligar o envio de verdade

> **Módulo em espera.** Por causa do custo, o WhatsApp automático está desligado (`WHATSAPP_ENABLED=False`, o padrão): não aparece no menu e não manda nada. Para usar, ponha `WHATSAPP_ENABLED=True` no `.env` e siga este guia.

O sistema já manda confirmações, lembretes, avisos de chuva, cobranças de contas a receber e respostas da equipe, e recebe o que os clientes escrevem. Enquanto a Meta não estiver configurada, ele roda em **modo de teste**: tudo fica registrado em **WhatsApp** no menu, mas nada sai para o celular de ninguém.

Para mandar de verdade, é preciso uma conta na Meta com a **WhatsApp Cloud API**. O sistema não usa a API oficial de terceiros nem automação do app: só a Cloud API, que é o caminho permitido pela Meta para empresas.

## O que você precisa ter antes

- Um **Portfólio Empresarial** (antigo Gerenciador de Negócios) em [business.facebook.com](https://business.facebook.com), de preferência com a empresa verificada. Sem verificação, a Meta limita o número de clientes que você pode contatar por dia.
- Um **número de telefone para o WhatsApp do sistema**. O mais simples é um número exclusivo, que não esteja em uso no app do WhatsApp. Um número que já está no WhatsApp Business do celular pode, em alguns casos, ser ligado no modo de coexistência da Meta; confira no painel se a opção aparece para você.
- O sistema publicado num **endereço com HTTPS** (por exemplo, `https://app.suaarena.com.br`). A Meta não aceita webhook em `http://` nem em `127.0.0.1`.
- Um **cartão de crédito** cadastrado no Gerenciador do WhatsApp. A Meta cobra por modelo de mensagem entregue; respostas dentro da janela de 24 horas aberta pelo cliente não são cobradas.

## Passo a passo

### 1. Criar o app na Meta

1. Entre em [developers.facebook.com](https://developers.facebook.com), em **Meus apps**, e crie um app do tipo **Empresa**, ligado ao seu Portfólio Empresarial.
2. No painel do app, adicione o produto **WhatsApp**.
3. Em **WhatsApp > Configuração da API**, adicione o seu número e confirme o código recebido por SMS ou ligação.
4. Anote o **Identificador do número de telefone** (Phone number ID) que aparece nessa tela. Ele não é o número em si: é um código só de dígitos.

### 2. Gerar o token permanente

O token temporário da tela de configuração expira em 24 horas. Para o sistema, use um token de **usuário do sistema**:

1. Em **Configurações do negócio > Usuários > Usuários do sistema**, crie um usuário com função **Administrador**.
2. Clique em **Atribuir ativos** e dê controle total do **app** e da **conta do WhatsApp** a esse usuário.
3. Clique em **Gerar token**, escolha o app, marque as permissões `whatsapp_business_messaging` e `whatsapp_business_management` e a validade **Nunca**.
4. Copie o token. Ele só aparece uma vez.

### 3. Copiar o segredo do app

Em **Configurações do app > Básico**, clique em **Mostrar** no campo **Chave secreta do aplicativo**. O sistema usa esse segredo para conferir que os avisos do webhook vieram mesmo da Meta.

### 4. Preencher o `.env` do servidor

```ini
WHATSAPP_PROVIDER=cloud
WHATSAPP_ACCESS_TOKEN=token-permanente-do-passo-2
WHATSAPP_APP_SECRET=chave-secreta-do-passo-3
WHATSAPP_VERIFY_TOKEN=uma-frase-qualquer-que-voce-inventar
SITE_URL=https://app.suaarena.com.br
```

O `WHATSAPP_VERIFY_TOKEN` é inventado por você e serve só para a Meta confirmar o webhook no passo seguinte. Gere um valor longo, por exemplo com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Nada disso vai para o repositório: o `.env` fica só no servidor. Reinicie o sistema e o worker do Celery depois de alterar.

### 5. Cadastrar o webhook

1. No painel do app, em **WhatsApp > Configuração**, clique em **Editar** no webhook.
2. **URL de callback:** `https://app.suaarena.com.br/whatsapp/webhook/` (o endereço exato aparece em **Ajustes > WhatsApp** no sistema).
3. **Token de verificação:** o mesmo `WHATSAPP_VERIFY_TOKEN` do `.env`.
4. Salve e, na lista de campos do webhook, assine o campo **messages**.

Com isso, o sistema passa a receber as mensagens dos clientes e a saber se cada envio foi entregue, lido ou falhou.

### 6. Cadastrar os modelos de mensagem

Fora das 24 horas seguintes a uma mensagem do cliente, a Meta só entrega **modelos aprovados**. Crie os oito abaixo no **Gerenciador do WhatsApp > Modelos de mensagem**, com:

- **Categoria:** Utilidade
- **Idioma:** Português (BR)
- **Nome:** exatamente como está aqui
- **Corpo:** exatamente o texto abaixo, com as variáveis `{{1}}`, `{{2}}`... na mesma ordem

A Meta pede um exemplo para cada variável; use os da tabela. A aprovação costuma levar de minutos a algumas horas.

| Nome | Corpo | Exemplos das variáveis |
|---|---|---|
| `reserva_confirmada` | Olá, {{1}}! Sua reserva em {{2}} está confirmada: {{3}}, {{4}}, das {{5}}. Até lá! | João · Arena Demo · Areia 1 · qui., 05/11 · 19:00 às 20:00 |
| `sinal_pendente` | Olá, {{1}}! Recebemos seu pedido de reserva em {{2}} para {{3}}, {{4}}. Para garantir o horário, pague o sinal de {{5}} até as {{6}} neste link: {{7}} . Qualquer dúvida, é só responder. | João · Arena Demo · qui., 05/11 · 19:00 · R$ 30,00 · 18:30 · https://exemplo.com/r/arena/p/abc |
| `lembrete_reserva` | Olá, {{1}}! Passando para lembrar do seu jogo hoje às {{2}} em {{3}}, na {{4}}. Bom jogo! | João · 19:00 · Areia 1 · Arena Demo |
| `reserva_cancelada` | Olá, {{1}}. Sua reserva em {{2}} de {{3}}, {{4}}, foi cancelada. Se quiser marcar outro horário, é só responder esta mensagem. | João · Arena Demo · qui., 05/11 · 19:00 |
| `reserva_expirada` | Olá, {{1}}. O prazo para pagar o sinal da reserva em {{2}} de {{3}}, {{4}}, terminou e o horário foi liberado. Se ainda quiser jogar, faça um novo pedido. | João · Arena Demo · qui., 05/11 · 19:00 |
| `aviso_remarcacao` | Olá, {{1}}. Por causa de {{2}}, não vai dar para usar {{3}} em {{4}}, {{5}}. Responda esta mensagem para remarcarmos o seu horário. | João · chuva · Areia 1 · qui., 05/11 · 19:00 |
| `pagamento_lembrete` | Olá, {{1}}! Passando para lembrar de um pagamento na {{2}} com vencimento {{3}}: {{4}}, no valor de {{5}}. Para ver os detalhes e pagar, acesse {{6}} . Se já pagou, desconsidere esta mensagem. | João · Arena Demo · amanhã (06/11) · Mensalidade Areia 1 · R$ 120,00 · https://exemplo.com/r/arena/conta/abc |
| `pagamento_atrasado` | Olá, {{1}}. Consta em aberto um pagamento na {{2}} que venceu em {{3}}: {{4}}, no valor de {{5}}. Para ver os detalhes e pagar, acesse {{6}} . Se já pagou, desconsidere esta mensagem. | João · Arena Demo · qui., 05/11 · Mensalidade Areia 1 · R$ 120,00 · https://exemplo.com/r/arena/conta/abc |

Os textos de referência ficam em `apps/whatsapp/modelos.py`. Se mudar um texto lá, mude também na Meta (a Meta trata como um modelo novo, que precisa de aprovação).

Os dois de pagamento precisam ficar em **Utilidade**: são avisos de uma conta que o cliente já tem. Se a Meta reclassificar como Marketing (texto com tom de promoção), cada mensagem passa a custar bem mais; não acrescente ofertas nesses textos.

Se a Meta recusar o `sinal_pendente`, o `pagamento_lembrete` ou o `pagamento_atrasado` por causa do link no corpo, a alternativa é um botão de link com sufixo variável; avise para o sistema ser ajustado.

### 7. Ligar no sistema

1. Entre como dono e abra **Ajustes > WhatsApp**. Os três itens de configuração devem aparecer em verde.
2. Marque **Enviar mensagens pelo WhatsApp**, preencha o **ID do número (phone number ID)** do passo 1 e as horas de antecedência do lembrete. Em **Contas a receber**, escolha quando lembrar do vencimento e quando avisar do atraso (os dois começam desligados). Salve.
3. Em **Testar a ligação**, mande o modelo `hello_world` para o seu celular. Enquanto o app da Meta estiver em modo de desenvolvimento, o destinatário precisa estar cadastrado como número de teste no painel da Meta.
4. Por fim, no painel do app da Meta, passe o app para o modo **Ao vivo** (exige o endereço de uma política de privacidade).

## Como o sistema usa o WhatsApp

| Situação | Mensagem | Quando sai |
|---|---|---|
| Reserva criada ou remarcada pela equipe | `reserva_confirmada` | Na hora |
| Pedido pelo link público com sinal | `sinal_pendente` | Na hora, com o link do Pix |
| Sinal pago | `reserva_confirmada` | Quando o pagamento é confirmado |
| Lembrete | `lembrete_reserva` | O número de horas antes do jogo definido em Ajustes (0 desliga) |
| Reserva cancelada | `reserva_cancelada` | Na hora |
| Sinal não pago no prazo | `reserva_expirada` | Quando o pedido expira |
| Bloqueio (chuva, manutenção, evento) | `aviso_remarcacao` | Quando a equipe clica em **Avisar todos pelo WhatsApp** na tela do bloqueio |
| Conta a receber perto do vencimento (mensalidade, evento, patrocínio) | `pagamento_lembrete` | No dia ou alguns dias antes, como definido em Ajustes |
| Conta a receber vencida e ainda em aberto | `pagamento_atrasado` | Alguns dias depois do vencimento, como definido em Ajustes |
| Resposta da equipe | Texto livre | Só nas 24 horas seguintes à última mensagem do cliente |

Regras das cobranças:

- Valem para as contas a receber com cliente, inclusive a mensalidade dos mensalistas. As contas das reservas ficam de fora: já têm confirmação e lembrete do jogo e são pagas no local.
- Saem só das 9h às 20h, no fuso do estabelecimento, e no máximo um lembrete e um aviso de atraso por conta. Se a equipe mudar o vencimento, os avisos voltam a valer para a data nova.
- Uma conta lançada há menos de 30 minutos espera, para dar tempo de receber no balcão.
- O aviso de atraso que não saiu no dia certo (sistema fora do ar) ainda sai nos 3 dias seguintes. Contas mais antigas não recebem nada quando você liga o aviso.
- O link abre uma página com a conta, o valor em aberto e o Pix (QR Code e copia e cola) da chave cadastrada em **Ajustes > Reservas online**. Quem confirma o pagamento é a equipe, dando baixa na conta.

Mesmo com o módulo desligado, a lista de **Contas a receber** tem um botão verde de WhatsApp em cada conta que dá para cobrar. Ele abre o WhatsApp do celular de quem atende com o mesmo texto e o mesmo link, sem custo. Quem envia é a pessoa, então não fica no histórico do sistema.

Regras que valem para tudo:

- **Só recebe quem aceitou** (LGPD). O aceite fica na ficha do cliente e é marcado por ele no link público. Os jogos de mensalistas não geram confirmação, para não mandar uma mensagem por semana.
- Quem responde **SAIR**, **PARAR** ou **STOP** deixa de receber na hora e recebe uma última mensagem explicando como voltar. **VOLTAR** reativa.
- Nada é mandado sobre jogo que já começou.
- Mensagens que falharam aparecem no histórico com o motivo e na tela **Hoje**, em **Pedem atenção**.
- Ao anonimizar um cliente, o texto das mensagens dele é apagado e o telefone some do histórico.

## Rotinas que precisam estar rodando

O lembrete do jogo e as cobranças saem por tarefas do Celery que rodam a cada 10 minutos. Em produção, deixe o worker e o agendador ligados (veja o README) ou, sem Celery, chame `manage.py rotinas` pelo cron a cada 10 minutos.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| A Meta não aceita o webhook | Endereço sem HTTPS, `WHATSAPP_VERIFY_TOKEN` diferente do digitado na Meta, ou o sistema não foi reiniciado depois de mudar o `.env` |
| As mensagens chegam ao sistema mas os status não mudam | O campo **messages** não foi assinado no webhook |
| "Template name does not exist in the translation" | Modelo ainda não aprovado, nome diferente ou idioma diferente de Português (BR) |
| "Recipient phone number not in allowed list" | App da Meta em modo de desenvolvimento e destinatário não cadastrado como número de teste |
| Erro 401 ou "Invalid OAuth access token" | Token temporário expirado: gere o token permanente do passo 2 |
| Avisos do webhook recusados com 403 | `WHATSAPP_APP_SECRET` errado |
