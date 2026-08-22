import { createReadStream } from 'node:fs';
import { realpath, stat, unlink } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, isAbsolute, join, resolve, sep } from 'node:path';

const port = Number(process.env.PORT || 3000);
const distRoot = resolve(process.env.DASHBOARD_DIST_ROOT || 'dist');
const mediaRoot = resolve(process.env.BOTLIVE_OUTPUT_ROOT || '/data/botlive/output');
const supabaseUrl = process.env.VITE_SUPABASE_URL;
const supabaseKey = process.env.VITE_SUPABASE_ANON_KEY;
// Credencial administrativa (service_role) — SOMENTE server-side. Nunca use prefixo
// VITE_ para esta variável: isso a incluiria no bundle do browser. As mutações de
// revisão só rodam com ela; sem ela os endpoints administrativos ficam desligados.
const adminKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.ROBO_SUPABASE_KEY;
// Aceita também o identificador legado de 35 caracteres já persistido no banco.
// A consulta continua limitada a hexadecimal/hífens e igualdade exata no Supabase.
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{11,12}$/i;

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.mp4': 'video/mp4',
};

function json(response, status, body) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(body));
}

async function querySupabase(table, column, value, select) {
  if (!supabaseUrl || !supabaseKey) throw new Error('Supabase não configurado');
  const url = new URL(`/rest/v1/${table}`, supabaseUrl);
  url.searchParams.set('select', select);
  url.searchParams.set(column, `eq.${value}`);
  url.searchParams.set('limit', '1');
  const response = await fetch(url, {
    headers: { apikey: supabaseKey, Authorization: `Bearer ${supabaseKey}` },
  });
  if (!response.ok) throw new Error(`Consulta de mídia falhou (${response.status})`);
  const rows = await response.json();
  return rows[0] || null;
}

async function querySupabaseFlexibleId(table, value, select) {
  try {
    const direct = await querySupabase(table, 'asset_id', value, select);
    if (direct) return direct;
  } catch (error) {
    if (String(value).length === 36) throw error;
  }
  if (!supabaseUrl || !supabaseKey) throw new Error('Supabase não configurado');
  const url = new URL(`/rest/v1/${table}`, supabaseUrl);
  url.searchParams.set('select', `asset_id,${select}`);
  url.searchParams.set('limit', '1000');
  const response = await fetch(url, { headers: { apikey: supabaseKey, Authorization: `Bearer ${supabaseKey}` } });
  if (!response.ok) throw new Error(`Consulta compatível de mídia falhou (${response.status})`);
  const rows = await response.json();
  return rows.find((row) => String(row.asset_id) === String(value)) || null;
}

function safeFilename(value, fallback) {
  const normalized = String(value || fallback)
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return normalized || fallback;
}

async function verifiedMediaPath(rawPath) {
  const root = await realpath(mediaRoot);
  const candidate = await realpath(isAbsolute(rawPath) ? resolve(rawPath) : resolve(mediaRoot, rawPath));
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    throw new Error('Arquivo fora do volume autorizado');
  }
  return candidate;
}

async function findMediaFile(filename) {
  if (!filename) return null;
  const safe = safeFilename(filename, '');
  if (!safe || safe !== filename) return null;
  const date = /-(\d{8})-/.exec(safe)?.[1];
  if (!date) return null;
  const candidate = join(mediaRoot, 'kwai_cut', 'ready', date, safe);
  try { return (await stat(candidate)).isFile() ? candidate : null; } catch { return null; }
}

