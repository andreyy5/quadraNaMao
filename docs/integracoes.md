# Integrações: Pix

## Como o sinal funciona hoje

Quando o cliente reserva pelo link público e o horário tem sinal (definido na tabela de preços do espaço), o sistema:

1. cria a reserva como **pendente**, segurando o horário pelo prazo definido em **Ajustes > Reservas online** (30 minutos por padrão);
2. gera um **Pix copia e cola** e o **QR Code** com a chave Pix do estabelecimento, o valor do sinal e um identificador da cobrança;
3. se o pagamento for confirmado dentro do prazo, a reserva vira **confirmada** e o valor entra no caixa;
4. se não for, a reserva é cancelada sozinha, o horário volta a ficar livre e o cliente é avisado pelo WhatsApp.

Sem chave Pix cadastrada, ou em horário sem sinal, a reserva pelo link já nasce confirmada.

## Provedores

O provedor é escolhido pela variável `PIX_PROVIDER`.

| Valor | Quem confirma o pagamento | Uso |
|---|---|---|
| `estatico` (padrão) | A equipe | Produção, enquanto não houver um provedor de cobrança |
| `simulado` | Um botão na página de pagamento | Só desenvolvimento e testes; o sistema se recusa a subir em produção com ele |

### Pix estático (padrão)

Funciona com qualquer banco e não tem custo, porque é a mesma coisa que o cliente digitar a sua chave Pix no app do banco. A diferença é que o banco não avisa o sistema quando o dinheiro chega. Por isso:

- A equipe confere o extrato e, na reserva pendente, clica em **Receber**, escolhe Pix e confirma o valor sugerido (o do sinal). A reserva vira confirmada na hora.
- O recebimento entra no caixa de quem recebeu, como qualquer outro.
- Se ninguém confirmar no prazo, a reserva expira mesmo que o cliente tenha pago. Para quem usa o Pix estático, vale aumentar o prazo do sinal em Ajustes.

### Provedor de cobrança (confirmação automática)

Para a reserva confirmar sozinha, é preciso um provedor de cobrança Pix (PSP) com API e webhook: o sistema cria uma cobrança com vencimento, e o provedor avisa quando ela é paga. Nesse caso o dinheiro entra num caixa próprio, chamado **Pix online**, que não pertence a nenhum operador.

O sistema já está preparado para isso (`apps/financeiro/pix.py`: classe `PixProvider`, campos `txid`, `id_externo` e `expira_em` em `Pagamento`, caixa online e a regra de pagamento atrasado). Falta escolher o provedor e escrever o adaptador e o webhook dele, o que depende de:

- **Decisão do provedor.** Opções comuns: Mercado Pago, Asaas, Efí (antiga Gerencianet), PagBank, ou a API Pix do próprio banco do estabelecimento (Itaú, Bradesco, Santander, Inter, Sicoob e outros oferecem). Os critérios principais são a taxa por Pix recebido, o prazo para o dinheiro cair na conta e se cada estabelecimento terá a própria conta no provedor (o mais comum em SaaS) ou se a plataforma recebe e repassa.
- **Credenciais de cada estabelecimento** no provedor escolhido (em geral, chave da API e, nos bancos, certificado digital).

## Pagamento atrasado

Com um provedor automático, pode acontecer de o pagamento chegar depois que a reserva expirou. O sistema não reabre o horário (alguém pode já ter reservado): marca o pagamento como **pago com atraso**, não lança no caixa e mostra o caso na tela **Hoje**, em **Pedem atenção**, para a equipe devolver o valor ou combinar outro horário com o cliente.

## Política de cancelamento

Em **Ajustes > Reservas online**, o campo **Cancelamento sem perder o sinal (horas antes)** define até quantas horas antes do jogo o sinal é devolvido. Ao cancelar uma reserva com valor recebido, o sistema mostra se o cancelamento está dentro ou fora desse prazo. A devolução continua sendo um estorno no caixa, feito por dono ou gerente: o sistema orienta, mas não devolve dinheiro sozinho.
