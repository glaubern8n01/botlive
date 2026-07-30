import { createReadStream } from 'node:fs';
import { realpath, stat, unlink } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, isAbsolute, join, resolve, sep } from 'node:path';

const port = Number(process.env.PORT || 3000);
const distRoot = resolve(process.env.DASHBOARD_DIST_ROOT || 'dist');
const mediaRoot = resolve(process.env.BOTLIVE_OUTPUT_ROOT || '/data/botlive/output');
const supabaseUrl = process.env.VITE_SUPABASE_URL;
const supabaseKey = process.env.VITE_SUPABASE_ANON_KEY;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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
    return createReadStream(path, { start, end }).pipe(response);
  }
  response.writeHead(200, { ...headers, 'Content-Length': info.size });
  createReadStream(path).pipe(response);
}

async function mediaRoute(request, response, url) {
  const match = /^\/api\/assets\/([^/]+)\/(video|cover|headline-frame|caption-frame)$/.exec(url.pathname);
  if (!match || !uuidPattern.test(match[1])) return false;
  const [, assetId, kind] = match;
  let rawPath;
  let filename;
  if (kind === 'video') {
    const asset = await querySupabase('media_assets', 'asset_id', assetId, 'path');
    if (!asset?.path) return json(response, 404, { error: 'Vídeo não encontrado' }), true;
    rawPath = asset.path;
    filename = url.searchParams.get('name') || `kwai-futebol-${assetId.slice(0, 8)}.mp4`;
  } else {
    const job = await querySupabase('publication_jobs', 'asset_id', assetId, 'cover_path,metadata');
    if (!job?.cover_path) return json(response, 404, { error: 'Capa não encontrada' }), true;
    const gates = job.metadata?.gates || {};
    rawPath = kind === 'headline-frame' ? gates.headline_frame
      : kind === 'caption-frame' ? gates.caption_frame : job.cover_path;
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

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || '/', `http://${request.headers.host || 'localhost'}`);
    if (url.pathname === '/health') return json(response, 200, { ok: true, mode: 'prepare_only' });
    if (await cleanupRoute(request, response, url)) return;
    if (await mediaRoute(request, response, url)) return;
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
