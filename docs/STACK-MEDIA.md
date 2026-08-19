# Stack de mídia — matriz de decisão

> Gerado por `botlive-media/mediastack/report.py`. Não editar à mão:
> regenere depois de registrar cada auditoria.

## Estado da auditoria

- Ferramentas no catálogo: **15**
- Prontas para produção: **0**

- NAO AUDITADO: 15 — arcads-claude-code, autosocial, capcut-cli, docker-android, dramaclaw, joyai-video-editor, moneyprinterturbo, open-generative-ai, open-llm-vtuber, openmontage, openshorts, social-auto-upload, video-shotcraft, wan2gp, youtube-automation-agent

Nenhum campo abaixo foi medido por mim. `não medido` quer dizer exatamente
isso: ninguém rodou, leu a licença nem mediu VRAM. Não é zero, não é falso.

## Matriz

| Ferramenta | Cobre | Prioridade | Licença | Custo | VRAM | RAM | Headless | API | CLI | Maturidade | Auditoria |
|---|---|---|---|---|---|---|---|---|---|---|---|
| arcads-claude-code | thumbnail, video | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| autosocial | publicacao | alta | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| capcut-cli | montagem | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| docker-android | infra | baixa | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| dramaclaw | video, montagem, render | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| joyai-video-editor | montagem, render | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| moneyprinterturbo | video, tts, legendas, montagem | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| open-generative-ai | imagem, video | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| open-llm-vtuber | avatar_live, tts | baixa | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| openmontage | montagem, render, legendas, tts | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| openshorts | clipping, transcricao, legendas | alta | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| social-auto-upload | publicacao | alta | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| video-shotcraft | montagem, render | alta | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| wan2gp | imagem, video, tts | muito-alta | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |
| youtube-automation-agent | publicacao | media | não medido | não medido | não medido | não medido | não medido | não medido | não medido | não medido | NAO AUDITADO |

## Proposta de menor conjunto (a validar)

Capacidades alvo: clipping, imagem, legendas, montagem, render, thumbnail, transcricao, tts, video

**Ferramentas propostas:** wan2gp, openshorts, video-shotcraft, arcads-claude-code

| Capacidade | Ferramenta proposta |
|---|---|
| clipping | openshorts |
| imagem | wan2gp |
| legendas | openshorts |
| montagem | video-shotcraft |
| render | video-shotcraft |
| thumbnail | arcads-claude-code |
| transcricao | openshorts |
| tts | wan2gp |
| video | wan2gp |

Pronta para produção: **não**
 — falta auditar 4 ferramenta(s): wan2gp, openshorts, video-shotcraft, arcads-claude-code.

Campos pendentes: api, cli, custo, headless, licenca, maturidade, ram, vram

## Stack adotável hoje (só auditadas)

Ferramentas: **nenhuma**

Capacidades ainda descobertas: clipping, imagem, legendas, montagem, render, thumbnail, transcricao, tts, video

## Perfis de hardware

| Perfil | VRAM | RAM | Quando usar |
|---|---|---|---|
| LOW_RESOURCE | 6.0 GB | 16.0 GB | Maquina sem GPU dedicada forte. Prioriza modelo pequeno e quantizado. |
| BALANCED | 12.0 GB | 32.0 GB | GPU intermediaria. Equilibra qualidade e tempo de render. |
| QUALITY | 24.0 GB | 64.0 GB | GPU dedicada grande. Libera os modelos maiores. |

## Repositórios

| Ferramenta | Repositório | O que se diz que ela faz |
|---|---|---|
| wan2gp | https://github.com/deepbeepmeep/Wan2GP | Video, imagem, audio/TTS, low-VRAM, API, headless, fila. |
| video-shotcraft | https://github.com/Vincentwei1021/video-shotcraft | 152 shot cards, 209 previews, Remotion, sound design, export JianYing. |
| openshorts | https://github.com/mutonby/openshorts | Whisper, deteccao de cenas, cortes, 9:16, captions, UGC. |
| openmontage | https://github.com/calesthio/OpenMontage | Clipes, narracao, musica, legenda, edicao e render. |
| dramaclaw | https://github.com/dramaclaw/dramaclaw | Pipeline self-hosted de roteiro ate filme. |
| moneyprinterturbo | https://github.com/harry0703/MoneyPrinterTurbo | Roteiro, narracao, legendas, busca visual e montagem de shorts. |
| joyai-video-editor | https://github.com/jd-opensource/JoyAI-Video-Editor | Edicao e transformacao de video em streaming. |
| capcut-cli | https://github.com/renezander030/capcut-cli | Automacao de drafts CapCut/JianYing via CLI/JSON. |
| open-generative-ai | https://github.com/Anil-matcha/Open-Generative-AI | Interface agregadora de imagem/video; providers variam. |
| arcads-claude-code | https://github.com/krusemediallc/arcads-claude-code | UGC, anuncios, thumbnails, clone-ad, workflows. |
| youtube-automation-agent | https://github.com/darkzOGx/youtube-automation-agent | Agente de gestao/producao/publicacao de canal. |
| autosocial | https://github.com/Katzca/AutoSocial | TikTok, Instagram, YouTube; multi-conta, filas, Playwright, FFmpeg. |
| social-auto-upload | https://github.com/dreammis/social-auto-upload | CLI, skills para agentes, upload e agendamento; Kuaishou suportado. |
| docker-android | https://github.com/HQarroum/docker-android | Android em Docker, ADB, KVM, headless. |
| open-llm-vtuber | https://github.com/Open-LLM-VTuber/Open-LLM-VTuber | LLM + STT + TTS + Live2D, pode operar local/offline. |

A coluna acima é o que o documento do projeto **declara** sobre cada
ferramenta — não é verificação. Auditar antes de instalar.
