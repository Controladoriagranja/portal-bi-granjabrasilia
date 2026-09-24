# Robô Comercial - Cadastro de Vendedores DIRETO
# Sem Selenium: dispara o relatório, lê o HTML gerado e salva somente a tabela principal.
# Caminho sugerido: \\\\192.168.1.139\\Controladoria\\BI_Granja\Agrosys_Extractor\Comercial\cadastro_de_vendedores.py

import argparse
import re
import sys
import traceback
import shutil
import time
from pathlib import Path
from io import StringIO
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# =========================
# CONFIG
# =========================
PASTA_EXPORTACAO = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Comercial\Cadastro de Vendedores")
PASTA_TRATADOS = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Comercial")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_EXPORTACAO.mkdir(parents=True, exist_ok=True)
PASTA_TRATADOS.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

ARQUIVO_EXCEL_GERAL = PASTA_EXPORTACAO / "cadastro_de_vendedores.xlsx"
ARQUIVO_PARQUET_GERAL = PASTA_TRATADOS / "cadastro_de_vendedores.parquet"
ARQUIVO_CSV_GERAL = PASTA_TRATADOS / "cadastro_de_vendedores.csv"

UNIDADES = [
    {"codigo": "10", "nome_arquivo": "Avenova", "descricao": "010 - AVE NOVA", "empresa_padrao": "Ave Nova"},
    {"codigo": "111", "nome_arquivo": "RealAlimentos", "descricao": "111 - REAL ALIMENTOS", "empresa_padrao": "Real Alimentos"},
    {"codigo": "102", "nome_arquivo": "CdJanuaria", "descricao": "102 - CD JANUARIA", "empresa_padrao": "CD Januária"},
    {"codigo": "180", "nome_arquivo": "CdRibeiraoDasNeves", "descricao": "180 - CD RIBEIRÃO DAS NEVES", "empresa_padrao": "CD Ribeirão das Neves"},
]


# =========================
# FUNÇÕES BASE
# =========================
def normalizar_nome(txt: str) -> str:
    return (
        str(txt).lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
        .replace(".", "")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def limpar_coluna(c) -> str:
    if c is None:
        return ""
    c = str(c).replace("\n", " ").replace("\r", " ")
    c = re.sub(r"\s+", " ", c).strip()
    return c


def chave_coluna(c) -> str:
    return normalizar_nome(limpar_coluna(c))


def make_unique_columns(cols):
    usados = {}
    saida = []
    for i, c in enumerate(cols):
        nome = limpar_coluna(c)
        if nome == "" or nome.lower().startswith("unnamed"):
            nome = f"coluna_{i}"
        if nome in usados:
            usados[nome] += 1
            nome = f"{nome}_{usados[nome]}"
        else:
            usados[nome] = 0
        saida.append(nome)
    return saida


def to_numeric_ptbr(series: pd.Series) -> pd.Series:
    def parse_one(x):
        if x is None or pd.isna(x):
            return None
        if isinstance(x, (int, float)):
            return float(x)
        txt = str(x).strip()
        if txt in ["", "-", "nan", "None", "NaT"]:
            return None
        negativo_final = txt.endswith("-")
        if negativo_final:
            txt = txt[:-1].strip()
        txt = txt.replace("R$", "").replace("%", "").strip()
        if "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        try:
            valor = float(txt)
            return -valor if negativo_final else valor
        except Exception:
            return None
    return series.apply(parse_one)


def normalize_text(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return s.replace({"nan": None, "None": None, "NaT": None, "<NA>": None, "": None})


# =========================
# SELENIUM - EXCEL OFICIAL (PADRÃO LOGÍSTICA)
# =========================
def criar_driver():
    chrome_options = Options()

    prefs = {
        "download.default_directory": str(PASTA_DOWNLOAD),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }

    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(PASTA_DOWNLOAD),
            },
        )
    except Exception:
        pass

    return driver


def limpar_downloads():
    for arquivo in PASTA_DOWNLOAD.glob("*"):
        try:
            if arquivo.is_file():
                arquivo.unlink()
            elif arquivo.is_dir():
                shutil.rmtree(arquivo)
        except Exception:
            pass


