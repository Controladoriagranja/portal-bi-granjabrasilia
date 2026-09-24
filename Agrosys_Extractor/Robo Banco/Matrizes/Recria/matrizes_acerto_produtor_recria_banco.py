# -*- coding: utf-8 -*-
r"""
MATRIZES - ACERTO DO PRODUTOR - RECRIA -> POSTGRESQL

Características:
- Programa: wgm800d
- Menu observado: 22283
- Módulo observado: 22169
- Situação: Aberto
- Estágio: Recria
- Tipo Movto: SEMANAL (vparlog... = "no")
- Seleciona TODOS os lotes retornados para cada unidade.
- Lê diretamente o HTML final de cada processo e grava no PostgreSQL.
- Preserva o Status visual (verde/vermelho) da tabela semanal.
- Cada nova execução substitui o snapshot da mesma empresa/unidade,
  evitando duplicação na atualização horária.

IMPORTANTE:
Unidades confirmadas para Granja Salomé:
- 002 - Fazenda Santa Lucia
- 003 - Granja Padre Liberio
- 005 - Granja Cascata
"""

import argparse
import inspect
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

PASTA_ROBO = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_ROBO))

from banco_matrizes import importar_dataframes_postgres, nomes_unicos, normalizar_coluna

# ----------------------------------------------------------------------
# Localiza a estrutura já existente do Agrosys_Extractor
# ----------------------------------------------------------------------
def localizar_raiz_agrosys() -> Path:
    atual = Path(__file__).resolve().parent
    for pasta in [atual] + list(atual.parents):
        if (pasta / "config.py").exists() and (pasta / "Core").exists():
            return pasta
    raise RuntimeError(
        "Não encontrei config.py + Core na árvore do Agrosys_Extractor."
    )

RAIZ = localizar_raiz_agrosys()
sys.path.insert(0, str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

# ----------------------------------------------------------------------
# Configuração observada no HAR / DevTools
# ----------------------------------------------------------------------
CAMINHO_RELATORIO = "/webpro/webprod/wgm800d"
CAMINHO_REPORTS = "/webpro/webpad/wppd004c"
MENU = 22283
MODULO = "22169"

TABELA_BANCO = "acerto_produtor_recria"
NOME_RELATORIO = "Matrizes - Acerto do Produtor - Recria"

SITUACAO = "A"      # Aberto
ESTAGIO = "yes"     # Recria
REPROCESSA = "no"   # Não
TIPO_MOVTO = "no"   # SEMANAL (no = SEMANAL / yes = DIÁRIO)

TIMEOUT_DOWNLOAD = 300

# Pedido do usuário:
UNIDADES_GRANJA_SALOME = [
    ("2", "Fazenda Santa Lucia"),
    ("3", "Granja Padre Liberio"),
    ("5", "Granja Cascata"),
]

ALVOS = [
    {
        "empresa_codigo": "2",
        "empresa_nome": "Granja Salomé",
        "unidade_codigo": "2",
        "unidade_nome": "Fazenda Santa Lucia",
    },
    {
        "empresa_codigo": "2",
        "empresa_nome": "Granja Salomé",
        "unidade_codigo": "3",
        "unidade_nome": "Granja Padre Liberio",
    },
    {
        "empresa_codigo": "2",
        "empresa_nome": "Granja Salomé",
        "unidade_codigo": "5",
        "unidade_nome": "Granja Cascata",
    },
    {
        "empresa_codigo": "11",
        "empresa_nome": "Adilson",
        "unidade_codigo": "1",
        "unidade_nome": "Unidade 1",
    },
]

PASTA_TEMP = (
    Path(tempfile.gettempdir())
    / "BI_Granja"
    / "Matrizes"
    / "Acerto_Produtor_Recria"
)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)

from Core.agrosys_runtime import PASTA_DOWNLOAD
PASTA_RELATORIOS = PASTA_TEMP / "_relatorios"
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)
PASTA_RELATORIOS.mkdir(parents=True, exist_ok=True)


def log(msg, nivel="INFO"):
    print(f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{nivel}] {msg}", flush=True)


def argumentos():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--somente-empresa",
        default=None,
        help="Opcional: 2 ou 11.",
    )
    p.add_argument(
        "--somente-unidade",
        default=None,
        help="Opcional: código da unidade (ex.: 2, 3, 1).",
    )
    p.add_argument(
        "--manter-excel",
        action="store_true",
        help="Mantém os HTMLs finais de diagnóstico após a importação.",
    )
    p.add_argument(
        "--data-inicial",
        default=None,
        help="Opcional. Use junto com --data-final para período manual DD/MM/AAAA.",
    )
    p.add_argument(
        "--data-final",
        default=None,
        help="Opcional. Use junto com --data-inicial para período manual DD/MM/AAAA.",
    )
    return p.parse_args()



def listar_periodos(a):
    """
    Padrão automático da Recria:
      1) mês anterior completo;
      2) mês atual do dia 1 até hoje.

    Exemplo em 23/09/2026:
      01/08/2026 a 31/08/2026
      01/09/2026 a 23/09/2026

    Se --data-inicial e --data-final forem informados juntos,
    executa somente o período manual.
    """
    if a.data_inicial or a.data_final:
        if not (a.data_inicial and a.data_final):
            raise RuntimeError(
                "Para período manual, informe --data-inicial e --data-final juntos."
            )

        ini = datetime.strptime(a.data_inicial, "%d/%m/%Y").date()
        fim = datetime.strptime(a.data_final, "%d/%m/%Y").date()

        if ini > fim:
            raise RuntimeError("A data inicial não pode ser maior que a data final.")

        return [{
            "nome": "PERÍODO MANUAL",
            "inicio": ini,
            "fim": fim,
        }]

    hoje = date.today()
    inicio_atual = hoje.replace(day=1)
    fim_anterior = inicio_atual - timedelta(days=1)
    inicio_anterior = fim_anterior.replace(day=1)

    return [
        {
            "nome": "MÊS ANTERIOR",
            "inicio": inicio_anterior,
            "fim": fim_anterior,
        },
        {
            "nome": "MÊS ATUAL",
            "inicio": inicio_atual,
            "fim": hoje,
        },
    ]


