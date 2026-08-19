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

## Regra para as próximas fases

1. Antes de copiar qualquer trecho, registrar a linha na tabela acima com commit exato.
2. Preservar o cabeçalho de licença original no arquivo adaptado.
3. Licença incompatível ou ausente: não copiar. Reimplementar a partir do comportamento observado e registrar como referência.
4. Código open source não significa provider gratuito — custo e quota de qualquer serviço usado por essas ferramentas são auditados à parte.