def aguardar_download(timeout=300, inicio_download=None):
    r"""
    Aceita o Excel final estável mesmo que o Chrome/Agrosys deixe
    .crdownload, .tmp ou .part auxiliares na pasta.
    """
    inicio = time.time()
    ultimo_arquivo = None
    ultimo_tamanho = None
    estabilidade = 0

    while time.time() - inicio < timeout:
        prontos = []

        for mascara in ("*.xlsx", "*.xls"):
            for arquivo in PASTA_DOWNLOAD.glob(mascara):
                try:
                    if not arquivo.is_file():
                        continue

                    if (
                        inicio_download is not None
                        and arquivo.stat().st_mtime < inicio_download - 1
                    ):
                        continue

                    if arquivo.stat().st_size <= 0:
                        continue

                    prontos.append(arquivo)

                except OSError:
                    pass

        if prontos:
            arquivo = max(
                prontos,
                key=lambda p: p.stat().st_mtime,
            )

            try:
                tamanho = arquivo.stat().st_size
            except OSError:
                tamanho = None

            if (
                arquivo == ultimo_arquivo
                and tamanho == ultimo_tamanho
                and tamanho
            ):
                estabilidade += 1
            else:
                ultimo_arquivo = arquivo
                ultimo_tamanho = tamanho
                estabilidade = 0

            # aproximadamente 3 segundos sem crescimento
            if estabilidade >= 6:
                auxiliares = [
                    a.name
                    for a in PASTA_DOWNLOAD.glob("*")
                    if a.is_file()
                    and (
                        a.name.endswith(".crdownload")
                        or a.suffix.lower() in {".tmp", ".part"}
                    )
                ]

                print(
                    "Arquivo final detectado:",
                    arquivo.name,
                    "| tamanho:",
                    f"{tamanho / 1024 / 1024:.2f} MB",
                    flush=True,
                )

                if auxiliares:
                    print(
                        "Arquivos auxiliares ignorados:",
                        auxiliares,
                        flush=True,
                    )

                return arquivo

        time.sleep(0.5)

    return None


def copiar_cookies_para_selenium(driver, ag):
    print("Preparando sessão Selenium...", flush=True)
    driver.get(BASE_AGROSYS)
    time.sleep(0.25)

    cookies = ag.session.cookies.get_dict()

    for nome, valor in cookies.items():
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

    print(
        f"Sessão Selenium pronta. Cookies copiados: {len(cookies)}",
        flush=True,
    )


def baixar_excel_oficial(driver, ag, url_relatorio, arquivo_destino):
    """
    Download oficial do Agrosys via Selenium,
    no mesmo padrão validado no Suprimentos.
    """
    limpar_downloads()
    copiar_cookies_para_selenium(driver, ag)

    print("Abrindo relatório pronto no Selenium...", flush=True)
    inicio_abertura = time.time()
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
        raise TimeoutException(
            "A página abriu, mas a função fexcel() "
            "não ficou disponível em 60 segundos."
        )

    print(
        f"fexcel() localizado em {time.time() - inicio_abertura:.1f}s. "
        "Solicitando Excel oficial...",
        flush=True,
    )

    inicio_download = time.time()
    driver.execute_script("fexcel();")
    print("fexcel() executado.", flush=True)

    inicio_confirmacao = time.time()
    download_iniciado = False

    while time.time() - inicio_confirmacao < 8:
        temporarios = [
            a
            for a in PASTA_DOWNLOAD.glob("*.crdownload")
            if a.is_file()
        ]

        excels = [
            a
            for mascara in ("*.xlsx", "*.xls")
            for a in PASTA_DOWNLOAD.glob(mascara)
            if a.is_file()
        ]

        if temporarios or excels:
            download_iniciado = True
            print(
                "Download detectado na pasta temporária.",
                flush=True,
            )
            break

        time.sleep(0.5)

    if not download_iniciado:
        print(
            "fexcel() não iniciou arquivo em 8s. "
            "Vou continuar aguardando o download.",
            flush=True,
        )

    print("Aguardando conclusão do Excel oficial...", flush=True)

    baixado = aguardar_download(
        timeout=300,
        inicio_download=inicio_download,
    )

    if baixado is None:
        presentes = [
            a.name
            for a in PASTA_DOWNLOAD.glob("*")
            if a.is_file()
        ]

        raise TimeoutException(
            "Não encontrei o arquivo baixado pelo Excel oficial. "
            f"Arquivos presentes: {presentes}"
        )

    destino_real = arquivo_destino.with_suffix(baixado.suffix.lower())
    destino_real.parent.mkdir(parents=True, exist_ok=True)

    if destino_real.exists():
        destino_real.unlink()

    shutil.move(str(baixado), str(destino_real))

    if (
        not destino_real.exists()
        or destino_real.stat().st_size <= 0
    ):
        raise Exception(
            "O Excel foi baixado, mas não foi salvo corretamente."
        )

    print(
        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
        destino_real,
        flush=True,
    )
    print(
        f"Tamanho: {destino_real.stat().st_size / 1024 / 1024:.2f} MB",
        flush=True,
    )

    return destino_real


