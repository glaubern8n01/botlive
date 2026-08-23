# Validação do Kwai — 22/08/2026

Execução da Etapa 10 do Prompt Mestre 1: percorrer a ordem definida e
documentar a compatibilidade como **SIM / PARCIAL / NÃO / NÃO VALIDADO**, sem
assumir que Kwai Brasil e Kuaishou são o mesmo alvo.

**Veredito: NÃO existe rota automatizável para o Kwai Brasil.** A publicação
continua manual, pelo celular — que é exatamente o que já acontece hoje.

Nada foi instalado, nenhuma conta foi acessada e nenhuma proteção foi
contornada. A investigação usou só superfície pública.

## Rota 1 — API oficial · **NÃO**

Procurado: documentação de desenvolvedor, cadastro de aplicativo, OAuth ou
endpoint de publicação para criador brasileiro.

O que existe publicamente é superfície **comercial**, não de publicação:

- [kwai.com/business](https://www.kwai.com/business) — anúncios;
- [creatormarketplace.kwai.com](https://creatormarketplace.kwai.com/) — Kwai
  for Business / marketplace de criadores;
- [kwai.com/creators](https://www.kwai.com/creators) — página institucional
  para criador, sem menção a upload por API ou pela web.

A página que aparece na busca como "Kwai business api documentation" é uma
página de navegação do site: não tem endpoint, não tem OAuth, não tem cadastro
de app. Nada encontrado permite publicar vídeo por API.

Isso bate com o que a própria conta já declara no banco: `api_enabled: false`,
`publication_mode: manual_mobile`.

## Rota 2 — dreammis/social-auto-upload · **NÃO** (para o Brasil)

O repositório é real, ativo (14,5k estrelas, MIT) e **tem** uploader de
Kuaishou — a pasta `uploader/ks_uploader`. Só que ele dirige a plataforma
**chinesa**:

| O que o código abre | |
|---|---|
| login | `passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api` |
| upload | `cp.kuaishou.com/article/publish/video` |
| gerenciamento | `cp.kuaishou.com/article/manage/video` |

Os seletores são da interface chinesa (por exemplo `div[role='tab']:has-text('图文')`).
`cp.kuaishou.com` é o painel de criador da Kuaishou China: exige conta chinesa
e não tem relação de sessão com a conta brasileira do Kwai.

Era exatamente o risco que o documento mandava não correr — tratar Kuaishou e
Kwai BR como equivalentes. Não são.

## Rota 3 — Fuploader · **NÃO** (mesmo motivo)

[fishimei/Fuploader](https://github.com/fishimei/Fuploader), aplicativo
desktop em Go + Wails, distribui para Bilibili, Douyin, Kuaishou, Baijiahao,
Xiaohongshu, Vídeo Channel e TikTok. É a mesma família de plataformas chinesas.
Nenhum alvo Kwai internacional.

## Rota 4 — Playwright específico para Kwai Brasil · **NÃO há o que automatizar**

Aqui está o achado que fecha a questão: **o Kwai não tem upload pela web.**

- `creator.kwai.com` responde **301** e joga para `https://www.kwai.com/`;
- `cp.kwai.com` não devolve conteúdo;
- a página de criadores fala em gravar vídeo de até 5 minutos **no aplicativo**,
  e não menciona envio pelo navegador;
- o material que circula sobre "postar no Kwai pelo PC" orienta **emulador
  Android** (BlueStacks), não o site.

Playwright automatiza páginas. Se não existe página de upload, não existe o que
automatizar. Isso não é limitação de ferramenta: é ausência do produto.

## Rota 5 — Android + ADB · **impossível na VPS**, e já é o que se faz no celular

`HQarroum/docker-android` exige `/dev/kvm`. Medido na VPS:

```
ls /dev/kvm        -> No such file or directory
grep vmx|svm /proc/cpuinfo -> (vazio)
```

Sem virtualização aninhada, não sobe emulador. No PC do Glauber seria
tecnicamente possível — mas o resultado prático seria o mesmo que já existe
hoje: o aplicativo do Kwai rodando e uma pessoa (ou um assistente) tocando na
tela. É o que o Kwai Local Uploader do celular já faz, com confirmação humana.

## O que isso muda no código

- `vexpublish/adapters/kwai.py` sai de `NAO VALIDADO` para **`NAO`**, com o
  veredito de cada rota registrado no próprio arquivo. A diferença importa:
  "não validado" convida alguém a tentar de novo; "não" diz que já se tentou e
  o caminho não existe.
- `publish()` continua recusando, agora explicando o motivo real em vez de
  pedir uma investigação que já foi feita.
- `prepare()` passa a declarar `rota_pretendida: "manual-mobile"`, que é a
  verdade operacional.

## O que fazer com isso

O fluxo atual — gerar, validar, revisar e publicar à mão pelo celular, com o
encerramento de lote em uma ação — **é o teto técnico do Kwai hoje**, e já está
implementado. Não há ganho escondido esperando uma integração.

Se algum dia mudar, será por uma destas três portas, nesta ordem de
probabilidade:

1. a agência (Edit-Vetra) liberar acesso de parceiro com API própria;
2. o Kwai lançar painel de criador na web, como TikTok e Instagram têm;
3. um programa de API para criador contratado, que hoje não existe publicamente.

Nenhuma delas depende de código nosso. As três dependem do Kwai.
