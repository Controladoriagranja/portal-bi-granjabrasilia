# -*- coding: utf-8 -*-
r"""ÍNDICE ZOOTÉCNICO - Movimento Mortalidade/Peso - LOTES FECHADOS -> PostgreSQL."""
import argparse
import calendar
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

import pandas as pd

PASTA_ROBO=Path(__file__).resolve().parent; sys.path.insert(0,str(PASTA_ROBO))
from banco_zootecnico import importar_excel_postgres, periodo_ja_carregado


def raiz_agrosys():
    a=Path(__file__).resolve().parent
    for p in [a]+list(a.parents):
        if (p/"config.py").exists() and (p/"Core").exists(): return p
    raise RuntimeError("Não encontrei config.py + Core na árvore do Agrosys_Extractor.")

RAIZ=raiz_agrosys(); sys.path.insert(0,str(RAIZ))
from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

MENU=17136; CAMINHO_RELATORIO="/webpro/webprod/wpf531d7"; MODULO="17000"; UNIDADE="52"
TABELA_BANCO="mortalidade_peso_fechados"; NOME_RELATORIO="Índice Zootécnico - Movimento Mortalidade/Peso - Lotes Fechados"
PASTA_TEMP=Path(tempfile.gettempdir())/"BI_Granja"/"Zootecnico"/"Mortalidade_Fechados"; PASTA_TEMP.mkdir(parents=True,exist_ok=True)


def log(m,n="INFO"): print(f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{n}] {m}",flush=True)


def args():
    p=argparse.ArgumentParser(); p.add_argument("--inicio"); p.add_argument("--fim"); p.add_argument("--dias",type=int); p.add_argument("--forcar",action="store_true"); a=p.parse_args(); hoje=datetime.now().date()
    if a.inicio or a.fim:
        if not(a.inicio and a.fim): p.error("Informe --inicio e --fim juntos.")
        a.ini=datetime.strptime(a.inicio,"%d/%m/%Y").date(); a.fim=datetime.strptime(a.fim,"%d/%m/%Y").date()
    elif a.dias:
        a.fim=hoje; a.ini=hoje-timedelta(days=max(a.dias,1)-1)
    else:
        # Mantém o comportamento original: mês anterior fechado.
        primeiro=hoje.replace(day=1); anterior=primeiro-timedelta(days=1); a.ini=anterior.replace(day=1); a.fim=anterior
    return a


def filtros(ini,fim):
    return {
        "vdata-ini":ini.strftime("%d/%m/%Y"),"vdata-fim":fim.strftime("%d/%m/%Y"),"vregiao":"","vrfo-codigo":"","vrfo-descri":"",
        "vtecinico":"","vlinhagem":"","vicuba":"","vsexo":"","vidade-ini":"","vidade-fim":"","vmort-peso-elim":"T","vmt-100":"QTD",
        "vcli-codigo":"","vgpp-codigo":"","vnuc-nucleo":"","vid-mt-ini":"","vid-mt-fim":"","vlote-mat":"","vacertados":"on","vtipo-dt":"1",
        "vuni-abate":"","vtipo":"S","vtaxa":"S","vpsproj":"no","vdesvio":"S","vdesviops":"S","vordena":"","vtp-granja":"","vtpgalp":"",
        "vempresa":"","vunidade":"","vnutricao":"","vpad-btdisp.x":"Disparar",
    }


def driver_novo():
    o=Options(); o.add_experimental_option("prefs",{"download.default_directory":str(PASTA_TEMP),"download.prompt_for_download":False,"download.directory_upgrade":True})
    for x in ("--headless=new","--disable-gpu","--window-size=1920,1080","--no-sandbox","--disable-dev-shm-usage"):o.add_argument(x)
    d=webdriver.Chrome(options=o)
    try:d.execute_cdp_cmd("Page.setDownloadBehavior",{"behavior":"allow","downloadPath":str(PASTA_TEMP)})
    except Exception:pass
    return d


def limpar():
    for p in PASTA_TEMP.glob("*"):
        try:
            if p.is_file():p.unlink()
        except Exception:pass


