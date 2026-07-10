# Robo de Cortes Dark GTA 6/Games

Sistema autonomo para detectar momentos fortes pelo conteudo do video, sem depender de chat.

## Modos principais

- `live-clips`: para live ao vivo. Captura blocos, detecta eventos, salva timestamps e gera previews rapidos em `D:/robo-cortes-dark/cortes/live_preview`.
- `final-hd`: transforma timestamps salvos de uma `session_id` em cortes finais HD, preferindo o VOD original quando `--target-height` e `--render-source vod` sao usados.
- `vod-clips`: para live gravada, replay ou VOD. Analisa, salva timestamps e depois renderiza os cortes finais em `ready_hd`.
- `scan-vod`: modo tecnico para apenas analisar VOD/replay e salvar timestamps.
- `near-live`: alias tecnico antigo de `live-clips`.
- `pos-live`: alias tecnico antigo de `final-hd`.

Fluxo recomendado para live ao vivo:

```powershell
python main.py "URL_DA_LIVE" --modo live-clips --session-id live_jogo_001 --block-seconds 45 --max-cortes 10 --pre-roll-seconds 12 --post-roll-seconds 33 --output-layout original --content-filter football --strict-football-filter
```

Depois que a live virar replay/VOD:

```powershell
python main.py "URL_DO_REPLAY" --modo final-hd --usar-momentos-salvos --session-id live_jogo_001 --max-cortes 30 --clip-duration 45 --output-layout original --target-height 720 --render-source vod --prefer-final-render-from-source
```

Fluxo recomendado para live gravada/VOD direto:

```powershell
python main.py "URL_DO_VOD" --modo vod-clips --session-id vod_jogo_001 --max-cortes 30 --clip-duration 45 --output-layout original --target-height 720 --content-filter football --strict-football-filter
```

Para VOD longo, limite a janela:

```powershell
python main.py "URL_DO_VOD" --modo vod-clips --session-id vod_jogo_final_001 --start-seconds 14000 --end-seconds 16480 --max-cortes 30 --clip-duration 45 --output-layout original --target-height 720 --content-filter football --strict-football-filter
```

Se quiser controle tecnico em duas etapas:

```powershell
python main.py "URL_DO_VOD" --modo scan-vod --session-id vod_jogo_001 --max-cortes 30 --content-filter football --strict-football-filter
python main.py "URL_DO_VOD" --modo final-hd --usar-momentos-salvos --session-id vod_jogo_001 --max-cortes 30 --clip-duration 45 --output-layout original --target-height 720 --render-source vod
```

## Modos

### 1. Modo atual/padrao

Mantem o fluxo que ja funcionava: prepara URL ou arquivo local, analisa o video inteiro e gera cortes. Por padrao o corte preserva o formato original do video, sem crop.

```powershell
python main.py "URL_OU_ARQUIVO" --max-cortes 8
```

### 2. Modo pos-live

Fluxo explicito para replay/VOD ou arquivo completo. Pode analisar o video ou usar timestamps salvos durante o modo live. `final-hd` e o alias de produto para usar timestamps salvos e renderizar cortes finais HD.

```powershell
python main.py "URL_OU_ARQUIVO" --modo pos-live --max-cortes 8
```

Usando timestamps salvos:

```powershell
python main.py "URL_DO_REPLAY_OU_ARQUIVO" --modo pos-live --usar-momentos-salvos --max-cortes 8
```

Filtrando por uma sessao criada no modo live:

```powershell
python main.py "URL_DO_REPLAY_OU_ARQUIVO" --modo pos-live --usar-momentos-salvos --session-id youtube_teste_real_001 --max-cortes 8
```

Com ajuste de offset entre live e VOD:

```powershell
python main.py "URL_DO_REPLAY_OU_ARQUIVO" --modo pos-live --usar-momentos-salvos --vod-offset-seconds 12 --max-cortes 8
```

### 3. Modo scan-vod

Varre um VOD/replay em blocos curtos e salva os melhores timestamps em uma sessao, sem baixar o VOD inteiro quando a URL direta permite leitura por trecho.

