# Auto Source Discovery

## Objetivo

Permitir que o usuario cadastre canais uma vez e o sistema encontre lives/VODs automaticamente, sem precisar colar links manualmente toda hora.

## Problema atual

Hoje o usuario precisa passar a URL manualmente.

Exemplo:

```powershell
python main.py "URL_DA_LIVE" --modo live-clips ...
```

Isso funciona para teste, mas nao e bom para produto/SaaS.

## Fluxo desejado

Usuario cadastra um projeto:

- nome do projeto;
- nicho;
- plataforma;
- canais monitorados;
- palavras-chave;
- modo preferido;
- filtro de conteudo;
- pasta de saida;
- limite de cortes;
- se gera preview ao vivo;
- se gera final HD depois.

Exemplo de projeto:

```text
Projeto: GTA 6 Clips
Plataformas:
- YouTube
- Twitch

Canais monitorados:
- canal 1
- canal 2
- canal 3

Regras:
- se canal entrar ao vivo, rodar live-clips;
- se aparecer VOD novo, rodar vod-clips;
- se live terminar e virar replay, rodar final-hd;
- salvar tudo em uma pasta por projeto e por sessao.
```

## Estrutura futura de configuracao

Sugerir algo como:

```text
config/projects/gta6.json
config/projects/futebol.json
config/projects/fluminense.json
```

Exemplo de JSON:

```json
{
  "project_id": "gta6",
  "name": "GTA 6 Clips",
  "niche": "gaming",
  "platforms": ["youtube", "twitch"],
  "channels": [
    {
      "platform": "youtube",
      "channel_name": "Canal Exemplo",
      "channel_url": "https://www.youtube.com/@canalexemplo",
      "enabled": true
    },
    {
      "platform": "twitch",
      "channel_name": "streamerexemplo",
      "channel_url": "https://www.twitch.tv/streamerexemplo",
      "enabled": true
    }
  ],
  "default_mode_live": "live-clips",
  "default_mode_vod": "vod-clips",
  "final_mode": "final-hd",
  "content_filter": "none",
  "smart_event_window": true,
  "no_multi_event_clips": true,
  "output_layout": "original",
  "target_height": 720,
  "max_cortes_live": 15,
  "max_cortes_vod": 30
}
```

## YouTube

Documentar que futuramente o sistema deve conseguir:

- monitorar canal por URL;
- identificar live ativa;
- identificar video/VOD novo;
- gerar session_id automaticamente;
- salvar historico para nao processar o mesmo video duas vezes.

Possiveis estados:

- `live_not_started`;
- `live_active`;
- `live_ended`;
- `replay_available`;
- `vod_available`;
- `already_processed`;
- `processing`;
- `failed`.

## Twitch

Documentar que futuramente o sistema deve conseguir:

- monitorar canais da Twitch;
- detectar streamer ao vivo;
- capturar live com live-clips;
- detectar VOD novo;
- rodar vod-clips;
- evitar processar o mesmo VOD duas vezes.

Importante:
Nao implementar integracao real agora.
Apenas documentar arquitetura.

Se no futuro a Twitch exigir autenticacao oficial/API, usar apenas caminho oficial e seguro.
Nao usar gambiarra, cookies, sessao de navegador ou login manual.

## Banco de dados futuro

Documentar tabelas futuras ou arquivos JSON locais para dashboard:

- `projects`
- `sources`
- `source_checks`
- `sessions`
- `detected_lives`
- `detected_vods`
- `jobs`
- `clips`
- `clip_reviews`

Cada `source` deve guardar:

- `id`;
- `project_id`;
- `platform`;
- `channel_name`;
- `channel_url`;
- `enabled`;
- `last_checked_at`;
- `last_live_id`;
- `last_vod_id`;
- `last_status`;
- `created_at`.

Cada `session` deve guardar:

- `session_id`;
- `project_id`;
- `platform`;
- `source_url`;
- `source_type`;
- `title`;
- `started_at`;
- `ended_at`;
- `output_root`;
- `status`.

## Worker futuro

Documentar um worker chamado, por exemplo:

```text
source_monitor.py
```

Funcao futura:

- ler projetos cadastrados;
- checar canais ativos;
- descobrir lives/VODs;
- criar jobs;
- chamar live-clips, vod-clips ou final-hd.

Nao implementar agora, apenas documentar.

## Dashboard futuro

No dashboard, criar telas futuras:

1. Projetos
   - criar projeto;
   - escolher nicho;
   - configurar marca/arroba;
   - escolher pasta de saida;
   - escolher plataformas.

2. Fontes/Canais
   - adicionar canal YouTube;
   - adicionar canal Twitch;
   - ativar/desativar monitoramento;
   - ver ultimo status.

3. Lives detectadas
   - ao vivo agora;
   - aguardando;
   - encerradas;
   - prontas para final-hd.

4. VODs detectados
   - novos VODs;
   - ja processados;
   - falhados.

5. Jobs
   - live-clips rodando;
   - vod-clips rodando;
   - final-hd pendente;
   - final-hd concluido.

6. Cortes
   - live_preview;
   - ready_hd;
   - needs_review;
   - rejected;
   - aprovado;
   - publicado/rascunho futuramente.

## Fluxo para GTA 6

Documentar exemplo:

1. Usuario cria projeto "GTA 6 Clips".
2. Cadastra canais/streamers de GTA.
3. Sistema monitora YouTube e Twitch.
4. Quando alguem entra ao vivo jogando GTA:
   - cria session_id automatico;
   - roda live-clips;
   - gera previews rapidos.
5. Quando a live termina:
   - se VOD estiver disponivel, roda final-hd;
   - se for VOD novo, roda vod-clips.
6. Dashboard mostra os melhores cortes para revisao.

## Fluxo para futebol

Documentar exemplo:

1. Usuario cria projeto "Futebol Clips".
2. Cadastra canais de transmissao permitidos.
3. Sistema monitora lives e VODs.
4. Quando detectar jogo:
   - roda live-clips com content-filter football;
   - usa smart-event-window;
   - evita multiplos lances no mesmo corte.
5. Depois do jogo:
   - roda final-hd se o replay estiver disponivel;
   - salva em ready_hd.

## Regras de seguranca e limites

Documentar:

- nao usar cookies;
- nao usar login manual;
- nao usar sessao de navegador;
- nao burlar plataforma;
- nao baixar conteudo proibido;
- respeitar bloqueios;
- se plataforma nao permitir, registrar erro e parar;
- preferir APIs oficiais quando necessario;
- nao postar automaticamente sem aprovacao do usuario.

## Ordem futura de implementacao

Depois do dashboard local, implementar nesta ordem:

1. Cadastro de projetos no dashboard.
2. Cadastro de fontes/canais.
3. Armazenar fontes em JSON ou SQLite local.
4. Criar `source_monitor.py`.
5. Detectar YouTube live/VOD.
6. Detectar Twitch live/VOD.
7. Criar fila de jobs.
8. Rodar live-clips automaticamente.
9. Rodar final-hd depois da live.
10. Mostrar resultados no dashboard.
11. So depois pensar em SaaS multiusuario.

## Importante

Este arquivo e apenas roadmap/documentacao.
Nao implementar codigo agora.
Nao rodar testes de live agora.
Nao fazer grandes mudancas.
