"""API local do Producao em Massa.

Com MASS_CONTENT_STUDIO_ENABLED=false a API inteira responde 404 e nada deste
modulo e tocado - o BotLive segue exatamente como hoje.
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import baixar, editor, exportar, fontes, postador, projetos, templates
from .store import MassaError, listar, migrar, modulo_ligado


PAPEIS = {"admin": {"*"}, "operator": {"read", "write", "run"}, "reviewer": {"read"}}


def exigir(acao: str):
    def dependencia(x_mass_token: str | None = Header(default=None)):
        if not modulo_ligado():
            raise HTTPException(404, "Modulo desativado")
        tokens = {
            "admin": os.getenv("MASS_ADMIN_TOKEN", ""),
            "operator": os.getenv("MASS_OPERATOR_TOKEN", ""),
            "reviewer": os.getenv("MASS_REVIEWER_TOKEN", ""),
        }
        for papel, token in tokens.items():
            if token and x_mass_token and hmac.compare_digest(token, x_mass_token):
                if "*" in PAPEIS[papel] or acao in PAPEIS[papel]:
                    return {"actor": papel, "role": papel}
                raise HTTPException(403, "Permissao insuficiente")
        raise HTTPException(401, "Token invalido")

    return dependencia


@asynccontextmanager
async def lifespan(_: FastAPI):
    if modulo_ligado():
        migrar()
    yield


app = FastAPI(title="BotLive Producao em Massa", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip() for x in os.getenv(
            "MASS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",") if x.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Mass-Token"],
)


class ProjetoIn(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    template_id: str | None = None
    notas: str = ""


class LinksIn(BaseModel):
    texto: str = ""
    arquivo: str = ""


class EnfileirarIn(BaseModel):
    urls: list[str] = []


class PerfilIn(BaseModel):
    url: str
    limite: int = Field(0, ge=0, le=1000)


class TemplateIn(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    formato: str = "9:16"
    modo_horizontal: str = "blur"
    logo_path: str = ""
    logo_posicao: str = "inferior-direita"
    logo_escala: float = Field(0.15, ge=0.02, le=0.4)
    logo_opacidade: float = Field(0.9, ge=0, le=1)
    mockup_path: str = ""
    mockup_opacidade: float = Field(1.0, ge=0, le=1)
    cta_texto: str = ""
    cta_posicao: str = "inferior"
    cta_tamanho: float = Field(0.055, ge=0.02, le=0.15)
    audio: str = "manter"
    volume: float = Field(1.0, ge=0, le=4)
    cortar_inicio: float = Field(0, ge=0)
    cortar_fim: float = Field(0, ge=0)
    velocidade: float = Field(1.0, ge=0.5, le=2.0)


class EditarIn(BaseModel):
    template_id: str
    entradas: list[str] = []
    usar_baixados: bool = True
    # pasta local: editar videos que o operador ja tem, sem passar pelo
    # downloader. Tem prioridade sobre usar_baixados quando vem preenchida.
    pasta: str = ""
    recursivo: bool = False


class PastaIn(BaseModel):
    caminho: str
    recursivo: bool = False


class PreviaIn(BaseModel):
    entrada: str
    template_id: str
    segundos: float = Field(3.0, ge=1, le=15)


class PublicarIn(BaseModel):
    arquivos: list[str] = []
    usar_editados: bool = True
    descricao: str = ""
    hashtags: list[str] = []
    conta: str = "principal"


class RodarIn(BaseModel):
    maximo: int = Field(5, ge=1, le=50)


def _erro(exc: MassaError) -> HTTPException:
    return HTTPException(422, str(exc))


@app.get("/mass/v1/health")
def health():
    return {
        "ok": True,
        "modulo_ligado": modulo_ligado(),
        "postador": postador.flags(),
        "formatos": sorted(templates.FORMATOS),
        "workers_editor": editor.WORKERS,
        "processamento": "100% local (FFmpeg + yt-dlp)",
        "entradas_aceitas": list(editor.VIDEO_EXT),
        "mockup_aceito": list(templates.MOCKUP_ACEITOS),
        "ensaio_no_navegador": postador.ligado("MASS_DRY_RUN_NAVEGADOR"),
    }


# --- projetos --------------------------------------------------------------


@app.get("/mass/v1/projetos", dependencies=[Depends(exigir("read"))])
def listar_projetos():
    return {"items": listar("mass_projetos", 200)}


@app.post("/mass/v1/projetos", status_code=201)
def criar_projeto(value: ProjetoIn, user=Depends(exigir("write"))):
    try:
        return projetos.criar(value.nome, value.template_id, value.notas)
    except MassaError as exc:
        raise _erro(exc)


@app.get("/mass/v1/projetos/{projeto_id}/historico", dependencies=[Depends(exigir("read"))])
def historico(projeto_id: str):
    try:
        return projetos.historico(projeto_id)
    except MassaError as exc:
        raise HTTPException(404, str(exc))


# --- 1. download -----------------------------------------------------------


@app.post("/mass/v1/links/detectar")
def detectar_links(value: LinksIn, user=Depends(exigir("read"))):
    """Recebe texto colado ou caminho de TXT e devolve '47 links detectados'."""
    try:
        urls = fontes.ler_arquivo(value.arquivo) if value.arquivo else fontes.extrair_urls(value.texto)
    except MassaError as exc:
        raise _erro(exc)
    return fontes.classificar(urls)


@app.post("/mass/v1/perfil/listar")
def listar_perfil(value: PerfilIn, user=Depends(exigir("read"))):
    """Lista videos publicos de um perfil, sem baixar. limite=0 traz tudo."""
    try:
        return baixar.listar_perfil(value.url, value.limite)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/projetos/{projeto_id}/downloads", status_code=201)
def enfileirar_downloads(projeto_id: str, value: EnfileirarIn, user=Depends(exigir("write"))):
    try:
        return baixar.enfileirar(projeto_id, value.urls)
    except MassaError as exc:
        raise _erro(exc)


@app.get("/mass/v1/projetos/{projeto_id}/downloads", dependencies=[Depends(exigir("read"))])
def fila_downloads(projeto_id: str, limit: int = Query(500, ge=1, le=2000)):
    return baixar.fila(projeto_id, limit)


@app.post("/mass/v1/projetos/{projeto_id}/downloads/rodar")
def rodar_downloads(projeto_id: str, value: RodarIn, user=Depends(exigir("run"))):
    try:
        return baixar.rodar_fila(projeto_id, value.maximo)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/downloads/{item_id}/status")
def status_download(item_id: str, status: str, user=Depends(exigir("write"))):
    try:
        return baixar.mudar_status(item_id, status)
    except MassaError as exc:
        raise _erro(exc)


# --- 2. templates e edicao -------------------------------------------------


@app.get("/mass/v1/templates", dependencies=[Depends(exigir("read"))])
def listar_templates():
    return {"items": templates.todos()}


@app.post("/mass/v1/templates", status_code=201)
def criar_template(value: TemplateIn, user=Depends(exigir("write"))):
    dados = value.model_dump()
    nome = dados.pop("nome")
    try:
        return templates.criar(nome, **dados)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/projetos/{projeto_id}/edicoes", status_code=201)
def enfileirar_edicoes(projeto_id: str, value: EditarIn, user=Depends(exigir("write"))):
    try:
        if value.pasta:
            return editor.enfileirar_pasta(projeto_id, value.template_id,
                                           value.pasta, value.recursivo)
        if value.usar_baixados and not value.entradas:
            return editor.enfileirar_baixados(projeto_id, value.template_id)
        return editor.enfileirar(projeto_id, value.template_id, value.entradas)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/pasta/listar")
def listar_pasta(value: PastaIn, user=Depends(exigir("read"))):
    """Mostra os videos de uma pasta local antes de enfileirar."""
    try:
        itens = editor.varrer_pasta(value.caminho, value.recursivo)
    except MassaError as exc:
        raise _erro(exc)
    return {"total": len(itens), "itens": itens, "pasta": value.caminho}


@app.get("/mass/v1/projetos/{projeto_id}/edicoes", dependencies=[Depends(exigir("read"))])
def fila_edicoes(projeto_id: str, limit: int = Query(500, ge=1, le=2000)):
    return editor.fila(projeto_id, limit)


@app.post("/mass/v1/projetos/{projeto_id}/edicoes/rodar")
def rodar_edicoes(projeto_id: str, value: RodarIn, user=Depends(exigir("run"))):
    try:
        return editor.rodar_fila(projeto_id, value.maximo)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/previa")
def previa(value: PreviaIn, user=Depends(exigir("run"))):
    """Amostra curta antes de processar o lote inteiro."""
    try:
        return {"arquivo": str(editor.previa(value.entrada, value.template_id, value.segundos))}
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/edicoes/{item_id}/status")
def status_edicao(item_id: str, status: str, user=Depends(exigir("write"))):
    try:
        return editor.mudar_status(item_id, status)
    except MassaError as exc:
        raise _erro(exc)


# --- 3. exportacao ---------------------------------------------------------


@app.get("/mass/v1/projetos/{projeto_id}/export", dependencies=[Depends(exigir("read"))])
def resumo_export(projeto_id: str):
    try:
        return exportar.resumo(projeto_id)
    except MassaError as exc:
        raise HTTPException(404, str(exc))


@app.post("/mass/v1/projetos/{projeto_id}/export/zip", status_code=201)
def gerar_zip(projeto_id: str, nome: str | None = None, user=Depends(exigir("run"))):
    try:
        return exportar.gerar_zip(projeto_id, nome)
    except MassaError as exc:
        raise _erro(exc)


# --- 4. postagem -----------------------------------------------------------


@app.post("/mass/v1/projetos/{projeto_id}/publicacoes", status_code=201)
def enfileirar_publicacoes(projeto_id: str, value: PublicarIn, user=Depends(exigir("write"))):
    arquivos = value.arquivos
    if value.usar_editados and not arquivos:
        arquivos = exportar.editados(projeto_id)
    try:
        return postador.enfileirar(projeto_id, arquivos, value.descricao,
                                   value.hashtags, value.conta)
    except MassaError as exc:
        raise _erro(exc)


@app.get("/mass/v1/projetos/{projeto_id}/publicacoes", dependencies=[Depends(exigir("read"))])
def fila_publicacoes(projeto_id: str, limit: int = Query(500, ge=1, le=2000)):
    return postador.fila(projeto_id, limit)


@app.post("/mass/v1/projetos/{projeto_id}/publicacoes/rodar")
def rodar_publicacoes(projeto_id: str, value: RodarIn, user=Depends(exigir("run"))):
    try:
        return postador.rodar_fila(projeto_id, value.maximo)
    except MassaError as exc:
        raise _erro(exc)


@app.post("/mass/v1/publicacoes/{item_id}/status")
def status_publicacao(item_id: str, status: str, user=Depends(exigir("write"))):
    try:
        return postador.mudar_status(item_id, status)
    except MassaError as exc:
        raise _erro(exc)


@app.get("/mass/v1/sessao/{conta}", dependencies=[Depends(exigir("read"))])
def estado_sessao(conta: str):
    """Se ha sessao salva para o modo local. Nao devolve nada da sessao."""
    return {"conta": conta, "salva": postador.sessao_salva(conta)}


@app.post("/mass/v1/sessao/{conta}/login")
def login_manual(conta: str, user=Depends(exigir("run"))):
    """Abre o navegador para o operador logar A MAO e salva a sessao."""
    try:
        return postador.abrir_para_login(conta)
    except MassaError as exc:
        raise _erro(exc)


@app.get("/mass/v1/audit", dependencies=[Depends(exigir("read"))])
def auditoria(limit: int = Query(200, ge=1, le=1000)):
    return {"items": listar("mass_audit", limit)}


# --- ajuda -----------------------------------------------------------------


@app.get("/mass/v1/ajuda", dependencies=[Depends(exigir("read"))])
def ajuda():
    """Central de tutoriais pedida no documento, comecando por texto."""
    return {"topicos": [
        {"titulo": "Como baixar em massa",
         "passos": ["Crie um projeto", "Cole as URLs ou importe o TXT",
                    "Confira quantos links foram detectados",
                    "Rode a fila de download"]},
        {"titulo": "Como editar em massa",
         "passos": ["Crie um template com formato, logo e CTA",
                    "Gere uma previa de 3s para conferir",
                    "Enfileire os baixados", "Rode a fila de edicao"]},
        {"titulo": "Como criar template",
         "passos": ["Escolha o formato (9:16 para Reels/TikTok)",
                    "Aponte logo e mockup (arquivos locais)",
                    "Escreva o CTA", "Salve: o template vale para o lote todo"]},
        {"titulo": "Como gerar ZIP",
         "passos": ["Termine a fila de edicao",
                    "Va na aba Postador e aperte Gerar ZIP",
                    "O ZIP fica em exports/ do projeto"]},
        {"titulo": "Como configurar o Instagram",
         "passos": ["Modo api: usa o token que o BotLive ja tem (recomendado)",
                    "Modo local: rode o login manual e a sessao e salva",
                    "Modo local vai contra os termos do Instagram e arrisca a conta"]},
        {"titulo": "Como editar uma pasta que eu ja tenho",
         "passos": ["Va na aba Editor e escolha o template",
                    "Cole o caminho da pasta (ex: C:\BotLive\Downloads)",
                    "Marque 'subpastas' se os videos estiverem em varias pastas",
                    "Confira quantos apareceram e mande para o editor",
                    "A saida vai para editados/ - o original nao e tocado"]},
        {"titulo": "Como usar mockup em video",
         "passos": ["Exporte o mockup em .webm (VP9 com alpha) ou .mov (ProRes 4444)",
                    "Aponte o arquivo no campo Mockup do template",
                    "Mockup curto entra em loop e termina junto com o video",
                    "Gere a previa de 3s antes de rodar o lote"]},
        {"titulo": "Como instalar no Windows",
         "passos": ["Build: powershell -File ops\build-instalador-massa.ps1",
                    "Sai BotLive-Massa.exe (portatil) e BotLive-Setup-Test.exe",
                    "No outro PC: instale o setup + FFmpeg + yt-dlp",
                    "Abra o programa: a janela mostra o token de acesso",
                    "Nenhum segredo vai no instalador - o token nasce na maquina"]},
        {"titulo": "Como usar o postador",
         "passos": ["Enfileire os editados", "Deixe o dry-run ligado primeiro",
                    "Confira a fila", "So entao desligue o dry-run"]},
    ]}