def preparar_pesquisa_periodo(pesquisa: dict, inicio: date, fim: date) -> dict:
    """
    Ajusta o intervalo enviado para cada lote.

    - lote já existente antes do mês: começa no dia 1 do período;
    - lote iniciado dentro do mês: começa na data real do lote;
    - lote iniciado depois do fim do período: não entra nesse disparo;
    - data final: fim do período.

    A Recria continua SEMANAL; somente o intervalo de datas muda.
    """
    nova = dict(pesquisa)
    lotes_periodo = []

    for item in pesquisa["lotes"]:
        x = dict(item)

        try:
            inicio_lote = datetime.strptime(
                x["data_inicio"],
                "%d/%m/%Y",
            ).date()
        except Exception:
            inicio_lote = inicio

        if inicio_lote > fim:
            continue

        inicio_efetivo = max(inicio_lote, inicio)

        x["data_inicio_original"] = x.get("data_inicio", "")
        x["data_inicio"] = inicio_efetivo.strftime("%d/%m/%Y")
        x["data_fim"] = fim.strftime("%d/%m/%Y")

        lotes_periodo.append(x)

    nova["lotes"] = lotes_periodo
    return nova


def criar_agrosys():
    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )
    ag.login()
    return ag


def ajustar_contexto_sessao(ag, empresa_codigo: str, unidade_codigo: str):
    """
    Configura o contexto do Agrosys exatamente antes de abrir o relatório.

    IMPORTANTE:
    O AgrosysEngine padrão grava semp-empresa="1".
    Para Matrizes precisamos respeitar a empresa real:
      - 2  = Granja Salomé
      - 11 = Adilson

    Por isso usamos configurar_unidade() e logo depois corrigimos
    os cookies de empresa para a empresa alvo.
    """
    dominio = "sistema.granjabrasilia.com.br"

    # Usa a rotina oficial que já funciona nos demais robôs.
    ag.configurar_unidade(
        unidade=str(unidade_codigo),
        menu=MENU,
        modulo=MODULO,
    )

    # Corrige a empresa, porque o AgrosysEngine padrão fixa semp-empresa=1.
    for nome, valor in {
        "semp-empresa": str(empresa_codigo),
        "empresa": str(empresa_codigo),
        "suni-unidade": str(unidade_codigo),
        "vpad-modulo": str(MODULO),
        "vpad-codmenu": str(MENU),
    }.items():
        try:
            ag.session.cookies.set(
                nome,
                valor,
                domain=dominio,
                path="/",
            )
        except Exception:
            pass


def pesquisar_lotes(ag, empresa_codigo: str, unidade_codigo: str):
    """
    Faz exatamente as duas etapas da tela:

    1) abre wgm800d no menu 22283;
    2) clica logicamente em PESQUISAR com:
       - unidade alvo
       - Situação = Aberto
       - Estágio = Recria
       - Reprocessa = Não

    Só depois lê TODOS os lotes que apareceram.
    """
    ajustar_contexto_sessao(
        ag,
        empresa_codigo,
        unidade_codigo,
    )

    # Abre a tela usando a mesma rotina do AgrosysEngine já validada
    # nos outros robôs. Ela envia Referer/menu corretamente.
    url_abertura, html_abertura = ag.abrir_tela(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
    )

    log(
        f"Tela wgm800d aberta | "
        f"{len(html_abertura or ''):,} caracteres"
    )

    soup_abertura = BeautifulSoup(
        html_abertura or "",
        "html.parser",
    )
    titulo_abertura = (
        soup_abertura.title.get_text(" ", strip=True)
        if soup_abertura.title
        else ""
    )

    if "Erro Processamento" in titulo_abertura or "Acesso não autorizado" in (html_abertura or ""):
        debug = (
            PASTA_TEMP
            / (
                f"DEBUG_abertura_"
                f"emp{empresa_codigo}_"
                f"uni{unidade_codigo}.html"
            )
        )
        debug.write_text(
            html_abertura or "",
            encoding="utf-8",
            errors="ignore",
        )
        raise RuntimeError(
            "A abertura do wgm800d retornou ACESSO NÃO AUTORIZADO. "
            f"HTML salvo em: {debug}"
        )

    url_post = url_abertura

    # Depois executa o botão PESQUISAR.
    log(
        f"Contexto Agrosys: empresa={empresa_codigo} | "
        f"unidade={unidade_codigo} | módulo={MODULO} | menu={MENU}"
    )

    payload_pesquisa = {
        "vunidade": str(unidade_codigo),
        "vsituacao": SITUACAO,
        "vestagio": ESTAGIO,
        "vrep": REPROCESSA,
        "vpad-btpesq.x": "Pesquisar",
        "vpad-ordena": "",
        "vpad-pesq": "",
    }

    html_pesquisa = ag.disparar_relatorio(
        url=url_post,
        dados=payload_pesquisa,
    )

    log(
        f"Pesquisa executada | "
        f"{len(html_pesquisa or ''):,} caracteres"
    )

    soup = BeautifulSoup(
        html_pesquisa or "",
        "html.parser",
    )

    lotes = []
    for inp in soup.find_all(
        "input",
        attrs={"name": "vlibera"},
    ):
        valor_libera = (
            inp.get("value") or ""
        ).strip()

        tr = inp.find_parent("tr")
        if tr is None:
            continue

        tds = tr.find_all("td")

        lote = ""
        granja = ""
        galpao = ""

        if len(tds) >= 2:
            lote = tds[1].get_text(
                " ",
                strip=True,
            )

        if len(tds) >= 3:
            granja = tds[2].get_text(
                " ",
                strip=True,
            )

        if len(tds) >= 4:
            galpao = tds[3].get_text(
                " ",
                strip=True,
            )

        if not lote:
            partes = valor_libera.split(",")
            if len(partes) >= 2:
                lote = partes[1].strip()

        if not lote:
            continue

        nome_ini = f"vpardate1{lote}"
        nome_fim = f"vpardate2{lote}"
        nome_mov = f"vparlog1{lote}"

        input_ini = tr.find(
            "input",
            attrs={"name": nome_ini},
        )
        input_fim = tr.find(
            "input",
            attrs={"name": nome_fim},
        )

        data_ini = (
            input_ini.get("value")
            if input_ini
            else ""
        ) or ""

        data_fim_tela = (
            input_fim.get("value")
            if input_fim
            else ""
        ) or ""

        lotes.append({
            "lote": lote,
            "granja": granja,
            "galpao": galpao,
            "vlibera": valor_libera,
            "campo_inicio": nome_ini,
            "data_inicio": data_ini.strip(),
            "campo_fim": nome_fim,
            # Sempre vai até o dia da execução.
            "data_fim": datetime.now().strftime(
                "%d/%m/%Y"
            ),
            "data_fim_tela": data_fim_tela.strip(),
            "campo_movto": nome_mov,
        })

    rowini = soup.find(
        "input",
        attrs={"name": "vpad-rowini"},
    )
    rowid = soup.find(
        "input",
        attrs={"name": "vpad-rowid"},
    )

    if not lotes:
        # Salva o HTML real para diagnóstico.
        debug = (
            PASTA_TEMP
            / (
                f"DEBUG_pesquisa_"
                f"emp{empresa_codigo}_"
                f"uni{unidade_codigo}.html"
            )
        )
        debug.write_text(
            html_pesquisa or "",
            encoding="utf-8",
            errors="ignore",
        )

        titulo = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else "sem título"
        )

        raise RuntimeError(
            "O botão Pesquisar foi executado, mas nenhum lote "
            f"foi encontrado no HTML. Título recebido: {titulo}. "
            f"HTML salvo para diagnóstico em: {debug}"
        )

    log(
        f"Pesquisa retornou {len(lotes)} lote(s). "
        "TODOS serão selecionados."
    )

    return {
        "lotes": lotes,
        "rowini": (
            rowini.get("value")
            if rowini
            else ""
        ),
        "rowid": (
            rowid.get("value")
            if rowid
            else ""
        ),
    }


