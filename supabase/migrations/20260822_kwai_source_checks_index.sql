-- Índice que faltava em football_source_checks.
--
-- Sintoma: a página Kwai CUT mostrava "Migration do Kwai CUT ainda não aplicada
-- ou leitura indisponível" e ficava sem dados. Não era migration ausente: as
-- nove tabelas existem e respondem. O que acontecia é que
-- football_source_checks passou de 900 mil linhas (contra 717 fontes e 285
-- jobs) e a consulta da página — filtro por profile_id mais `order by
-- checked_at desc limit 100` — fazia varredura completa.
--
-- Medido em produção, com a chave de serviço:
--     só o filtro ................  80 ms
--     filtro + order by .......... 6.126 ms
--     só o order by .............. 2.219 ms
-- Com a chave anônima do painel o teto é menor e o banco cancelava a consulta
-- com 57014 (statement timeout), o que a página traduzia como migration ausente.
--
-- O índice cobre exatamente esse acesso: filtra por perfil e já entrega
-- ordenado por data, então o limit 100 para nas primeiras linhas.
--
-- Não altera dado nenhum: só cria índice.

create index if not exists football_source_checks_profile_checked_idx
    on public.football_source_checks (profile_id, checked_at desc);

-- Em tabela desse tamanho a criação leva alguns segundos e bloqueia ESCRITA
-- nela enquanto roda (leitura continua). Se preferir zero bloqueio, rode fora
-- de transação, uma instrução sozinha:
--
--     create index concurrently if not exists football_source_checks_profile_checked_idx
--         on public.football_source_checks (profile_id, checked_at desc);
--
-- Observação para depois: 900 mil verificações para 717 fontes é histórico
-- acumulado que ninguém lê além das 100 últimas. Uma política de retenção
-- (apagar checks com mais de N dias) deixaria a tabela saudável — mas isso
-- APAGA dado e fica para uma decisão sua, não entra aqui.
