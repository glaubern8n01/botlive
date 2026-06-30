# Robo de Cortes Dark GTA 6/Games

Sistema autonomo para detectar momentos fortes pelo conteudo do video, sem depender de chat.

## Modos

### 1. Modo atual/padrao

Mantem o fluxo que ja funcionava: prepara URL ou arquivo local, analisa o video inteiro e gera cortes. Por padrao o corte preserva o formato original do video, sem crop.

```powershell
python main.py "URL_OU_ARQUIVO" --max-cortes 8
```

### 2. Modo pos-live

Fluxo explicito para replay/VOD ou arquivo completo. Pode analisar o video ou usar timestamps salvos durante o modo live.

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

## Paths obrigatorios no Drive D

```text
D:/robo-cortes-dark/cache
D:/robo-cortes-dark/cache/live_blocks
D:/robo-cortes-dark/cache/vod_blocks
D:/robo-cortes-dark/cortes
D:/robo-cortes-dark/fila_local.jsonl
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

- `main.py`: entrada CLI dos modos `atual`, `live`, `pos-live` e `scan-vod`.
- `highlight_detector.py`: detecta momentos por audio alto, movimento e mudancas visuais.
- `live_buffer.py`: captura blocos temporarios da live em cache.
- `live_watcher.py`: orquestra captura/análise/salvamento de timestamps ao vivo.
- `vod_scanner.py`: varre VOD/replay em blocos e salva timestamps deduplicados.
- `moment_logger.py`: salva/lista momentos detectados em `fila_local.jsonl`.
- `post_live_processor.py`: gera cortes definitivos com analise ou timestamps salvos.
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

### Fase 6: automacao maior

Evoluir o fluxo para:

- monitorar canais ou lives configuradas;
- detectar quando uma live comeca;
- salvar timestamps fortes ao vivo;
- detectar quando a live termina;
- processar o replay/VOD no modo pos-live;
- gerar multiplos cortes;
- preparar posts com metadados e organizacao por projeto.