```powershell
python main.py "URL_DO_REPLAY" --modo scan-vod --session-id youtube_teste_layout_001 --block-seconds 45 --max-cortes 10 --score-threshold 0.55 --min-gap-seconds 120
```

Depois gere cortes a partir dos timestamps salvos:

```powershell
python main.py "URL_DO_REPLAY" --modo pos-live --usar-momentos-salvos --session-id youtube_teste_layout_001 --max-cortes 10 --clip-duration 45 --output-layout original
```

Para gerar cortes finais em HD a partir do VOD original, mantendo os timestamps salvos pelo scan:

```powershell
python main.py "URL_DO_REPLAY" --modo pos-live --usar-momentos-salvos --session-id youtube_teste_layout_001 --max-cortes 10 --clip-duration 45 --min-gap-seconds 0 --output-layout original --target-height 720
```

Nesse fluxo, os blocos de `scan-vod` continuam servindo para analise e classificacao. O render final tenta baixar apenas os trechos necessarios do VOD original em ate `--target-height`, por exemplo `720`, para gerar arquivos melhores que os blocos de analise. Se o VOD original falhar, o sistema pode cair para os blocos locais como fallback e registra isso no log.

Use `--render-source vod` para forcar a tentativa pelo VOD original, `--render-source cache` para usar apenas blocos locais, ou `--prefer-final-render-from-source` como atalho para preferir a fonte original no pos-live.

Para testar vertical sem cortar o campo/tela:

```powershell
python main.py "URL_DO_REPLAY" --modo pos-live --usar-momentos-salvos --session-id youtube_teste_layout_001 --max-cortes 3 --clip-duration 45 --output-layout vertical-fit
```

## Teste vs uso real

Os cortes gerados durante validacao, como 3, 6 ou 9 arquivos, foram apenas testes para confirmar layout, audio, imagem valida, deduplicacao e limpeza de intermediarios. Eles nao representam um limite do sistema.

Para uma live ou VOD longo, por exemplo com aproximadamente 2 horas, o comportamento esperado e:

- analisar a live/VOD inteira em blocos;
- detectar varios timestamps bons;
- deduplicar momentos proximos;
- selecionar os melhores momentos;
- gerar varios cortes finais.

Em uso real, use `--max-cortes` como limite maximo, nao como quantidade fixa obrigatoria. Por exemplo, `--max-cortes 25` significa gerar ate 25 cortes se existirem timestamps bons suficientes. Para lives longas, valores comuns sao `15`, `20`, `25` ou `30`, dependendo da quantidade de momentos fortes encontrados.

Fluxo recomendado para VOD grande:

```powershell
python main.py "URL_DO_YOUTUBE" --modo scan-vod --session-id canal_teste_001 --block-seconds 45 --max-cortes 25 --score-threshold 0.55 --min-gap-seconds 120
```

Depois:

```powershell
python main.py "URL_DO_YOUTUBE" --modo pos-live --usar-momentos-salvos --session-id canal_teste_001 --max-cortes 25 --clip-duration 45 --output-layout original --titulo "MELHOR MOMENTO DA LIVE" --descricao "corte automatico da live" --marca "@seucanal" --cta "segue para mais cortes"
```

Para postagem, prefira renderizar os cortes finais a partir do VOD original em HD:

```powershell
python main.py "URL_DO_YOUTUBE" --modo pos-live --usar-momentos-salvos --session-id canal_teste_001 --max-cortes 25 --clip-duration 45 --min-gap-seconds 0 --output-layout original --target-height 720 --titulo "MELHOR MOMENTO DA LIVE" --descricao "corte automatico da live" --marca "@seucanal" --cta "segue para mais cortes"
```

Para futebol, gameplay e lives, o layout principal deve continuar sendo `original`, porque preserva a tela inteira e evita cortar partes importantes do jogo.

## Layout de saida

Use `--output-layout` para escolher o formato final:

- `original`: padrao. Mantem largura/altura do video original e nao corta nada.
- `vertical-fit`: gera 1080x1920, mas encaixa o video inteiro no canvas vertical com fundo preto.
- `vertical-crop`: modo antigo. Corta para 9:16 e deve ser usado apenas quando voce realmente quer crop.

