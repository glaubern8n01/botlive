# Robo de Cortes Dark GTA 6/Games

Sistema autonomo para detectar momentos fortes pelo conteudo do video, sem depender de chat.

## Modos

### 1. Modo atual/padrao

Mantem o fluxo que ja funcionava: prepara URL ou arquivo local, analisa o video inteiro e gera cortes 9:16.

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

### 3. Modo live

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

## Arquitetura

- `main.py`: entrada CLI dos modos `atual`, `live` e `pos-live`.
- `highlight_detector.py`: detecta momentos por audio alto, movimento e mudancas visuais.
- `live_buffer.py`: captura blocos temporarios da live em cache.
- `live_watcher.py`: orquestra captura/análise/salvamento de timestamps ao vivo.
- `moment_logger.py`: salva/lista momentos detectados em `fila_local.jsonl`.
- `post_live_processor.py`: gera cortes definitivos com analise ou timestamps salvos.
- `clipper.py`: gera cortes verticais 9:16 e pode aplicar overlay opcional.
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