def montar_payload_disparo(unidade_codigo: str, pesquisa: dict):
    """
    Replica o POST capturado no HAR.

    vlibera é enviado repetido para cada lote.
    requests/AgrosysEngine codifica lista como múltiplos campos de mesmo nome.
    """
    lotes = pesquisa["lotes"]

    payload = {
        "vunidade": str(unidade_codigo),
        "vsituacao": SITUACAO,
        "vestagio": ESTAGIO,
        "vrep": REPROCESSA,
        "vpad-btpesq.x": "Pesquisar",
        "vpad-ordena": "",
        "vpad-pesq": "",
        "vpad-rowini": pesquisa.get("rowini", ""),
        "vlibera": [x["vlibera"] for x in lotes],
        "vpad-rowid": pesquisa.get("rowid", ""),
        "bacerto.x": "Disparar",
    }

    for item in lotes:
        payload[item["campo_inicio"]] = item["data_inicio"]
        payload[item["campo_fim"]] = item["data_fim"]

        # REGRA PEDIDA: RECRIA = SEMANAL.
        payload[item["campo_movto"]] = TIPO_MOVTO

    return payload


def executar_relatorio_compat(ag, unidade_codigo: str, filtros: dict, nome_debug: str):
    assinatura = inspect.signature(ag.executar_relatorio)
    parametros = assinatura.parameters

    kwargs = {
        "caminho": CAMINHO_RELATORIO,
        "menu": MENU,
        "unidade": str(unidade_codigo),
        "filtros": filtros,
        "nome_debug": nome_debug,
    }

    if "modulo" in parametros:
        kwargs["modulo"] = MODULO
    if "tentativas" in parametros:
        kwargs["tentativas"] = 30
    if "espera" in parametros:
        kwargs["espera"] = 20
    if "tentativas_disparo" in parametros:
        kwargs["tentativas_disparo"] = 8
    if "espera_disparo" in parametros:
        kwargs["espera_disparo"] = 15

    return ag.executar_relatorio(**kwargs)


def criar_driver():
    op = Options()
    op.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(PASTA_DOWNLOAD),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
        },
    )

    for x in (
        "--headless=new",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-notifications",
        "--disable-popup-blocking",
    ):
        op.add_argument(x)

    d = webdriver.Chrome(options=op)

    try:
        d.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(PASTA_DOWNLOAD)},
        )
    except Exception:
        pass

    return d


def copiar_cookies(driver, ag):
    """
    Sincroniza o Selenium com a sessão Requests atual.

    Isso é importante porque, enquanto aguardamos os processos,
    o robô pode renovar o login do Agrosys. Nesse caso o Selenium
    fica com cookies antigos se não sincronizarmos novamente.
    """
    driver.get(BASE_AGROSYS)
    time.sleep(0.5)

    try:
        driver.delete_all_cookies()
    except Exception:
        pass

    for cookie in ag.session.cookies:
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "path": cookie.path or "/",
        }

        dominio = cookie.domain or "sistema.granjabrasilia.com.br"
        if dominio.startswith("."):
            dominio = dominio[1:]

        item["domain"] = dominio

        try:
            driver.add_cookie(item)
        except Exception:
            # fallback para o domínio principal
            try:
                item["domain"] = "sistema.granjabrasilia.com.br"
                driver.add_cookie(item)
            except Exception:
                pass

    try:
        driver.refresh()
        time.sleep(0.5)
    except Exception:
        pass


def limpar_download_browser():
    for p in PASTA_DOWNLOAD.glob("*"):
        try:
            if p.is_file():
                p.unlink()
        except Exception:
            pass



def _texto_html(celula) -> str:
    if celula is None:
        return ""
    texto = celula.get_text(" ", strip=True)
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _status_da_celula(celula) -> str:
    """
    Converte o ícone visual do Agrosys em texto.
    """
    if celula is None:
        return ""

    img = celula.find("img")
    if img is None:
        return _texto_html(celula)

    src = (img.get("src") or "").lower()

    if "pa-verde" in src or "verde" in src:
        return "Verde"
    if "pa-vermelho" in src or "vermelho" in src:
        return "Vermelho"
    if "amarelo" in src:
        return "Amarelo"

    return _texto_html(celula)


