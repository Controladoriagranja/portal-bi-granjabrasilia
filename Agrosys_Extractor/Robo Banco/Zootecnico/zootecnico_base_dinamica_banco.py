# -*- coding: utf-8 -*-
r"""
ÍNDICE ZOOTÉCNICO - BASE DE DADOS DINÂMICA -> POSTGRESQL

Origem Agrosys:
- Programa: wpf800d1
- Menu: 30118
- Unidade: 52
- Histórico padrão: desde 01/01/2023, mês a mês

Destino:
- PostgreSQL: bi_granja
- Tabela: zootecnico.base_dinamica

O Excel é somente temporário: baixa -> trata -> grava PostgreSQL -> apaga.

EXEMPLOS:
    py zootecnico_base_dinamica_banco.py --inicio 01/08/2026 --fim 31/08/2026
    py zootecnico_base_dinamica_banco.py --inicio 01/08/2026 --fim 31/08/2026 --forcar
    py zootecnico_base_dinamica_banco.py
"""

import argparse
import calendar
import re
import sys
import tempfile
import time
import traceback
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# -----------------------------------------------------------------------------
# FUNÇÕES DO BANCO (ficam na mesma pasta deste robô)
# -----------------------------------------------------------------------------
PASTA_ROBO = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_ROBO))

from banco_zootecnico import importar_excel_postgres, periodo_ja_carregado


# -----------------------------------------------------------------------------
# LOCALIZA A ESTRUTURA JÁ EXISTENTE DO AGROSYS_EXTRACTOR
# -----------------------------------------------------------------------------
def localizar_raiz_agrosys() -> Path:
    atual = Path(__file__).resolve().parent
    for pasta in [atual] + list(atual.parents):
        if (pasta / "config.py").exists() and (pasta / "Core").exists():
            return pasta
    raise RuntimeError(
        "Não encontrei a raiz do Agrosys_Extractor. "
        "Preciso encontrar config.py e a pasta Core."
    )


RAIZ = localizar_raiz_agrosys()
sys.path.insert(0, str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DO RELATÓRIO
# -----------------------------------------------------------------------------
MENU = 30118
PROGRAMA = "wpf800d1"
CAMINHO_RELATORIO = "/webpro/weball/wpf800d1"
MODULO = "17000"
UNIDADE = "52"

DATA_HISTORICA_INICIO = date(2023, 1, 1)
TABELA_BANCO = "base_dinamica"
NOME_RELATORIO = "Índice Zootécnico - Base de Dados Dinâmica"
TIMEOUT_DOWNLOAD = 300

PASTA_TEMP = (
    Path(tempfile.gettempdir())
    / "BI_Granja"
    / "Zootecnico"
    / "Base_Dinamica"
)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# LOG
# -----------------------------------------------------------------------------
def log(mensagem, nivel="INFO"):
    print(
        f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{nivel}] {mensagem}",
        flush=True,
    )


# -----------------------------------------------------------------------------
# ARGUMENTOS
# -----------------------------------------------------------------------------
def ler_argumentos():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inicio",
        type=str,
        default=None,
        help="Data inicial DD/MM/AAAA. Sem informar: 01/01/2023.",
    )
    parser.add_argument(
        "--fim",
        type=str,
        default=None,
        help="Data final DD/MM/AAAA. Sem informar: hoje.",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Reprocessa períodos que já existem no PostgreSQL.",
    )
    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    hoje = datetime.now().date()
    try:
        args.data_inicio = (
            datetime.strptime(args.inicio, "%d/%m/%Y").date()
            if args.inicio
            else DATA_HISTORICA_INICIO
        )
        args.data_fim = (
            datetime.strptime(args.fim, "%d/%m/%Y").date()
            if args.fim
            else hoje
        )
    except ValueError:
        parser.error("Datas devem estar no formato DD/MM/AAAA.")

    if args.data_inicio > args.data_fim:
        parser.error("A data inicial não pode ser maior que a data final.")

    if args.data_fim > hoje:
        args.data_fim = hoje

    return args


# -----------------------------------------------------------------------------
# PERÍODOS MENSAIS
# -----------------------------------------------------------------------------
def proximo_mes(data_atual):
    if data_atual.month == 12:
        return date(data_atual.year + 1, 1, 1)
    return date(data_atual.year, data_atual.month + 1, 1)


def gerar_periodos(inicio, fim):
    """
    Sempre processa mês a mês.

    Exemplo:
        01/08/2026 -> 31/08/2026
        01/09/2026 -> hoje (se setembro for o mês atual)
    """
    atual = date(inicio.year, inicio.month, 1)
    ultimo_mes = date(fim.year, fim.month, 1)

    while atual <= ultimo_mes:
        ultimo_dia = calendar.monthrange(atual.year, atual.month)[1]
        fim_mes = date(atual.year, atual.month, ultimo_dia)

        # Primeiro e último mês respeitam os limites informados.
        data_ini = max(atual, inicio)
        data_fim = min(fim_mes, fim)

        yield data_ini, data_fim
        atual = proximo_mes(atual)