def montar_filtros(args):
    return {
        "vven-codigo": args.vendedor or "",
        "vsup-codigo": args.supervisor or "",
        "vsituacao": args.situacao or "A",  # 1=Ativos, 2=Inativos, A=Ambos
        "vpad-btdisp.x": "Disparar",
    }


# =========================
# EXTRAÇÃO DA TABELA PRINCIPAL
# =========================
def score_tabela_cadastro(df: pd.DataFrame) -> int:
    cols = {chave_coluna(c) for c in df.columns}
    score = 0

    grupos = [
        {"codigo", "cod", "codigovendedor", "vendedor"},
        {"nome", "nomevendedor", "vendedor"},
        {"supervisor", "supervisornome", "nomesupervisor"},
        {"situacao", "status"},
        {"email", "emailvendedor"},
        {"telefone", "fone", "celular"},
    ]

    for grupo in grupos:
        if cols.intersection(grupo):
            score += 1

    return score


def promover_linha_cabecalho_se_preciso(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.copy()

    if score_tabela_cadastro(df) >= 2:
        df.columns = make_unique_columns(df.columns)
        return df

    limite = min(len(df), 100)
    for i in range(limite):
        linha = [chave_coluna(v) for v in df.iloc[i].tolist()]
        tem_codigo = any(x in linha for x in ["codigo", "cod", "vendedor", "codigovendedor"])
        tem_nome = any(x in linha for x in ["nome", "nomevendedor"])
        tem_supervisor_ou_situacao = any(x in linha for x in ["supervisor", "situacao", "status"])

        if tem_codigo and tem_nome and tem_supervisor_ou_situacao:
            novo = df.iloc[i + 1:].copy()
            novo.columns = make_unique_columns(df.iloc[i].tolist())
            return novo

    return None


def extrair_tabela_principal_do_html(html: str) -> pd.DataFrame:
    tabelas = pd.read_html(StringIO(html), decimal=",", thousands=".")
    candidatas = []

    for idx, tabela in enumerate(tabelas):
        if tabela is None or tabela.empty:
            continue

        tabela2 = promover_linha_cabecalho_se_preciso(tabela)
        if tabela2 is None or tabela2.empty:
            continue

        score = score_tabela_cadastro(tabela2)
        if score < 2:
            continue

        candidatas.append((idx, score, len(tabela2), tabela2))

    if not candidatas:
        raise Exception("Não encontrei a tabela principal do Cadastro de Vendedores no HTML do relatório.")

    _, _, _, df = max(candidatas, key=lambda x: (x[1], x[2]))
    df = df.copy()
    df.columns = make_unique_columns(df.columns)

    df = df.dropna(how="all").copy()

    col_codigo = None
    for c in df.columns:
        if chave_coluna(c) in ["codigo", "cod", "vendedor", "codigovendedor"]:
            col_codigo = c
            break

    if col_codigo is not None:
        cod_num = pd.to_numeric(df[col_codigo], errors="coerce")
        if cod_num.notna().sum() > 0:
            df = df[cod_num.notna()].copy()

    mask_total = df.astype(str).apply(
        lambda col: col.str.contains(r"^\s*Total:?\s*$", case=False, regex=True, na=False)
    )
    df = df.loc[~mask_total.any(axis=1)].copy()

    return df.reset_index(drop=True)


def tratar_tipos_basicos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for c in df.columns:
        ck = chave_coluna(c)
        if ck in ["codigo", "cod", "vendedor", "codigovendedor", "matricula", "codigosm", "supervisor", "codigosupervisor"]:
            df[c] = to_numeric_ptbr(df[c])
        elif ck in ["comissao", "comissaopadrao", "comcaractere", "desconto", "percentualcomissao"]:
            df[c] = to_numeric_ptbr(df[c])
        else:
            if df[c].dtype == "object":
                df[c] = normalize_text(df[c])

    return df


# =========================
# DOWNLOAD / PROCESSAMENTO
# =========================
def baixar_cadastro_vendedores(ag, driver, unidade, args):
    print("=" * 80)
    print(f"Cadastro de Vendedores - Excel oficial - {unidade['descricao']}")
    print(f"Situação: {args.situacao} | Vendedor: {args.vendedor or 'Todos'} | Supervisor: {args.supervisor or 'Todos'}")
    print("=" * 80)

    filtros = montar_filtros(args)

    html, processo = ag.executar_relatorio(
        caminho="/webpro/weball/wad030d4",
        menu=30352,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"cadastro_vendedores_{unidade['nome_arquivo']}",
        modulo="14400",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=20,
    )

    if processo is None:
        raise Exception("O Agrosys não retornou o número do processo.")

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = (
        PASTA_EXPORTACAO /
        f"cadastro_de_vendedores_{unidade['nome_arquivo']}.xlsx"
    )

    arquivo = baixar_excel_oficial(
        driver=driver,
        ag=ag,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    bruto = pd.read_excel(arquivo, header=None)
    df_principal = promover_linha_cabecalho_se_preciso(bruto)
    if df_principal is None or df_principal.empty:
        # fallback usando leitor de tabelas do Excel já com primeira linha como cabeçalho
        df_principal = pd.read_excel(arquivo)

    df_principal.columns = make_unique_columns(df_principal.columns)
    df_principal = tratar_tipos_basicos(df_principal)
    df_principal.insert(0, "Empresa", unidade["empresa_padrao"])
    df_principal.insert(1, "Unidade_Codigo", unidade["codigo"])
    df_principal.insert(2, "Unidade_Descricao", unidade["descricao"])
    df_principal["Processo_Agrosys"] = processo
    df_principal["Data_Processamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("Processo:", processo)
    print("Linhas capturadas:", len(df_principal))
    return df_principal


def salvar_saidas(df_geral: pd.DataFrame):
    df_geral = df_geral.copy()
    df_geral.columns = make_unique_columns(df_geral.columns.tolist())
    df_geral = df_geral.drop_duplicates()

    if ARQUIVO_EXCEL_GERAL.exists():
        ARQUIVO_EXCEL_GERAL.unlink()
    if ARQUIVO_PARQUET_GERAL.exists():
        ARQUIVO_PARQUET_GERAL.unlink()
    if ARQUIVO_CSV_GERAL.exists():
        ARQUIVO_CSV_GERAL.unlink()

    df_geral.to_excel(ARQUIVO_EXCEL_GERAL, index=False)
    df_geral.to_parquet(ARQUIVO_PARQUET_GERAL, index=False)
    df_geral.to_csv(ARQUIVO_CSV_GERAL, index=False, sep=";", encoding="utf-8-sig")

    print("=" * 80)
    print("ARQUIVOS GERADOS")
    print("Excel conferência:", ARQUIVO_EXCEL_GERAL)
    print("Parquet Power BI:", ARQUIVO_PARQUET_GERAL)
    print("CSV conferência:", ARQUIVO_CSV_GERAL)
    print("Linhas totais:", len(df_geral))
    print("Colunas:", len(df_geral.columns))
    print("=" * 80)


def ler_argumentos():
    parser = argparse.ArgumentParser()
    parser.add_argument("--situacao", choices=["1", "2", "A"], default="A", help="1=Ativos, 2=Inativos, A=Ambos")
    parser.add_argument("--vendedor", default="", help="Código do vendedor. Vazio = todos.")
    parser.add_argument("--supervisor", default="", help="Código do supervisor. Vazio = todos.")
    return parser.parse_args()


def main():
    args = ler_argumentos()

    print("=" * 80)
    print("ROBÔ COMERCIAL - CADASTRO DE VENDEDORES")
    print("Unidades: Ave Nova, Real Alimentos, CD Januária, CD Ribeirão das Neves")
    print("Excel:", ARQUIVO_EXCEL_GERAL)
    print("Parquet:", ARQUIVO_PARQUET_GERAL)
    print("=" * 80)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()
    driver = criar_driver()

    bases = []
    total_erros = 0

    for unidade in UNIDADES:
        try:
            df_unidade = baixar_cadastro_vendedores(ag, driver, unidade, args)
            if df_unidade is not None and not df_unidade.empty:
                bases.append(df_unidade)
            else:
                print("AVISO: unidade sem linhas:", unidade["descricao"])
        except Exception as e:
            total_erros += 1
            print("AVISO: falha ao baixar/tratar cadastro de vendedores.")
            print("Unidade:", unidade["descricao"])
            print("Erro:", e)

    if not bases:
        raise Exception("Nenhuma unidade gerou dados válidos para Cadastro de Vendedores.")

    df_geral = pd.concat(bases, ignore_index=True)
    salvar_saidas(df_geral)

    print("=" * 80)
    print("CADASTRO DE VENDEDORES FINALIZADO")
    print("Unidades processadas com sucesso:", len(bases))
    print("Erros/avisos:", total_erros)
    print("=" * 80)
    try:
        driver.quit()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
        print("\n" + "=" * 80)
        print("PROCESSO FINALIZADO COM SUCESSO!")
        print("=" * 80)
    except Exception:
        print("\n" + "=" * 80)
        print("ERRO DURANTE A EXECUÇÃO")
        print("=" * 80)
        traceback.print_exc()
        sys.exit(1)