def _cabecalhos_tabela(table):
    thead = table.find("thead")
    if thead is None:
        return []

    tr = thead.find("tr")
    if tr is None:
        return []

    return [
        _texto_html(td)
        for td in tr.find_all(["td", "th"])
    ]


def extrair_relatorio_html(
    html: str,
    processo: str,
    programa: str,
    descricao_processo: str,
):
    """
    Extrai SOMENTE:
      1) tabela Empresa/Descrição/Unidade/Descrição;
      2) bloco Cód./Granja/Lote/Galpão/... acima da tabela;
      3) tabela semanal principal;
      4) Status Verde/Vermelho a partir da imagem do HTML.

    Ignora:
      - Totais
      - gráficos
      - rodapés
    """
    soup = BeautifulSoup(html or "", "html.parser")

    meta = {
        "processo": str(processo),
        "programa": programa or "",
        "descricao_processo": descricao_processo or "",
        "sexo_relatorio": (
            "Femeas/Misto"
            if str(programa).lower() == "wgm800r.p"
            else (
                "Machos/Misto"
                if str(programa).lower() == "wgm801r.p"
                else ""
            )
        ),
    }

    # --------------------------------------------------------
    # 1) Empresa / Unidade
    # --------------------------------------------------------
    tabtop = soup.find("table", id="tabtop")
    if tabtop:
        cab = _cabecalhos_tabela(tabtop)
        tbody = tabtop.find("tbody")
        row = tbody.find("tr") if tbody else None

        if cab and row:
            vals = [
                _texto_html(td)
                for td in row.find_all(["td", "th"])
            ]

            # Esperado: Empresa, Descrição, Unidade, Descrição
            if len(vals) >= 4:
                meta["cab_empresa_codigo"] = vals[0]
                meta["cab_empresa_descricao"] = vals[1]
                meta["cab_unidade_codigo"] = vals[2]
                meta["cab_unidade_descricao"] = vals[3]

    # --------------------------------------------------------
    # 2) Bloco imediatamente acima da tabela semanal
    # --------------------------------------------------------
    tabela_principal = None

    for table in soup.find_all("table", class_="tabela"):
        cab = _cabecalhos_tabela(table)
        cab_norm = [
            re.sub(r"\s+", " ", x).strip().lower()
            for x in cab
        ]

        conjunto = " | ".join(cab_norm)

        if (
            "ini semana" in conjunto
            and "status" in conjunto
            and (
                "morte" in conjunto
                or "viab" in conjunto
            )
        ):
            tabela_principal = table
            break

        if (
            "cód." in conjunto
            or "cod." in conjunto
            or "cód" in conjunto
            or "cod" in conjunto
        ) and "granja" in conjunto and "lote" in conjunto:
            tbody = table.find("tbody")
            row = tbody.find("tr") if tbody else None

            if row:
                vals = [
                    _texto_html(td)
                    for td in row.find_all(["td", "th"])
                ]

                for nome, valor in zip(cab, vals):
                    chave = normalizar_coluna(nome)
                    if chave and chave != "coluna":
                        meta[f"cab_{chave}"] = valor

    if tabela_principal is None:
        raise RuntimeError(
            f"Processo {processo}: não encontrei a tabela semanal principal no HTML."
        )

    # --------------------------------------------------------
    # 3) Tabela principal semanal
    # --------------------------------------------------------
    cabec_raw = _cabecalhos_tabela(tabela_principal)
    cabec = nomes_unicos(cabec_raw)

    linhas = []

    tbody = tabela_principal.find("tbody")
    trs = tbody.find_all("tr") if tbody else []

    for tr in trs:
        cels = tr.find_all(["td", "th"])
        if not cels:
            continue

        texto_linha = " ".join(
            _texto_html(c)
            for c in cels
        ).lower()

        if re.search(r"\btotais?\b", texto_linha):
            break

        valores = []

        for idx, cel in enumerate(cels):
            nome_col = cabec[idx] if idx < len(cabec) else f"coluna_{idx+1}"

            if nome_col == "status":
                valores.append(_status_da_celula(cel))
            else:
                valores.append(_texto_html(cel))

        if not any(str(v).strip() for v in valores):
            continue

        # Completa para o número de colunas do cabeçalho.
        if len(valores) < len(cabec):
            valores += [""] * (len(cabec) - len(valores))

        linhas.append(valores[:len(cabec)])

    if not linhas:
        raise RuntimeError(
            f"Processo {processo}: tabela semanal encontrada, mas sem linhas."
        )

    df = pd.DataFrame(
        linhas,
        columns=cabec,
    )

    # Replica TUDO que está acima da tabela em cada semana.
    for chave, valor in meta.items():
        df[chave] = valor

    return df, meta


def obter_html_relatorio_pronto(ag, processo: str):
    """
    Localiza e devolve diretamente o HTML final do processo.

    Prioridade:
      <usuario>-XXXXXXXXXX.php
      powerbi-XXXXXXXXXX.php
    """
    proc10 = f"{int(processo):010d}"

    candidatos = [
        (
            f"{BASE_AGROSYS}/sistema/reports/"
            f"{ag.usuario}-{proc10}.php"
        ),
        (
            f"{BASE_AGROSYS}/sistema/reports/"
            f"powerbi-{proc10}.php"
        ),
    ]

    ultimo = None

    for tentativa in range(1, 21):
        for url in candidatos:
            try:
                resp = ag.session.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": (
                            f"{BASE_AGROSYS}"
                            f"{CAMINHO_REPORTS}"
                        ),
                        "Cache-Control": "no-cache",
                        "Connection": "close",
                    },
                    timeout=60,
                )

                html = resp.text or ""
                html_low = html.lower()

                pronto = (
                    resp.status_code == 200
                    and "recria - lotes" in html_low
                    and "<table" in html_low
                    and "status" in html_low
                    and "ini" in html_low
                    and "semana" in html_low
                )

                if pronto:
                    log(
                        f"HTML final localizado | processo {processo} | "
                        f"HTTP {resp.status_code}"
                    )
                    return url, html

                ultimo = (
                    f"{url} | HTTP {resp.status_code}"
                )

            except Exception as erro:
                ultimo = (
                    f"{url} | {type(erro).__name__}: {erro}"
                )

        if tentativa < 20:
            log(
                f"HTML final do processo {processo} ainda não disponível. "
                f"Tentativa {tentativa}/20. Aguardando 5s...",
                "AVISO",
            )
            time.sleep(5)

    raise RuntimeError(
        f"Não consegui obter o HTML final do processo {processo}. "
        f"Último retorno: {ultimo}"
    )


