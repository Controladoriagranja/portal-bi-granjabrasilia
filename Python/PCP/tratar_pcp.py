import os
import argparse
import re
import sys
import unicodedata
import pandas as pd
from datetime import time, datetime, timedelta

# =========================
# 1) CONFIG - suas pastas
# =========================
PASTA_DIARIO_INDUSTRIA = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Diario Industria"
PASTA_DIARIO_INDUSTRIA_TURNOS = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Diario Industria\AveNova Turno"
PASTA_MOVIMENTO_GERAL = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Movimento Geral"
PASTA_ESTOQUE_TRANSACAO = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Estoque por Transacao"
PASTA_RELATORIO_GERAL_CONDENACOES = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Relatorio Geral de Condenacoes"
PASTA_DEVOLUCAO_PCP = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Devolucao"
PASTA_DESPERDICIO = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Desperdicio"
PASTA_ESTOQUE_ONLINE = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Estoque Online"
PASTA_PLANO_PRODUCAO = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Plano de Producao"
PASTA_SAIDA = r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\PCP"
HORA_CORTE_TURNO_AVE_NOVA = "14:00:00"

os.makedirs(PASTA_SAIDA, exist_ok=True)

# =========================
# 2) DIAGNÓSTICO PYTHON
# =========================
print("=" * 80)
print("PYTHON EM USO:")
print(sys.executable)
print(sys.version)

try:
    import pyarrow
    print("PYARROW OK:", pyarrow.__version__)
except Exception as e:
    print("ERRO AO IMPORTAR PYARROW:", e)
print("=" * 80)

# =========================
# 3) ESTRUTURAS
# =========================
TERMOS_EXCLUIR_ESTRUTURA = [
    "RECEPÇÃO DE AVES VIVAS",
    "RECEPCAO DE AVES VIVAS",
    "COMPRA DE AVES VIVAS",
    "ABATE - TOTAL",
    "DADOS GERAIS DA PRODUÇÃO",
    "DADOS GERAIS DA PRODUCAO",
    "MES",
    "MÊS",
    "DIA",
    "UNIDADE",
    "REFERENCIA",
    "REFERÊNCIA",
    "DIAS PLANEJADOS",
    "PERIODO",
    "PERÍODO",
]

COLUNAS_PRODUCAO = [
    "Data", "Ano", "Mes", "Dia", "Empresa",
    "Código", "Descrição", "Quantidade"
]

COLUNAS_DADOS_GERAIS = [
    "Data", "Ano", "Mes", "Dia", "Empresa",
    "Código", "Descrição", "Quantidade"
]

COLUNAS_RESUMO_DIARIO = [
    "Data", "Ano", "Mes", "Dia", "Empresa",
    "Descrição", "Quantidade"
]

DESCRICOES_RESUMO_DIARIO = [
    "BASE PARA RENDIMENTO (KG)",
]

COLUNAS_BASE = [
    "Data", "Ano", "Mes", "Dia", "Empresa"
]

# Bases específicas do Diário da Indústria Ave Nova por turno.
# São mantidas SEPARADAS das bases gerais para não duplicar Ave Nova.
COLUNAS_PRODUCAO_TURNOS = [
    "Data", "Ano", "Mes", "Dia", "Empresa", "Turno",
    "Código", "Descrição", "Quantidade"
]

COLUNAS_DADOS_GERAIS_TURNOS = [
    "Data", "Ano", "Mes", "Dia", "Empresa", "Turno",
    "Código", "Descrição", "Quantidade"
]

COLUNAS_RESUMO_DIARIO_TURNOS = [
    "Data", "Ano", "Mes", "Dia", "Empresa", "Turno",
    "Descrição", "Quantidade"
]

COLUNAS_BASE_TURNOS = [
    "Data", "Ano", "Mes", "Dia", "Empresa", "Turno"
]

COLUNAS_RECEPCAO_COMPRA_TURNOS = COLUNAS_BASE_TURNOS + [
    "Cabeças",
    "Peso Vivo(-D+A)",
    "Peso Médio",
    "Cabeças - Mortos",
    "Qtde Aproveitada (Cab)",
    "Mortos Transporte (Cab)",
    "Mortos Transporte (% Cab)",
    "Mortos Transporte (Kg)",
    "Mortos Transporte (% Kg)",
    "Peso Real (Peso Vivo - Mortos Transporte)",
    "Condenação Total (Cab)",
    "Condenação Parcial (Cab)",
    "Peso Condenação(Descon Rendi)",
    "Peso Vivo para Rendimento",
    "Condenação Total (%) 1,00",
    "Condenação Parcial (%) 1,00",
    "Quilos Cond (Tot+Par)",
    "% Cond (Tot+Par Quilos)",
    "Número de Viagens",
    "Distância Média",
    "Tempo Médio Espera",
]

COLUNAS_ABATE_TURNOS = COLUNAS_BASE_TURNOS + [
    "Cabeças",
    "Peso Vivo(-D+A)",
    "Peso Médio",
    "Cabeças - Mortos",
    "Qtde Aproveitada (Cab)",
    "Mortos Transporte (Cab)",
    "Mortos Transporte (% Cab)",
    "Mortos Transporte (Kg)",
    "Mortos Transporte (% Kg)",
    "Peso Real (Peso Vivo - Mortos Transporte)",
    "Condenação Total (Cab)",
    "Condenação Parcial (Cab)",
    "Peso Condenação(Descon Rendi)",
    "Peso Vivo para Rendimento",
    "Condenação Total (%) 1,00",
    "Condenação Parcial (%) 1,00",
    "Quilos Cond (Tot+Par)",
    "% Cond (Tot+Par Quilos)",
    "Número de Viagens",
    "Distância Média",
    "Tempo Médio Espera",
    "Frete Transporte / Ton",
]

COLUNAS_RECEPCAO_COMPRA = COLUNAS_BASE + [
    "Cabeças",
    "Peso Vivo(-D+A)",
    "Peso Médio",
    "Cabeças - Mortos",
    "Qtde Aproveitada (Cab)",
    "Mortos Transporte (Cab)",
    "Mortos Transporte (% Cab)",
    "Mortos Transporte (Kg)",
    "Mortos Transporte (% Kg)",
    "Peso Real (Peso Vivo - Mortos Transporte)",
    "Condenação Total (Cab)",
    "Condenação Parcial (Cab)",
    "Peso Condenação(Descon Rendi)",
    "Peso Vivo para Rendimento",
    "Condenação Total (%) 1,00",
    "Condenação Parcial (%) 1,00",
    "Quilos Cond (Tot+Par)",
    "% Cond (Tot+Par Quilos)",
    "Número de Viagens",
    "Distância Média",
    "Tempo Médio Espera",
]

COLUNAS_ABATE = COLUNAS_BASE + [
    "Cabeças",
    "Peso Vivo(-D+A)",
    "Peso Médio",
    "Cabeças - Mortos",
    "Qtde Aproveitada (Cab)",
    "Mortos Transporte (Cab)",
    "Mortos Transporte (% Cab)",
    "Mortos Transporte (Kg)",
    "Mortos Transporte (% Kg)",
    "Peso Real (Peso Vivo - Mortos Transporte)",
    "Condenação Total (Cab)",
    "Condenação Parcial (Cab)",
    "Peso Condenação(Descon Rendi)",
    "Peso Vivo para Rendimento",
    "Condenação Total (%) 1,00",
    "Condenação Parcial (%) 1,00",
    "Quilos Cond (Tot+Par)",
    "% Cond (Tot+Par Quilos)",
    "Número de Viagens",
    "Distância Média",
    "Tempo Médio Espera",
    "Frete Transporte / Ton",
]

COLUNAS_ESTOQUE_TRANSACAO = [
    "Empresa",
    "Armazem",
    "Código",
    "Descrição",
    "Data",
    "Turno",
    "Peso Liquido(Mov)",
    "Volumes(Mov)",
    "Usuario",
    "Nota Fiscal",
    "Cliente",
    "Galpão",
    "Lote",
    "Observação",
    "Dt Sistema",
    "Hr Sistema",
    "Transação",
    "Descrição Produto",
]

COLUNAS_REL_GERAL_CONDENACOES = [
    "Empresa",
    "Data Abate",
    "Turno",
    "Granja",
    "Fornecedor",
    "Galpão",
    "Lote",
    "Técnico",
    "Região",
    "Tipo Ave",
    "Co-Produtor",
    "Cidade",
    "Código",
    "Condenação",
    "Tipo",
    "Ocorrência",
    "% Ocorrência",
    "Peso Total",
    "Peso Pesagem",
    "% Peso Total",
]

# =========================
# 3.1) MODO INCREMENTAL
# =========================
USAR_INCREMENTAL = True

# Cada pasta é comparada com seu(s) Parquet(s) tratado(s).
# Na primeira execução desta versão, se o Parquet ainda não possuir
# Arquivo_Origem, o tratamento daquela pasta é completo uma vez.
MAPA_SAIDAS_INCREMENTAIS = {
    os.path.normcase(os.path.normpath(PASTA_DIARIO_INDUSTRIA_TURNOS)): [
        "pcp_producao_diaria_turnos",
        "pcp_recepcao_turnos",
        "pcp_compra_turnos",
        "pcp_abate_turnos",
        "pcp_dados_gerais_turnos",
        "pcp_resumo_diario_turnos",
    ],
    os.path.normcase(os.path.normpath(PASTA_DIARIO_INDUSTRIA)): [
        "pcp_producao_diaria",
        "pcp_recepcao",
        "pcp_compra",
        "pcp_abate",
        "pcp_dados_gerais",
        "pcp_resumo_diario",
    ],
    os.path.normcase(os.path.normpath(PASTA_MOVIMENTO_GERAL)): [
        "pcp_efic_abate_base",
    ],
    os.path.normcase(os.path.normpath(PASTA_ESTOQUE_TRANSACAO)): [
        "pcp_estoque_transacao",
    ],
    os.path.normcase(os.path.normpath(PASTA_RELATORIO_GERAL_CONDENACOES)): [
        "pcp_rel_geral_condenacoes",
    ],
    os.path.normcase(os.path.normpath(PASTA_DEVOLUCAO_PCP)): [
        "pcp_devolucao",
    ],
    os.path.normcase(os.path.normpath(PASTA_ESTOQUE_ONLINE)): [
        "pcp_estoque_online",
    ],
    os.path.normcase(os.path.normpath(PASTA_DESPERDICIO)): [
        "pcp_desperdicio",
    ],
    os.path.normcase(os.path.normpath(PASTA_PLANO_PRODUCAO)): [
        "pcp_plano_producao",
    ],
}


def _parquet_saida(nome):
    return os.path.join(PASTA_SAIDA, f"{nome}.parquet")


def _parquet_tem_origem(caminho):
    if not os.path.exists(caminho):
        return False
    try:
        amostra = pd.read_parquet(caminho, columns=["Arquivo_Origem"])
        return "Arquivo_Origem" in amostra.columns
    except Exception:
        return False


def filtrar_arquivos_incrementais(pasta, arquivos):
    """
    Retorna apenas Excel novos/alterados para a pasta.

    Segurança:
    - --completo => todos;
    - se algum Parquet ainda não existe => todos;
    - se o Parquet antigo não possui Arquivo_Origem => todos uma vez;
    - depois disso, somente arquivos mais novos que os Parquets.
    """
    arquivos = list(arquivos)

    if not USAR_INCREMENTAL:
        return arquivos

    chave = os.path.normcase(os.path.normpath(pasta))
    saidas = MAPA_SAIDAS_INCREMENTAIS.get(chave)

    if not saidas:
        return arquivos

    caminhos = [_parquet_saida(nome) for nome in saidas]

    if any(not os.path.exists(c) for c in caminhos):
        print(
            f"[PCP] {os.path.basename(pasta)}: saída ainda não existe; "
            "tratamento completo desta pasta.",
            flush=True,
        )
        return arquivos

    # Uma saída principal com Arquivo_Origem é suficiente para saber
    # que a versão incremental já foi inicializada.
    if not _parquet_tem_origem(caminhos[0]):
        print(
            f"[PCP] {os.path.basename(pasta)}: Parquet antigo sem Arquivo_Origem; "
            "tratamento completo uma vez.",
            flush=True,
        )
        return arquivos

    corte = min(os.path.getmtime(c) for c in caminhos)

    pendentes = []
    for arq in arquivos:
        try:
            if os.path.getmtime(arq) > corte + 0.5:
                pendentes.append(arq)
        except OSError:
            pendentes.append(arq)

    print(
        f"[PCP] {os.path.basename(pasta)}: {len(arquivos)} arquivo(s) | "
        f"{len(pendentes)} novo(s)/alterado(s) | "
        f"{len(arquivos)-len(pendentes)} reaproveitado(s).",
        flush=True,
    )

    return pendentes


def adicionar_arquivo_origem(df, caminho_arquivo):
    if df is None:
        return df
    df = df.copy()
    df["Arquivo_Origem"] = os.path.basename(caminho_arquivo)
    return df


# =========================
# 4) FUNÇÕES UTILITÁRIAS
# =========================
def clean_col_name(c):
    if c is None:
        return ""
    c = str(c)
    c = c.replace("_x000d_", " ")
    c = c.replace("\n", " ")
    c = re.sub(r"\s+", " ", c).strip()
    return c

def remover_acentos(txt):
    if pd.isna(txt):
        return ""
    txt = str(txt)
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", txt)
        if not unicodedata.combining(ch)
    )

def normalizar_texto_base(txt):
    txt = clean_col_name(txt)
    txt = remover_acentos(txt)
    txt = str(txt).strip().upper()
    txt = re.sub(r"\s+", " ", txt)
    return txt