O padrao e:

```powershell
--output-layout original
```

## Deduplicacao

`--min-gap-seconds` evita cortes repetidos do mesmo lance. O padrao e `120`, entao se um corte ja foi escolhido em `00:10:00`, outro em `00:10:30` ou `00:11:00` sera ignorado.

### 4. Modo live

Captura blocos curtos da live, analisa audio/movimento/mudanca visual e salva timestamps fortes.

```powershell
python main.py "URL_DA_LIVE" --modo live --block-seconds 45 --max-cortes 8
```

Com session id definido:

```powershell
python main.py "URL_DA_LIVE" --modo live --block-seconds 45 --max-cortes 8 --session-id youtube_teste_real_001
```

Para teste controlado:

```powershell
python main.py "test_source.mp4" --modo live --block-seconds 30 --max-cortes 1 --max-blocks 2
```

### 5. Modo near-live

Captura blocos como o modo live, salva timestamps fortes e tambem gera previews rapidos enquanto a transmissao ou arquivo ainda esta sendo acompanhado. `live-clips` e o nome recomendado; `near-live` continua funcionando como alias tecnico antigo. Os previews sao provisorios e ficam em:

```text
D:/robo-cortes-dark/cortes/live_preview
```

Teste local:

```powershell
python main.py "test_source.mp4" --modo near-live --session-id near_live_local_001 --block-seconds 30 --max-cortes 2 --pre-roll-seconds 8 --post-roll-seconds 20 --output-layout original
```

Depois, use a mesma sessao no pos-live para gerar os cortes finais em HD a partir do VOD ou arquivo original:

```powershell
python main.py "test_source.mp4" --modo pos-live --usar-momentos-salvos --session-id near_live_local_001 --max-cortes 2 --clip-duration 45 --output-layout original --target-height 720
```

Com `--content-filter football --strict-football-filter`, o near-live aplica a mesma triagem de futebol usada no scan: rejeita entrevista, estudio, tela parada e audio alto sem imagem de jogo antes de salvar o preview como aproveitavel.

### 6. Modo vod-clips

Fluxo de produto para live gravada, replay ou VOD. Em URL, roda `scan-vod` para salvar timestamps e depois chama o render final HD pelos timestamps. Em arquivo local, analisa o arquivo, salva timestamps na `session_id` e renderiza pelos mesmos timestamps.

```powershell
python main.py "URL_DO_VOD" --modo vod-clips --session-id vod_jogo_001 --max-cortes 30 --clip-duration 45 --output-layout original --target-height 720 --content-filter football --strict-football-filter
```

Para arquivo local:

```powershell
python main.py "test_source.mp4" --modo vod-clips --session-id teste_vod_clips_001 --max-cortes 1 --clip-duration 45 --output-layout original --target-height 720
```

## Paths obrigatorios no Drive D

Por padrao, o sistema usa:

```text
D:/robo-cortes-dark/cache
D:/robo-cortes-dark/cache/live_blocks
D:/robo-cortes-dark/cache/vod_blocks
D:/robo-cortes-dark/cortes
D:/robo-cortes-dark/cortes/live_preview
D:/robo-cortes-dark/cortes/ready_hd
D:/robo-cortes-dark/fila_local.jsonl
```

Para isolar uma execucao em outra pasta, use `--output-root`:

```powershell
python main.py "URL_DA_LIVE" --modo live-clips --session-id futebol_live_001 --output-root "G:\robo-cortes-live\futebol_live_001"
```

Esse argumento redireciona `cache`, `live_blocks`, `vod_blocks`, `cortes`, `live_preview`, `ready_hd`, `needs_review`, `rejected`, `fila_local.jsonl` e `run_logs`. Sem `--output-root`, o comportamento antigo no Drive D continua.

A prioridade de resolucao da pasta base e: `--output-root` (flag) > env `BOTLIVE_OUTPUT_ROOT` > default do sistema (`D:/robo-cortes-dark` no Windows, `/data/botlive/output` no Linux/Docker). No Windows sem env nada muda.

Use `--output-tag` para gerar as subpastas de `cortes/` com um sufixo, sem sobrescrever uma execucao anterior (util para comparar testes lado a lado):