def resolver_url_relatorio_pronto(ag, processo: str):
    """
    O menu Reports mostra powerbi-XXXXXXXXXX.php, mas os relatórios que
    efetivamente carregam fexcel() no AgroWeb costumam estar no padrão:

        /sistema/reports/<usuario>-XXXXXXXXXX.php

    Por isso testamos primeiro a URL do usuário e depois a URL powerbi.
    """
    proc10 = f"{int(processo):010d}"

    candidatos = [
        (
            f"{BASE_AGROSYS}/sistema/reports/"
            f"{ag.usuario}-{proc10}.php"
        ),
        (
            f"{BASE_AGROSYS}/sistema/reports/"
            f"powerbi-{proc10}.php"
        ),
    ]

    ultimo = None

    for tentativa in range(1, 21):
        for url in candidatos:
            try:
                resp = ag.session.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": (
                            f"{BASE_AGROSYS}"
                            f"{CAMINHO_REPORTS}"
                        ),
                        "Cache-Control": "no-cache",
                        "Connection": "close",
                    },
                    timeout=60,
                )

                html = resp.text or ""
                titulo = ""

                try:
                    soup = BeautifulSoup(html, "html.parser")
                    titulo = (
                        soup.title.get_text(" ", strip=True)
                        if soup.title
                        else ""
                    )
                except Exception:
                    pass

                pronto = (
                    resp.status_code == 200
                    and "function fexcel" in html.lower()
                    and (
                        "ida sem" in html.lower()
                        or "recria - lotes" in html.lower()
                    )
                )

                log(
                    f"Teste URL processo {processo} | "
                    f"HTTP {resp.status_code} | "
                    f"fexcel={'SIM' if 'function fexcel' in html.lower() else 'NÃO'} | "
                    f"título='{titulo}'"
                )

                if pronto:
                    debug = (
                        PASTA_TEMP
                        / f"DEBUG_relatorio_pronto_{proc10}.html"
                    )
                    try:
                        debug.write_text(
                            html,
                            encoding="latin1",
                            errors="replace",
                        )
                    except Exception:
                        pass

                    return url

                ultimo = (
                    f"{url} | HTTP {resp.status_code} | "
                    f"título={titulo}"
                )

            except Exception as erro:
                ultimo = f"{url} | {type(erro).__name__}: {erro}"

        if tentativa < 20:
            log(
                f"Relatório {processo} ainda não abriu no formato final. "
                f"Tentativa {tentativa}/20. Aguardando 5s...",
                "AVISO",
            )
            time.sleep(5)

    raise RuntimeError(
        f"Não consegui localizar a página final do processo {processo}. "
        f"Último retorno: {ultimo}"
    )


def baixar_excel_oficial(
    driver,
    ag,
    processo: str,
    destino: Path,
):
    """
    1. Descobre qual URL realmente contém o relatório final.
    2. Sincroniza os cookies atuais com o Selenium.
    3. Abre a página final.
    4. Executa fexcel().
    5. Aguarda o .xlsx terminar.
    """
    limpar_download_browser()

    url_relatorio = resolver_url_relatorio_pronto(
        ag,
        processo,
    )

    copiar_cookies(driver, ag)

    log(
        f"Abrindo página FINAL do processo {processo}: "
        f"{url_relatorio}"
    )

    driver.get(url_relatorio)
    time.sleep(2)

    limite_relatorio = time.time() + 120

    while time.time() < limite_relatorio:
        try:
            pronto = driver.execute_script(
                "return document.readyState === 'complete' "
                "&& typeof fexcel === 'function';"
            )
        except Exception:
            pronto = False

        if pronto:
            break

        titulo = ""
        try:
            titulo = driver.title or ""
        except Exception:
            pass

        log(
            f"Aguardando fexcel() do processo {processo} "
            f"| título='{titulo}'",
            "AVISO",
        )
        time.sleep(3)
    else:
        raise RuntimeError(
            f"A página final do processo {processo} foi localizada, "
            "mas o Selenium não disponibilizou fexcel()."
        )

    inicio_download = time.time()
    driver.execute_script("fexcel();")

    log(
        f"fexcel() executado | processo {processo}"
    )

    ultimo = None
    ultimo_tam = None
    estavel = 0

    while time.time() - inicio_download < TIMEOUT_DOWNLOAD:
        if any(PASTA_DOWNLOAD.glob("*.crdownload")):
            time.sleep(0.5)
            continue

        candidatos = []

        for mascara in ("*.xlsx", "*.xls"):
            for arq in PASTA_DOWNLOAD.glob(mascara):
                try:
                    if (
                        arq.is_file()
                        and arq.stat().st_mtime >= inicio_download - 1
                        and arq.stat().st_size > 0
                    ):
                        candidatos.append(arq)
                except OSError:
                    pass

        if candidatos:
            arq = max(
                candidatos,
                key=lambda p: p.stat().st_mtime,
            )
            tam = arq.stat().st_size

            if arq == ultimo and tam == ultimo_tam:
                estavel += 1
            else:
                ultimo = arq
                ultimo_tam = tam
                estavel = 0

            if estavel >= 6:
                destino.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                if destino.exists():
                    destino.unlink()

                arq.replace(destino)

                log(
                    f"Download concluído | processo {processo} | "
                    f"{destino.name}"
                )

                return destino

        time.sleep(0.5)

    raise TimeoutError(
        f"Download do Excel do processo {processo} "
        "não terminou dentro do prazo."
    )

