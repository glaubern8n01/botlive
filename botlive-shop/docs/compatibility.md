# Compatibilidade

Linha de base em 2026-08-08, antes da alteração:

- dashboard `npm run lint`: aprovado;
- dashboard `npm run build`: aprovado, com aviso de chunk >500 kB;
- Pytest com temporário isolado: 151 aprovados e 1 falha preexistente em `test_real_size_geometry_uses_64mb_then_remainder`;
- sem `--basetemp`, 43 setups falharam por permissão do temporário global do Windows.

Qualquer falha adicional bloqueia a entrega. A divergência preexistente de `chunk_geometry` não faz parte deste módulo.

## Branch limpa da Fase 1

A branch foi recriada sobre `origin/main` em `3f2eca1`. Essa base não contém a pasta rastreada `tests/`; a suíte de 151 testes observada anteriormente pertencia aos 90 commits não relacionados da branch antiga e não foi copiada. Validações disponíveis na base limpa: typecheck e builds Vite off/on. O Shop LIVE possui sua própria suíte isolada com endpoint, WebSocket, origem, persistência, migração, simulador, compliance e contrato do dashboard.