async function serveFile(request, response, path, options = {}) {
  const info = await stat(path);
  if (!info.isFile()) throw new Error('Arquivo não encontrado');
  const type = mimeTypes[extname(path).toLowerCase()] || 'application/octet-stream';
  const headers = {
    'Accept-Ranges': 'bytes',
    'Cache-Control': options.cache ? 'public, max-age=3600' : 'no-store',
    'Content-Type': type,
  };
  if (options.filename) {
    headers['Content-Disposition'] = `${options.download ? 'attachment' : 'inline'}; filename="${safeFilename(options.filename, 'arquivo')}"`;
  }
  const range = request.headers.range;
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (!match) return json(response, 416, { error: 'Intervalo inválido' });
    const start = match[1] ? Number(match[1]) : 0;
    const end = match[2] ? Math.min(Number(match[2]), info.size - 1) : info.size - 1;
    if (start > end || start >= info.size) return json(response, 416, { error: 'Intervalo inválido' });
    response.writeHead(206, { ...headers, 'Content-Length': end - start + 1, 'Content-Range': `bytes ${start}-${end}/${info.size}` });
    if (request.method === 'HEAD') return response.end();
    return createReadStream(path, { start, end }).pipe(response);
  }
  response.writeHead(200, { ...headers, 'Content-Length': info.size });
  if (request.method === 'HEAD') return response.end();
  createReadStream(path).pipe(response);
}

async function mediaRoute(request, response, url) {
  const match = /^\/api\/assets\/([^/]+)\/(video|cover|headline-frame|caption-frame)$/.exec(url.pathname);
  if (!match || !uuidPattern.test(match[1])) return false;
  const [, assetId, kind] = match;
  let rawPath;
  let filename;
  if (kind === 'video') {
    rawPath = await findMediaFile(safeFilename(url.searchParams.get('name'), ''));
    if (!rawPath) {
      const asset = await querySupabaseFlexibleId('media_assets', assetId, 'path');
      rawPath = asset?.path;
      if (!rawPath) {
        const job = await querySupabaseFlexibleId('publication_jobs', assetId, 'metadata');
        rawPath = await findMediaFile(job?.metadata?.download_filename);
      }
    }
    if (!rawPath) return json(response, 404, { error: 'Vídeo não encontrado' }), true;
    filename = url.searchParams.get('name') || `kwai-futebol-${assetId.slice(0, 8)}.mp4`;
  } else {
    const job = await querySupabaseFlexibleId('publication_jobs', assetId, 'cover_path,metadata');
    if (!job?.cover_path && !job?.metadata?.download_filename) return json(response, 404, { error: 'Capa não encontrada' }), true;
    const gates = job.metadata?.gates || {};
    rawPath = kind === 'headline-frame' ? gates.headline_frame
      : kind === 'caption-frame' ? gates.caption_frame : (job.cover_path || await findMediaFile(job.metadata.download_filename.replace(/\.mp4$/, '-capa.jpg')));
    if (!rawPath) return json(response, 404, { error: 'Frame de validação não encontrado' }), true;
    filename = url.searchParams.get('name') || `kwai-futebol-${kind}-${assetId.slice(0, 8)}${extname(rawPath) || '.jpg'}`;
  }
  const path = await verifiedMediaPath(rawPath);
  await serveFile(request, response, path, { filename, download: url.searchParams.get('download') === '1' });
  return true;
}

async function cleanupRoute(request, response, url) {
  const match = /^\/api\/assets\/([^/]+)\/cleanup$/.exec(url.pathname);
  if (!match || request.method !== 'POST' || !uuidPattern.test(match[1])) return false;
  const assetId = match[1];
  const job = await querySupabase('publication_jobs', 'asset_id', assetId, 'status,cover_path');
  if (job?.status !== 'published') {
    return json(response, 409, { error: 'O vídeo precisa estar publicado antes da limpeza' }), true;
  }
  const asset = await querySupabase('media_assets', 'asset_id', assetId, 'path');
  const rawPaths = [asset?.path, job.cover_path].filter(Boolean);
  const removed = [];
  for (const rawPath of rawPaths) {
    try {
      const path = await verifiedMediaPath(rawPath);
      await unlink(path);
      removed.push(path);
    } catch (error) {
      if (!(error instanceof Error) || !('code' in error) || error.code !== 'ENOENT') throw error;
    }
  }
  return json(response, 200, { ok: true, removed: removed.length }), true;
}