def _extrair_processos_reports_html(html: str):
    """
    Lê diretamente o HTML do wppd004c - Relatórios do Sistema.

    A tela mostra:
      Processo
      Descrição
      Data
      Hora
      Tempo
      Programa

    Processo pronto:
      <img src='/sistema/imagens/verde.gif'>
      <a href=JavaScript:fabre('/sistema/reports/powerbi-000XXXXXXXX.php')>

    Processo ainda executando:
      não possui link powerbi pronto.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    resultados = []

    tabela = soup.find("table", id="vtabela")
    if tabela is None:
        titulo = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else "sem título"
        )
        raise RuntimeError(
            "A tela wppd004c não trouxe a tabela vtabela. "
            f"Título recebido: {titulo}"
        )

    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        # A coluna Processo é a terceira célula da linha de dados.
        texto_processo = tds[2].get_text(" ", strip=True)
        m_proc = re.search(r"\b(\d{7,10})\b", texto_processo)
        if not m_proc:
            continue

        processo = m_proc.group(1)
        descricao = tds[3].get_text(" ", strip=True)
        data_proc = tds[4].get_text(" ", strip=True)
        hora_proc = tds[5].get_text(" ", strip=True)
        tempo_proc = tds[6].get_text(" ", strip=True)
        programa = tds[7].get_text(" ", strip=True)

        href_final = ""

        # O Agrosys usa href SEM aspas:
        #   href=JavaScript:fabre('/sistema/reports/powerbi-0003824684.php')
        #
        # Dependendo do parser HTML, BeautifulSoup pode quebrar esse href.
        # Por isso procuramos primeiro no HTML BRUTO da célula.
        html_celula_processo = str(tds[2])

        m_href = re.search(
            r"(/sistema/reports/powerbi-\d+\.(?:php|html?))",
            html_celula_processo,
            re.I,
        )

        if m_href:
            href_final = m_href.group(1)
        else:
            link = tds[2].find("a")
            if link:
                href = link.get("href") or ""
                m_href = re.search(
                    r"(/sistema/reports/powerbi-\d+\.(?:php|html?))",
                    href,
                    re.I,
                )
                if m_href:
                    href_final = m_href.group(1)

        # Verde = processo concluído.
        img = tds[1].find("img")
        src_img = (img.get("src") or "") if img else ""
        verde = "verde.gif" in src_img.lower()

        # Se a bolinha já está verde, o relatório está concluído.
        # Mesmo que o BeautifulSoup não consiga ler o href JavaScript,
        # conhecemos o padrão oficial do Agrosys e podemos montar a URL.
        if verde and not href_final:
            href_final = (
                f"/sistema/reports/"
                f"powerbi-{int(processo):010d}.php"
            )

        resultados.append({
            "processo": processo,
            "descricao": descricao,
            "data": data_proc,
            "hora": hora_proc,
            "tempo": tempo_proc,
            "programa": programa,
            "href": href_final,
            "pronto": bool(verde),
        })

    return resultados


def listar_processos_reports(ag, tentativas=12):
    """
    Consulta diretamente:
        /webpro/webpad/wppd004c

    A tela Reports pode fechar a conexão HTTP sem responder durante a geração
    dos relatórios. Isso NÃO significa que o processo falhou.

    Por isso:
    - usa Connection: close para não reaproveitar conexão encerrada;
    - tenta novamente automaticamente;
    - só gera erro depois de várias falhas consecutivas.
    """
    url = f"{BASE_AGROSYS}{CAMINHO_REPORTS}"
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        try:
            resp = ag.session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{BASE_AGROSYS}/webpro/webpad/wpadmenu",
                    "Cache-Control": "no-cache",
                    "Connection": "close",
                },
                timeout=60,
            )
            resp.raise_for_status()

            html = resp.text or ""

            debug = PASTA_TEMP / "DEBUG_reports_ultimo.html"
            try:
                debug.write_text(
                    html,
                    encoding="latin1",
                    errors="replace",
                )
            except Exception:
                pass

            processos = _extrair_processos_reports_html(html)

            log(
                f"Reports direto (wppd004c): "
                f"{len(processos)} processo(s) visíveis."
            )

            return processos

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as erro:
            ultimo_erro = erro

            if tentativa >= tentativas:
                break

            espera = min(3 * tentativa, 15)

            log(
                "Reports fechou/interrompeu a conexão. "
                f"Tentativa {tentativa}/{tentativas}. "
                f"Vou tentar novamente em {espera}s.",
                "AVISO",
            )

            time.sleep(espera)

        except RuntimeError as erro:
            # O Agrosys às vezes devolve uma página "Erro Processamento"
            # enquanto os relatórios ainda estão sendo gerados.
            # Isso é temporário e NÃO deve encerrar o robô.
            ultimo_erro = erro

            if tentativa >= tentativas:
                break

            espera = min(5 * tentativa, 20)

            log(
                "Reports retornou uma página temporária de erro/processamento. "
                f"Tentativa {tentativa}/{tentativas}. "
                f"Vou aguardar {espera}s e consultar novamente.",
                "AVISO",
            )

            # Se persistir algumas vezes, renova a sessão sem redisparar o relatório.
            if tentativa in (3, 6):
                try:
                    log(
                        "Erro de processamento persistente. "
                        "Renovando somente a sessão do Agrosys, sem novo disparo.",
                        "AVISO",
                    )
                    ag.login()
                except Exception as erro_login:
                    log(
                        f"Não consegui renovar a sessão agora: {erro_login}",
                        "AVISO",
                    )

            time.sleep(espera)

        except requests.exceptions.RequestException as erro:
            ultimo_erro = erro

            if tentativa >= tentativas:
                break

            espera = min(3 * tentativa, 15)

            log(
                f"Falha HTTP ao consultar Reports: {erro}. "
                f"Tentativa {tentativa}/{tentativas}. "
                f"Nova tentativa em {espera}s.",
                "AVISO",
            )

            time.sleep(espera)

    raise RuntimeError(
        "Não foi possível consultar a tela Reports após "
        f"{tentativas} tentativas consecutivas. "
        f"Último erro: {ultimo_erro}"
    )


def esperar_processos_dos_lotes(
    driver,
    ag,
    lotes_alvo,
    processos_antes,
    timeout=600,
):
    ids_antes = {str(x["processo"]) for x in processos_antes}
    lotes_alvo = [str(x) for x in lotes_alvo]

    inicio = time.time()
    ultima_assinatura = None
    estavel_desde = None
    encontrados = {}

    while time.time() - inicio < timeout:
        processos = listar_processos_reports(ag)

        for item in processos:
            pid = str(item["processo"])
            if pid in ids_antes:
                continue

            desc = item["descricao"]

            if not any(
                re.search(
                    rf"(?<!\d){re.escape(lote)}(?!\d)",
                    desc,
                )
                for lote in lotes_alvo
            ):
                continue

            if not re.search(
                r"\[Recria\s*-\s*Lotes",
                desc,
                re.I,
            ):
                continue

            encontrados[pid] = item

        por_lote = {
            lote: [
                p for p in encontrados.values()
                if re.search(
                    rf"(?<!\d){re.escape(lote)}(?!\d)",
                    p["descricao"],
                )
            ]
            for lote in lotes_alvo
        }

        faltando_lotes = [
            lote
            for lote, itens in por_lote.items()
            if not itens
        ]

        pendentes = [
            p
            for p in encontrados.values()
            if not p["pronto"]
        ]

        log(
            "Reports: "
            f"{len(encontrados)} processo(s) novo(s) dos lotes | "
            f"pendentes={len(pendentes)} | "
            f"lotes sem processo={faltando_lotes or 'nenhum'}"
        )

        for p in sorted(
            encontrados.values(),
            key=lambda x: int(x["processo"]),
        ):
            log(
                f"    Processo {p['processo']} | "
                f"{p['programa'] or '-'} | "
                f"{'PRONTO' if p['pronto'] else 'AGUARDANDO'}"
            )

        assinatura = tuple(
            sorted(
                (
                    pid,
                    bool(item["pronto"]),
                    item["programa"],
                )
                for pid, item in encontrados.items()
            )
        )

        if assinatura != ultima_assinatura:
            ultima_assinatura = assinatura
            estavel_desde = time.time()
        elif estavel_desde is None:
            estavel_desde = time.time()

        todos_lotes_apareceram = not faltando_lotes
        todos_prontos = bool(encontrados) and not pendentes
        estavel = (
            estavel_desde is not None
            and time.time() - estavel_desde >= 15
        )

        if todos_lotes_apareceram and todos_prontos and estavel:
            return sorted(
                encontrados.values(),
                key=lambda x: int(x["processo"]),
            )

        time.sleep(10)

    raise TimeoutError(
        "Os processos dos lotes não ficaram todos prontos dentro do prazo. "
        f"Encontrados: {list(encontrados.values())}"
    )


def consolidar_excels(arquivos, destino):
    """
    Consolida os arquivos preservando PROCESSO e PROGRAMA no nome da aba.

    Exemplo:
      emp02_uni002_proc3824712_wgm800r_p.xlsx
        -> aba proc3824712_wgm800r_p_1

    Assim o tratamento consegue gravar Processo / Programa / Sexo.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)

    if destino.exists():
        destino.unlink()

    contador_global = 0

    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        for arq in arquivos:
            abas = pd.read_excel(
                arq,
                sheet_name=None,
                header=None,
                dtype=object,
            )

            m_proc = re.search(r"proc(\d+)", arq.stem, re.I)
            processo = m_proc.group(1) if m_proc else "semproc"

            if re.search(r"wgm800r", arq.stem, re.I):
                programa = "wgm800r_p"
            elif re.search(r"wgm801r", arq.stem, re.I):
                programa = "wgm801r_p"
            else:
                programa = "relatorio"

            for _, df in abas.items():
                contador_global += 1
                nome = f"proc{processo}_{programa}_{contador_global}"
                nome = re.sub(r"[\[\]:*?/\\\\]", "_", nome)[:31]

                df.to_excel(
                    writer,
                    sheet_name=nome,
                    index=False,
                    header=False,
                )

    return destino