```powershell
python main.py "URL_DA_LIVE" --modo live-clips --session-id futebol_live_001 --output-root "G:\robo-cortes-live\futebol_live_001" --output-tag smart
```

Isso gera `cortes/live_preview_smart`, `cortes/ready_hd_smart`, `cortes/needs_review_smart` e `cortes/rejected_smart` em vez das pastas padrao. `cache/` e `fila_local.jsonl` continuam compartilhados (nao sao tageados).

## Janela inteligente de corte (smart-event-window)

Por padrao, um corte usa pre-roll/post-roll fixos (`--pre-roll-seconds`/`--post-roll-seconds` ou `--clip-duration`), o que pode juntar dois lances no mesmo mp4 quando os eventos estao proximos (ex.: um pico aos 3s e outro aos 27s dentro de um corte de 45s).

Use `--smart-event-window` para calcular a janela do corte de forma adaptativa, com base no `event_type` do filtro de futebol e nos eventos vizinhos da sessao:

```powershell
python main.py "URL" --modo final-hd --usar-momentos-salvos --session-id sessao_001 --smart-event-window --output-root "G:\robo-cortes-live\sessao_001"
```

Regras aplicadas (`smart_window.py`, funcao `calculate_smart_event_window`):

- cada corte tem 1 lance principal; pre-roll/post-roll ideais por `event_type`:
  - `penalty_kick`: pre-roll 12s, post-roll 15s;
  - `goal_or_chance`: pre-roll 20s, post-roll 17s;
  - `goalkeeper_save`: pre-roll 15s, post-roll 15s;
  - `big_chance`: pre-roll 18s, post-roll 15s;
  - outros/`highlight`: usa `--pre-roll-seconds`/`--post-roll-seconds` informados (ou 15s/15s);
- se o proximo evento da sessao cair dentro da janela, o fim do corte e antecipado (`end = proximo_pico - --min-event-separation`), nunca juntando dois lances no mesmo arquivo;
- se o evento anterior estiver perto, o inicio e adiado pelo mesmo motivo;
- a duracao nunca passa de `--max-clip-duration` (padrao 50s para futebol); o excesso e cortado do post-roll primeiro, protegendo o inicio da jogada;
- `--no-multi-event-clips` isoladamente (sem `--smart-event-window`) so aplica a regra anti-junção usando os pre/post-roll fixos informados, sem trocar os valores por tipo de evento; `--smart-event-window` já ativa as duas coisas.

Flags novas:

- `--smart-event-window`: ativa a janela adaptativa completa (pre/post-roll por tipo + anti multi-lance).
- `--no-multi-event-clips`: garante sozinha que dois eventos fortes nunca caiam no mesmo corte.
- `--max-clip-duration`: duracao maxima do corte com janela inteligente (padrao 50).
- `--min-event-separation`: folga minima, em segundos, entre o fim/inicio de um corte e o pico do evento vizinho (padrao 8).

No `live-clips`/`near-live`, como os eventos chegam em tempo real, o corte so e renderizado depois de capturar um pouco alem do post-roll (`--min-event-separation` de folga extra), dando tempo do bot perceber um evento vizinho e encurtar a janela antes de gravar o arquivo final; se um evento novo aparecer dentro da janela de um corte ainda pendente, esse corte anterior e encurtado automaticamente.

No `final-hd`/`pos-live`/`vod-clips`, como todos os timestamps da sessao ja sao conhecidos, a janela de cada corte e calculada olhando o evento anterior e o proximo da lista ordenada por tempo.

Metadados extras ficam salvos em `fila_local.jsonl` (dentro de `metadata.smart_window` nos cortes finais, ou direto em `metadata` nos momentos/previews do near-live): `smart_start_seconds`, `smart_end_seconds`, `smart_duration_seconds`, `smart_pre_roll_seconds`, `smart_post_roll_seconds`, `previous_event_seconds`, `next_event_seconds`, `prevented_multi_event` e `window_reason`.

## Football strict mode

