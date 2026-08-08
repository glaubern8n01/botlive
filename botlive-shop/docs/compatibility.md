# Compatibilidade

Linha de base em 2026-08-08, antes da alteração:

- dashboard `npm run lint`: aprovado;
- dashboard `npm run build`: aprovado, com aviso de chunk >500 kB;
- Pytest com temporário isolado: 151 aprovados e 1 falha preexistente em `test_real_size_geometry_uses_64mb_then_remainder`;
- sem `--basetemp`, 43 setups falharam por permissão do temporário global do Windows.

Qualquer falha adicional bloqueia a entrega. A divergência preexistente de `chunk_geometry` não faz parte deste módulo.