def processar_alvo(
    ag,
    driver,
    empresa_codigo: str,
    empresa_nome: str,
    unidade_codigo: str,
    unidade_nome: str,
    periodo_nome: str,
    periodo_inicio: date,
    periodo_fim: date,
    manter_excel=False,
):
    log("=" * 90)
    log(
        f"EMPRESA {empresa_codigo} - {empresa_nome} | "
        f"UNIDADE {unidade_codigo} - {unidade_nome}"
    )
    log(
        f"{periodo_nome}: "
        f"{periodo_inicio:%d/%m/%Y} até {periodo_fim:%d/%m/%Y}"
    )
    log("Situação: Aberto | Estágio: Recria | Tipo Movto: SEMANAL")
    log("=" * 90)

    ajustar_contexto_sessao(
        ag,
        empresa_codigo,
        unidade_codigo,
    )

    pesquisa_base = pesquisar_lotes(
        ag=ag,
        empresa_codigo=empresa_codigo,
        unidade_codigo=unidade_codigo,
    )

    pesquisa = preparar_pesquisa_periodo(
        pesquisa=pesquisa_base,
        inicio=periodo_inicio,
        fim=periodo_fim,
    )

    lotes = pesquisa["lotes"]

    if not lotes:
        log(
            f"Nenhum lote ativo no período "
            f"{periodo_inicio:%d/%m/%Y} até {periodo_fim:%d/%m/%Y}. "
            "Nada a disparar."
        )
        return 0

    log(
        f"Lotes encontrados para o período: {len(lotes)}"
    )
    log("Selecionando TODOS os lotes retornados...")

    for lote in lotes:
        log(
            f"  [X] Lote {lote['lote']} | "
            f"{lote.get('granja', '')} | "
            f"Galpão {lote.get('galpao', '')} | "
            f"{lote['data_inicio']} até {lote['data_fim']} | "
            f"Tipo Movto = SEMANAL"
        )

    payload = montar_payload_disparo(
        unidade_codigo,
        pesquisa,
    )

    ajustar_contexto_sessao(
        ag,
        empresa_codigo,
        unidade_codigo,
    )

    processos_antes = listar_processos_reports(ag)

    log(
        f"Processos existentes antes do disparo: "
        f"{len(processos_antes)}"
    )

    ajustar_contexto_sessao(
        ag,
        empresa_codigo,
        unidade_codigo,
    )

    url_disparo = (
        f"{BASE_AGROSYS}{CAMINHO_RELATORIO}"
        f"?vmen-codigo={MENU}"
    )

    html_retorno = ag.disparar_relatorio(
        url=url_disparo,
        dados=payload,
    )

    log(
        "Disparo realizado uma única vez. "
        "Vou acompanhar os processos pelo wppd004c."
    )

    processos = esperar_processos_dos_lotes(
        driver=driver,
        ag=ag,
        lotes_alvo=[
            x["lote"]
            for x in lotes
        ],
        processos_antes=processos_antes,
        timeout=600,
    )

    log(
        f"Processos encontrados e prontos: "
        f"{len(processos)}"
    )

    data_inicio = periodo_inicio
    data_fim = periodo_fim

    abas = []
    arquivos_html = []

    for indice, p in enumerate(processos, start=1):
        processo = str(int(p["processo"]))

        log("=" * 70)
        log(
            f"LENDO HTML {indice}/{len(processos)} | "
            f"Processo {processo} | "
            f"{p['descricao']}"
        )

        url_final, html = obter_html_relatorio_pronto(
            ag,
            processo,
        )

        log(
            f"Página final: {url_final}"
        )

        df, meta = extrair_relatorio_html(
            html=html,
            processo=processo,
            programa=p.get("programa") or "",
            descricao_processo=p.get("descricao") or "",
        )

        nome_aba = (
            f"proc{processo}_"
            f"{(p.get('programa') or 'relatorio').replace('.', '_')}"
        )

        abas.append(
            (nome_aba, df)
        )

        log(
            f"HTML tratado | processo {processo} | "
            f"{len(df):,} semana(s) | "
            f"lote={meta.get('cab_lote', '')} | "
            f"sexo={meta.get('sexo_relatorio', '')}"
        )

        if manter_excel:
            destino_html = (
                PASTA_RELATORIOS
                / f"{nome_aba}.html"
            )

            destino_html.write_text(
                html,
                encoding="latin1",
                errors="replace",
            )

            arquivos_html.append(destino_html)

    qtd = importar_dataframes_postgres(
        abas=abas,
        origem_arquivo=(
            f"HTML_Acerto_Produtor_Recria_"
            f"emp{int(empresa_codigo):02d}_"
            f"uni{int(unidade_codigo):03d}_"
            f"{data_inicio:%Y-%m-%d}_a_{data_fim:%Y-%m-%d}"
        ),
        tabela=TABELA_BANCO,
        empresa_codigo=empresa_codigo,
        empresa_nome=empresa_nome,
        unidade_codigo=unidade_codigo,
        unidade_nome=unidade_nome,
        situacao="Aberto",
        estagio="Recria",
        tipo_movto="Semanal",
        relatorio=NOME_RELATORIO,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    log(
        f"SUCESSO: {qtd:,} registros carregados "
        f"no PostgreSQL diretamente do HTML."
    )

    return qtd


def main():
    a = argumentos()

    # ALVOS é uma lista "plana": cada item já representa uma
    # combinação Empresa + Unidade.
    alvos = []

    for alvo in ALVOS:
        empresa_codigo = str(alvo["empresa_codigo"])
        empresa_nome = alvo["empresa_nome"]
        unidade_codigo = str(alvo["unidade_codigo"])
        unidade_nome = alvo["unidade_nome"]

        if (
            a.somente_empresa
            and empresa_codigo != str(a.somente_empresa)
        ):
            continue

        if (
            a.somente_unidade
            and unidade_codigo != str(a.somente_unidade)
        ):
            continue

        alvos.append((
            empresa_codigo,
            empresa_nome,
            unidade_codigo,
            unidade_nome,
        ))

    if not alvos:
        raise RuntimeError(
            "Nenhum alvo selecionado pelos argumentos informados."
        )

    periodos = listar_periodos(a)

    log("=" * 90)
    log(
        "PERÍODOS DA RECRIA: "
        + " | ".join(
            f"{p['nome']} {p['inicio']:%d/%m/%Y} a {p['fim']:%d/%m/%Y}"
            for p in periodos
        )
    )
    log(
        f"Total previsto: {len(periodos)} período(s) x "
        f"{len(alvos)} alvo(s) = {len(periodos) * len(alvos)} execução(ões)."
    )

    ag = criar_agrosys()
    driver = None  # HTML direto: Selenium não é mais necessário para a carga.

    total = 0
    falhas = []

    try:
        for periodo in periodos:
            for empresa_codigo, empresa_nome, unidade_codigo, unidade_nome in alvos:
                try:
                    total += processar_alvo(
                        ag=ag,
                        driver=driver,
                        empresa_codigo=empresa_codigo,
                        empresa_nome=empresa_nome,
                        unidade_codigo=unidade_codigo,
                        unidade_nome=unidade_nome,
                        periodo_nome=periodo["nome"],
                        periodo_inicio=periodo["inicio"],
                        periodo_fim=periodo["fim"],
                        manter_excel=a.manter_excel,
                    )
                except Exception as exc:
                    falhas.append(
                        f"{periodo['nome']} | "
                        f"Empresa {empresa_codigo} / Unidade {unidade_codigo}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    log(falhas[-1], "ERRO")
                    traceback.print_exc()

        log("=" * 90)
        log(f"FINALIZADO | Total carregado/atualizado: {total:,}")

        if falhas:
            log(f"Falhas: {len(falhas)}", "ERRO")
            for f in falhas:
                log(f"  {f}", "ERRO")
            return 1

        return 0

    finally:
        pass


if __name__ == "__main__":
    sys.exit(main())
