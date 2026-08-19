# Respondedor de comentários

Alguém comenta **"preço"** no seu Reel e recebe o link no direct. É a mecânica
do ManyChat — sem mensalidade.

**Estado: IMPLEMENTADO + VALIDADO LOCALMENTE (20 testes). Nenhuma mensagem real enviada.**

## Por que isso não derruba conta

Usa a **Private Reply oficial** da Graph API: `POST /{ig_user_id}/messages`
com `recipient={"comment_id": ...}`. É o mesmo endpoint que o ManyChat usa.

Não automatiza o app, não usa sessão de navegador, não faz scraping. A Meta
permite **uma** resposta privada por comentário, dentro de 7 dias — e essa
regra virou trava no banco (`comment_id UNIQUE`), não só boa intenção.

## Como funciona

```
comentário → casa a regra → monta a resposta → Private Reply no direct
```

Regra tem: palavras-gatilho, texto da resposta, link, prioridade e,
opcionalmente, um `media_id` (vale só naquele post).

O casamento é por **palavra inteira, sem acento e sem caixa**:
- `"Quanto é o PREÇO?"` → casa com `preco` ✅
- `"curto linkin park"` → **não** casa com `link` ✅

## As travas

| Trava | O que faz |
|---|---|
| `DM_ENABLED=false` | nasce desligado; ligado só quando você quiser |
| `DM_DRY_RUN=true` | casa a regra e mostra o texto, **sem enviar** |
| Regra nasce inativa | cadastrar não dispara nada |
| `comment_id` UNIQUE | a mesma pessoa **nunca** recebe duas vezes |
| Teto por hora / por dia | não vira spam nem estoura limite da Meta |
| Dry-run não gasta teto | testar à vontade não consome sua cota |

Falha da API fica registrada com o motivo, e o envio não é reprocessado às cegas.

## O que falta para ligar de verdade

O código está pronto. O que depende da Meta:

1. Conta Instagram **Profissional** vinculada a uma Página (você já tem)
2. Permissão **`instagram_manage_messages`** no app da Meta
3. **Webhook** de `comments` apontando para o endpoint, para receber os comentários

Sem o webhook, dá para usar chamando `responder()` com o comentário na mão —
útil para testar as regras antes de ligar tudo.

## Uso

```bash
python -m pytest botlive-dm/tests -q
```

Fluxo recomendado: cadastrar regra → ativar → deixar `DM_DRY_RUN=true` por um
dia → conferir no log se as respostas estão certas → só então desligar o
dry-run.
