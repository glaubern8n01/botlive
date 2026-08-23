# Auditoria das ferramentas de mídia — 22/08/2026

Execução da Etapa 5 do Prompt Mestre 1 e da Etapa 4 do Prompt Mestre 2
(`BotLive_TikTokShop_Arquitetura_e_Prompts_Completos.docx`), que pediam:
auditar antes de instalar, montar matriz de decisão e escolher **o menor
conjunto** que cubra imagem, vídeo, TTS, transcrição, legendas, montagem,
render, thumbnail e clipping.

**Nada foi instalado.** Nenhum código de terceiros foi copiado. As 15
ferramentas do documento saíram de `NÃO AUDITADO` para auditadas por fonte
oficial (página do repositório, licença e requisitos declarados).

## O hardware decide quase tudo

Medido nas duas máquinas, e não estimado:

| | PC do Glauber | VPS |
|---|---|---|
| GPU | **AMD RX 580 2048SP, 4 GB** | nenhuma |
| CUDA / ROCm | não / **fora** (Polaris é GCN, não RDNA) | — |
| CPU | Ryzen 5 3500, 6 núcleos | 4 vCPU |
| RAM | 16 GB | 16 GB |
| `/dev/kvm` | — | **não existe**, e sem flag `vmx`/`svm` |

Isso não é detalhe: **geração local de vídeo por difusão está fora das duas
máquinas**, e não por pouco. É o eixo que derruba metade da lista.

## Matriz

Legenda de veredito: **usar** · **condicional** (depende de decisão sua) ·
**referência** (ler, não integrar) · **descartar** (com motivo).

| Ferramenta | Licença | Estrelas | Função | Roda no hardware? | Custo obrigatório | Veredito |
|---|---|---|---|---|---|---|
| deepbeepmeep/Wan2GP (WanGP) | MIT | 8,8k | vídeo/imagem/TTS local | **Não.** Exige GPU ≥6 GB; AMD só RDNA 2/3/4 — a RX 580 é Polaris | nenhum | **descartar** (hardware) |
| jd-opensource/JoyAI-Video-Edit ¹ | Apache-2.0 | 1,6k | edição por difusão em tempo real | **Não.** 16B parâmetros; demo em RTX PRO 6000; sem caminho CPU | nenhum | **descartar** (hardware) |
| mutonby/openshorts | MIT (core) | 3,4k | clipping 9:16, legendas, dublagem | Sim, CPU (5–8 min por vídeo de 8 min) | **fal.ai ~US$ 0,50–1,50 por vídeo** + Gemini + ElevenLabs | **descartar** (custo por vídeo, e já temos clipping) |
| calesthio/OpenMontage | **AGPLv3** | 49,5k | pipeline agêntico de produção | Sim, GPU opcional; funciona com Piper/Pexels grátis | nenhum (provedores pagos são opcionais) | **referência** — a AGPL contamina: o painel é servido pela rede |
| dramaclaw/dramaclaw | **Elastic 2.0** | 3,9k | roteiro → storyboard → filme | Sim (2 vCPU/4 GB) | gateway compatível com OpenAI | **descartar** (licença não é OSI + LLM obrigatório) |
| harry0703/MoneyPrinterTurbo | MIT | 114,7k | shorts a partir de tema | Sim; GPU opcional | nenhum (Edge TTS grátis, Ollama local) | **referência** — sobrepõe ao pipeline que já existe |
| Vincentwei1021/video-shotcraft | Apache-2.0 | 6,1k | 152 shot cards, motion design, render Remotion | Sim — documentam headless com 2 núcleos | **Remotion cobra de empresas** | **condicional** (ver decisão abaixo) |
| Anil-matcha/Open-Generative-AI | MIT | 26,8k | estúdio de imagem/vídeo | Sim | **chave Muapi.ai, créditos pagos** | **descartar** (viola LOCAL > GRÁTIS) |
| krusemediallc/arcads-claude-code | MIT | 1,4k | fórmulas de UGC, product hero, thumbnails | Sim | **chave Arcads obrigatória** | **referência** — exatamente como o documento mandou: prompts sim, dependência não |
| renezander030/capcut-cli | MIT | 379 | edita projetos CapCut/JianYing | Sim (Node 18+) | nenhum | **descartar** — gera *draft*, não renderiza; o final exige abrir o CapCut à mão, o oposto de lote |
| Katzca/AutoSocial | MIT | 618 | publica TikTok/IG/YT por Playwright | Sim | nenhum | **referência** para o VexPublish (fila por conta, scheduler, sessões isoladas) |
| dreammis/social-auto-upload | MIT | 14,5k | upload multi-plataforma, **Kuaishou incluído** | Sim | nenhum | **condicional** — é o caminho nº 2 da trilha Kwai |
| HQarroum/docker-android | MIT | 7,2k | Android em Docker com ADB | **Não na VPS**: exige `/dev/kvm`, que não existe lá | nenhum | **descartar na VPS**; no PC seria possível |
| Open-LLM-VTuber | MIT | 13,4k | avatar Live2D com voz, roda offline | Sim, **funciona em CPU** | nenhum | **referência** — só interessa se houver apresentador em LIVE |
| darkzOGx/youtube-automation-agent | MIT | 2,5k | agente de canal do YouTube | Sim | Gemini free tier cobre o básico | **referência** — sobrepõe ao pipeline atual |

