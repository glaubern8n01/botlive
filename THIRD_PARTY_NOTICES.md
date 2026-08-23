# Third Party Notices

Registro de código de terceiros reutilizado no BotLive. Toda entrada precisa de
projeto de origem, repositório, commit, arquivo e o que foi adaptado. Repositório
consultado apenas como referência de arquitetura, sem cópia de código, também é
registrado — com `source_file: (nenhum)` — para que a origem da ideia fique clara.

## VexPublish

### Nenhum código de terceiros copiado até aqui

O módulo `vexpublish/` foi escrito do zero nesta fase. Os repositórios abaixo
foram levantados como candidatos de referência para as próximas fases, mas
**nada deles foi lido, copiado ou instalado** até este ponto.

| source_project | source_repository | source_commit | source_file | license | adaptations |
|---|---|---|---|---|---|
| Katzca/AutoSocial | https://github.com/Katzca/AutoSocial | (não auditado) | (nenhum) | (não verificada) | Candidato de referência para TikTok/Instagram/YouTube, multi-conta, fila, scheduler, Playwright e sessões. Não auditado. |
| dreammis/social-auto-upload | https://github.com/dreammis/social-auto-upload | (não auditado) | (nenhum) | (não verificada) | Candidato prioritário de referência para Kuaishou/Kwai. Não auditado. |
| Fuploader | (repositório a confirmar) | (não auditado) | (nenhum) | (não verificada) | Fallback de pesquisa para Kuaishou. Repositório atual e licença precisam ser confirmados antes de qualquer leitura de código. |

## Importar / Adaptar / Publicar

### Nenhum código de terceiros copiado até aqui

O módulo `botlive-import/` reaproveita **código do próprio repositório**
(`clipper.py`, `overlay_editor.py`), carregado por `importlib` sem alterar os
arquivos originais. As ferramentas abaixo foram avaliadas para download de
fontes autorizadas e **não foram instaladas nem integradas** nesta fase.

| source_project | source_repository | source_commit | source_file | license | adaptations |
|---|---|---|---|---|---|
| yt-dlp | https://github.com/yt-dlp/yt-dlp | (não auditado) | (nenhum) | Unlicense (a confirmar) | Já usado em outra parte do BotLive para captura. Aqui seria o executor de download de fonte autorizada — não implementado. |
| gallery-dl | https://github.com/mikf/gallery-dl | (não auditado) | (nenhum) | GPL-2.0 (a confirmar) | Candidato para fontes de imagem/galeria autorizadas. Não auditado. A licença GPL exige análise antes de qualquer vínculo de código. |

Nenhuma dessas ferramentas é usada para remover marca d'água, crédito ou
proteção técnica — o plano de adaptação recusa esse tipo de opção por código.

## Ferramentas de mídia — auditadas em 22/08/2026

As 15 candidatas do documento de arquitetura saíram de `NÃO AUDITADO`. A
verificação foi por fonte oficial (página do repositório, arquivo de licença e
requisitos declarados). **Nenhuma foi instalada e nenhuma linha foi copiada.**
O raciocínio completo, com a matriz e o hardware medido, está em
[docs/AUDITORIA-FERRAMENTAS-MIDIA.md](docs/AUDITORIA-FERRAMENTAS-MIDIA.md).

| source_project | source_repository | license | veredito |
|---|---|---|---|
| deepbeepmeep/Wan2GP | https://github.com/deepbeepmeep/Wan2GP | MIT | Descartado: exige GPU ≥6 GB; AMD só RDNA 2/3/4 e a máquina tem Polaris 4 GB |
| jd-opensource/JoyAI-Video-Edit | https://github.com/jd-opensource/JoyAI-Video-Edit | Apache-2.0 | Descartado: 16B parâmetros, sem caminho em CPU |
| mutonby/openshorts | https://github.com/mutonby/openshorts | MIT (core) | Descartado: fal.ai cobra por vídeo e o clipping já existe aqui |
| calesthio/OpenMontage | https://github.com/calesthio/OpenMontage | AGPL-3.0 | Só referência: AGPL contaminaria o painel, que é servido pela rede |
| dramaclaw/dramaclaw | https://github.com/dramaclaw/dramaclaw | Elastic 2.0 | Descartado: licença não-OSI e LLM externo obrigatório |
| harry0703/MoneyPrinterTurbo | https://github.com/harry0703/MoneyPrinterTurbo | MIT | Só referência: sobrepõe ao pipeline atual |
| Vincentwei1021/video-shotcraft | https://github.com/Vincentwei1021/video-shotcraft | Apache-2.0 | Condicional: roda em CPU, mas o Remotion cobra licença de empresa |
| Anil-matcha/Open-Generative-AI | https://github.com/Anil-matcha/Open-Generative-AI | MIT | Descartado: exige créditos pagos da Muapi.ai |
| krusemediallc/arcads-claude-code | https://github.com/krusemediallc/arcads-claude-code | MIT | Só referência de prompts: a API da Arcads é obrigatória e paga |
| renezander030/capcut-cli | https://github.com/renezander030/capcut-cli | MIT | Descartado: entrega draft, não render final |
| Katzca/AutoSocial | https://github.com/Katzca/AutoSocial | MIT | Referência para o VexPublish (fila por conta, scheduler, sessões) |
| dreammis/social-auto-upload | https://github.com/dreammis/social-auto-upload | MIT | Condicional: suporta Kuaishou; Kwai BR ainda NÃO VALIDADO |
| HQarroum/docker-android | https://github.com/HQarroum/docker-android | MIT | Descartado na VPS: exige /dev/kvm, que não existe lá |
| Open-LLM-VTuber | https://github.com/Open-LLM-VTuber/Open-LLM-VTuber | MIT | Só referência: roda em CPU, mas só serve com avatar em LIVE |
| darkzOGx/youtube-automation-agent | https://github.com/darkzOGx/youtube-automation-agent | MIT | Só referência: sobrepõe ao pipeline atual |

## Regra para as próximas fases

1. Antes de copiar qualquer trecho, registrar a linha na tabela acima com commit exato.
2. Preservar o cabeçalho de licença original no arquivo adaptado.
3. Licença incompatível ou ausente: não copiar. Reimplementar a partir do comportamento observado e registrar como referência.
4. Código open source não significa provider gratuito — custo e quota de qualquer serviço usado por essas ferramentas são auditados à parte.