# -----------------------------------------------------------------------------
# LIMPEZA ESPECÍFICA DA BASE DINÂMICA
# -----------------------------------------------------------------------------
def _texto_normalizado(valor):
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor).strip()).lower()


def tratar_base_dinamica(nome_aba, df):
    """
    Limpeza conservadora.

    Não tenta adivinhar regras de negócio que não conhecemos. Apenas remove
    sujeira típica do Excel/Agrosys que não representa uma linha analítica:
    - linhas totalmente vazias (já removidas também na função comum);
    - cabeçalho repetido dentro do corpo;
    - linhas explícitas de resumo/total geral;
    - espaços extras nos textos.

    Os nomes das colunas são normalizados pela biblioteca banco_zootecnico.py.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # Padroniza células textuais sem converter números/datas em texto aqui.
    for coluna in df.columns:
        if df[coluna].dtype == object:
            df[coluna] = df[coluna].map(
                lambda v: re.sub(r"\s+", " ", v.strip())
                if isinstance(v, str)
                else v
            )

    colunas = list(df.columns)

    def eh_cabecalho_repetido(row):
        comparacoes = 0
        iguais = 0
        for coluna in colunas:
            valor = _texto_normalizado(row.get(coluna))
            if not valor:
                continue
            comparacoes += 1
            if valor == _texto_normalizado(coluna):
                iguais += 1
        return comparacoes >= 2 and iguais >= max(2, int(comparacoes * 0.6))

    def eh_resumo(row):
        valores = [
            _texto_normalizado(row.get(c))
            for c in colunas
            if _texto_normalizado(row.get(c))
        ]
        if not valores:
            return True

        texto = " | ".join(valores)

        # Remoção deliberadamente restrita para não perder registros reais.
        termos_inicio = (
            "resumo por ",
            "resumo geral",
            "total geral",
            "totais gerais",
        )

        primeiro = valores[0]
        if primeiro.startswith(termos_inicio):
            return True

        # Linhas que são somente um rótulo de totalização.
        if len(valores) <= 2 and primeiro in {
            "total",
            "totais",
            "resumo",
            "total geral",
        }:
            return True

        # Linhas de rodapé conhecidas, mas apenas se houver pouquíssimos valores.
        if len(valores) <= 2 and (
            texto.startswith("emitido em")
            or texto.startswith("impresso em")
        ):
            return True

        return False

    mascara_manter = []
    for _, row in df.iterrows():
        manter = not eh_cabecalho_repetido(row) and not eh_resumo(row)
        mascara_manter.append(manter)

    df = df.loc[mascara_manter].copy()
    df = df.dropna(axis=0, how="all")
    df = df.reset_index(drop=True)

    return df


# -----------------------------------------------------------------------------
# SELENIUM / DOWNLOAD
# -----------------------------------------------------------------------------
def criar_driver():
    opcoes = Options()
    opcoes.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(PASTA_TEMP),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
        },
    )

    for argumento in (
        "--headless=new",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-notifications",
        "--disable-popup-blocking",
    ):
        opcoes.add_argument(argumento)

    driver = webdriver.Chrome(options=opcoes)

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(PASTA_TEMP),
            },
        )
    except Exception:
        pass

    return driver


def limpar_temp():
    for arquivo in PASTA_TEMP.glob("*"):
        try:
            if arquivo.is_file():
                arquivo.unlink()
        except Exception:
            pass


def copiar_cookies(driver, ag):
    driver.get(BASE_AGROSYS)
    time.sleep(0.25)

    for nome, valor in ag.session.cookies.get_dict().items():
        try:
            driver.add_cookie(
                {
                    "name": nome,
                    "value": valor,
                    "domain": "sistema.granjabrasilia.com.br",
                    "path": "/",
                }
            )
        except Exception:
            pass


def aguardar_download(inicio_download, timeout=TIMEOUT_DOWNLOAD):
    inicio = time.time()
    ultimo_arquivo = None
    ultimo_tamanho = None
    estabilidade = 0

    while time.time() - inicio < timeout:
        prontos = []

        for mascara in ("*.xlsx", "*.xls"):
            for arquivo in PASTA_TEMP.glob(mascara):
                try:
                    if not arquivo.is_file():
                        continue
                    if arquivo.stat().st_mtime < inicio_download - 1:
                        continue
                    if arquivo.stat().st_size <= 0:
                        continue
                    prontos.append(arquivo)
                except OSError:
                    pass

        if prontos:
            arquivo = max(prontos, key=lambda p: p.stat().st_mtime)
            tamanho = arquivo.stat().st_size

            if arquivo == ultimo_arquivo and tamanho == ultimo_tamanho:
                estabilidade += 1
            else:
                ultimo_arquivo = arquivo
                ultimo_tamanho = tamanho
                estabilidade = 0

            if estabilidade >= 6:
                log(
                    f"Excel temporário detectado: {arquivo.name} "
                    f"({tamanho / 1024 / 1024:.2f} MB)"
                )
                return arquivo

        time.sleep(0.5)

    presentes = [p.name for p in PASTA_TEMP.glob("*") if p.is_file()]
    raise TimeoutError(
        "Excel oficial não apareceu na pasta temporária dentro do prazo. "
        f"Arquivos presentes: {presentes}"
    )


def baixar_excel(driver, url_relatorio, data_ini, data_fim):
    limpar_temp()

    log("Abrindo relatório pronto no Selenium...")
    driver.get(url_relatorio)

    limite = time.time() + 60
    pronto = False

    while time.time() < limite:
        try:
            pronto = driver.execute_script(
                "return document.readyState === 'complete' "
                "&& typeof fexcel === 'function';"
            )
            if pronto:
                break
        except Exception:
            pass
        time.sleep(0.25)

    if not pronto:
        raise RuntimeError(
            "A página abriu, mas fexcel() não ficou disponível em 60 segundos."
        )

    inicio_download = time.time()
    driver.execute_script("fexcel();")
    log("fexcel() executado. Aguardando Excel oficial...")

    baixado = aguardar_download(inicio_download)

    destino = (
        PASTA_TEMP
        / f"Base_Dados_Dinamica_{data_ini:%d-%m-%Y}_{data_fim:%d-%m-%Y}.xlsx"
    )

    if destino.exists():
        destino.unlink()

    baixado.replace(destino)
    return destino


# -----------------------------------------------------------------------------
# AGROSYS -> EXCEL TEMP -> POSTGRESQL
# -----------------------------------------------------------------------------
def executar_periodo(ag, data_ini, data_fim):
    driver = None
    arquivo = None

    try:
        driver = criar_driver()
        copiar_cookies(driver, ag)

        filtros = {
            "vdat-inicial": data_ini.strftime("%d/%m/%Y"),
            "vdat-final": data_fim.strftime("%d/%m/%Y"),
            "vdinamico": "yes",
            "vpad-btdisp.x": "Disparar",
        }

        log("=" * 80)
        log(f"BASE DINÂMICA: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}")
        log(f"Programa {PROGRAMA} | Menu {MENU} | Unidade {UNIDADE}")

        _, processo = ag.executar_relatorio(
            caminho=CAMINHO_RELATORIO,
            menu=MENU,
            unidade=UNIDADE,
            filtros=filtros,
            nome_debug=(
                "zootecnico_base_dinamica_banco_"
                f"{data_ini:%d-%m-%Y}_{data_fim:%d-%m-%Y}"
            ),
            modulo=MODULO,
            tentativas=30,
            espera=20,
            tentativas_disparo=8,
            espera_disparo=15,
        )

        log(f"Processo Agrosys: {processo}")

        url_relatorio = (
            f"{BASE_AGROSYS}/sistema/reports/"
            f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
        )

        arquivo = baixar_excel(
            driver=driver,
            url_relatorio=url_relatorio,
            data_ini=data_ini,
            data_fim=data_fim,
        )

        qtd = importar_excel_postgres(
            caminho=arquivo,
            tabela=TABELA_BANCO,
            data_inicio=data_ini,
            data_fim=data_fim,
            relatorio=NOME_RELATORIO,
            transformador=tratar_base_dinamica,
        )

        log(f"SUCESSO: {qtd:,} registros carregados no PostgreSQL.")
        return qtd

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

        if arquivo is not None:
            try:
                arquivo.unlink(missing_ok=True)
            except Exception:
                pass


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    args = ler_argumentos()
    hoje = datetime.now().date()

    log("=" * 80)
    log("ÍNDICE ZOOTÉCNICO - BASE DINÂMICA -> POSTGRESQL")
    log(f"Período solicitado: {args.data_inicio:%d/%m/%Y} até {args.data_fim:%d/%m/%Y}")
    log(f"Forçar reprocessamento: {'SIM' if args.forcar else 'NÃO'}")
    log("=" * 80)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    log("Realizando login no Agrosys...")
    ag.login()
    log("Login realizado.")

    total = 0
    periodos_processados = 0

    for data_ini, data_fim in gerar_periodos(args.data_inicio, args.data_fim):
        eh_mes_atual = (
            data_ini.year == hoje.year
            and data_ini.month == hoje.month
        )

        if (
            not args.forcar
            and not eh_mes_atual
            and periodo_ja_carregado(TABELA_BANCO, data_ini, data_fim)
        ):
            log(
                f"{data_ini:%m/%Y} já existe no PostgreSQL. Pulando.",
                "INFO",
            )
            continue

        total += executar_periodo(ag, data_ini, data_fim)
        periodos_processados += 1

    log("=" * 80)
    log(
        f"FINALIZADO. Períodos processados: {periodos_processados} | "
        f"Registros carregados: {total:,}"
    )
    log("=" * 80)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"ERRO FATAL: {type(exc).__name__}: {exc}", "ERRO")
        traceback.print_exc()
        sys.exit(1)