¹ O documento listava `JoyAI-Video-Editor`; o repositório real é
`jd-opensource/JoyAI-Video-Edit`.

## O menor conjunto que cobre tudo

A conclusão incômoda é que **o BotLive já cobre as nove funções pedidas**, com
ferramentas que rodam no hardware que existe. Nenhuma das 15 é obrigatória:

| Função | Já em uso hoje | Precisa de algo novo? |
|---|---|---|
| Transcrição | `faster-whisper` na CPU (`transcriber.py`) | não |
| TTS / narração | Piper `pt_BR-faber-medium`, ONNX na CPU, ~1× tempo real | não |
| Imagem / thumbnail | Pillow (capa de frame, card de produto) | não |
| Legendas | FFmpeg `drawtext` + SRT | não |
| Clipping | `highlight_detector.py` + `clipper.py` | não |
| Montagem / render | FFmpeg (Produção em Massa e Campanhas) | não |
| Vídeo **gerado** por IA | — | **não tem como**, sem GPU |

O que muda com isto é a expectativa, não o código: a Fase 6 do documento
imaginava WanGP gerando vídeo local. Com RX 580 de 4 GB e VPS sem GPU, esse
caminho não existe. O que o BotLive faz — e faz bem — é **montar e adaptar
material que já existe**, não inventar imagem do zero.

## As duas decisões que dependem de você

1. **video-shotcraft** (Apache-2.0, 6,1k) traz 152 receitas de plano e um
   template Remotion pronto — é o único da lista que acrescenta algo real ao
   nosso lado de montagem, e roda em CPU. Mas o **Remotion cobra licença de
   empresas**. Vale ler os termos antes; se a Vextriq entrar como empresa, é
   custo recorrente.

2. **social-auto-upload** (MIT, 14,5k) suporta Kuaishou por cookies +
   navegador, com CLI. É o passo 2 da ordem de investigação do Kwai. **Aviso
   que precisa ficar dito:** Kwai Brasil não é Kuaishou China — domínio,
   cookies e seletores mudam, e o próprio documento manda tratar como
   `NÃO VALIDADO` até teste real com a conta brasileira.

## O que fica descartado, e por quê

- **por hardware**: WanGP, JoyAI-Video-Edit, docker-android (na VPS);
- **por custo obrigatório**: OpenShorts (por vídeo), Open-Generative-AI,
  arcads-claude-code (como dependência), DramaClaw;
- **por licença**: OpenMontage (AGPLv3 contaminaria o painel), DramaClaw
  (Elastic 2.0 não é OSI);
- **por não servir ao lote**: capcut-cli (gera draft, exige mão humana no
  render final).

Nenhum foi instalado. Nenhuma linha copiada. O `THIRD_PARTY_NOTICES.md` foi
atualizado com licença, veredito e data desta auditoria.
