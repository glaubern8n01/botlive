# Stack local de mídia

Camada de decisão sobre **quais** ferramentas de geração/edição usar, com a
prioridade do projeto: `LOCAL > GRATUITO > FREE TIER > PAGO`.

**Estado: IMPLEMENTADO + VALIDADO LOCALMENTE. Nenhuma ferramenta auditada,
nenhuma instalada.**

## O que este módulo é — e o que ele não é

Ele **não** instala nem executa nada dos 15 repositórios. Ele é a régua que
decide o que pode entrar, e que se recusa a decidir com dado que ninguém
levantou.

O catálogo carrega o que o documento do projeto *declara* sobre cada
ferramenta. Licença, custo, VRAM, RAM, headless, API, CLI e maturidade nascem
como `None` — que a matriz mostra como **`não medido`**. Não é zero, não é
falso, não é "provavelmente ok".

## Como uma ferramenta vira adotável

```
NAO AUDITADO  →  PARCIAL  →  AUDITADO  (ou DESCARTADO)
```

`registrar_auditoria()` só aceita concluir como `AUDITADO` com **licença e
commit auditado** informados — concluir sem licença não é auditoria, é chute.
Só ferramenta `AUDITADO` com licença entra na stack adotável.

## Duas seleções, de propósito

| Chamada | O que devolve |
|---|---|
| `menor_conjunto()` | a **proposta** a validar — hoje 4 ferramentas, `pronta_para_producao=False` |
| `menor_conjunto(somente_auditadas=True)` | a stack **adotável hoje** — hoje vazia, com as 9 capacidades listadas como descobertas |

A proposta atual lidera com **WanGP**, como o documento manda, mesmo havendo
candidata que cobre mais capacidades: prioridade declarada pesa antes de
cobertura bruta.

## Providers

`providers.py` é a fila por capacidade. Duas travas:

- **Provider pago não liga sozinho.** Precisa de `autorizar_pago(id, "autorizo custo")` — a
  confirmação literal existe justamente para gasto não entrar por descuido de config.
- **Pago fora do ar não derruba o grátis.** Some o pago, a seleção cai para o
  próximo da fila e segue funcionando.

Perfil de hardware filtra antes: provider que pede mais VRAM/RAM do que o
perfil permite não entra na seleção.

## Uso

```bash
python -m pytest botlive-media/tests -q
python botlive-media/mediastack/report.py > docs/STACK-MEDIA.md
```

A matriz em [docs/STACK-MEDIA.md](../docs/STACK-MEDIA.md) é **gerada pelo
código** — matriz escrita à mão envelhece e passa a mentir. Regere depois de
cada auditoria registrada.

## Ainda não feito

- A auditoria em si: rodar, ler licença, medir VRAM/RAM das 15 ferramentas.
- Executores reais de provider (hoje `Provider` descreve, não executa).
- Integração com o pipeline de produção do BotLive.