function readJsonBody(request) {
  return new Promise((resolvePromise, reject) => {
    let data = '';
    request.on('data', (chunk) => {
      data += chunk;
      if (data.length > 1_000_000) { request.destroy(); reject(new Error('payload muito grande')); }
    });
    request.on('end', () => {
      if (!data) return resolvePromise({});
      try { resolvePromise(JSON.parse(data)); } catch { reject(new Error('JSON inválido')); }
    });
    request.on('error', reject);
  });
}

// Chama uma RPC administrativa com a credencial service-side. A service key nunca
// sai do servidor; o browser só recebe a resposta já processada.
async function callAdminRpc(fnName, params) {
  if (!supabaseUrl || !adminKey) throw new Error('Backend administrativo não configurado');
  const url = new URL(`/rest/v1/rpc/${fnName}`, supabaseUrl);
  const response = await fetch(url, {
    method: 'POST',
    headers: { apikey: adminKey, Authorization: `Bearer ${adminKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  // A mensagem do Postgres vem no corpo e é o que diz POR QUE um item do lote
  // foi recusado ("somente vídeos prontos...", "já foi registrado..."). Sem ela
  // o relatório por item viraria um "falhou" sem utilidade nenhuma.
  let error = '';
  if (!response.ok) {
    try { error = String((await response.json())?.message || '').slice(0, 200); } catch { /* corpo não-JSON */ }
  }
  return { ok: response.ok, status: response.status, error };
}

function missingFields(body, fields) {
  return fields.filter((field) => !String(body?.[field] ?? '').trim());
}

// Proxy autenticado (atrás do Basic Auth do Traefik) para as mutações de revisão.
// O anon key foi revogado dessas RPCs; esta é a única porta para aprovar/bloquear/reavaliar.
async function kwaiReviewRoute(request, response, url) {
  if (!url.pathname.startsWith('/api/kwai/prospects/')) return false;
  if (request.method !== 'POST') return json(response, 405, { error: 'Método não permitido' }), true;
  if (!adminKey) return json(response, 503, { error: 'Backend administrativo não configurado' }), true;
  const action = url.pathname.slice('/api/kwai/prospects/'.length);
  const body = await readJsonBody(request);
  if (!uuidPattern.test(String(body.prospect_id || ''))) return json(response, 400, { error: 'prospect_id inválido' }), true;

  if (action === 'review') {
    const status = String(body.status || '');
    if (!['authorized', 'licensed', 'campaign_allowed', 'approved', 'blocked'].includes(status)) {
      return json(response, 400, { error: 'status inválido' }), true;
    }
    if (status === 'blocked') {
      if (!String(body.blocked_reason || '').trim()) return json(response, 400, { error: 'motivo do bloqueio obrigatório' }), true;
    } else {
      const missing = missingFields(body, ['owner_name', 'authorization_reason', 'license_or_cut_task', 'evidence_url']);
      if (missing.length) return json(response, 400, { error: `campos obrigatórios: ${missing.join(', ')}` }), true;
    }
    const rpc = await callAdminRpc('review_football_source_prospect', {
      p_prospect_id: body.prospect_id, p_status: status,
      p_owner_name: body.owner_name || '', p_authorization_reason: body.authorization_reason || '',
      p_license_or_cut_task: body.license_or_cut_task || '', p_evidence_url: body.evidence_url || '',
      p_review_notes: body.review_notes || null, p_reviewed_by: 'dashboard',
      p_authorization_expires_at: body.authorization_expires_at || null,
      p_blocked_reason: status === 'blocked' ? body.blocked_reason : null,
    });
    return json(response, rpc.ok ? 200 : 422, rpc.ok ? { ok: true } : { error: 'Operação recusada pela regra de revisão' }), true;
  }

  if (action === 'reevaluate') {
    if (!String(body.reason || '').trim()) return json(response, 400, { error: 'motivo da reavaliação obrigatório' }), true;
    const rpc = await callAdminRpc('reevaluate_football_source_prospect', {
      p_prospect_id: body.prospect_id, p_reviewed_by: 'dashboard',
      p_reason: body.reason, p_notes: body.review_notes || null,
    });
    return json(response, rpc.ok ? 200 : 422, rpc.ok ? { ok: true } : { error: 'Operação recusada pela regra de revisão' }), true;
  }

  return json(response, 404, { error: 'Ação desconhecida' }), true;
}

// Confirmação em lote pelo responsável: marca fontes como "Permitida para uso"
// (campaign_allowed) ou bloqueia várias de uma vez. O responsável confirma no
// painel que tem permissão; registramos usuário/data/URL sem formulário por vídeo.
async function kwaiBulkRoute(request, response, url) {
  if (url.pathname !== '/api/kwai/prospects/bulk') return false;
  if (request.method !== 'POST') return json(response, 405, { error: 'Método não permitido' }), true;
  if (!adminKey) return json(response, 503, { error: 'Backend administrativo não configurado' }), true;
  const body = await readJsonBody(request);
  const action = String(body.action || '');
  const items = Array.isArray(body.items) ? body.items : [];
  if (!['permit', 'block'].includes(action)) return json(response, 400, { error: 'ação inválida' }), true;
  if (!body.confirmed && action === 'permit') return json(response, 400, { error: 'confirmação obrigatória' }), true;
  if (!items.length) return json(response, 400, { error: 'nenhuma fonte selecionada' }), true;
  if (items.length > 500) return json(response, 400, { error: 'lote muito grande' }), true;
  let done = 0; let failed = 0;
  for (const item of items) {
    const prospectId = String(item?.prospect_id || '');
    if (!uuidPattern.test(prospectId)) { failed += 1; continue; }
    const params = action === 'block'
      ? { p_prospect_id: prospectId, p_status: 'blocked', p_owner_name: '', p_authorization_reason: '',
          p_license_or_cut_task: '', p_evidence_url: '', p_reviewed_by: 'dashboard',
          p_blocked_reason: String(body.blocked_reason || 'triagem em lote') }
      : { p_prospect_id: prospectId, p_status: 'campaign_allowed',
          p_owner_name: 'Responsável pelo canal',
          p_authorization_reason: 'Permissão confirmada pelo responsável no painel',
          p_license_or_cut_task: 'Uso permitido',
          p_evidence_url: String(item?.source_url || 'confirmado-no-painel'),
          p_reviewed_by: 'dashboard' };
    try {
      const rpc = await callAdminRpc('review_football_source_prospect', params);
      if (rpc.ok) done += 1; else failed += 1;
    } catch { failed += 1; }
  }
  return json(response, 200, { ok: true, action, done, failed }), true;
}

// Registro de publicação manual (o operador postou no app do Kwai e confirma no
// painel). O anon foi revogado da RPC mark_manual_publication; esta é a porta
// service-side. Depois o janitor/cleanup remove o arquivo da VPS.
async function kwaiPublishRoute(request, response, url) {
  if (url.pathname !== '/api/kwai/mark-published') return false;
  if (request.method !== 'POST') return json(response, 405, { error: 'Método não permitido' }), true;
  if (!adminKey) return json(response, 503, { error: 'Backend administrativo não configurado' }), true;
  const body = await readJsonBody(request);
  if (!uuidPattern.test(String(body.job_id || ''))) return json(response, 400, { error: 'job_id inválido' }), true;
  // Link/URL do Kwai é OPCIONAL. Se o operador não colar nada, usamos um marcador
  // interno (a RPC de produção exige valor não-vazio). Um clique já tira o vídeo
  // do painel e da VPS — sem precisar de link.
  const externalId = String(body.external_id || '').trim() || `postado-manual-${Date.now()}`;
  const rpc = await callAdminRpc('mark_manual_publication', {
    p_job_id: body.job_id,
    p_external_id: externalId,
    p_published_at: body.published_at || new Date().toISOString(),
  });
  if (!rpc.ok) return json(response, 422, { error: 'Não foi possível registrar a publicação' }), true;
  // Sai da VPS NA HORA (o janitor a cada 15min também cobre, mas isto é imediato).
  let removidos = 0;
  try {
    const job = await querySupabase('publication_jobs', 'job_id', body.job_id, 'asset_id,cover_path');
    const paths = [];
    if (job?.cover_path) paths.push(job.cover_path);
    if (job?.asset_id) {
      const asset = await querySupabase('media_assets', 'asset_id', job.asset_id, 'path');
      if (asset?.path) { paths.push(asset.path); paths.push(asset.path.replace(/\.mp4$/, '-capa.jpg')); }
    }
    for (const raw of [...new Set(paths)]) {
      try { await unlink(await verifiedMediaPath(raw)); removidos += 1; }
      catch { /* arquivo já sumiu ou fora da raiz: o janitor cobre */ }
    }
  } catch { /* deleção é best-effort */ }
  return json(response, 200, { ok: true, removidos }), true;
}

// --- Encerramento do lote Kwai -------------------------------------------
//
// Fechar o lote item a item pela tela não serve por dois motivos concretos:
// a página carrega só os 100 jobs mais recentes (hoje o perfil tem 282, e os
// prontos não cabem todos nessa janela), e um erro no meio deixava metade
// marcada e metade não, sem dizer quais.
//
// Aqui a lista vem do banco com a chave administrativa — todos os prontos, não
// os que couberam na tela — e cada item é registrado individualmente: um que
// falha não derruba o resto e volta identificado, para reprocessar só ele.
//
// GET  = prévia. Não apaga NADA. Diz quantos registros, quantos arquivos e
//        quantos bytes seriam afetados.
// POST = executa, e só com as duas confirmações (Kwai principal e clone).
const PERFIL_KWAI = 'kwai_cut_futebol';

async function jobsProntosDoLote(jobIds) {
  const consulta = new URL('/rest/v1/publication_jobs', supabaseUrl);
  consulta.searchParams.set('select', 'job_id,asset_id,cover_path,title,media_assets(path,validation_status)');
  consulta.searchParams.set('profile_id', `eq.${PERFIL_KWAI}`);
  consulta.searchParams.set('status', 'eq.ready');
  consulta.searchParams.set('order', 'created_at.asc');
  consulta.searchParams.set('limit', '1000');
  const resposta = await fetch(consulta, { headers: { apikey: adminKey, Authorization: `Bearer ${adminKey}` } });
  if (!resposta.ok) throw new Error(`Consulta de jobs prontos falhou (${resposta.status})`);
  let linhas = (await resposta.json()).map((linha) => ({
    ...linha,
    media_assets: Array.isArray(linha.media_assets) ? linha.media_assets[0] || null : linha.media_assets,
  }));
  if (Array.isArray(jobIds) && jobIds.length) {
    const alvo = new Set(jobIds.filter((id) => uuidPattern.test(String(id))));
    linhas = linhas.filter((linha) => alvo.has(linha.job_id));
  }
  return linhas;
}

function arquivosDoJob(job) {
  const caminhos = [];
  if (job.cover_path) caminhos.push(job.cover_path);
  const caminhoVideo = job.media_assets?.path;
  if (caminhoVideo) {
    caminhos.push(caminhoVideo);
    caminhos.push(caminhoVideo.replace(/\.mp4$/, '-capa.jpg'));
  }
  return [...new Set(caminhos)];
}

async function kwaiBatchRoute(request, response, url) {
  if (url.pathname !== '/api/kwai/batch-close') return false;
  if (!adminKey) return json(response, 503, { error: 'Backend administrativo não configurado' }), true;

  if (request.method === 'GET') {
    const jobs = await jobsProntosDoLote(null);
    let arquivos = 0;
    let bytes = 0;
    for (const job of jobs) {
      for (const bruto of arquivosDoJob(job)) {
        try {
          const caminho = await verifiedMediaPath(bruto);
          bytes += (await stat(caminho)).size;
          arquivos += 1;
        } catch { /* arquivo já não está na VPS: não conta */ }
      }
    }
    return json(response, 200, { registros: jobs.length, arquivos, bytes }), true;
  }

  if (request.method !== 'POST') return json(response, 405, { error: 'Método não permitido' }), true;
  const body = await readJsonBody(request);
  // As duas confirmações são exigidas aqui também, e não só na tela: assim uma
  // chamada solta não apaga nada por engano.
  if (!body.confirm_principal || !body.confirm_clone) {
    return json(response, 400, {
      error: 'Confirme que publicou no Kwai principal E no Kwai clone antes de encerrar o lote',
    }), true;
  }

  const jobs = await jobsProntosDoLote(body.job_ids);
  if (!jobs.length) return json(response, 200, { registros: 0, sucesso: 0, falhas: [], arquivos: 0, bytes: 0 }), true;

  const dia = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const falhas = [];
  let sucesso = 0;
  let arquivos = 0;
  let bytes = 0;

  for (const job of jobs) {
    // Identificador próprio por vídeo: a RPC exige valor não-vazio e há índice
    // único em (platform, external_id) — um valor repetido derrubaria o lote
    // inteiro no segundo item.
    const externalId = `lote-manual-${dia}-${job.job_id.slice(0, 8)}`;
    const rpc = await callAdminRpc('mark_manual_publication', {
      p_job_id: job.job_id,
      p_external_id: externalId,
      p_published_at: new Date().toISOString(),
    });
    if (!rpc.ok) {
      falhas.push({ job_id: job.job_id, titulo: job.title || '', erro: rpc.error || 'RPC recusou o registro' });
      continue;  // segue o lote: um item ruim não trava os outros
    }
    sucesso += 1;
    // Arquivo só sai DEPOIS do registro dar certo. Na ordem inversa, um erro
    // no banco deixaria o vídeo apagado e o job ainda em aberto.
    for (const bruto of arquivosDoJob(job)) {
      try {
        const caminho = await verifiedMediaPath(bruto);
        bytes += (await stat(caminho)).size;
        await unlink(caminho);
        arquivos += 1;
      } catch { /* já não existia: o janitor cobre */ }
    }
  }

  return json(response, 200, { registros: jobs.length, sucesso, falhas, arquivos, bytes }), true;
}

// Salvar/aprovar o texto da publicação. Mesmo motivo: anon revogado da RPC.
async function kwaiTextRoute(request, response, url) {
  if (url.pathname !== '/api/kwai/update-text') return false;
  if (request.method !== 'POST') return json(response, 405, { error: 'Método não permitido' }), true;
  if (!adminKey) return json(response, 503, { error: 'Backend administrativo não configurado' }), true;
  const body = await readJsonBody(request);
  if (!uuidPattern.test(String(body.job_id || ''))) return json(response, 400, { error: 'job_id inválido' }), true;
  const rpc = await callAdminRpc('update_publication_text', {
    p_job_id: body.job_id,
    p_description: String(body.description || ''),
    p_hashtags: String(body.hashtags || ''),
    p_credits: String(body.credits || ''),
    p_caption: String(body.caption || ''),
  });
  return json(response, rpc.ok ? 200 : 422, rpc.ok ? { ok: true } : { error: 'Não foi possível salvar o texto' }), true;
}

// Proxy dos agentes locais (VexPublish, Importar, Commerce, DM, Produção em Massa).
//
// Existe porque quem serve o painel é ESTE processo — não há nginx no meio — e
// nenhum agente tem rota pública própria. Sem isto as abas carregam e não têm
// como falar com a API: cada uma tentaria 127.0.0.1 na porta do agente, que só
// existe dentro do container deles.
//
// Sem AGENTES_API_TARGET (nem MASS_API_TARGET) nenhuma dessas rotas existe: em
// qualquer instalação que não configure, o painel continua exatamente como está.
//
// Repassa só o necessário: método, corpo e o cabeçalho de token da aba. Quem
// autoriza continua sendo cada módulo — este proxy não decide nada.
const agentesTarget = process.env.AGENTES_API_TARGET;
const massaTarget = process.env.MASS_API_TARGET;

// Um uvicorn por porta, todos no mesmo container.
const PORTAS_AGENTES = {
  '/vexpublish/': 8785,
  '/import/': 8795,
  '/commerce/': 8805,
  '/dm/': 8815,
  '/mass/': 8825,
};

// Cada aba manda o token no seu próprio cabeçalho; repassar todos é mais simples
// (e mais seguro) do que adivinhar qual pertence a qual rota.
const CABECALHOS_REPASSADOS = [
  'content-type', 'accept',
  'x-mass-token', 'x-vexpublish-token', 'x-import-token',
  'x-commerce-token', 'x-dm-token', 'x-campaigns-token',
];

function destinoDoAgente(pathname, search) {
  // MASS_API_TARGET veio primeiro e continua valendo sozinho, para não quebrar
  // instalação que já esteja usando só ele.
  if (pathname.startsWith('/mass/') && massaTarget) return new URL(pathname + search, massaTarget);
  if (!agentesTarget) return null;
  const prefixo = Object.keys(PORTAS_AGENTES).find((p) => pathname.startsWith(p));
  if (!prefixo) return null;
  return new URL(pathname + search, `${agentesTarget}:${PORTAS_AGENTES[prefixo]}`);
}

function corpoBruto(request) {
  return new Promise((ok, falhou) => {
    const partes = [];
    request.on('data', (parte) => partes.push(parte));
    request.on('end', () => ok(Buffer.concat(partes)));
    request.on('error', falhou);
  });
}

async function agentesRoute(request, response, url) {
  const destino = destinoDoAgente(url.pathname, url.search);
  if (!destino) return false;
  const cabecalhos = {};
  for (const nome of CABECALHOS_REPASSADOS) {
    if (request.headers[nome]) cabecalhos[nome] = request.headers[nome];
  }
  const semCorpo = request.method === 'GET' || request.method === 'HEAD';
  const corpo = semCorpo ? undefined : await corpoBruto(request);
  try {
    const resposta = await fetch(destino, {
      method: request.method,
      headers: cabecalhos,
      body: corpo && corpo.length ? corpo : undefined,
    });
    const dados = Buffer.from(await resposta.arrayBuffer());
    response.writeHead(resposta.status, {
      'Content-Type': resposta.headers.get('content-type') || 'application/json; charset=utf-8',
      'Content-Length': dados.length,
      'Cache-Control': 'no-store',
    });
    response.end(request.method === 'HEAD' ? undefined : dados);
  } catch {
    json(response, 502, { error: 'Agente local indisponível' });
  }
  return true;
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || '/', `http://${request.headers.host || 'localhost'}`);
    if (url.pathname === '/health') return json(response, 200, { ok: true, mode: 'prepare_only' });
    if (await kwaiBulkRoute(request, response, url)) return;
    if (await kwaiPublishRoute(request, response, url)) return;
    if (await kwaiBatchRoute(request, response, url)) return;
    if (await kwaiTextRoute(request, response, url)) return;
    if (await kwaiReviewRoute(request, response, url)) return;
    if (await cleanupRoute(request, response, url)) return;
    if (await mediaRoute(request, response, url)) return;
    if (await agentesRoute(request, response, url)) return;
    const requested = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/+/, '');
    let path = resolve(join(distRoot, requested));
    if (path !== distRoot && !path.startsWith(`${distRoot}${sep}`)) return json(response, 403, { error: 'Caminho inválido' });
    try {
      if (!(await stat(path)).isFile()) path = join(distRoot, 'index.html');
    } catch {
      path = join(distRoot, 'index.html');
    }
    await serveFile(request, response, path, { cache: path !== join(distRoot, 'index.html') });
  } catch (error) {
    json(response, 404, { error: error instanceof Error ? error.message : 'Arquivo indisponível' });
  }
});

server.listen(port, '0.0.0.0', () => {
  console.log(`[dashboard] disponível em 0.0.0.0:${port}; mídia em modo prepare_only`);
});