def cookies(d,ag):
    d.get(BASE_AGROSYS);time.sleep(.25)
    for n,v in ag.session.cookies.get_dict().items():
        try:d.add_cookie({"name":n,"value":v,"domain":"sistema.granjabrasilia.com.br","path":"/"})
        except Exception:pass


def excel(d,url,ini,fim):
    limpar();d.get(url);lim=time.time()+60
    while time.time()<lim:
        try:
            if d.execute_script("return document.readyState==='complete' && typeof fexcel==='function';"):break
        except Exception:pass
        time.sleep(.25)
    else:raise RuntimeError("fexcel() não ficou disponível.")
    inicio=time.time();d.execute_script("fexcel();");ultimo=None;tam=None;est=0
    while time.time()-inicio<300:
        arqs=[p for m in("*.xlsx","*.xls") for p in PASTA_TEMP.glob(m) if p.is_file() and p.stat().st_mtime>=inicio-1 and p.stat().st_size>0]
        if arqs:
            a=max(arqs,key=lambda p:p.stat().st_mtime);t=a.stat().st_size
            if a==ultimo and t==tam:est+=1
            else:ultimo,tam,est=a,t,0
            if est>=6:
                dst=PASTA_TEMP/f"Mortalidade_Peso_Fechados_{ini:%d-%m-%Y}_{fim:%d-%m-%Y}.xlsx"
                if dst.exists():dst.unlink()
                a.replace(dst);return dst
        time.sleep(.5)
    raise TimeoutError("Download não terminou em 300 segundos.")



def tratar_mortalidade_fechados(nome_aba, df):
    """
    Mantém somente as linhas analíticas do relatório de lotes fechados.

    Remove linhas auxiliares/resumos do Excel e mantém apenas registros
    com semana válida. Quando existir a coluna ano, mantém anos válidos.
    """
    dados = df.copy()

    texto_linha = dados.fillna("").astype(str).agg(" | ".join, axis=1)
    mascara_resumo = texto_linha.str.contains(
        r"\bresumo\s+por\b|\btotal\s+geral\b",
        case=False,
        regex=True,
        na=False,
    )
    dados = dados.loc[~mascara_resumo].copy()

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
        semana_num = pd.to_numeric(semana_txt, errors="coerce")
        dados = dados.loc[semana_num.between(1, 53, inclusive="both")].copy()

    if "ano" in dados.columns:
        ano_num = pd.to_numeric(dados["ano"], errors="coerce")
        dados = dados.loc[ano_num.between(2000, 2100, inclusive="both")].copy()

    return dados.reset_index(drop=True)

def executar(ag,ini,fim):
    d=driver_novo();arq=None
    try:
        cookies(d,ag);_,proc=ag.executar_relatorio(caminho=CAMINHO_RELATORIO,menu=MENU,unidade=UNIDADE,filtros=filtros(ini,fim),
            nome_debug=f"zootecnico_mortalidade_fechados_banco_{ini:%d-%m-%Y}_{fim:%d-%m-%Y}",modulo=MODULO,tentativas=30,espera=20,tentativas_disparo=8,espera_disparo=15)
        url=f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(proc):010d}.php";arq=excel(d,url,ini,fim)
        qtd=importar_excel_postgres(
            arq,
            TABELA_BANCO,
            ini,
            fim,
            NOME_RELATORIO,
            transformador=tratar_mortalidade_fechados,
        );log(f"{qtd:,} registros carregados no PostgreSQL.");return qtd
    finally:
        try:d.quit()
        except Exception:pass
        if arq:
            try:arq.unlink(missing_ok=True)
            except Exception:pass


def main():
    a=args()
    if not a.forcar and periodo_ja_carregado(TABELA_BANCO,a.ini,a.fim):
        log("Período já existe no banco. Use --forcar para reprocessar.");return 0
    ag=AgrosysEngine(base_url=BASE_AGROSYS,usuario=USUARIO_AGROSYS,senha=SENHA_AGROSYS,pasta_html=PASTA_HTML);ag.login();executar(ag,a.ini,a.fim);return 0

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as e:log(f"ERRO FATAL: {type(e).__name__}: {e}","ERRO");traceback.print_exc();sys.exit(1)
