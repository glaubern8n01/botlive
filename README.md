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
