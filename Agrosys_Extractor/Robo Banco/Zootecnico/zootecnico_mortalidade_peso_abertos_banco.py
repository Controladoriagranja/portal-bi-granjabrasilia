# -*- coding: utf-8 -*-
r"""ÍNDICE ZOOTÉCNICO - Movimento Mortalidade/Peso - LOTES ABERTOS -> PostgreSQL."""
import argparse
import calendar
import sys
import tempfile
import time
import traceback
from datetime import date, datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PASTA_ROBO = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_ROBO))
from banco_zootecnico import importar_excel_postgres, periodo_ja_carregado

import pandas as pd


def localizar_raiz_agrosys():
    atual = Path(__file__).resolve().parent
    for pasta in [atual] + list(atual.parents):
        if (pasta / "config.py").exists() and (pasta / "Core").exists():
            return pasta
    raise RuntimeError("Não encontrei config.py + Core na árvore do Agrosys_Extractor.")

RAIZ = localizar_raiz_agrosys(); sys.path.insert(0, str(RAIZ))
from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

MENU = 17136
CAMINHO_RELATORIO = "/webpro/webprod/wpf531d7"
MODULO = "17136"
UNIDADE = "52"
TABELA_BANCO = "mortalidade_peso_abertos"
NOME_RELATORIO = "Índice Zootécnico - Movimento Mortalidade/Peso - Lotes Abertos"
DATA_HISTORICA_INICIO = date(2023, 1, 1)
PASTA_TEMP = Path(tempfile.gettempdir()) / "BI_Granja" / "Zootecnico" / "Mortalidade_Abertos"
PASTA_TEMP.mkdir(parents=True, exist_ok=True)


def log(msg, nivel="INFO"): print(f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{nivel}] {msg}", flush=True)


def argumentos():
    p = argparse.ArgumentParser()
    p.add_argument("--inicio", default=None, help="DD/MM/AAAA")
    p.add_argument("--fim", default=None, help="DD/MM/AAAA")
    p.add_argument("--forcar-todos", action="store_true")
    a = p.parse_args()
    hoje = datetime.now().date()
    a.data_inicio = datetime.strptime(a.inicio, "%d/%m/%Y").date() if a.inicio else DATA_HISTORICA_INICIO
    a.data_fim = datetime.strptime(a.fim, "%d/%m/%Y").date() if a.fim else hoje
    return a


def meses_entre(ini, fim):
    atual = ini.replace(day=1)
    while atual <= fim:
        natural = date(atual.year, atual.month, calendar.monthrange(atual.year, atual.month)[1])
        yield atual, min(natural, fim)
        atual = date(atual.year + 1, 1, 1) if atual.month == 12 else date(atual.year, atual.month + 1, 1)


def montar_filtros(data_ini, data_fim):
    return {
        "vdata-ini": data_ini.strftime("%d/%m/%Y"), "vdata-fim": data_fim.strftime("%d/%m/%Y"),
        "vregiao": "", "vrfo-codigo": "", "vrfo-descri": "", "vtecinico": "", "vlinhagem": "", "vicuba": "", "vsexo": "",
        "vidade-ini": "", "vidade-fim": "", "vmort-peso-elim": "T", "vmt-100": "QTD", "vckpendente": "", "vcmaq": "",
        "vstd": "", "vcli-codigo": "", "vgpp-codigo": "", "vnuc-nucleo": "", "vid-mt-ini": "", "vid-mt-fim": "",
        "vlote-mat": "", "vmat-100": "", "vcompos": "", "vgrafico": "", "vacertados": "", "vtipo": "S", "vtaxa": "S",
        "vpsproj": "no", "vdesvio": "S", "vdesviops": "S", "vordena": "", "vtp-granja": "", "vtpgalp": "",
        "vempresa": "", "vunidade": "", "vnutricao": "", "vpad-btdisp.x": "Disparar",
    }


def driver_novo():
    o = Options(); o.add_experimental_option("prefs", {"download.default_directory": str(PASTA_TEMP), "download.prompt_for_download": False, "download.directory_upgrade": True})
    for x in ("--headless=new", "--disable-gpu", "--window-size=1920,1080", "--no-sandbox", "--disable-dev-shm-usage"): o.add_argument(x)
    d = webdriver.Chrome(options=o)
    try: d.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(PASTA_TEMP)})
    except Exception: pass
    return d


def limpar_temp():
    for p in PASTA_TEMP.glob("*"):
        try:
            if p.is_file(): p.unlink()
        except Exception: pass


def cookies(driver, ag):
    driver.get(BASE_AGROSYS); time.sleep(.25)
    for n, v in ag.session.cookies.get_dict().items():
        try: driver.add_cookie({"name": n, "value": v, "domain": "sistema.granjabrasilia.com.br", "path": "/"})
        except Exception: pass


