// Leitura do cookie do YouTube. Roda com: node --test dashboard/server.test.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

import { avaliarCookies, lerCookies } from './server.mjs';

const TAB = '\t';
function linha(nome, expira, dominio = '.youtube.com') {
  return [dominio, 'TRUE', '/', 'TRUE', String(expira), nome, 'valor'].join(TAB);
}

const DAQUI_UM_ANO = Math.floor(Date.now() / 1000) + 365 * 86400;
const ONTEM = Math.floor(Date.now() / 1000) - 86400;

test('ignora comentario e linha curta', () => {
  const texto = ['# Netscape HTTP Cookie File', '', 'lixo', linha('SID', DAQUI_UM_ANO)].join('\n');
  assert.equal(lerCookies(texto).length, 1);
});

test('cookie bom vira estado ok', () => {
  const texto = [linha('SID', DAQUI_UM_ANO), linha('LOGIN_INFO', DAQUI_UM_ANO)].join('\n');
  const leitura = avaliarCookies(texto);
  assert.equal(leitura.estado, 'ok');
  assert.ok(leitura.dias_que_faltam > 300);
});

test('cookie vencido e recusado', () => {
  assert.equal(avaliarCookies(linha('SID', ONTEM)).estado, 'vencido');
});

test('avisa quando esta perto de vencer', () => {
  const emTresDias = Math.floor(Date.now() / 1000) + 3 * 86400;
  assert.equal(avaliarCookies(linha('SID', emTresDias)).estado, 'vencendo');
});

test('arquivo sem cookie de login nao serve', () => {
  // PREF e VISITOR_INFO1_LIVE existem em qualquer visita anonima: sem SID o
  // yt-dlp volta a levar "Sign in to confirm you're not a bot".
  const texto = [linha('PREF', DAQUI_UM_ANO), linha('VISITOR_INFO1_LIVE', DAQUI_UM_ANO)].join('\n');
  const leitura = avaliarCookies(texto);
  assert.equal(leitura.estado, 'invalido');
  assert.match(leitura.motivo, /login/);
});

test('arquivo de outro site nao serve', () => {
  assert.equal(avaliarCookies(linha('SID', DAQUI_UM_ANO, '.google.com')).estado, 'invalido');
});

test('texto vazio nao explode', () => {
  assert.equal(avaliarCookies('').estado, 'invalido');
});

test('cookie de sessao (expira 0) nao decide o vencimento', () => {
  const texto = [linha('SID', DAQUI_UM_ANO), linha('__Secure-1PSID', 0)].join('\n');
  assert.equal(avaliarCookies(texto).estado, 'ok');
});