Campo/gramado visivel, placar na tela, torcida com emocao ou movimento de camera **sozinhos nao provam que existe jogada real acontecendo**. Pre-jogo (chegada ao estadio, aquecimento, escalacao), pos-jogo (comemoracao longa, patrocinador, encerramento), estudio/comentarista, tela de VAR/grafico e torcida/estadio sem bola em jogo tem esses mesmos sinais visuais e podiam ser aprovados como corte "pronto" por engano.

Com `--content-filter football --strict-football-filter`, o `football_content_filter.py` agora classifica cada bloco em uma categoria, com um score proprio para cada uma (`classify_football_metrics`/`classify_football_content`, campos `category`, `active_play_score`, `pregame_score`, `postgame_score`, `studio_score`, `var_graphics_score`, `crowd_only_score`):

- `active_play`: lance real de jogo (ataque, defesa, gol, penalti, chance clara). E a unica categoria que pode virar `save_ready`.
- `pregame` / `postgame`: panoramica ampla do estadio parada ou com pan de camera grande, pouca energia de torcida reagindo a lance. Como o filtro nao le o placar/relogio da transmissao (sem OCR pesado), pre-jogo e pos-jogo usam a mesma heuristica visual — a separacao real por tempo continua sendo responsabilidade do `--start-seconds`/`--end-seconds` (veja exemplo abaixo).
- `studio_or_commentary`: bancada, narrador, comentarista, entrevista, close de pessoa falando (junta os antigos `interview_penalty`/`studio_penalty`).
- `var_or_graphics`: tela de VAR, infografico, replay parado, tela de patrocinador/placar cheia de informacao — pouco ou nenhum campo visivel, alto contraste, pouco movimento.
- `crowd_or_stadium_only`: torcida ou camera aberta do estadio sem jogada real visivel (pouco campo, sem rosto em destaque, energia de audio/movimento sem forma de jogo).

Regra de decisao no modo strict:

- `save_ready` **somente** se `category == "active_play"` e `active_play_score` alto o bastante (a acao NUNCA e `save_ready` para as outras 5 categorias, mesmo com campo/placar/torcida visiveis);
- `save_needs_review` quando a categoria e `active_play` mas o score ainda esta em duvida;
- `reject` para pre-jogo, pos-jogo, estudio, VAR/grafico, torcida/estadio puro e telas estaticas — no modo strict, casos ambiguos que nao batem com nenhuma categoria tambem caem em `reject` em vez de `needs_review` (fora do strict, ficam em `needs_review`).

Essa protecao roda automaticamente sempre que `--strict-football-filter` e usado; nao existe uma flag `--football-game-only` separada (o proprio `strict=True` ja ativa os limiares mais conservadores).

Para VODs longos com pre-jogo antes do apito inicial, pule direto para o inicio real da partida com `--start-seconds` (o filtro fica mais preciso, e a analise nao perde tempo com o pre-jogo):

```powershell
python main.py "URL_DO_VOD" --modo vod-clips --session-id jogo_001 --start-seconds 1800 --max-cortes 30 --content-filter football --strict-football-filter --smart-event-window --no-multi-event-clips
```

Se o sistema nao tiver certeza se e lance real, o corte vai para `needs_review`, nunca direto para `ready_hd`.

Teste leve sem baixar video (`classify_football_metrics` com metadados simulados para cada categoria):

```powershell
python test_football_content_filter.py
```

## Validacao dos cortes

Depois de renderizar, o sistema valida o arquivo final antes de marcar como concluido:

- arquivo existe;
- duracao maior que 5 segundos;
- stream de video abre corretamente;
- audio presente quando a fonte tem audio;
- resolucao valida;
- tamanho minimo aceitavel;
- amostras nao parecem video todo preto, roxo ou blank.

Se o corte com overlay ficar invalido, o arquivo bugado e apagado e o sistema tenta novamente sem overlay. Se ainda falhar, o corte e marcado como erro e o processamento continua.

Por padrao, arquivos intermediarios nao ficam na pasta final. Se precisar depurar, use:

```powershell
--keep-intermediate
```

## Arquitetura