def baixar_excel(driver, url, ini, fim):
    limpar_temp(); driver.get(url)
    limite = time.time() + 60
    while time.time() < limite:
        try:
            if driver.execute_script("return document.readyState==='complete' && typeof fexcel==='function';"): break
        except Exception: pass
        time.sleep(.25)
    else: raise RuntimeError("fexcel() não ficou disponível.")
    inicio = time.time(); driver.execute_script("fexcel();")
    ultimo=None; tam=None; estavel=0
    while time.time()-inicio < 300:
        arqs=[p for m in ("*.xlsx","*.xls") for p in PASTA_TEMP.glob(m) if p.is_file() and p.stat().st_mtime >= inicio-1 and p.stat().st_size>0]
        if arqs:
            a=max(arqs,key=lambda p:p.stat().st_mtime); t=a.stat().st_size
            if a==ultimo and t==tam: estavel+=1
            else: ultimo,tam,estavel=a,t,0
            if estavel>=6:
                destino=PASTA_TEMP/f"Mortalidade_Peso_Abertos_{ini:%d-%m-%Y}_{fim:%d-%m-%Y}.xlsx"
                if destino.exists(): destino.unlink()
                a.replace(destino); return destino
        time.sleep(.5)
    raise TimeoutError("Download do Excel não terminou em 300 segundos.")


def tratar_mortalidade_abertos(nome_aba, df):
    """
    Mantém somente as linhas analíticas do relatório.

    O Excel do Agrosys traz também linhas auxiliares, como
    "Resumo Por Incubatorio". Essas linhas não são lotes e não devem ir
    para a tabela analítica.
    """
    dados = df.copy()

    # Remove linhas de resumo/totalização que aparecem no meio/fim do Excel.
    texto_linha = dados.fillna("").astype(str).agg(" | ".join, axis=1)
    mascara_resumo = texto_linha.str.contains(
        r"\bresumo\s+por\b|\btotal\s+geral\b",
        case=False,
        regex=True,
        na=False,
    )
    dados = dados.loc[~mascara_resumo].copy()

    # Depois da normalização do cabeçalho, o campo do relatório deve ficar
    # como semana_ano (antes aparecia como semana_x000d_ano).
    coluna_semana = next(
        (c for c in dados.columns if c == "semana_ano" or c.startswith("semana_ano_")),
        None,
    )

    if coluna_semana is not None:
        semana_txt = (
            dados[coluna_semana]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )
        # Semana real: 1 a 53. Elimina textos/cabeçalhos/resumos.
        semana_num = pd.to_numeric(semana_txt, errors="coerce")
        dados = dados.loc[semana_num.between(1, 53, inclusive="both")].copy()

    # Quando existir Ano, mantém somente anos válidos. Isso também elimina
    # eventuais linhas repetidas de cabeçalho dentro da planilha.
    if "ano" in dados.columns:
        ano_num = pd.to_numeric(dados["ano"], errors="coerce")
        dados = dados.loc[ano_num.between(2000, 2100, inclusive="both")].copy()

    return dados.reset_index(drop=True)


def executar(ag, ini, fim):
    d=driver_novo(); arquivo=None
    try:
        cookies(d,ag)
        _, processo=ag.executar_relatorio(caminho=CAMINHO_RELATORIO,menu=MENU,unidade=UNIDADE,filtros=montar_filtros(ini,fim),
            nome_debug=f"zootecnico_mortalidade_abertos_banco_{ini:%d-%m-%Y}_{fim:%d-%m-%Y}",modulo=MODULO,tentativas=30,espera=20,tentativas_disparo=8,espera_disparo=15)
        url=f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"
        arquivo=baixar_excel(d,url,ini,fim)
        qtd=importar_excel_postgres(
            arquivo,
            TABELA_BANCO,
            ini,
            fim,
            NOME_RELATORIO,
            transformador=tratar_mortalidade_abertos,
        )
        log(f"{ini:%m/%Y}: {qtd:,} registros carregados."); return qtd
    finally:
        try:d.quit()
        except Exception:pass
        if arquivo:
            try:arquivo.unlink(missing_ok=True)
            except Exception:pass


def main():
    a=argumentos(); hoje=datetime.now().date(); ag=AgrosysEngine(base_url=BASE_AGROSYS,usuario=USUARIO_AGROSYS,senha=SENHA_AGROSYS,pasta_html=PASTA_HTML); ag.login(); total=0
    for ini,fim in meses_entre(a.data_inicio,a.data_fim):
        atual=ini.year==hoje.year and ini.month==hoje.month
        if not a.forcar_todos and not atual and periodo_ja_carregado(TABELA_BANCO,ini,fim):
            log(f"{ini:%m/%Y} já carregado. Pulando."); continue
        total+=executar(ag,ini,fim)
    log(f"FINALIZADO. Total processado: {total:,}"); return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as e:
        log(f"ERRO FATAL: {type(e).__name__}: {e}","ERRO"); traceback.print_exc(); sys.exit(1)