def unidade_para_empresa(valor_unidade):
    if pd.isna(valor_unidade):
        return "Não Identificada"

    txt = str(valor_unidade).strip()

    if txt == "10":
        return "Ave Nova"
    if txt == "111":
        return "Real Alimentos"

    return "Não Identificada"

def header_key(text):
    t = clean_col_name(text)
    t = remover_acentos(t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def normalize_text(series):
    s = series.astype(str).str.strip()
    s = s.replace({"nan": None, "None": None, "": None})
    return s

def force_all_object_to_string(df):
    df = df.copy()

    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()].copy()

    obj_cols = df.select_dtypes(include=["object", "string"]).columns

    for c in obj_cols:
        if c in df.columns:
            serie = df[c]
            if isinstance(serie, pd.Series):
                df[c] = normalize_text(serie)

    return df

def force_string_columns(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = normalize_text(df[c])
    return df

def to_numeric_ptbr(series):
    s = series.astype(str).str.strip()
    s = s.replace({"nan": None, "None": None, "": None, "-": None})

    def parse_one(x):
        if x is None or pd.isna(x):
            return None

        x = str(x).strip()
        if x == "":
            return None

        if "," in x:
            x = x.replace(".", "").replace(",", ".")
            try:
                return float(x)
            except Exception:
                return None

        if "." in x:
            try:
                return float(x)
            except Exception:
                return None

        try:
            return float(x)
        except Exception:
            return None

    return s.apply(parse_one)

def listar_arquivos_excel(pasta):
    arquivos = []
    if not os.path.exists(pasta):
        return arquivos

    for nome in os.listdir(pasta):
        if nome.lower().endswith(".xlsx") and not nome.startswith("~$"):
            arquivos.append(os.path.join(pasta, nome))

    arquivos = sorted(arquivos)
    return filtrar_arquivos_incrementais(pasta, arquivos)

def salvar_parquet(df, nome):
    caminho_parquet = os.path.join(PASTA_SAIDA, f"{nome}.parquet")
    caminho_csv = os.path.join(PASTA_SAIDA, f"{nome}.csv")

    try:
        import pyarrow as pa
        print(f"PYARROW disponível para {nome}: {pa.__version__}")

        df = df.copy()

        # -------------------------------------------------------------
        # MERGE INCREMENTAL
        # -------------------------------------------------------------
        if (
            USAR_INCREMENTAL
            and os.path.exists(caminho_parquet)
            and "Arquivo_Origem" in df.columns
        ):
            try:
                existente = pd.read_parquet(caminho_parquet)

                if "Arquivo_Origem" in existente.columns:
                    origens_novas = set(
                        df["Arquivo_Origem"]
                        .dropna()
                        .astype("string")
                        .astype(str)
                    )

                    if origens_novas:
                        existente = existente[
                            ~existente["Arquivo_Origem"]
                            .astype("string")
                            .isin(origens_novas)
                        ].copy()

                        df = pd.concat(
                            [existente, df],
                            ignore_index=True,
                            sort=False,
                        ).drop_duplicates()

                    elif df.empty:
                        df = existente

                elif df.empty:
                    df = existente

            except Exception as erro:
                print(
                    f"AVISO incremental {nome}: não consegui mesclar o histórico: {erro}"
                )

        elif (
            USAR_INCREMENTAL
            and os.path.exists(caminho_parquet)
            and df.empty
        ):
            # Nenhum Excel desta pasta mudou: preserva saída existente.
            print(
                f"[PCP] {nome}: sem alteração; Parquet existente preservado.",
                flush=True,
            )
            return

        # Garante nomes de colunas simples e sem duplicidade
        df.columns = limpar_nome_colunas([str(c) for c in df.columns])

        for col in df.columns:
            serie = df[col]

            if pd.api.types.is_datetime64_any_dtype(serie):
                df[col] = pd.to_datetime(serie, errors="coerce")
            elif pd.api.types.is_numeric_dtype(serie):
                df[col] = pd.to_numeric(serie, errors="coerce")
            else:
                df[col] = serie.astype(str)
                df[col] = df[col].replace(
                    {"<NA>": None, "nan": None, "None": None}
                )

        df.to_parquet(
            caminho_parquet,
            index=False,
            engine="pyarrow",
            compression=None,
        )

        df.to_csv(
            caminho_csv,
            index=False,
            sep=";",
            encoding="utf-8-sig",
        )

        print(f"OK: {nome} salvo em PARQUET e CSV com {len(df)} linhas")
        print(f"PARQUET: {caminho_parquet}")
        print(f"CSV: {caminho_csv}")

    except Exception as e:
        print(f"ERRO ao salvar {nome}: {e}")

def limpar_nome_colunas(colunas):
    novas = []
    usados = {}

    for i, col in enumerate(colunas):
        nome = "" if pd.isna(col) else str(col).strip()
        if nome == "":
            nome = f"coluna_{i}"

        if nome in usados:
            usados[nome] += 1
            nome = f"{nome}_{usados[nome]}"
        else:
            usados[nome] = 0

        novas.append(nome)

    return novas

def converter_valor(v):
    if pd.isna(v):
        return None

    if isinstance(v, time):
        return v.strftime("%H:%M:%S")

    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")

    return v

def limpar_texto(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()

    if texto.isdigit():
        return texto

    return texto

def preparar_dataframe(df, usar_primeira_linha_como_cabecalho=False):
    df = df.copy()
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")

    if df.empty:
        return df

    if usar_primeira_linha_como_cabecalho:
        cabecalho = df.iloc[0].tolist()
        df = df.iloc[1:].copy()
        df.columns = limpar_nome_colunas(cabecalho)
    else:
        df.columns = limpar_nome_colunas(df.columns)

    for col in df.columns:
        df[col] = df[col].apply(converter_valor)
        df[col] = df[col].apply(limpar_texto)

    df = df.reset_index(drop=True)
    return df

def criar_df_vazio(colunas):
    return pd.DataFrame(columns=colunas)

def garantir_colunas(df, colunas_esperadas):
    if df is None or df.empty:
        return pd.DataFrame(columns=colunas_esperadas)

    df = df.copy()

    for col in colunas_esperadas:
        if col not in df.columns:
            df[col] = pd.NA

    extras = [c for c in df.columns if c not in colunas_esperadas]
    df = df[colunas_esperadas + extras]

    return df

def fatiar_bloco(df, inicio, fim):
    if inicio is None:
        return pd.DataFrame()

    if fim is None:
        return df.iloc[inicio:].copy()

    return df.iloc[inicio:fim].copy()

def encontrar_colunas_dias(colunas):
    return [c for c in colunas if str(c).strip().isdigit()]

def montar_data(df_long, ano_ref, mes_ref):
    df_long["Dia"] = pd.to_numeric(df_long["Dia"], errors="coerce")
    df_long = df_long.dropna(subset=["Dia"]).copy()

    if df_long.empty:
        return df_long

    df_long["Dia"] = df_long["Dia"].astype(int)
    df_long["Mes"] = mes_ref
    df_long["Ano"] = ano_ref

    df_long["Data"] = pd.to_datetime(
        dict(
            year=df_long["Ano"],
            month=df_long["Mes"],
            day=df_long["Dia"]
        ),
        errors="coerce"
    )

    df_long = df_long.dropna(subset=["Data"]).copy()
    return df_long

def remover_estrutura(df, coluna_indicador):
    if df.empty:
        return df

    serie = df[coluna_indicador].fillna("").astype(str).str.upper().str.strip()
    excluir = [x.upper() for x in TERMOS_EXCLUIR_ESTRUTURA]
    return df.loc[~serie.isin(excluir)].copy()

# =========================
# 5) DIÁRIO INDÚSTRIA
# =========================
def extrair_info_nome_arquivo(caminho_arquivo):
    nome = os.path.basename(caminho_arquivo)
    nome_sem_ext = os.path.splitext(nome)[0]

    padrao = r"diario_industria_(.+)_(\d{2})-(\d{4})$"
    m = re.search(padrao, nome_sem_ext, flags=re.IGNORECASE)

    if not m:
        raise ValueError(
            f"Nome do arquivo fora do padrão esperado: {nome}\n"
            f"Use algo como: diario_industria_Real_03-2026.xlsx"
        )

    empresa = m.group(1).strip()
    mes = int(m.group(2))
    ano = int(m.group(3))

    return empresa, mes, ano

def identificar_blocos(df):
    inicio_producao = None
    inicio_recepcao = None
    inicio_compra = None
    inicio_abate = None
    inicio_indicadores = None

    for i, row in df.iterrows():
        texto = " ".join([str(x).lower() for x in row.values])

        if ("código" in texto or "codigo" in texto) and inicio_producao is None:
            inicio_producao = i

        if "recepção de aves vivas" in texto or "recepcao de aves vivas" in texto:
            inicio_recepcao = i

        if "compra de aves vivas" in texto:
            inicio_compra = i

        if "abate - total" in texto:
            inicio_abate = i

        if "dados gerais da produção" in texto or "dados gerais da producao" in texto:
            inicio_indicadores = i

    return inicio_producao, inicio_recepcao, inicio_compra, inicio_abate, inicio_indicadores

def encontrar_linha_cabecalho_producao(bloco, primeiras_linhas=15):
    limite = min(primeiras_linhas, len(bloco))

    for i in range(limite):
        linha = bloco.iloc[i].tolist()
        texto = " ".join("" if pd.isna(x) else str(x).lower() for x in linha)

        if ("código" in texto or "codigo" in texto) and "descr" in texto:
            return i

    return 0

def padronizar_indicador(nome):
    if pd.isna(nome):
        return nome

    original = str(nome).strip()
    n = normalizar_texto_base(original)
    n_sem_final = re.sub(r"\s+\d+$", "", n)

    mapa = {
        "CABECAS": "Cabeças",
        "PESO VIVO(-D+A)": "Peso Vivo(-D+A)",
        "PESO MEDIO": "Peso Médio",
        "CABECAS - MORTOS": "Cabeças - Mortos",
        "QTDE APROVEITADA (CAB)": "Qtde Aproveitada (Cab)",
        "MORTOS TRANSPORTE (CAB)": "Mortos Transporte (Cab)",
        "MORTOS TRANSPORTE (% CAB)": "Mortos Transporte (% Cab)",
        "MORTOS TRANSPORTE (KG)": "Mortos Transporte (Kg)",
        "MORTOS TRANSPORTE (% KG)": "Mortos Transporte (% Kg)",
        "PESO REAL (PESO VIVO - MORTOS TRANSPORTE)": "Peso Real (Peso Vivo - Mortos Transporte)",
        "CONDENACAO TOTAL (CAB)": "Condenação Total (Cab)",
        "CONDENACAO PARCIAL (CAB)": "Condenação Parcial (Cab)",
        # Mantém os dois layouts separados no parquet.
        # Relatórios antigos usam "Peso Condenação(Descon Rendi)".
        # Relatórios novos usam "Quilos Cond (Tot+Par)".
        # O Power BI decide qual usar, priorizando o campo novo e usando
        # o antigo somente como fallback.
        "PESO CONDENACAO(DESCON RENDI)": "Peso Condenação(Descon Rendi)",
        "PESO VIVO PARA RENDIMENTO": "Peso Vivo para Rendimento",
        "CONDENACAO TOTAL (%) 1,00": "Condenação Total (%) 1,00",
        "CONDENACAO PARCIAL (%) 1,00": "Condenação Parcial (%) 1,00",
        "QUILOS COND (TOT+PAR)": "Quilos Cond (Tot+Par)",
        "% COND (TOT+PAR QUILOS)": "% Cond (Tot+Par Quilos)",
        "NUMERO DE VIAGENS": "Número de Viagens",
        "DISTANCIA MEDIA": "Distância Média",
        "TEMPO MEDIO ESPERA": "Tempo Médio Espera",
        "FRETE TRANSPORTE / TON": "Frete Transporte / Ton",
    }

    if n in mapa:
        return mapa[n]

    if n_sem_final in mapa:
        return mapa[n_sem_final]

    return original



def consolidar_peso_condenacao_abate(df):
    """
    Mantém compatibilidade entre os layouts antigo e novo do Diário da Indústria.

    Regra: para o bloco ABATE - TOTAL, quando "Quilos Cond (Tot+Par)" tiver valor,
    ele passa a ser a referência canônica em "Peso Condenação(Descon Rendi)".
    Nos arquivos antigos, em que o campo novo não existe/está vazio, mantém o valor
    antigo. A coluna nova continua preservada no parquet para auditoria.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    col_antiga = "Peso Condenação(Descon Rendi)"
    col_nova = "Quilos Cond (Tot+Par)"

    if col_antiga not in df.columns:
        df[col_antiga] = pd.NA
    if col_nova not in df.columns:
        return df

    nova = df[col_nova].astype("string").str.strip()
    antiga = df[col_antiga].astype("string").str.strip()

    nova_valida = nova.notna() & ~nova.isin(["", "nan", "None", "<NA>", "-"])

    df.loc[nova_valida, col_antiga] = df.loc[nova_valida, col_nova]
    df.loc[~nova_valida, col_antiga] = antiga[~nova_valida]

    return df

def transformar_producao(bloco, empresa, mes_ref, ano_ref):
    if bloco is None or bloco.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    bloco = bloco.dropna(how="all").dropna(axis=1, how="all").copy()
    if bloco.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    idx_header = encontrar_linha_cabecalho_producao(bloco)
    bloco = bloco.iloc[idx_header:].copy()
    bloco = preparar_dataframe(bloco, usar_primeira_linha_como_cabecalho=True)

    if bloco.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    bloco.columns = [str(c).strip() for c in bloco.columns]

    if "Descricao" in bloco.columns and "Descrição" not in bloco.columns:
        bloco = bloco.rename(columns={"Descricao": "Descrição"})
    if "Codigo" in bloco.columns and "Código" not in bloco.columns:
        bloco = bloco.rename(columns={"Codigo": "Código"})

    if "Código" not in bloco.columns or "Descrição" not in bloco.columns:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    colunas_dias = encontrar_colunas_dias(bloco.columns)
    if not colunas_dias:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    bloco = bloco[["Código", "Descrição"] + colunas_dias].copy()

    bloco["Código"] = pd.to_numeric(bloco["Código"], errors="coerce")
    bloco["Descrição"] = bloco["Descrição"].apply(lambda x: None if pd.isna(x) else str(x).strip())

    bloco = bloco.dropna(subset=["Código", "Descrição"]).copy()
    if bloco.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    bloco["Código"] = bloco["Código"].astype(int)

    df_long = bloco.melt(
        id_vars=["Código", "Descrição"],
        value_vars=colunas_dias,
        var_name="Dia",
        value_name="Quantidade"
    )

    df_long = df_long.dropna(subset=["Quantidade"]).copy()
    df_long["Quantidade"] = pd.to_numeric(df_long["Quantidade"], errors="coerce")
    df_long = df_long.dropna(subset=["Quantidade"]).copy()

    if df_long.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    df_long = montar_data(df_long, ano_ref, mes_ref)
    if df_long.empty:
        return criar_df_vazio(COLUNAS_PRODUCAO)

    df_long["Empresa"] = empresa

    df_long = df_long[
        ["Data", "Ano", "Mes", "Dia", "Empresa", "Código", "Descrição", "Quantidade"]
    ].reset_index(drop=True)

    return garantir_colunas(df_long, COLUNAS_PRODUCAO)

def transformar_resumo_diario(bloco, empresa, mes_ref, ano_ref):
    if bloco is None or bloco.empty:
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    bloco = bloco.copy()
    bloco = bloco.dropna(how="all").dropna(axis=1, how="all")

    if bloco.empty:
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    idx_header = encontrar_linha_cabecalho_producao(bloco)
    bloco = bloco.iloc[idx_header:].copy()
    bloco = preparar_dataframe(bloco, usar_primeira_linha_como_cabecalho=True)

    if bloco.empty:
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    bloco.columns = [str(c).strip() for c in bloco.columns]

    if "Descricao" in bloco.columns and "Descrição" not in bloco.columns:
        bloco = bloco.rename(columns={"Descricao": "Descrição"})
    if "Codigo" in bloco.columns and "Código" not in bloco.columns:
        bloco = bloco.rename(columns={"Codigo": "Código"})

    if "Descrição" not in bloco.columns:
        bloco["Descrição"] = None

    if "Código" not in bloco.columns:
        bloco["Código"] = None

    colunas_dias = encontrar_colunas_dias(bloco.columns)
    if not colunas_dias:
        print(f"Resumo diário sem colunas de dias para empresa={empresa}, mês={mes_ref}, ano={ano_ref}")
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    bloco["Código"] = bloco["Código"].apply(lambda x: "" if pd.isna(x) else str(x).strip())
    bloco["Descrição"] = bloco["Descrição"].apply(lambda x: "" if pd.isna(x) else str(x).strip())

    bloco["TextoBusca"] = (bloco["Código"] + " " + bloco["Descrição"]).str.strip()

    def eh_base_para_rendimento(txt):
        if txt is None or pd.isna(txt):
            return False

        txt_norm = normalizar_texto_base(txt)

        return (
            "BASE PARA RENDIMENTO" in txt_norm
            or "BASE P RENDIMENTO" in txt_norm
        )

    bloco_resumo = bloco[bloco["TextoBusca"].apply(eh_base_para_rendimento)].copy()

    if bloco_resumo.empty:
        print(f"Resumo diário não encontrou BASE PARA RENDIMENTO para empresa={empresa}, mês={mes_ref}, ano={ano_ref}")
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    bloco_resumo["Descrição"] = "BASE PARA RENDIMENTO (KG)"

    df_long = bloco_resumo.melt(
        id_vars=["Descrição"],
        value_vars=colunas_dias,
        var_name="Dia",
        value_name="Quantidade"
    )

    df_long = df_long.dropna(subset=["Quantidade"]).copy()
    df_long["Quantidade"] = pd.to_numeric(df_long["Quantidade"], errors="coerce")
    df_long = df_long.dropna(subset=["Quantidade"]).copy()

    if df_long.empty:
        print(f"Resumo diário encontrou a linha, mas sem valores numéricos para empresa={empresa}, mês={mes_ref}, ano={ano_ref}")
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    df_long = montar_data(df_long, ano_ref, mes_ref)

    if df_long.empty:
        print(f"Resumo diário falhou ao montar datas para empresa={empresa}, mês={mes_ref}, ano={ano_ref}")
        return criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    df_long["Empresa"] = empresa

    df_long = df_long[
        ["Data", "Ano", "Mes", "Dia", "Empresa", "Descrição", "Quantidade"]
    ].reset_index(drop=True)

    return garantir_colunas(df_long, COLUNAS_RESUMO_DIARIO)

def transformar_dados_gerais(bloco, empresa, mes_ref, ano_ref):
    if bloco is None or bloco.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    bloco = bloco.dropna(how="all").dropna(axis=1, how="all").copy()
    if bloco.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    idx_header = encontrar_linha_cabecalho_producao(bloco)
    bloco = bloco.iloc[idx_header:].copy()
    bloco = preparar_dataframe(bloco, usar_primeira_linha_como_cabecalho=True)

    if bloco.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    bloco.columns = [str(c).strip() for c in bloco.columns]

    if "Descricao" in bloco.columns and "Descrição" not in bloco.columns:
        bloco = bloco.rename(columns={"Descricao": "Descrição"})
    if "Codigo" in bloco.columns and "Código" not in bloco.columns:
        bloco = bloco.rename(columns={"Codigo": "Código"})

    if "Código" not in bloco.columns or "Descrição" not in bloco.columns:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    colunas_dias = encontrar_colunas_dias(bloco.columns)
    if not colunas_dias:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    bloco = bloco[["Código", "Descrição"] + colunas_dias].copy()

    bloco["Código"] = pd.to_numeric(bloco["Código"], errors="coerce")
    bloco["Descrição"] = bloco["Descrição"].apply(lambda x: None if pd.isna(x) else str(x).strip())

    bloco = bloco.dropna(subset=["Código", "Descrição"]).copy()
    if bloco.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    bloco = bloco[
        ~bloco["Descrição"].str.contains("%", na=False)
    ].copy()

    bloco = bloco[bloco["Descrição"].str.strip() != ""].copy()

    if bloco.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    bloco["Código"] = bloco["Código"].astype(int)

    df_long = bloco.melt(
        id_vars=["Código", "Descrição"],
        value_vars=colunas_dias,
        var_name="Dia",
        value_name="Quantidade"
    )

    df_long = df_long.dropna(subset=["Quantidade"]).copy()
    df_long["Quantidade"] = pd.to_numeric(df_long["Quantidade"], errors="coerce")
    df_long = df_long.dropna(subset=["Quantidade"]).copy()

    if df_long.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    df_long = montar_data(df_long, ano_ref, mes_ref)
    if df_long.empty:
        return criar_df_vazio(COLUNAS_DADOS_GERAIS)

    df_long["Empresa"] = empresa

    df_long = df_long[
        ["Data", "Ano", "Mes", "Dia", "Empresa", "Código", "Descrição", "Quantidade"]
    ].reset_index(drop=True)

    return garantir_colunas(df_long, COLUNAS_DADOS_GERAIS)

def transformar_bloco_indicador(bloco, empresa, mes_ref, ano_ref, nome_coluna_indicador, colunas_esperadas):
    if bloco is None or bloco.empty:
        return criar_df_vazio(colunas_esperadas)

    bloco = bloco.copy()
    bloco = bloco.dropna(how="all").dropna(axis=1, how="all")
    if bloco.empty:
        return criar_df_vazio(colunas_esperadas)

    if len(bloco) < 2:
        return criar_df_vazio(colunas_esperadas)

    header_raw = bloco.iloc[0].tolist()
    dados = bloco.iloc[1:].copy().reset_index(drop=True)

    if dados.empty:
        return criar_df_vazio(colunas_esperadas)

    dados.columns = limpar_nome_colunas(header_raw)

    primeira_coluna = dados.columns[0]
    dados = dados.rename(columns={primeira_coluna: nome_coluna_indicador})

    for col in dados.columns:
        dados[col] = dados[col].apply(converter_valor)
        dados[col] = dados[col].apply(limpar_texto)

    colunas_dias = encontrar_colunas_dias(dados.columns)
    if not colunas_dias:
        return criar_df_vazio(colunas_esperadas)

    dados = dados[[nome_coluna_indicador] + colunas_dias].copy()

    dados = dados.dropna(subset=[nome_coluna_indicador]).copy()
    if dados.empty:
        return criar_df_vazio(colunas_esperadas)

    dados[nome_coluna_indicador] = dados[nome_coluna_indicador].astype(str).str.strip()
    dados = dados[dados[nome_coluna_indicador] != ""].copy()

    dados[nome_coluna_indicador] = dados[nome_coluna_indicador].apply(padronizar_indicador)

    dados = remover_estrutura(dados, nome_coluna_indicador)
    if dados.empty:
        return criar_df_vazio(colunas_esperadas)

    dados = dados[dados[colunas_dias].notna().any(axis=1)].copy()
    if dados.empty:
        return criar_df_vazio(colunas_esperadas)

    df_long = dados.melt(
        id_vars=[nome_coluna_indicador],
        value_vars=colunas_dias,
        var_name="Dia",
        value_name="Valor"
    )

    df_long = df_long.dropna(subset=["Valor"]).copy()
    df_long = df_long[df_long["Valor"].astype(str).str.strip() != ""].copy()

    if df_long.empty:
        return criar_df_vazio(colunas_esperadas)

    df_long["Valor"] = df_long["Valor"].astype(str).str.strip()

    df_long = montar_data(df_long, ano_ref, mes_ref)
    if df_long.empty:
        return criar_df_vazio(colunas_esperadas)

    df_long["Empresa"] = empresa

    df_wide = df_long.pivot_table(
        index=["Data", "Ano", "Mes", "Dia", "Empresa"],
        columns=nome_coluna_indicador,
        values="Valor",
        aggfunc="first"
    ).reset_index()

    df_wide.columns.name = None
    df_wide.columns = [str(c).strip() for c in df_wide.columns]

    return garantir_colunas(df_wide, colunas_esperadas)



# =========================
# 5.1) DIÁRIO INDÚSTRIA - AVE NOVA POR TURNO
# =========================
def extrair_info_nome_arquivo_turno(caminho_arquivo):
    """
    Padrão aceito:
      diario_industria_Avenova_turno1_06-2026.xlsx
      diario_industria_Avenova_turno2_06-2026.xlsx
    """
    nome = os.path.basename(caminho_arquivo)
    nome_sem_ext = os.path.splitext(nome)[0]

    m = re.search(
        r"diario_industria_(?:avenova|ave_nova|ave nova)_turno([12])_(\d{2})-(\d{4})$",
        nome_sem_ext,
        flags=re.IGNORECASE,
    )

    if not m:
        raise ValueError(
            f"Nome do arquivo de turno fora do padrão esperado: {nome}\\n"
            "Esperado: diario_industria_Avenova_turno1_06-2026.xlsx "
            "ou diario_industria_Avenova_turno2_06-2026.xlsx"
        )

    turno_num = int(m.group(1))
    mes = int(m.group(2))
    ano = int(m.group(3))

    return "Ave Nova", f"Turno {turno_num}", mes, ano


def adicionar_turno(df, turno, colunas_esperadas):
    df = garantir_colunas(df, [c for c in colunas_esperadas if c != "Turno"]).copy()
    df["Turno"] = turno
    return garantir_colunas(df, colunas_esperadas)


def processar_diario_industria_turnos():
    """
    Trata os arquivos Ave Nova Turno 1/2 em bases SEPARADAS.

    IMPORTANTE:
    Não adiciona os turnos nas tabelas pcp_producao_diaria/pcp_recepcao/etc.
    Isso evita duplicar Ave Nova, pois o Diário geral já contém o total da empresa.
    """
    arquivos = listar_arquivos_excel(PASTA_DIARIO_INDUSTRIA_TURNOS)

    print("\\nArquivos Diário Indústria Ave Nova por turno encontrados:")
    for arq in arquivos:
        print("-", os.path.basename(arq))

    if not arquivos:
        print(
            "[PCP] Ave Nova Turnos: nenhum Excel novo/alterado. "
            "As bases de turno existentes serão preservadas.",
            flush=True,
        )
        return

    lista_producao = []
    lista_recepcao = []
    lista_compra = []
    lista_abate = []
    lista_dados_gerais = []
    lista_resumo = []

    for arquivo in arquivos:
        print("\\n" + "=" * 70)
        print("Processando Ave Nova por turno:", os.path.basename(arquivo))

        try:
            empresa, turno, mes_ref, ano_ref = extrair_info_nome_arquivo_turno(arquivo)
        except Exception as e:
            print(f"AVISO: arquivo ignorado: {e}")
            continue

        print(
            f"Empresa: {empresa} | Turno: {turno} | "
            f"Mês: {mes_ref} | Ano: {ano_ref}"
        )

        try:
            df = pd.read_excel(arquivo, header=None)
        except Exception as e:
            print(f"ERRO ao abrir {os.path.basename(arquivo)}: {e}")
            continue

        (
            inicio_producao,
            inicio_recepcao,
            inicio_compra,
            inicio_abate,
            inicio_indicadores,
        ) = identificar_blocos(df)

        print("Blocos encontrados:")
        print("inicio_producao =", inicio_producao)
        print("inicio_recepcao =", inicio_recepcao)
        print("inicio_compra =", inicio_compra)
        print("inicio_abate =", inicio_abate)
        print("inicio_indicadores =", inicio_indicadores)

        # PRODUÇÃO
        try:
            bloco = fatiar_bloco(df, inicio_producao, inicio_recepcao)
            temp = transformar_producao(bloco, empresa, mes_ref, ano_ref)
            temp = adicionar_turno(temp, turno, COLUNAS_PRODUCAO_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_producao.append(temp)
            print(f"OK produção {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro produção {turno}: {e}")

        # RESUMO DIÁRIO
        try:
            bloco = fatiar_bloco(df, inicio_producao, inicio_recepcao)
            temp = transformar_resumo_diario(bloco, empresa, mes_ref, ano_ref)
            temp = adicionar_turno(temp, turno, COLUNAS_RESUMO_DIARIO_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_resumo.append(temp)
            print(f"OK resumo diário {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro resumo diário {turno}: {e}")

        # RECEPÇÃO
        try:
            fim_recepcao = inicio_compra if inicio_compra is not None else inicio_indicadores
            bloco = fatiar_bloco(df, inicio_recepcao, fim_recepcao)
            temp = transformar_bloco_indicador(
                bloco, empresa, mes_ref, ano_ref,
                "Recepção de Aves Vivas", COLUNAS_RECEPCAO_COMPRA
            )
            temp = adicionar_turno(temp, turno, COLUNAS_RECEPCAO_COMPRA_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_recepcao.append(temp)
            print(f"OK recepção {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro recepção {turno}: {e}")

        # COMPRA
        try:
            if inicio_compra is None:
                temp = criar_df_vazio(COLUNAS_RECEPCAO_COMPRA)
            else:
                fim_compra = inicio_abate if inicio_abate is not None else inicio_indicadores
                bloco = fatiar_bloco(df, inicio_compra, fim_compra)
                temp = transformar_bloco_indicador(
                    bloco, empresa, mes_ref, ano_ref,
                    "Compra de Aves Vivas", COLUNAS_RECEPCAO_COMPRA
                )
            temp = adicionar_turno(temp, turno, COLUNAS_RECEPCAO_COMPRA_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_compra.append(temp)
            print(f"OK compra {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro compra {turno}: {e}")

        # ABATE
        try:
            if inicio_abate is None:
                temp = criar_df_vazio(COLUNAS_ABATE)
            else:
                bloco = fatiar_bloco(df, inicio_abate, inicio_indicadores)
                temp = transformar_bloco_indicador(
                    bloco, empresa, mes_ref, ano_ref,
                    "Abate - Total", COLUNAS_ABATE
                )
            temp = adicionar_turno(temp, turno, COLUNAS_ABATE_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_abate.append(temp)
            print(f"OK abate {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro abate {turno}: {e}")

        # DADOS GERAIS
        try:
            bloco = fatiar_bloco(df, inicio_indicadores, None)
            temp = transformar_dados_gerais(bloco, empresa, mes_ref, ano_ref)
            temp = adicionar_turno(temp, turno, COLUNAS_DADOS_GERAIS_TURNOS)
            temp = adicionar_arquivo_origem(temp, arquivo)
            lista_dados_gerais.append(temp)
            print(f"OK dados gerais {turno}: {len(temp)} linhas")
        except Exception as e:
            print(f"Erro dados gerais {turno}: {e}")

    def juntar(lista, colunas):
        if lista:
            return force_all_object_to_string(
                garantir_colunas(pd.concat(lista, ignore_index=True, sort=False), colunas)
            )
        return criar_df_vazio(colunas)

    df_prod = juntar(lista_producao, COLUNAS_PRODUCAO_TURNOS)
    df_rec = juntar(lista_recepcao, COLUNAS_RECEPCAO_COMPRA_TURNOS)
    df_comp = juntar(lista_compra, COLUNAS_RECEPCAO_COMPRA_TURNOS)
    df_abate = juntar(lista_abate, COLUNAS_ABATE_TURNOS)
    df_dados = juntar(lista_dados_gerais, COLUNAS_DADOS_GERAIS_TURNOS)
    df_resumo = juntar(lista_resumo, COLUNAS_RESUMO_DIARIO_TURNOS)

    df_abate = consolidar_peso_condenacao_abate(df_abate)

    salvar_parquet(df_prod, "pcp_producao_diaria_turnos")
    salvar_parquet(df_rec, "pcp_recepcao_turnos")
    salvar_parquet(df_comp, "pcp_compra_turnos")
    salvar_parquet(df_abate, "pcp_abate_turnos")
    salvar_parquet(df_dados, "pcp_dados_gerais_turnos")
    salvar_parquet(df_resumo, "pcp_resumo_diario_turnos")

    print("\\n[PCP] Ave Nova por turno concluído:")
    print("Produção turnos:", len(df_prod))
    print("Recepção turnos:", len(df_rec))
    print("Compra turnos:", len(df_comp))
    print("Abate turnos:", len(df_abate))
    print("Dados Gerais turnos:", len(df_dados))
    print("Resumo Diário turnos:", len(df_resumo))


# =========================
# 6) MOVIMENTO GERAL / EFIC ABATE
# =========================
def normalizar_empresa_movimento(nome_arquivo):
    nome = os.path.basename(nome_arquivo).lower()

    if "avenova" in nome or "ave_nova" in nome or "ave nova" in nome:
        return "Ave Nova"

    if "real" in nome:
        return "Real Alimentos"

    return "Não Identificada"


def tipo_dia_abate(data_valor):
    if pd.isna(data_valor):
        return None

    data_valor = pd.to_datetime(data_valor, errors="coerce")
    if pd.isna(data_valor):
        return None

    if data_valor.weekday() == 5:
        return "Sábado"

    return "Seg a Sexta"


def hora_str_para_time(texto):
    h, m, s = texto.split(":")
    return time(int(h), int(m), int(s))


def converter_hora_para_time(valor):
    if pd.isna(valor):
        return None

    if isinstance(valor, time):
        return valor

    if isinstance(valor, datetime):
        return valor.time()

    if isinstance(valor, timedelta):
        total_seconds = int(valor.total_seconds())
        h = (total_seconds // 3600) % 24
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return time(h, m, s)

    texto = str(valor).strip()

    try:
        if "days" in texto:
            td = pd.to_timedelta(texto)
            total_seconds = int(td.total_seconds())
            h = (total_seconds // 3600) % 24
            m = (total_seconds % 3600) // 60
            s = total_seconds % 60
            return time(h, m, s)

        dt = pd.to_datetime(texto, errors="coerce")
        if pd.notna(dt):
            return dt.time()

        partes = texto.split(":")
        if len(partes) >= 2:
            h = int(float(partes[0]))
            m = int(float(partes[1]))
            s = int(float(partes[2])) if len(partes) >= 3 else 0
            return time(h, m, s)
    except Exception:
        return None

    return None


def time_para_texto(t):
    if t is None or pd.isna(t):
        return None
    return t.strftime("%H:%M:%S")


def calcular_diferenca_horas(hora_inicial, hora_final):
    if hora_inicial is None or hora_final is None:
        return None

    dt_base = datetime(2000, 1, 1)
    dt_ini = datetime.combine(dt_base.date(), hora_inicial)
    dt_fim = datetime.combine(dt_base.date(), hora_final)

    if dt_fim < dt_ini:
        dt_fim = dt_fim + timedelta(days=1)

    diferenca = dt_fim - dt_ini
    return diferenca.total_seconds() / 3600.0


def definir_turno_efic(empresa, data_abate, hora_tara):
    if empresa == "Real Alimentos":
        return "Total"

    tipo_dia = tipo_dia_abate(data_abate)
    if tipo_dia == "Sábado":
        return "Total"

    if hora_tara is None:
        return None

    hora_corte = hora_str_para_time(HORA_CORTE_TURNO_AVE_NOVA)

    if hora_tara < hora_corte:
        return "Turno 1"

    return "Turno 2"


def criar_parametros_efic_abate():
    # Parâmetros oficiais conforme planilha de Eficiência de Abate.
    # Ave Nova: 120.000 aves de Seg a Sexta = 61.000 no Turno 1
    # + 59.000 restantes no Turno 2. Sábado = Total 60.000.
    # Real Alimentos: apenas um turno (Total).
    return pd.DataFrame(
        [
            ["Ave Nova", "Seg a Sexta", "Turno 1", 61000, 10800],
            ["Ave Nova", "Seg a Sexta", "Turno 2", 59000, 9500],
            ["Ave Nova", "Sábado", "Total", 60000, 10800],
            ["Real Alimentos", "Seg a Sexta", "Total", 90000, 11500],
            ["Real Alimentos", "Sábado", "Total", 70000, 11500],
        ],
        columns=["Empresa", "TipoDia", "Turno", "MetaQtd", "Velocidade"],
    )


def criar_parametros_efic_abate_geral():
    return pd.DataFrame(
        [
            ["Ave Nova", 740, 0.95, 0.002, "06:00:00", 0.75, 1.00, 1.1667, 1.1667],
            ["Real Alimentos", 450, 0.95, 0.002, "06:00:00", 0.00, 0.00, 1.1667, 0.00],
        ],
        columns=[
            "Empresa",
            "PessoasMedias",
            "MetaEficienciaProdutiva",
            "MetaMortalidadeTransporte",
            "InicioAbate",
            "PausaTurno1",
            "PausaTurno2",
            "Almoco",
            "Janta",
        ],
    )


def criar_df_vazio_efic():
    return pd.DataFrame(
        columns=[
            "Dt.Tara", "Dt.Bruto", "Data Abate",
            "Hr.Tara_Texto", "Hr.Bruto_Texto",
            "Tempo_Abate_Horas", "Tempo_Abate_Min",
            "Pesagem", "NF.Saida", "Operação", "Placa", "Motorista",
            "Granja/Fornecedor", "Lote", "Silo", "Item", "Descrição Item",
            "Seq", "Refer", "Lacre", "Obs", "Usuario",
            "Peso Bruto", "Peso Tara", "Peso Liquido", "Captura",
            "Empresa", "Ano", "Mes", "Dia", "TipoDiaAbate", "TurnoEfic"
        ]
    )


def descobrir_aba_movimento(caminho_arquivo):
    xls = pd.ExcelFile(caminho_arquivo)
    abas = xls.sheet_names

    print(f"Abas disponíveis em {os.path.basename(caminho_arquivo)}: {abas}")

    abas_prioridade = ["Relatório", "Relatorio", "RELATÓRIO", "RELATORIO"]

    for aba in abas_prioridade:
        if aba in abas:
            return aba

    return abas[0] if abas else None


def tratar_arquivo_movimento_geral(caminho_arquivo):
    empresa = normalizar_empresa_movimento(caminho_arquivo)
    print(f"Processando movimento geral: {os.path.basename(caminho_arquivo)} | Empresa: {empresa}")

    aba = descobrir_aba_movimento(caminho_arquivo)
    if aba is None:
        print(f"Nenhuma aba encontrada em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_efic()

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=aba, header=7)
    except Exception as e:
        print(f"Erro ao ler arquivo {os.path.basename(caminho_arquivo)} na aba {aba}: {e}")
        return criar_df_vazio_efic()

    print(f"Aba usada: {aba}")
    print(f"Colunas encontradas no movimento geral: {list(df.columns)}")

    colunas_esperadas = [
        "Dt.Tara",
        "Dt.Bruto",
        "Data Abate",
        "Hr.Tara",
        "Hr.Bruto",
        "Time",
        "Pesagem",
        "NF.Saida",
        "Operação",
        "Placa",
        "Motorista",
        "Granja/Fornecedor",
        "Lote",
        "Silo",
        "Item",
        "Descrição Item",
        "Seq",
        "Refer",
        "Lacre",
        "Obs",
        "Usuario",
        "Peso Bruto",
        "Peso Tara",
        "Peso Liquido",
        "Captura",
    ]

    colunas_existentes = [c for c in colunas_esperadas if c in df.columns]
    print(f"Colunas aproveitadas: {colunas_existentes}")

    if not colunas_existentes:
        return criar_df_vazio_efic()

    df = df[colunas_existentes].copy()
    df = df.dropna(how="all").copy()

    if df.empty:
        return criar_df_vazio_efic()

    for col in ["Dt.Tara", "Dt.Bruto", "Data Abate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "Hr.Tara" in df.columns:
        df["Hr.Tara"] = df["Hr.Tara"].apply(converter_hora_para_time)

    if "Hr.Bruto" in df.columns:
        df["Hr.Bruto"] = df["Hr.Bruto"].apply(converter_hora_para_time)

    if "Time" in df.columns:
        def tratar_time_col(v):
            if pd.isna(v):
                return None

            if isinstance(v, timedelta):
                return v.total_seconds() / 3600.0

            texto = str(v).strip()

            try:
                td = pd.to_timedelta(texto)
                return td.total_seconds() / 3600.0
            except Exception:
                return None

        tempo_time = df["Time"].apply(tratar_time_col)
    else:
        tempo_time = pd.Series([None] * len(df), index=df.index, dtype="object")

    if "Hr.Tara" in df.columns and "Hr.Bruto" in df.columns:
        tempo_calc = df.apply(
            lambda r: calcular_diferenca_horas(r.get("Hr.Tara"), r.get("Hr.Bruto")),
            axis=1
        )
    else:
        tempo_calc = pd.Series([None] * len(df), index=df.index, dtype="object")

    df["Tempo_Abate_Horas"] = pd.to_numeric(tempo_time, errors="coerce")
    tempo_calc = pd.to_numeric(tempo_calc, errors="coerce")
    df["Tempo_Abate_Horas"] = df["Tempo_Abate_Horas"].fillna(tempo_calc)
    df["Tempo_Abate_Min"] = df["Tempo_Abate_Horas"] * 60

    df["Empresa"] = empresa

    if "Data Abate" in df.columns:
        df["Ano"] = df["Data Abate"].dt.year
        df["Mes"] = df["Data Abate"].dt.month
        df["Dia"] = df["Data Abate"].dt.day
        df["TipoDiaAbate"] = df["Data Abate"].apply(tipo_dia_abate)
    else:
        df["Ano"] = pd.NA
        df["Mes"] = pd.NA
        df["Dia"] = pd.NA
        df["TipoDiaAbate"] = pd.NA

    df["TurnoEfic"] = df.apply(
        lambda r: definir_turno_efic(r.get("Empresa"), r.get("Data Abate"), r.get("Hr.Tara")),
        axis=1
    )

    if "Hr.Tara" in df.columns:
        df["Hr.Tara_Texto"] = df["Hr.Tara"].apply(time_para_texto)

    if "Hr.Bruto" in df.columns:
        df["Hr.Bruto_Texto"] = df["Hr.Bruto"].apply(time_para_texto)

    for col in ["Peso Bruto", "Peso Tara", "Peso Liquido", "Pesagem", "Seq", "Item"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    colunas_texto = [
        "NF.Saida", "Operação", "Placa", "Motorista", "Granja/Fornecedor",
        "Lote", "Silo", "Descrição Item", "Refer", "Lacre", "Obs",
        "Usuario", "Captura", "Empresa", "TipoDiaAbate", "TurnoEfic",
        "Hr.Tara_Texto", "Hr.Bruto_Texto"
    ]
    for col in colunas_texto:
        if col in df.columns:
            df[col] = df[col].astype("string")

    df = df.drop(columns=["Hr.Tara", "Hr.Bruto", "Time"], errors="ignore")

    ordem_preferida = [
        "Dt.Tara", "Dt.Bruto", "Data Abate",
        "Hr.Tara_Texto", "Hr.Bruto_Texto",
        "Tempo_Abate_Horas", "Tempo_Abate_Min",
        "Pesagem", "NF.Saida", "Operação", "Placa", "Motorista",
        "Granja/Fornecedor", "Lote", "Silo", "Item", "Descrição Item",
        "Seq", "Refer", "Lacre", "Obs", "Usuario",
        "Peso Bruto", "Peso Tara", "Peso Liquido", "Captura",
        "Empresa", "Ano", "Mes", "Dia", "TipoDiaAbate", "TurnoEfic"
    ]

    ordem_existente = [c for c in ordem_preferida if c in df.columns]
    extras = [c for c in df.columns if c not in ordem_existente]
    df = df[ordem_existente + extras]

    print(f"Linhas finais do movimento geral: {len(df)}")
    return df.reset_index(drop=True)

# =========================
# 7) ESTOQUE POR TRANSACAO
# =========================
def normalizar_empresa_estoque(descricao_topo):
    if descricao_topo is None or pd.isna(descricao_topo):
        return "Não Identificada"

    txt = remover_acentos(str(descricao_topo)).strip().lower()

    if "ave nova" in txt or "avenova" in txt:
        return "Ave Nova"

    if "real alimentos" in txt or "real" in txt:
        return "Real Alimentos"

    return str(descricao_topo).strip()


def descobrir_aba_estoque_transacao(caminho_arquivo):
    xls = pd.ExcelFile(caminho_arquivo)
    abas = xls.sheet_names

    print(f"Abas disponíveis em {os.path.basename(caminho_arquivo)}: {abas}")

    abas_prioridade = ["Relatório", "Relatorio", "RELATÓRIO", "RELATORIO"]

    for aba in abas_prioridade:
        if aba in abas:
            return aba

    return abas[0] if abas else None


def extrair_info_topo_estoque(df):
    empresa_final = "Não Identificada"
    armazem_final = "Não Identificado"

    limite = min(len(df) - 1, 12)

    for i in range(limite):
        linha_titulos = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_valores = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i + 1].tolist()]

        linha_titulos_norm = [normalizar_texto_base(x) for x in linha_titulos]

        if "UNIDADE" in linha_titulos_norm and ("ARMAZEM" in linha_titulos_norm or "ARMAZÉM" in linha_titulos_norm):
            idx_unidade = None
            idx_armazem = None

            for j, titulo in enumerate(linha_titulos_norm):
                if titulo == "UNIDADE":
                    idx_unidade = j
                if titulo in ["ARMAZEM", "ARMAZÉM"]:
                    idx_armazem = j

            if idx_unidade is not None:
                for k in range(idx_unidade + 1, min(idx_unidade + 4, len(linha_titulos_norm))):
                    titulo_k = linha_titulos_norm[k]
                    valor_k = linha_valores[k].strip()

                    if titulo_k in ["DESCRICAO", "DESCRIÇÃO"] and valor_k != "":
                        empresa_final = valor_k
                        break

            if idx_armazem is not None and idx_armazem < len(linha_valores):
                valor_arm = linha_valores[idx_armazem].strip()
                if valor_arm != "":
                    armazem_final = valor_arm

            break

    return empresa_final, armazem_final


def _eh_cabecalho_estoque(linha):
    """Identifica o cabeçalho mesmo com pequenas variações do Agrosys."""
    valores = ["" if pd.isna(x) else str(x).strip() for x in linha.values]
    chaves = [header_key(x) for x in valores if str(x).strip() != ""]
    texto = " | ".join(chaves)

    tem_codigo = any(
        c in {"codigo", "codigo produto", "cod", "cod produto"}
        or c.startswith("codigo ")
        for c in chaves
    )
    tem_descricao = any(
        c in {"descricao", "descricao produto", "produto"}
        or c.startswith("descricao")
        for c in chaves
    )
    tem_transacao = any(
        c in {"transacao", "transacao num", "numero transacao", "num transacao"}
        or "transacao" in c
        for c in chaves
    )

    # Código + descrição são obrigatórios. Transação ajuda a evitar falso positivo,
    # mas alguns layouts não repetem a coluna em todos os blocos.
    return tem_codigo and tem_descricao and (tem_transacao or len(chaves) >= 5)


def _mapear_coluna_estoque(nome_coluna):
    """Converte nomes variados do relatório para o padrão usado no Power BI."""
    c = header_key(nome_coluna)

    if c in {"codigo", "codigo produto", "cod", "cod produto"} or c.startswith("codigo "):
        return "Código"
    if c in {"descricao", "descricao item"}:
        return "Descrição"
    if c == "data" or c.startswith("data movimento"):
        return "Data"
    if c == "turno":
        return "Turno"
    if "peso liquido" in c and "mov" in c:
        return "Peso Liquido(Mov)"
    if "volume" in c and "mov" in c:
        return "Volumes(Mov)"
    if c in {"usuario", "usuário"}:
        return "Usuario"
    if c in {"nota fiscal", "nf", "nf saida", "nota"}:
        return "Nota Fiscal"
    if c == "cliente" or c.startswith("cliente "):
        return "Cliente"
    if c in {"galpao", "galpão"}:
        return "Galpão"
    if c == "lote":
        return "Lote"
    if c in {"observacao", "obs", "observação"}:
        return "Observação"
    if c in {"dt sistema", "data sistema"}:
        return "Dt Sistema"
    if c in {"hr sistema", "hora sistema"}:
        return "Hr Sistema"
    if "transacao" in c:
        return "Transação"
    if c in {"descricao produto", "produto descricao", "desc produto"}:
        return "Descrição Produto"

    return nome_coluna


def _normalizar_transacao(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()
    if texto == "" or texto.lower() in {"nan", "none", "<na>"}:
        return None

    # Aceita 27, 27.0, 27,0 e textos que contenham apenas o número.
    texto = texto.replace(",", ".")
    try:
        numero = float(texto)
        if numero.is_integer():
            return str(int(numero))
    except Exception:
        pass

    m = re.search(r"\b(27|29|38)\b", texto)
    return m.group(1) if m else texto



def _extrair_transacao_contexto_linha(linha):
    """
    Procura o número da transação em linhas de título/seção do relatório.
    Ex.: 'Transação 29', 'Transacao: 29', '29 - ...'
    Retorna apenas transações usadas pelo PCP: 27, 29 ou 38.
    """
    if linha is None:
        return None

    try:
        valores = linha.values if hasattr(linha, "values") else linha
    except Exception:
        valores = linha

    textos = []
    for valor in valores:
        if pd.isna(valor):
            continue
        txt = str(valor).strip()
        if txt:
            textos.append(txt)

    if not textos:
        return None

    texto = normalizar_texto_base(" ".join(textos))

    # Preferência: linha explicitamente identificada como transação.
    if "TRANSACAO" in texto:
        m = re.search(r"\b(27|29|38)\b", texto)
        if m:
            return m.group(1)

    # Alguns layouts mostram apenas "29 - descrição da transação".
    m = re.match(r"^\s*(27|29|38)\b", texto)
    if m:
        return m.group(1)

    return None


def _buscar_transacao_contexto(df, indice_cabecalho, limite_anterior=12):
    """
    Busca a transação nas linhas imediatamente anteriores ao cabeçalho da tabela.
    Isso cobre relatórios em que a coluna Transação não é repetida dentro da tabela.
    """
    inicio = max(0, indice_cabecalho - limite_anterior)

    for k in range(indice_cabecalho - 1, inicio - 1, -1):
        trans = _extrair_transacao_contexto_linha(df.iloc[k])
        if trans:
            return trans

    return None


def tratar_arquivo_estoque_transacao(caminho_arquivo):
    nome_arquivo = os.path.basename(caminho_arquivo)
    print(f"\nProcessando estoque transação: {nome_arquivo}")

    try:
        aba = descobrir_aba_estoque_transacao(caminho_arquivo)
        if aba is None:
            print(f"AVISO: nenhuma aba encontrada em {nome_arquivo}")
            return pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)

        df = pd.read_excel(caminho_arquivo, sheet_name=aba, header=None, dtype=object)
    except Exception as e:
        print(f"ERRO ao abrir {nome_arquivo}: {type(e).__name__}: {e}")
        return pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)

    if df is None or df.empty:
        print(f"AVISO: arquivo vazio: {nome_arquivo}")
        return pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)

    try:
        empresa_topo_bruta, armazem_topo = extrair_info_topo_estoque(df)
    except Exception as e:
        print(f"AVISO: não foi possível ler o topo de {nome_arquivo}: {e}")
        empresa_topo_bruta, armazem_topo = "Não Identificada", "Não Identificado"

    empresa_topo = normalizar_empresa_estoque(empresa_topo_bruta)

    print(f"Empresa do topo bruta: {empresa_topo_bruta}")
    print(f"Empresa do topo padronizada: {empresa_topo}")
    print(f"Armazem do topo: {armazem_topo}")

    blocos = []
    cabecalhos_encontrados = 0
    linhas_com_codigo = 0
    linhas_transacoes_permitidas = 0
    transacoes_encontradas = set()
    transacoes_contexto_encontradas = set()

    total_linhas = len(df)
    i = 0

    while i < total_linhas:
        try:
            linha = df.iloc[i]

            if not _eh_cabecalho_estoque(linha):
                i += 1
                continue

            cabecalhos_encontrados += 1

            # NOVO:
            # Alguns arquivos do Agrosys têm uma tabela por transação e não
            # repetem a coluna "Transação" nas linhas. Nesses casos, capturamos
            # a transação no título imediatamente acima da tabela.
            transacao_contexto = _buscar_transacao_contexto(df, i)
            if transacao_contexto:
                transacoes_contexto_encontradas.add(transacao_contexto)
                print(
                    f"  Cabeçalho linha {i + 1}: transação de contexto "
                    f"{transacao_contexto}"
                )

            cabecalho = limpar_nome_colunas(linha.tolist())
            dados = []
            j = i + 1

            while j < total_linhas:
                linha_j = df.iloc[j]

                # Próximo cabeçalho = próxima tabela.
                if _eh_cabecalho_estoque(linha_j):
                    break

                valores_j = ["" if pd.isna(x) else str(x).strip() for x in linha_j.values]
                texto_j_norm = normalizar_texto_base(" ".join(valores_j))

                # Linhas de total encerram somente a tabela atual.
                # O laço externo continuará procurando as próximas tabelas,
                # inclusive as de Transação 29.
                if "TOTAL DIARIO" in texto_j_norm or "TOTAL GERAL" in texto_j_norm:
                    j += 1
                    break

                # Linhas que apenas anunciam uma nova transação não são dados.
                # Elas serão usadas como contexto do próximo cabeçalho.
                trans_linha = _extrair_transacao_contexto_linha(linha_j)
                if trans_linha and "TRANSACAO" in texto_j_norm:
                    break

                if not linha_j.isna().all():
                    dados.append(linha_j.tolist())

                j += 1

            # Garante avanço mesmo em bloco inesperado.
            proximo_i = max(j, i + 1)

            if not dados:
                i = proximo_i
                continue

            bloco = pd.DataFrame(dados, columns=cabecalho)
            bloco = bloco.dropna(how="all").dropna(axis=1, how="all")

            if bloco.empty:
                i = proximo_i
                continue

            # Padroniza e remove duplicidades causadas por cabeçalhos repetidos.
            mapa = {col: _mapear_coluna_estoque(col) for col in bloco.columns}
            bloco = bloco.rename(columns=mapa)
            bloco = bloco.loc[:, ~bloco.columns.duplicated()].copy()
            bloco = garantir_colunas(bloco, COLUNAS_ESTOQUE_TRANSACAO)

            bloco["Código"] = pd.to_numeric(bloco["Código"], errors="coerce")
            bloco = bloco.dropna(subset=["Código"]).copy()
            linhas_com_codigo += len(bloco)

            if bloco.empty:
                i = proximo_i
                continue

            bloco["Código"] = bloco["Código"].round().astype("Int64")

            # Normaliza a transação existente na linha.
            bloco["Transação"] = bloco["Transação"].apply(_normalizar_transacao)

            # Se a transação aparece apenas na primeira linha do bloco,
            # propaga para as demais.
            bloco["Transação"] = bloco["Transação"].ffill().bfill()

            # Se a tabela não possui a coluna preenchida, usa a transação do
            # título/seção encontrada acima do cabeçalho.
            if transacao_contexto:
                bloco["Transação"] = bloco["Transação"].fillna(transacao_contexto)

            transacoes_arquivo = (
                bloco["Transação"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )
            transacoes_encontradas.update(transacoes_arquivo)

            # Regra PCP mantida: entram 27, 29 e 38.
            bloco = bloco[bloco["Transação"].isin(["27", "29", "38"])].copy()
            linhas_transacoes_permitidas += len(bloco)

            if bloco.empty:
                i = proximo_i
                continue

            bloco["Empresa"] = empresa_topo
            bloco["Armazem"] = armazem_topo

            bloco["Data"] = pd.to_datetime(
                bloco["Data"], errors="coerce", dayfirst=True
            )
            bloco["Dt Sistema"] = pd.to_datetime(
                bloco["Dt Sistema"], errors="coerce", dayfirst=True
            )

            for col in ["Peso Liquido(Mov)", "Volumes(Mov)", "Turno"]:
                bloco[col] = to_numeric_ptbr(bloco[col])

            colunas_texto = [
                "Empresa", "Armazem", "Descrição", "Usuario", "Nota Fiscal",
                "Cliente", "Galpão", "Lote", "Observação", "Hr Sistema",
                "Transação", "Descrição Produto"
            ]
            bloco = force_string_columns(bloco, colunas_texto)
            bloco = bloco[COLUNAS_ESTOQUE_TRANSACAO].copy()
            blocos.append(bloco)

            i = proximo_i

        except Exception as e:
            # Um bloco ruim não interrompe o tratamento dos demais arquivos/blocos.
            print(
                f"AVISO: bloco iniciado na linha {i + 1} foi ignorado em "
                f"{nome_arquivo}: {type(e).__name__}: {e}"
            )
            i += 1

    if blocos:
        try:
            df_final = pd.concat(blocos, ignore_index=True)
            df_final = garantir_colunas(df_final, COLUNAS_ESTOQUE_TRANSACAO)
            df_final = df_final[COLUNAS_ESTOQUE_TRANSACAO].copy()

            print(
                f"OK estoque transação: {len(df_final)} linhas em {nome_arquivo} | "
                f"transações finais: "
                f"{sorted(df_final['Transação'].dropna().astype(str).unique().tolist())}"
            )

            # Diagnóstico específico para conferir o item 200.
            item_200 = df_final[
                pd.to_numeric(df_final["Código"], errors="coerce").eq(200)
            ].copy()

            if not item_200.empty:
                resumo_200 = (
                    item_200.groupby("Transação", dropna=False)
                    .size()
                    .to_dict()
                )
                print(
                    f"  DIAGNÓSTICO item 200: {len(item_200)} linha(s) | "
                    f"por transação: {resumo_200}"
                )

            return df_final

        except Exception as e:
            print(f"ERRO ao consolidar {nome_arquivo}: {type(e).__name__}: {e}")
            return pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)

    if cabecalhos_encontrados == 0:
        print(f"AVISO: nenhum cabeçalho de estoque foi reconhecido em {nome_arquivo}")
    elif linhas_com_codigo == 0:
        print(f"AVISO: cabeçalho encontrado, mas nenhuma linha com Código válido em {nome_arquivo}")
    elif linhas_transacoes_permitidas == 0:
        transacoes_txt = ", ".join(sorted(transacoes_encontradas)) if transacoes_encontradas else "nenhuma"
        contexto_txt = (
            ", ".join(sorted(transacoes_contexto_encontradas))
            if transacoes_contexto_encontradas
            else "nenhuma"
        )
        print(
            f"AVISO: há {linhas_com_codigo} linhas com código, mas nenhuma possui "
            f"Transação 27, 29 ou 38 em {nome_arquivo}. "
            f"Transações nas linhas: {transacoes_txt}. "
            f"Transações encontradas nos títulos: {contexto_txt}"
        )
    else:
        print(f"AVISO: nenhuma linha válida foi consolidada em {nome_arquivo}")

    return pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)

# =========================
# 8) RELATÓRIO GERAL DE CONDENAÇÕES
# =========================
def extrair_empresa_topo_condenacoes(df):
    empresa_final = "Não Identificada"

    limite = min(len(df) - 1, 12)

    for i in range(limite):
        linha_titulos = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_valores = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i + 1].tolist()]

        linha_titulos_norm = [normalizar_texto_base(x) for x in linha_titulos]

        if "UNIDADE" in linha_titulos_norm:
            idx_unidade = None

            for j, titulo in enumerate(linha_titulos_norm):
                if titulo == "UNIDADE":
                    idx_unidade = j
                    break

            if idx_unidade is not None:
                for k in range(idx_unidade + 1, min(idx_unidade + 4, len(linha_titulos_norm))):
                    titulo_k = linha_titulos_norm[k]
                    valor_k = linha_valores[k].strip()

                    if titulo_k in ["DESCRICAO", "DESCRIÇÃO"] and valor_k != "":
                        empresa_final = valor_k
                        return empresa_final

    return empresa_final


def criar_df_vazio_condenacoes():
    return pd.DataFrame(columns=COLUNAS_REL_GERAL_CONDENACOES)


def tratar_arquivo_relatorio_geral_condenacoes(caminho_arquivo):
    print(f"\nProcessando relatório geral de condenações: {os.path.basename(caminho_arquivo)}")

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, header=None)
    except Exception as e:
        print(f"Erro ao ler {os.path.basename(caminho_arquivo)}: {e}")
        return criar_df_vazio_condenacoes()

    empresa_topo = extrair_empresa_topo_condenacoes(df)
    print(f"Empresa do topo: {empresa_topo}")

    idx_header_1 = None
    for i in range(len(df)):
        if str(df.iloc[i, 0]).strip() == "Data Abate":
            idx_header_1 = i
            break

    if idx_header_1 is None:
        print(f"Não encontrei o cabeçalho principal em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_condenacoes()

    idx_header_2 = None
    for i in range(idx_header_1 + 1, len(df)):
        if str(df.iloc[i, 0]).strip() == "Data Abate":
            idx_header_2 = i
            break

    header = [clean_col_name(x) for x in df.iloc[idx_header_1].tolist()]

    blocos = []

    fim_bloco_1 = idx_header_2 if idx_header_2 is not None else len(df)
    bloco_1 = df.iloc[idx_header_1 + 1:fim_bloco_1].copy()
    if not bloco_1.empty:
        bloco_1.columns = header
        blocos.append(bloco_1)

    if idx_header_2 is not None:
        bloco_2 = df.iloc[idx_header_2 + 1:].copy()
        if not bloco_2.empty:
            bloco_2.columns = header
            blocos.append(bloco_2)

    if not blocos:
        return criar_df_vazio_condenacoes()

    final = pd.concat(blocos, ignore_index=True)
    final = final.dropna(how="all").copy()

    if "Data Abate" in final.columns:
        final = final[final["Data Abate"].astype(str).str.strip() != "Data Abate"].copy()

    if "Código" in final.columns:
        final["Código"] = pd.to_numeric(final["Código"], errors="coerce")

    final = final.dropna(subset=["Código"]).copy()

    codigos_permitidos = [410, 140, 440, 260, 280]
    final = final[final["Código"].isin(codigos_permitidos)].copy()

    if final.empty:
        return criar_df_vazio_condenacoes()

    if "Data Abate" in final.columns:
        final["Data Abate"] = pd.to_datetime(final["Data Abate"], errors="coerce")

    colunas_numericas = [
        "Turno", "Granja", "Galpão", "Lote", "Código",
        "Ocorrência", "% Ocorrência", "Peso Total", "Peso Pesagem", "% Peso Total"
    ]

    for col in colunas_numericas:
        if col in final.columns:
            final[col] = pd.to_numeric(final[col], errors="coerce")

    colunas_texto = [
        "Fornecedor", "Técnico", "Região", "Tipo Ave", "Co-Produtor",
        "Cidade", "Condenação", "Tipo"
    ]

    for col in colunas_texto:
        if col in final.columns:
            final[col] = final[col].astype("string")

    final["Empresa"] = empresa_topo

    final = garantir_colunas(final, COLUNAS_REL_GERAL_CONDENACOES)
    final = final[COLUNAS_REL_GERAL_CONDENACOES].copy()

    print(f"OK condenações: {len(final)} linhas em {os.path.basename(caminho_arquivo)}")
    return final


def processar_relatorio_geral_condenacoes():
    arquivos = listar_arquivos_excel(PASTA_RELATORIO_GERAL_CONDENACOES)

    if not arquivos:
        print("Nenhum arquivo encontrado em Relatorio Geral de Condenacoes.")
        return criar_df_vazio_condenacoes()

    lista = []

    for arq in arquivos:
        try:
            df_temp = tratar_arquivo_relatorio_geral_condenacoes(arq)
            if df_temp is not None and not df_temp.empty:
                df_temp = adicionar_arquivo_origem(df_temp, arq)
                lista.append(df_temp)
            else:
                print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
        except Exception as e:
            print(f"ERRO relatório geral de condenações em {os.path.basename(arq)}: {e}")

    if lista:
        return pd.concat(lista, ignore_index=True)

    return criar_df_vazio_condenacoes()


# =========================
# 9) DEVOLUÇÃO PCP
# =========================
def extrair_empresa_topo_devolucao(df):
    empresa_final = "Não Identificada"

    limite = min(len(df) - 1, 12)

    for i in range(limite):
        linha_titulos = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_valores = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i + 1].tolist()]

        linha_titulos_norm = [normalizar_texto_base(x) for x in linha_titulos]

        if "UNIDADE" in linha_titulos_norm:
            idx_unidade = None

            for j, titulo in enumerate(linha_titulos_norm):
                if titulo == "UNIDADE":
                    idx_unidade = j
                    break

            if idx_unidade is not None:
                for k in range(idx_unidade + 1, min(idx_unidade + 4, len(linha_titulos_norm))):
                    titulo_k = linha_titulos_norm[k]
                    valor_k = linha_valores[k].strip()

                    if titulo_k in ["DESCRICAO", "DESCRIÇÃO"] and valor_k != "":
                        empresa_final = valor_k
                        return empresa_final

    return empresa_final


def criar_df_vazio_devolucao_pcp():
    return pd.DataFrame()


def tratar_arquivo_devolucao_pcp(caminho_arquivo):
    print(f"\nProcessando devolução PCP: {os.path.basename(caminho_arquivo)}")

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, header=None)
    except Exception as e:
        print(f"Erro ao ler {os.path.basename(caminho_arquivo)}: {e}")
        return criar_df_vazio_devolucao_pcp()

    empresa_topo = extrair_empresa_topo_devolucao(df)
    print(f"Empresa do topo: {empresa_topo}")

    idx_header = None
    for i in range(len(df)):
        linha = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_norm = [normalizar_texto_base(x) for x in linha]

        if "DATA ENTRADA" in linha_norm and "PEDIDO" in linha_norm and "NOTA" in linha_norm:
            idx_header = i
            break

    if idx_header is None:
        print(f"Não encontrei o cabeçalho principal em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_devolucao_pcp()

    # Limpa e torna únicos os nomes das colunas.
    # Alguns arquivos do Agrosys repetem cabeçalhos como "Plano Mestre",
    # o que fazia o pd.concat falhar com InvalidIndexError.
    header = limpar_nome_colunas([clean_col_name(x) for x in df.iloc[idx_header].tolist()])
    dados = df.iloc[idx_header + 1:].copy()
    dados.columns = header
    dados = dados.dropna(how="all").copy()

    if "Data Entrada" not in dados.columns:
        print(f"Coluna 'Data Entrada' não encontrada em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_devolucao_pcp()

    dados["Data Entrada"] = pd.to_datetime(dados["Data Entrada"], errors="coerce", dayfirst=True)
    dados = dados[dados["Data Entrada"].notna()].copy()

    if dados.empty:
        return criar_df_vazio_devolucao_pcp()

    ren = {}
    for col in dados.columns:
        col_norm = normalizar_texto_base(col)

        if col_norm == "SERIE":
            ren[col] = "Série"
        elif col_norm == "VALOR NF":
            ren[col] = "Valor NF"

    if ren:
        dados = dados.rename(columns=ren)

    for col in ["Pedido", "Nota", "Valor NF", "Série"]:
        if col not in dados.columns:
            dados[col] = pd.NA

    dados["Valor NF"] = pd.to_numeric(dados["Valor NF"], errors="coerce")

    for col in ["Pedido", "Nota", "Série"]:
        dados[col] = dados[col].astype("string")

    dados["Empresa"] = empresa_topo

    colunas_finais = ["Empresa"] + [c for c in dados.columns if c != "Empresa"]
    dados = dados[colunas_finais].copy()

    print(f"OK devolução PCP: {len(dados)} linhas em {os.path.basename(caminho_arquivo)}")
    return dados


def processar_devolucao_pcp():
    arquivos = listar_arquivos_excel(PASTA_DEVOLUCAO_PCP)

    if not arquivos:
        print("Nenhum arquivo encontrado em Devolucao.")
        return criar_df_vazio_devolucao_pcp()

    lista = []

    for arq in arquivos:
        try:
            df_temp = tratar_arquivo_devolucao_pcp(arq)
            if df_temp is not None and not df_temp.empty:
                df_temp = adicionar_arquivo_origem(df_temp, arq)
                lista.append(df_temp)
            else:
                print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
        except Exception as e:
            print(f"ERRO devolução PCP em {os.path.basename(arq)}: {e}")

    if lista:
        return pd.concat(lista, ignore_index=True)

    return criar_df_vazio_devolucao_pcp()


# =========================
# 10) ESTOQUE ONLINE / DESPERDÍCIO / PLANO DE PRODUÇÃO
# =========================
def extrair_unidade_topo(df):
    unidade = None
    limite = min(len(df) - 1, 15)

    for i in range(limite):
        linha_titulos = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_valores = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i + 1].tolist()]
        linha_titulos_norm = [normalizar_texto_base(x) for x in linha_titulos]

        if "UNIDADE" in linha_titulos_norm:
            idx_unidade = None
            for j, titulo in enumerate(linha_titulos_norm):
                if titulo == "UNIDADE":
                    idx_unidade = j
                    break

            if idx_unidade is not None and idx_unidade < len(linha_valores):
                valor = linha_valores[idx_unidade].strip()
                if valor != "":
                    unidade = valor
                    break

    return unidade_para_empresa(unidade)


def criar_df_vazio_estoque_online():
    return pd.DataFrame()


def criar_df_vazio_desperdicio():
    return pd.DataFrame()


def criar_df_vazio_plano_producao():
    return pd.DataFrame()


def tratar_arquivo_estoque_online(caminho_arquivo):
    print(f"\nProcessando estoque online: {os.path.basename(caminho_arquivo)}")

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, header=None)
    except Exception as e:
        print(f"Erro ao ler {os.path.basename(caminho_arquivo)}: {e}")
        return criar_df_vazio_estoque_online()

    empresa_topo = extrair_unidade_topo(df)
    print(f"Empresa do topo: {empresa_topo}")

    idx_header = None
    for i in range(len(df)):
        linha = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_norm = [normalizar_texto_base(x) for x in linha]

        if "CODIGO" in linha_norm and "DESCRICAO PRODUTO" in linha_norm:
            idx_header = i
            break

    if idx_header is None:
        print(f"Não encontrei o cabeçalho principal em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_estoque_online()

    header = [clean_col_name(x) for x in df.iloc[idx_header].tolist()]
    dados = df.iloc[idx_header + 1:].copy()
    dados.columns = header
    dados = dados.dropna(how="all").copy()

    if "Código" not in dados.columns:
        for c in dados.columns:
            if normalizar_texto_base(c) == "CODIGO":
                dados = dados.rename(columns={c: "Código"})
                break

    if "Código" not in dados.columns:
        return criar_df_vazio_estoque_online()

    dados["Código"] = pd.to_numeric(dados["Código"], errors="coerce")
    dados = dados[dados["Código"].notna()].copy()

    if dados.empty:
        return criar_df_vazio_estoque_online()

    dados["Código"] = dados["Código"].astype(int)
    dados["Empresa"] = empresa_topo

    colunas_finais = ["Empresa"] + [c for c in dados.columns if c != "Empresa"]
    dados = dados[colunas_finais].copy()

    print(f"OK estoque online: {len(dados)} linhas em {os.path.basename(caminho_arquivo)}")
    return dados


def processar_estoque_online():
    arquivos = listar_arquivos_excel(PASTA_ESTOQUE_ONLINE)

    if not arquivos:
        print("Nenhum arquivo encontrado em Estoque Online.")
        return criar_df_vazio_estoque_online()

    lista = []
    for arq in arquivos:
        try:
            df_temp = tratar_arquivo_estoque_online(arq)
            if df_temp is not None and not df_temp.empty:
                df_temp = adicionar_arquivo_origem(df_temp, arq)
                lista.append(df_temp)
            else:
                print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
        except Exception as e:
            print(f"ERRO estoque online em {os.path.basename(arq)}: {e}")

    if lista:
        return pd.concat(lista, ignore_index=True)

    return criar_df_vazio_estoque_online()


def tratar_arquivo_desperdicio(caminho_arquivo):
    print(f"\nProcessando desperdício: {os.path.basename(caminho_arquivo)}")

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, header=None)
    except Exception as e:
        print(f"Erro ao ler {os.path.basename(caminho_arquivo)}: {e}")
        return criar_df_vazio_desperdicio()

    empresa_topo = extrair_unidade_topo(df)
    print(f"Empresa do topo: {empresa_topo}")

    idx_header = None
    for i in range(len(df)):
        linha = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_norm = [normalizar_texto_base(x) for x in linha]

        if "ITEM" in linha_norm and "DESCRICAO" in linha_norm and "UN" in linha_norm:
            idx_header = i
            break

    if idx_header is None:
        print(f"Não encontrei o cabeçalho principal em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_desperdicio()

    header = [clean_col_name(x) for x in df.iloc[idx_header].tolist()]
    dados = df.iloc[idx_header + 1:].copy()
    dados.columns = header
    dados = dados.dropna(how="all").copy()

    if "Item" not in dados.columns:
        for c in dados.columns:
            if normalizar_texto_base(c) == "ITEM":
                dados = dados.rename(columns={c: "Item"})
                break

    if "Item" not in dados.columns:
        return criar_df_vazio_desperdicio()

    dados["Item"] = pd.to_numeric(dados["Item"], errors="coerce")
    dados = dados[dados["Item"].notna()].copy()

    if dados.empty:
        return criar_df_vazio_desperdicio()

    dados["Item"] = dados["Item"].astype(int)
    dados["Empresa"] = empresa_topo

    colunas_finais = ["Empresa"] + [c for c in dados.columns if c != "Empresa"]
    dados = dados[colunas_finais].copy()

    print(f"OK desperdício: {len(dados)} linhas em {os.path.basename(caminho_arquivo)}")
    return dados


def processar_desperdicio():
    arquivos = listar_arquivos_excel(PASTA_DESPERDICIO)

    if not arquivos:
        print("Nenhum arquivo encontrado em Desperdicio.")
        return criar_df_vazio_desperdicio()

    lista = []
    for arq in arquivos:
        try:
            df_temp = tratar_arquivo_desperdicio(arq)
            if df_temp is not None and not df_temp.empty:
                df_temp = adicionar_arquivo_origem(df_temp, arq)
                lista.append(df_temp)
            else:
                print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
        except Exception as e:
            print(f"ERRO desperdício em {os.path.basename(arq)}: {e}")

    if lista:
        return pd.concat(lista, ignore_index=True)

    return criar_df_vazio_desperdicio()


def tratar_arquivo_plano_producao(caminho_arquivo):
    print(f"\nProcessando plano de produção: {os.path.basename(caminho_arquivo)}")

    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, header=None)
    except Exception as e:
        print(f"Erro ao ler {os.path.basename(caminho_arquivo)}: {e}")
        return criar_df_vazio_plano_producao()

    empresa_topo = extrair_unidade_topo(df)
    print(f"Empresa do topo: {empresa_topo}")

    idx_header = None
    for i in range(len(df)):
        linha = ["" if pd.isna(x) else str(x).strip() for x in df.iloc[i].tolist()]
        linha_norm = [normalizar_texto_base(x) for x in linha]

        if "PLANO PRODUCAO (PRODUTO)" in linha_norm or (
            "PLANO MESTRE" in linha_norm and "PLANO AJUSTADO" in linha_norm
        ):
            idx_header = i
            break

    if idx_header is None:
        print(f"Não encontrei o cabeçalho principal em {os.path.basename(caminho_arquivo)}")
        return criar_df_vazio_plano_producao()

    header = [clean_col_name(x) for x in df.iloc[idx_header].tolist()]
    dados = df.iloc[idx_header + 1:].copy()
    dados.columns = header
    dados = dados.dropna(how="all").copy()

    col_produto = None
    for c in dados.columns:
        if normalizar_texto_base(c) == "PLANO PRODUCAO (PRODUTO)":
            col_produto = c
            break

    if col_produto is None:
        return criar_df_vazio_plano_producao()

    dados[col_produto] = dados[col_produto].astype(str).str.strip()
    dados = dados[dados[col_produto] != ""].copy()
    dados = dados[~dados[col_produto].str.upper().eq("TOTAL")].copy()

    if dados.empty:
        return criar_df_vazio_plano_producao()

    dados["Empresa"] = empresa_topo

    colunas_finais = ["Empresa"] + [c for c in dados.columns if c != "Empresa"]
    dados = dados[colunas_finais].copy()

    print(f"OK plano produção: {len(dados)} linhas em {os.path.basename(caminho_arquivo)}")
    return dados


def processar_plano_producao():
    arquivos = listar_arquivos_excel(PASTA_PLANO_PRODUCAO)

    if not arquivos:
        print("Nenhum arquivo encontrado em Plano de Producao.")
        return criar_df_vazio_plano_producao()

    lista = []
    for arq in arquivos:
        try:
            df_temp = tratar_arquivo_plano_producao(arq)
            if df_temp is not None and not df_temp.empty:
                df_temp = adicionar_arquivo_origem(df_temp, arq)
                lista.append(df_temp)
            else:
                print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
        except Exception as e:
            print(f"ERRO plano de produção em {os.path.basename(arq)}: {e}")

    if lista:
        lista_corrigida = []

        for posicao, df_item in enumerate(lista, start=1):
            df_item = df_item.copy()

            # Proteção extra: garante índice de colunas único antes do concat.
            if df_item.columns.duplicated().any():
                duplicadas = list(df_item.columns[df_item.columns.duplicated()])
                print(
                    f"AVISO plano de produção: DataFrame {posicao} possuía "
                    f"colunas duplicadas: {duplicadas}. Renomeando automaticamente."
                )
                df_item.columns = limpar_nome_colunas(list(df_item.columns))

            lista_corrigida.append(df_item)

        try:
            return pd.concat(lista_corrigida, ignore_index=True, sort=False)
        except Exception as e:
            print(f"ERRO ao consolidar plano de produção: {e}")
            print("Tentando consolidar após padronizar todas as colunas...")

            todas_colunas = []
            for df_item in lista_corrigida:
                for coluna in df_item.columns:
                    if coluna not in todas_colunas:
                        todas_colunas.append(coluna)

            lista_padronizada = []
            for df_item in lista_corrigida:
                df_item = df_item.reindex(columns=todas_colunas)
                lista_padronizada.append(df_item)

            return pd.concat(lista_padronizada, ignore_index=True, sort=False)

    return criar_df_vazio_plano_producao()

# =========================
# 10.1) DIAGNÓSTICO
# =========================
def normalizar_nome_coluna(txt):
    if pd.isna(txt):
        return ""

    txt = str(txt).strip().upper()
    txt = remover_acentos(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def comparar_colunas(nome_tabela, df, colunas_esperadas):
    cols_df = list(df.columns)
    norm_df = {normalizar_nome_coluna(c): c for c in cols_df}
    norm_esp = {normalizar_nome_coluna(c): c for c in colunas_esperadas}

    faltando = []

    print(f"\n--- DIAGNÓSTICO: {nome_tabela} ---")
    print("Colunas encontradas no DataFrame:")
    for c in cols_df:
        print(" -", c)

    for chave_norm, nome_original in norm_esp.items():
        if chave_norm not in norm_df:
            faltando.append(nome_original)

    if faltando:
        print("Colunas esperadas que NÃO foram encontradas:")
        for c in faltando:
            print(" -", c)
    else:
        print("Todas as colunas esperadas foram encontradas.")

    return faltando

# =========================
# 11) ARGUMENTOS / RUN FINAL
# =========================
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-pausa", action="store_true")
    parser.add_argument(
        "--completo",
        action="store_true",
        help="Relê todos os Excel e reconstrói todas as bases PCP.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    USAR_INCREMENTAL = not args.completo

    print(
        "[PCP] Modo de tratamento:",
        "INCREMENTAL - somente arquivos novos/alterados"
        if USAR_INCREMENTAL
        else "COMPLETO - todos os arquivos",
        flush=True,
    )

    arquivos_excel = listar_arquivos_excel(PASTA_DIARIO_INDUSTRIA)

    if not arquivos_excel:
        if USAR_INCREMENTAL:
            print(
                "[PCP] Diário Indústria: nenhum Excel novo/alterado. "
                "As bases existentes serão preservadas.",
                flush=True,
            )
        else:
            raise FileNotFoundError(
                f"Nenhum arquivo .xlsx encontrado em: {PASTA_DIARIO_INDUSTRIA}"
            )

    print("Arquivos encontrados para processar agora:")
    for arq in arquivos_excel:
        print("-", os.path.basename(arq))

    lista_producao = []
    lista_recepcao = []
    lista_compra = []
    lista_abate = []
    lista_dados_gerais = []
    lista_resumo_diario = []

    for arquivo in arquivos_excel:
        print("\n" + "=" * 70)
        print("Processando:", os.path.basename(arquivo))

        empresa, mes_ref, ano_ref = extrair_info_nome_arquivo(arquivo)
        print(f"Empresa: {empresa} | Mês: {mes_ref} | Ano: {ano_ref}")

        df = pd.read_excel(arquivo, header=None)

        inicio_producao, inicio_recepcao, inicio_compra, inicio_abate, inicio_indicadores = identificar_blocos(df)

        print("Blocos encontrados:")
        print("inicio_producao =", inicio_producao)
        print("inicio_recepcao =", inicio_recepcao)
        print("inicio_compra =", inicio_compra)
        print("inicio_abate =", inicio_abate)
        print("inicio_indicadores =", inicio_indicadores)

        try:
            bloco_producao = fatiar_bloco(df, inicio_producao, inicio_recepcao)
            df_producao = transformar_producao(bloco_producao, empresa, mes_ref, ano_ref)
            df_producao = adicionar_arquivo_origem(df_producao, arquivo)
            lista_producao.append(df_producao)
            print(f"OK produção: {len(df_producao)} linhas")
        except Exception as e:
            print(f"Erro produção em {os.path.basename(arquivo)}: {e}")
            lista_producao.append(criar_df_vazio(COLUNAS_PRODUCAO))

        try:
            bloco_producao = fatiar_bloco(df, inicio_producao, inicio_recepcao)
            df_resumo_diario = transformar_resumo_diario(bloco_producao, empresa, mes_ref, ano_ref)
            df_resumo_diario = adicionar_arquivo_origem(df_resumo_diario, arquivo)
            lista_resumo_diario.append(df_resumo_diario)
            print(f"OK resumo diário: {len(df_resumo_diario)} linhas")
        except Exception as e:
            print(f"Erro resumo diário em {os.path.basename(arquivo)}: {e}")
            lista_resumo_diario.append(criar_df_vazio(COLUNAS_RESUMO_DIARIO))

        try:
            fim_recepcao = inicio_compra if inicio_compra is not None else inicio_indicadores
            bloco_recepcao = fatiar_bloco(df, inicio_recepcao, fim_recepcao)

            df_recepcao = transformar_bloco_indicador(
                bloco_recepcao,
                empresa,
                mes_ref,
                ano_ref,
                "Recepção de Aves Vivas",
                COLUNAS_RECEPCAO_COMPRA
            )

            df_recepcao = adicionar_arquivo_origem(df_recepcao, arquivo)
            lista_recepcao.append(df_recepcao)
            print(f"OK recepção: {len(df_recepcao)} linhas")
        except Exception as e:
            print(f"Erro recepção em {os.path.basename(arquivo)}: {e}")
            lista_recepcao.append(criar_df_vazio(COLUNAS_RECEPCAO_COMPRA))

        try:
            if inicio_compra is None:
                df_compra = criar_df_vazio(COLUNAS_RECEPCAO_COMPRA)
            else:
                fim_compra = inicio_abate if inicio_abate is not None else inicio_indicadores
                bloco_compra = fatiar_bloco(df, inicio_compra, fim_compra)

                df_compra = transformar_bloco_indicador(
                    bloco_compra,
                    empresa,
                    mes_ref,
                    ano_ref,
                    "Compra de Aves Vivas",
                    COLUNAS_RECEPCAO_COMPRA
                )

            df_compra = adicionar_arquivo_origem(df_compra, arquivo)
            lista_compra.append(df_compra)
            print(f"OK compra: {len(df_compra)} linhas")
        except Exception as e:
            print(f"Erro compra em {os.path.basename(arquivo)}: {e}")
            lista_compra.append(criar_df_vazio(COLUNAS_RECEPCAO_COMPRA))

        try:
            if inicio_abate is None:
                df_abate = criar_df_vazio(COLUNAS_ABATE)
            else:
                bloco_abate = fatiar_bloco(df, inicio_abate, inicio_indicadores)

                df_abate = transformar_bloco_indicador(
                    bloco_abate,
                    empresa,
                    mes_ref,
                    ano_ref,
                    "Abate - Total",
                    COLUNAS_ABATE
                )

            df_abate = adicionar_arquivo_origem(df_abate, arquivo)
            lista_abate.append(df_abate)
            print(f"OK abate: {len(df_abate)} linhas")
        except Exception as e:
            print(f"Erro abate em {os.path.basename(arquivo)}: {e}")
            lista_abate.append(criar_df_vazio(COLUNAS_ABATE))

        try:
            bloco_dados_gerais = fatiar_bloco(df, inicio_indicadores, None)

            df_dados_gerais = transformar_dados_gerais(
                bloco_dados_gerais,
                empresa,
                mes_ref,
                ano_ref
            )

            df_dados_gerais = adicionar_arquivo_origem(df_dados_gerais, arquivo)
            lista_dados_gerais.append(df_dados_gerais)
            print(f"OK dados gerais: {len(df_dados_gerais)} linhas")
        except Exception as e:
            print(f"Erro dados gerais em {os.path.basename(arquivo)}: {e}")
            lista_dados_gerais.append(criar_df_vazio(COLUNAS_DADOS_GERAIS))

    df_final_producao = pd.concat(lista_producao, ignore_index=True) if lista_producao else criar_df_vazio(COLUNAS_PRODUCAO)
    df_final_recepcao = pd.concat(lista_recepcao, ignore_index=True) if lista_recepcao else criar_df_vazio(COLUNAS_RECEPCAO_COMPRA)
    df_final_compra = pd.concat(lista_compra, ignore_index=True) if lista_compra else criar_df_vazio(COLUNAS_RECEPCAO_COMPRA)
    df_final_abate = pd.concat(lista_abate, ignore_index=True) if lista_abate else criar_df_vazio(COLUNAS_ABATE)

    # No indicador de condenação, o benchmark usa o bloco ABATE - TOTAL.
    # Em layouts novos, prioriza "Quilos Cond (Tot+Par)"; em antigos, mantém
    # "Peso Condenação(Descon Rendi)" como fallback.
    df_final_abate = consolidar_peso_condenacao_abate(df_final_abate)
    df_final_dados_gerais = pd.concat(lista_dados_gerais, ignore_index=True) if lista_dados_gerais else criar_df_vazio(COLUNAS_DADOS_GERAIS)
    df_final_resumo_diario = pd.concat(lista_resumo_diario, ignore_index=True) if lista_resumo_diario else criar_df_vazio(COLUNAS_RESUMO_DIARIO)

    df_final_producao = force_all_object_to_string(garantir_colunas(df_final_producao, COLUNAS_PRODUCAO))
    df_final_recepcao = force_all_object_to_string(garantir_colunas(df_final_recepcao, COLUNAS_RECEPCAO_COMPRA))
    df_final_compra = force_all_object_to_string(garantir_colunas(df_final_compra, COLUNAS_RECEPCAO_COMPRA))
    df_final_abate = force_all_object_to_string(garantir_colunas(df_final_abate, COLUNAS_ABATE))
    df_final_dados_gerais = force_all_object_to_string(garantir_colunas(df_final_dados_gerais, COLUNAS_DADOS_GERAIS))
    df_final_resumo_diario = force_all_object_to_string(garantir_colunas(df_final_resumo_diario, COLUNAS_RESUMO_DIARIO))

    comparar_colunas("pcp_producao_diaria", df_final_producao, COLUNAS_PRODUCAO)
    comparar_colunas("pcp_recepcao", df_final_recepcao, COLUNAS_RECEPCAO_COMPRA)
    comparar_colunas("pcp_compra", df_final_compra, COLUNAS_RECEPCAO_COMPRA)
    comparar_colunas("pcp_abate", df_final_abate, COLUNAS_ABATE)
    comparar_colunas("pcp_dados_gerais", df_final_dados_gerais, COLUNAS_DADOS_GERAIS)
    comparar_colunas("pcp_resumo_diario", df_final_resumo_diario, COLUNAS_RESUMO_DIARIO)

    salvar_parquet(df_final_producao, "pcp_producao_diaria")
    salvar_parquet(df_final_recepcao, "pcp_recepcao")
    salvar_parquet(df_final_compra, "pcp_compra")
    salvar_parquet(df_final_abate, "pcp_abate")
    salvar_parquet(df_final_dados_gerais, "pcp_dados_gerais")
    salvar_parquet(df_final_resumo_diario, "pcp_resumo_diario")

    # Diário da Indústria Ave Nova por turno - bases separadas
    # para não duplicar os números do Diário geral.
    processar_diario_industria_turnos()

    df_param_efic = criar_parametros_efic_abate()
    df_param_efic_geral = criar_parametros_efic_abate_geral()

    salvar_parquet(df_param_efic, "parametros_efic_abate")
    salvar_parquet(df_param_efic_geral, "parametros_efic_abate_geral")

    arquivos_movimento = listar_arquivos_excel(PASTA_MOVIMENTO_GERAL)

    print("\nArquivos movimento geral encontrados:")
    for arq in arquivos_movimento:
        print("-", os.path.basename(arq))

    if not arquivos_movimento:
        print("Nenhum arquivo encontrado em Movimento Geral de Pesagem.")
        df_efic_base = criar_df_vazio_efic()
    else:
        lista_efic = []
        for arq in arquivos_movimento:
            try:
                df_temp = tratar_arquivo_movimento_geral(arq)
                if df_temp is not None and not df_temp.empty:
                    df_temp = adicionar_arquivo_origem(df_temp, arq)
                    lista_efic.append(df_temp)
                else:
                    print(f"Arquivo {os.path.basename(arq)} não gerou linhas.")
            except Exception as e:
                print(f"ERRO movimento geral em {os.path.basename(arq)}: {e}")

        df_efic_base = pd.concat(lista_efic, ignore_index=True) if lista_efic else criar_df_vazio_efic()

    df_efic_base = force_all_object_to_string(df_efic_base)

    print(f"\nLinhas consolidadas pcp_efic_abate_base: {len(df_efic_base)}")
    print(f"Colunas consolidadas pcp_efic_abate_base: {list(df_efic_base.columns)}")

    salvar_parquet(df_efic_base, "pcp_efic_abate_base")

    arquivos_estoque_transacao = listar_arquivos_excel(PASTA_ESTOQUE_TRANSACAO)

    print("\nArquivos estoque por transação encontrados:")
    for arq in arquivos_estoque_transacao:
        print("-", os.path.basename(arq))

    if not arquivos_estoque_transacao:
        print("Nenhum arquivo encontrado em Estoque por Transacao.")
        df_estoque_transacao = pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)
    else:
        lista_estoque_transacao = []

        for arq in arquivos_estoque_transacao:
            try:
                df_temp = tratar_arquivo_estoque_transacao(arq)
                if df_temp is not None and not df_temp.empty:
                    df_temp = adicionar_arquivo_origem(df_temp, arq)
                    lista_estoque_transacao.append(df_temp)
                else:
                    print(f"Arquivo {os.path.basename(arq)} não gerou linhas de estoque por transação.")
            except Exception as e:
                print(f"ERRO estoque por transação em {os.path.basename(arq)}: {e}")

        df_estoque_transacao = (
            pd.concat(lista_estoque_transacao, ignore_index=True)
            if lista_estoque_transacao
            else pd.DataFrame(columns=COLUNAS_ESTOQUE_TRANSACAO)
        )

    df_estoque_transacao = force_all_object_to_string(df_estoque_transacao)

    print(f"\nLinhas consolidadas pcp_estoque_transacao: {len(df_estoque_transacao)}")
    print(f"Colunas consolidadas pcp_estoque_transacao: {list(df_estoque_transacao.columns)}")

    salvar_parquet(df_estoque_transacao, "pcp_estoque_transacao")

    df_rel_geral_condenacoes = processar_relatorio_geral_condenacoes()
    df_rel_geral_condenacoes = force_all_object_to_string(df_rel_geral_condenacoes)

    print(f"\nLinhas consolidadas pcp_rel_geral_condenacoes: {len(df_rel_geral_condenacoes)}")
    print(f"Colunas consolidadas pcp_rel_geral_condenacoes: {list(df_rel_geral_condenacoes.columns)}")

    salvar_parquet(df_rel_geral_condenacoes, "pcp_rel_geral_condenacoes")

    df_devolucao_pcp = processar_devolucao_pcp()
    df_devolucao_pcp = force_all_object_to_string(df_devolucao_pcp)

    print(f"\nLinhas consolidadas pcp_devolucao: {len(df_devolucao_pcp)}")
    print(f"Colunas consolidadas pcp_devolucao: {list(df_devolucao_pcp.columns)}")

    salvar_parquet(df_devolucao_pcp, "pcp_devolucao")

    df_estoque_online = processar_estoque_online()
    df_estoque_online = force_all_object_to_string(df_estoque_online)

    print(f"\nLinhas consolidadas pcp_estoque_online: {len(df_estoque_online)}")
    print(f"Colunas consolidadas pcp_estoque_online: {list(df_estoque_online.columns)}")

    salvar_parquet(df_estoque_online, "pcp_estoque_online")

    df_desperdicio = processar_desperdicio()
    df_desperdicio = force_all_object_to_string(df_desperdicio)

    print(f"\nLinhas consolidadas pcp_desperdicio: {len(df_desperdicio)}")
    print(f"Colunas consolidadas pcp_desperdicio: {list(df_desperdicio.columns)}")

    salvar_parquet(df_desperdicio, "pcp_desperdicio")

    df_plano_producao = processar_plano_producao()
    df_plano_producao = force_all_object_to_string(df_plano_producao)

    print(f"\nLinhas consolidadas pcp_plano_producao: {len(df_plano_producao)}")
    print(f"Colunas consolidadas pcp_plano_producao: {list(df_plano_producao.columns)}")

    salvar_parquet(df_plano_producao, "pcp_plano_producao")

    print("\n==============================")
    print("OK! Arquivos gerados em:", PASTA_SAIDA)
    print("Produção:", len(df_final_producao), "linhas")
    print("Recepção:", len(df_final_recepcao), "linhas")
    print("Compra:", len(df_final_compra), "linhas")
    print("Abate:", len(df_final_abate), "linhas")
    print("Dados Gerais:", len(df_final_dados_gerais), "linhas")
    print("Efic Abate Base:", len(df_efic_base), "linhas")
    print("Estoque por Transação:", len(df_estoque_transacao), "linhas")
    print("Relatório Geral de Condenações:", len(df_rel_geral_condenacoes), "linhas")
    print("Devolução PCP:", len(df_devolucao_pcp), "linhas")
    print("Estoque Online:", len(df_estoque_online), "linhas")
    print("Desperdicio:", len(df_desperdicio), "linhas")
    print("Plano de Producao:", len(df_plano_producao), "linhas")
    print("Resumo Diário:", len(df_final_resumo_diario), "linhas")
    print("==============================\n")