- `main.py`: entrada CLI dos modos `atual`, `live`, `live-clips`, `near-live`, `final-hd`, `pos-live`, `scan-vod` e `vod-clips`.
- `highlight_detector.py`: detecta momentos por audio alto, movimento e mudancas visuais.
- `live_buffer.py`: captura blocos temporarios da live em cache.
- `live_watcher.py`: orquestra captura/análise/salvamento de timestamps ao vivo.
- `vod_scanner.py`: varre VOD/replay em blocos e salva timestamps deduplicados.
- `moment_logger.py`: salva/lista momentos detectados em `fila_local.jsonl`.
- `post_live_processor.py`: gera cortes definitivos com analise ou timestamps salvos.
- `smart_window.py`: calcula a janela adaptativa de corte (`--smart-event-window`/`--no-multi-event-clips`), evitando juntar dois lances no mesmo mp4.
- `clipper.py`: gera cortes nos layouts `original`, `vertical-fit` e `vertical-crop`, valida arquivo final e pode aplicar overlay opcional.
- `overlay_editor.py`: titulo, descricao, marca e CTA final opcionais.
- `caption_generator.py`: stub para futura legenda automatica.
- `chat_monitor.py`: legado/opcional; o fluxo principal nao usa chat.
- `database.py`: Supabase isolado ou fallback local.

## Overlay opcional

```powershell
python main.py "D:\videos\live.mp4" --modo pos-live --max-cortes 3 --titulo "GTA 6 INSANO" --descricao "momento absurdo da live" --marca "@seucanal" --cta "segue para mais"
```

## Instalar

```powershell
pip install -r requirements.txt
```

## Deploy na VPS (Docker + EasyPanel)

A imagem Docker roda o pipeline completo no Linux: `python:3.12-slim` + ffmpeg (apt) + fonte Anton embarcada + modelo whisper `small` pre-baixado no build (~460MB, runtime nunca baixa nada). Usuario nao-root `botlive` (uid 1000).

### Build e teste local

```powershell
docker build -t botlive .
docker run --rm -v botlive_output:/data/botlive/output -e BOTLIVE_SOURCE="URL_DO_VOD" -e BOTLIVE_MODO=vod-clips -e BOTLIVE_CONTENT_FILTER=football -e BOTLIVE_STRICT_FOOTBALL=1 botlive
```

Argumentos diretos no container ignoram as envs (escape hatch para comandos avulsos):

```powershell
docker run --rm -it -v botlive_tokens:/app/.tokens botlive python yt_publisher.py auth --conta principal
```

### EasyPanel (VPS 69.62.96.161)

1. Criar App a partir do repo privado do GitHub (conectar via GitHub App do EasyPanel), build type `Dockerfile`.
2. Montar dois volumes:
    - `/data/botlive/output` — cache, cortes, fila_local.jsonl, run_logs (dados).
    - `/app/.tokens` — tokens OAuth do YouTube (secrets, leitura+escrita: o refresh regrava o token).
3. Configurar as env vars (nao usar arquivo `.env` no container):
    - Pipeline: `BOTLIVE_SOURCE` **ou** `BOTLIVE_LISTA_LINKS` (mutuamente exclusivos), `BOTLIVE_MODO`, `BOTLIVE_SESSION_ID`, `BOTLIVE_CONTENT_FILTER`, `BOTLIVE_STRICT_FOOTBALL=1`, `BOTLIVE_RETENTION` (segundos), `BOTLIVE_MAX_CORTES`, `BOTLIVE_CLIP_DURATION`, `BOTLIVE_TARGET_HEIGHT`, `BOTLIVE_OUTPUT_LAYOUT`.
    - Publicacao: `BOTLIVE_PUBLISH_VERTICAL=1`, `BOTLIVE_POST_YOUTUBE=1`, `BOTLIVE_POST_VISIBILIDADE`, `BOTLIVE_POST_CONTA`, `BOTLIVE_CREDITO_STREAMER`, `BOTLIVE_CREDITO_CANAL`.
    - Flags nao mapeadas: `BOTLIVE_EXTRA_ARGS` (ex.: `--smart-event-window --no-multi-event-clips`).
    - Bloqueio "Sign in to confirm you're not a bot" (IP de datacenter): `BOTLIVE_YT_CLIENT=android` faz o yt-dlp se apresentar como app (aceita lista: `android,web`). Se nao bastar, plano B: `BOTLIVE_COOKIES_FILE=/app/.tokens/cookies.txt` apontando para um cookies.txt (formato Netscape) exportado de um navegador logado, copiado para o volume de tokens.
    - Secrets do `.env.example`: `ROBO_SUPABASE_URL`, `ROBO_SUPABASE_KEY`, `ROBO_SUPABASE_CLIPS_TABLE`, `PUBLISH_AI_*`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`.
4. Recursos: 2 vCPU / 4 GB RAM. Restart policy `always` para o modo live 24h.

### OAuth do YouTube na VPS

A primeira autorizacao e interativa (abre navegador) e nao funciona na VPS. Autorize no PC Windows (`python yt_publisher.py auth --conta principal`) e copie `.tokens/youtube/*.json` para o volume montado em `/app/.tokens` (mesma estrutura: `/app/.tokens/youtube/principal.json`). Se o volume for montado como root e der erro de permissao, na VPS: `chown -R 1000:1000` na pasta do volume.

### O que NUNCA entra na imagem

`.env` e `.tokens/` estao no `.dockerignore` — secrets vao por env var e volume, nunca no build. `teste_*/`, logs e `.git` tambem ficam fora.

## Supabase

Opcional. Para teste local, deixe vazio no `.env`.

```env
ROBO_SUPABASE_URL=
ROBO_SUPABASE_KEY=
ROBO_SUPABASE_CLIPS_TABLE=dark_gta_clips
```

Sem Supabase, eventos e status ficam em:

```text
D:/robo-cortes-dark/fila_local.jsonl
```

## Observacoes

O modo live salva timestamps aproximados. Se o replay/VOD tiver intro, atraso ou corte diferente, use `--vod-offset-seconds`.

Em lives do YouTube, o `live_buffer.py` tenta primeiro abrir a URL com ffmpeg direto. Quando o ffmpeg nao consegue ler a pagina do YouTube diretamente, o sistema usa `yt-dlp` para resolver a URL real do stream e entao grava o bloco com ffmpeg.

Legenda automatica ainda e modulo futuro. A estrutura esta pronta em `caption_generator.py`, mas nenhum Whisper/faster-whisper foi instalado nesta etapa.

## Roadmap do fluxo automatico

### A) Modo ao vivo

Objetivo: monitorar uma live em andamento, capturar blocos, analisar audio, movimento e mudanca visual, e salvar timestamps fortes enquanto a live acontece.

### B) Modo pos-live

Objetivo: quando a live terminar e virar replay/VOD, usar os timestamps salvos, gerar cortes finais em alta qualidade e salvar tudo em:

```text
D:/robo-cortes-dark/cortes
```

O near-live tambem salva timestamps nessa mesma fila. Assim, o fluxo rapido e: gerar previews durante a live em `live_preview`, validar o que apareceu, e depois renderizar os cortes finais HD com `--modo pos-live --usar-momentos-salvos --session-id ... --target-height 720`.

Quando `--target-height` e usado com timestamps salvos de uma URL, o pos-live tenta renderizar os cortes finais pelo VOD original em vez de reutilizar os blocos locais de analise. Cortes aprovados nesse fluxo HD sao organizados em:

```text
D:/robo-cortes-dark/cortes/ready_hd
```

### C) Futuro modo automatico

Objetivo futuro:

- monitorar canais ou URLs configuradas;
- detectar quando uma live comeca;
- rodar o modo live automaticamente;
- detectar quando a live termina;
- rodar o modo pos-live automaticamente;
- gerar varios cortes finais;
- deixar os videos prontos para postagem manual ou rascunho.

## Roadmap de publicacao e canais dark

Depois que a qualidade dos cortes estiver bem validada, o proximo objetivo do produto e preparar os videos para publicacao em canais dark. O foco inicial nao e publicar automaticamente, mas sim gerar cortes, organizar arquivos, preparar metadados e deixar tudo pronto para revisao manual.

Fluxo desejado:

- o bot recebe uma live/VOD ou monitora uma live;
- analisa o conteudo;
- gera varios cortes;
- salva os cortes finais;
- gera metadados basicos, como titulo, descricao, hashtags, nome do canal/projeto e categoria/nicho;
- organiza os cortes por canal ou projeto;
- envia ou prepara os videos para publicacao nas plataformas;
- deixa como rascunho ou pendente de aprovacao manual quando a plataforma permitir;
- o operador revisa e publica manualmente.

Canais e projetos futuros:

- futebol;
- GTA/GTA 6;
- lives de gameplay;
- entrevistas/reactions;
- outros canais dark.

### Fase atual

- gerar cortes localmente;
- validar qualidade de imagem, audio, duracao e layout;
- manter `--output-layout original` como padrao para futebol, gameplay e lives;
- nao postar automaticamente.

### Fase 2: organizacao por projeto/canal

Organizar os cortes em pastas por projeto ou canal, por exemplo:

```text
D:/robo-cortes-dark/projetos/futebol/cortes
D:/robo-cortes-dark/projetos/gta/cortes
```

### Fase 3: metadados para postagem

Gerar titulo, descricao e hashtags para cada corte. A primeira versao pode usar texto fixo ou templates simples. Depois, a geracao pode evoluir para IA opcional, sempre com revisao antes da publicacao.

### Fase 4: integracao com plataformas

Estudar integracoes com:

- TikTok;
- Instagram/Reels;
- YouTube Shorts;
- outras plataformas no futuro.

Qualquer integracao com plataforma depende das APIs oficiais, permissoes, limites, validacao de conta e regras de cada plataforma. Nao ha OAuth, token ou integracao de postagem implementados nesta fase.

### Fase 5: rascunho e aprovacao manual

A primeira versao de publicacao deve ser orientada a aprovacao manual:

- o bot prepara os cortes e metadados;
- quando possivel, envia como rascunho ou deixa pendente de aprovacao;
- o operador revisa;
- o operador publica manualmente.

Publicacao automatica sem revisao nao e objetivo inicial.

## Fluxo de revisao e rascunho

Na fase de validacao, o operador pode assistir alguns cortes para calibrar o detector. No uso real, o objetivo nao e assistir manualmente todos os cortes, e sim deixar o bot fazer a maior parte da triagem.

Fluxo desejado:

- gerar cortes automaticamente a partir da live/VOD;
- validar video, audio, duracao, resolucao e duplicidade;
- separar cortes bons, suspeitos e invalidos;
- organizar os resultados em uma pasta ou painel local;
- preparar os melhores cortes para postagem;
- deixar a revisao humana como uma etapa rapida antes da publicacao manual.

Cada corte deve evoluir para um status operacional:

- `ready`: corte aprovado automaticamente pelas validacoes e pronto para revisao rapida;
- `ready_hd`: corte aprovado em renderizacao HD a partir do VOD original, pronto para validacao de postagem;
- `needs_review`: corte possivelmente bom, mas com algum sinal de duvida, como score baixo, duplicidade proxima, pouca imagem de jogo ou metadados incompletos;
- `rejected`: corte invalido, repetido, sem audio, com video ruim, fora do conteudo desejado ou descartado pelo filtro;
- `published_draft`: corte enviado/preparado como rascunho ou pendente de aprovacao em alguma plataforma.

No futuro, uma galeria ou painel local deve mostrar:

- miniatura do corte;
- botao de assistir;
- timestamp;
- score;
- motivo do corte;
- status;
- botao aprovar;
- botao rejeitar;
- botao enviar para rascunho.

Para TikTok, Instagram/Reels e YouTube Shorts, a prioridade futura deve ser preparar a postagem, enviar como rascunho quando a plataforma permitir, ou deixar em fila de aprovacao manual. O bot nao deve publicar automaticamente sem confirmacao humana no inicio.

### Fase 6: automacao maior

Evoluir o fluxo para:

- monitorar canais ou lives configuradas;
- detectar quando uma live comeca;
- salvar timestamps fortes ao vivo;
- detectar quando a live termina;
- processar o replay/VOD no modo pos-live;
- gerar multiplos cortes;
- preparar posts com metadados e organizacao por projeto.
