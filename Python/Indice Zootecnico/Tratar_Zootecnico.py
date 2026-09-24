# -*- coding: utf-8 -*-
r"""
TRATAMENTO ZOOTÉCNICO — BASE DINÂMICA + MOVIMENTO MORTALIDADE/PESO

OBJETIVO
- lê todos os Excel oficiais da Base de Dados Frango de Corte;
- identifica automaticamente o cabeçalho analítico;
- preserva todas as colunas do relatório;
- trata textos, datas e colunas numéricas;
- adiciona metadados do arquivo/período;
- consolida arquivos sobrepostos mantendo a versão mais recente;
- gera Parquets tratados separados para consumo no Portal/Power BI;
- inclui Movimento Mortalidade/Peso - Lotes Abertos;
- inclui Movimento Mortalidade/Peso - Lotes Fechados.

ENTRADA:
\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Base de Dados Dinamica

SAÍDA:
\\192.168.1.139\Controladoria\BI_Granja\Tratados\Indice Zootecnico\indice_zootecnico_base_dinamica_tratado.parquet

USO MANUAL:
    py Tratar_Zootecnico.py

USO PELO PORTAL:
    py Tratar_Zootecnico.py --sem-pausa
"""

import argparse
import re
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd


# =============================================================================
# 1) CONFIGURAÇÕES
# =============================================================================

PASTA_ENTRADA_BASE_DINAMICA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Base de Dados Dinamica"
)

PASTA_ENTRADA_MORTALIDADE_PESO_ABERTOS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Movimento MortalidadePeso\Lotes Aberto"
)

PASTA_ENTRADA_MORTALIDADE_PESO_FECHADOS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Movimento MortalidadePeso\Lotes Fechados"
)

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Indice Zootecnico"
)

ARQUIVO_PARQUET_BASE_DINAMICA = (
    PASTA_SAIDA
    / "indice_zootecnico_base_dinamica_tratado.parquet"
)

ARQUIVO_PARQUET_MORTALIDADE_PESO_ABERTOS = (
    PASTA_SAIDA
    / "indice_zootecnico_mortalidade_peso_lotes_abertos_tratado.parquet"
)

ARQUIVO_PARQUET_MORTALIDADE_PESO_FECHADOS = (
    PASTA_SAIDA
    / "indice_zootecnico_mortalidade_peso_lotes_fechados_tratado.parquet"
)

PASTA_SAIDA.mkdir(
    parents=True,
    exist_ok=True,
)


# =============================================================================
# 2) FUNÇÕES UTILITÁRIAS
# =============================================================================

def clean_col_name(value) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value)
    text = text.replace("_x000d_", " ")
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def strip_accents(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize(
            "NFKD",
            str(text),
        )
        if not unicodedata.combining(char)
    )


def header_key(text: str) -> str:
    text = strip_accents(
        clean_col_name(text)
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def make_unique_columns(columns):
    used = {}
    result = []

    for index, column in enumerate(columns):
        name = clean_col_name(column)

        if (
            not name
            or name.lower().startswith("unnamed")
        ):
            name = f"coluna_{index}"

        quantity = used.get(name, 0)

        if quantity:
            final_name = f"{name}.{quantity}"
        else:
            final_name = name

        result.append(final_name)
        used[name] = quantity + 1

    return result


def normalize_text(series: pd.Series) -> pd.Series:
    result = (
        series.astype("string")
        .str.replace("_x000d_", " ", regex=False)
        .str.replace("\n", " ", regex=False)
        .str.replace("\r", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    return result.replace(
        {
            "nan": pd.NA,
            "NaT": pd.NA,
            "None": pd.NA,
            "<NA>": pd.NA,
            "": pd.NA,
        }
    )


def to_numeric_ptbr(series: pd.Series) -> pd.Series:
    def parse_one(value):
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()

        if text in {
            "",
            "-",
            "nan",
            "None",
            "NaT",
            "<NA>",
        }:
            return None

        negative_end = text.endswith("-")
        negative_parentheses = (
            text.startswith("(")
            and text.endswith(")")
        )

        if negative_end:
            text = text[:-1].strip()

        if negative_parentheses:
            text = text[1:-1].strip()

        text = (
            text.replace("R$", "")
            .replace("%", "")
            .replace("\xa0", " ")
            .strip()
        )

        text = re.sub(
            r"[^0-9,.\-]",
            "",
            text,
        )

        if not text:
            return None

        # PT-BR: 1.234,56
        if "," in text:
            text = (
                text.replace(".", "")
                .replace(",", ".")
            )

        try:
            number = float(text)
        except Exception:
            return None

        if negative_end or negative_parentheses:
            number = -abs(number)

        return number

    return series.apply(
        parse_one
    ).astype("float64")


def parse_known_dates(series: pd.Series) -> pd.Series:
    output = pd.Series(
        pd.NaT,
        index=series.index,
        dtype="datetime64[ns]",
    )

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(
            series,
            errors="coerce",
        )

    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    numeric_mask = (
        numeric.notna()
        & numeric.between(1, 100000)
    )

    if numeric_mask.any():
        output.loc[numeric_mask] = pd.to_datetime(
            numeric.loc[numeric_mask],
            unit="D",
            origin="1899-12-30",
            errors="coerce",
        )

    text_mask = ~numeric_mask

    if text_mask.any():
        output.loc[text_mask] = pd.to_datetime(
            series.loc[text_mask],
            errors="coerce",
            dayfirst=True,
        )

    return output


def drop_total_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    total_mask = df.astype("string").apply(
        lambda column: column.str.contains(
            r"^\s*(total|totais|subtotal|total geral)\s*:?\s*$",
            case=False,
            regex=True,
            na=False,
        )
    )

    return df.loc[
        ~total_mask.any(axis=1)
    ].copy()


def listar_arquivos_excel(pasta_entrada: Path):
    arquivos = []

    if not pasta_entrada.exists():
        return arquivos

    for pattern in (
        "*.xlsx",
        "*.xlsm",
        "*.xls",
    ):
        arquivos.extend(
            pasta_entrada.glob(pattern)
        )

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if (
                arquivo.is_file()
                and not arquivo.name.startswith("~$")
            )
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def extrair_periodo_nome(caminho_arquivo: Path):
    """
    Exemplo:
    Base_Dados_Dinamica_01-09-2026_09-09-2026.xlsx
    """
    datas = re.findall(
        r"(\d{2}-\d{2}-\d{4})",
        caminho_arquivo.name,
    )

    if len(datas) < 2:
        return pd.NaT, pd.NaT

    try:
        inicio = pd.Timestamp(
            datetime.strptime(
                datas[0],
                "%d-%m-%Y",
            )
        )

        fim = pd.Timestamp(
            datetime.strptime(
                datas[1],
                "%d-%m-%Y",
            )
        )

        return inicio, fim

    except Exception:
        return pd.NaT, pd.NaT


# =============================================================================
# 3) LEITURA DO EXCEL OFICIAL
# =============================================================================

def encontrar_linha_cabecalho(
    caminho_arquivo: Path,
    max_rows: int = 100,
) -> int:
    """
    O arquivo validado possui o cabeçalho analítico na linha 8, começando por:
    Produtor | Cod Prod | Tipo de Granja | Galpão | Modelo | Lote | ...

    A posição não fica fixa no código para tolerar mudanças no cabeçalho
    superior do Agrosys.
    """
    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    preview = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=None,
        nrows=max_rows,
        dtype=object,
        engine=engine,
    )

    grupos = [
        {"produtor"},
        {"cod prod", "codigo produtor"},
        {"tipo de granja"},
        {"galpao"},
        {"lote"},
        {"data de alojamento"},
        {"data de abate"},
        {"aves alojadas"},
        {"peso medio"},
        {"iep"},
    ]

    melhor_linha = None
    melhor_score = 0

    for index in range(len(preview)):
        chaves = {
            header_key(value)
            for value in preview.iloc[index].tolist()
            if clean_col_name(value)
        }

        score = 0

        for grupo in grupos:
            grupo_norm = {
                header_key(item)
                for item in grupo
            }

            if chaves.intersection(grupo_norm):
                score += 1

        if score >= 7:
            print(
                "  Cabeçalho encontrado na linha:",
                index + 1,
                f"(score={score})",
            )
            return index

        if score > melhor_score:
            melhor_score = score
            melhor_linha = index

    if melhor_linha is not None and melhor_score >= 5:
        print(
            "  AVISO: cabeçalho parcial utilizado na linha:",
            melhor_linha + 1,
            f"(score={melhor_score})",
        )
        return melhor_linha

    raise ValueError(
        "Não encontrei o cabeçalho da Base de Dados Frango de Corte em "
        f"{caminho_arquivo.name}"
    )


def ler_tabela_principal(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho(
        caminho_arquivo
    )

    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=header_row,
        dtype=object,
        engine=engine,
    )

    df.columns = make_unique_columns(
        df.columns.tolist()
    )

    # Preserva todas as colunas do relatório, inclusive uma coluna que esteja
    # vazia no período atual. Remove apenas linhas completamente vazias.
    df = (
        df.dropna(
            axis=0,
            how="all",
        )
        .copy()
    )

    df = drop_total_rows(df)

    # Somente linhas analíticas: Produtor preenchido.
    if "Produtor" not in df.columns:
        raise ValueError(
            "A coluna Produtor não foi encontrada em "
            f"{caminho_arquivo.name}"
        )

    produtor = normalize_text(
        df["Produtor"]
    )

    df = df[
        produtor.notna()
        & ~produtor.str.lower().str.startswith(
            "total",
            na=False,
        )
    ].copy()

    return df.reset_index(drop=True)


# =============================================================================
# 4) PARÂMETROS DO TOPO DO RELATÓRIO
# =============================================================================

def extrair_parametros_relatorio(
    caminho_arquivo: Path,
) -> dict:
    """
    O arquivo observado possui:
    linha 5: Empresa | Descrição | Unidade | Descrição | Data Inicial | Data Final
    linha 6: 1 | Granja Brasilia | 52 | Producao Avicola | ...
    """
    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    raw = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=None,
        nrows=20,
        dtype=object,
        engine=engine,
    )

    for index in range(max(0, len(raw) - 1)):
        chaves = [
            header_key(value)
            for value in raw.iloc[index].tolist()
        ]

        conjunto = {
            chave
            for chave in chaves
            if chave
        }

        if not {
            "empresa",
            "unidade",
            "data inicial",
            "data final",
        }.issubset(conjunto):
            continue

        valores = raw.iloc[index + 1].tolist()

        parametros = {
            "Parametro_Empresa": None,
            "Parametro_Empresa_Descricao": None,
            "Parametro_Unidade": None,
            "Parametro_Unidade_Descricao": None,
            "Parametro_Data_Inicial": None,
            "Parametro_Data_Final": None,
        }

        descricao_posicoes = []

        for posicao, chave in enumerate(chaves):
            valor = (
                valores[posicao]
                if posicao < len(valores)
                else None
            )

            if chave == "empresa":
                parametros["Parametro_Empresa"] = valor

            elif chave == "unidade":
                parametros["Parametro_Unidade"] = valor

            elif chave == "data inicial":
                parametros["Parametro_Data_Inicial"] = valor

            elif chave == "data final":
                parametros["Parametro_Data_Final"] = valor

            elif chave == "descricao":
                descricao_posicoes.append(
                    (posicao, valor)
                )

        if descricao_posicoes:
            parametros[
                "Parametro_Empresa_Descricao"
            ] = descricao_posicoes[0][1]

        if len(descricao_posicoes) >= 2:
            parametros[
                "Parametro_Unidade_Descricao"
            ] = descricao_posicoes[1][1]

        for coluna in [
            "Parametro_Data_Inicial",
            "Parametro_Data_Final",
        ]:
            serie = pd.Series(
                [parametros[coluna]],
                dtype=object,
            )

            parametros[coluna] = (
                parse_known_dates(
                    serie
                ).iloc[0]
            )

        return parametros

    return {}


# =============================================================================
# 5) TRATAMENTO
# =============================================================================

COLUNAS_DATA_EXATAS = {
    "data de alojamento",
    "data de abate",
    "data de acerto",
    "data corte",
    "validade",
}

COLUNAS_TEXTO_EXATAS = {
    "produtor",
    "cod prod",
    "tipo de granja",
    "galpao",
    "modelo",
    "lote",
    "cidade",
    "uf",
    "regiao",
    "tecnico",
    "nutricao",
    "sexo",
    "linhagem",
    "standard",
    "dia sem aloj",
    "mes aloj",
    "dia sem abate",
    "mes abate",
    "tipo ave",
    "classe",
    "doenca",
    "medicamento",
    "principio ativo",
    "status acerto",
    "planta de producao",
    "planta de abate",
    "tipo comedouro",
    "tipo bebedouro",
    "fornecedor pinto",
    "incubatorio",
    "lotes matriz",
    "positividade",
    "hora corte",
    "equipe apanha",
    "inicio abate",
    "parada abate",
    "tipo vacina",
    "laboratorio",
    "partida",
}

PREFIXOS_NUMERICOS = (
    "% ",
    "r$ ",
    "ps medio",
    "qtd aves",
    "ps liqui",
)

TERMOS_NUMERICOS = (
    "aves inic",
    "aves alojadas",
    "aves abatidas",
    "aves kg",
    "kg final",
    "peso mort",
    "mort transporte",
    "quantidade",
    "valor medicamento",
    "peso med pintos",
    "peso 7 dias",
    "peso 14 dias",
    "peso 21 dias",
    "peso 28 dias",
    "peso 35 dias",
    "peso 42 dias",
    "peso 49 dias",
    "cons ave",
    "racao consumida",
    "sobra de racao",
    "peso medio",
    "idade",
    "gmd",
    "cond",
    "ea",
    "ca",
    "cac",
    "iep",
    "dist fabrica",
    "dist incubatorio",
    "dist frigorifico",
    "idade matriz",
    "uniformidade",
    "calo pes",
    "jejum",
    "tempo espera",
    "kg parcial",
    "cab parcial",
    "kg total",
    "cab total",
)


def coluna_deve_ser_data(coluna: str) -> bool:
    chave = header_key(coluna)

    if chave in COLUNAS_DATA_EXATAS:
        return True

    # Evita transformar Dia/Mês/Ano em datas.
    return chave.startswith("data ")


def coluna_deve_ser_texto(coluna: str) -> bool:
    chave = header_key(coluna)

    if chave in COLUNAS_TEXTO_EXATAS:
        return True

    # Colunas de identificação/código devem permanecer texto.
    if chave.startswith("cod "):
        return True

    return False


def coluna_deve_ser_numerica(coluna: str) -> bool:
    chave = header_key(coluna)

    if coluna_deve_ser_data(coluna):
        return False

    if coluna_deve_ser_texto(coluna):
        return False

    if chave.startswith(PREFIXOS_NUMERICOS):
        return True

    return any(
        termo in chave
        for termo in TERMOS_NUMERICOS
    )


def tratar_arquivo(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    df = ler_tabela_principal(
        caminho_arquivo
    )

    if df.empty:
        return df

    parametros = extrair_parametros_relatorio(
        caminho_arquivo
    )

    # -----------------------------------------------------------------
    # Datas
    # -----------------------------------------------------------------
    for coluna in list(df.columns):
        if coluna_deve_ser_data(coluna):
            convertida = parse_known_dates(
                df[coluna]
            )

            if convertida.notna().any():
                df[coluna] = convertida

    # -----------------------------------------------------------------
    # Numéricos
    # -----------------------------------------------------------------
    for coluna in list(df.columns):
        if coluna_deve_ser_numerica(coluna):
            convertida = to_numeric_ptbr(
                df[coluna]
            )

            # Só troca se houver pelo menos algum número válido.
            if convertida.notna().any():
                df[coluna] = convertida

    # -----------------------------------------------------------------
    # Textos
    # -----------------------------------------------------------------
    for coluna in list(df.columns):
        if (
            pd.api.types.is_object_dtype(df[coluna])
            or pd.api.types.is_string_dtype(df[coluna])
        ):
            df[coluna] = normalize_text(
                df[coluna]
            )

    # -----------------------------------------------------------------
    # Parâmetros superiores
    # -----------------------------------------------------------------
    for coluna, valor in parametros.items():
        df[coluna] = valor

    periodo_inicio, periodo_fim = (
        extrair_periodo_nome(
            caminho_arquivo
        )
    )

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # -----------------------------------------------------------------
    # Data analítica
    # -----------------------------------------------------------------
    if (
        "Data de Acerto" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Data de Acerto"]
        )
    ):
        df["Data_Analise"] = df["Data de Acerto"]

    elif (
        "Data de Abate" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Data de Abate"]
        )
    ):
        df["Data_Analise"] = df["Data de Abate"]

    else:
        df["Data_Analise"] = periodo_fim

    if pd.api.types.is_datetime64_any_dtype(
        df["Data_Analise"]
    ):
        df["Ano_Analise"] = (
            df["Data_Analise"].dt.year
        )

        df["Mes_Numero_Analise"] = (
            df["Data_Analise"].dt.month
        )

        df["Dia_Analise"] = (
            df["Data_Analise"].dt.day
        )

        df["AnoMes_Analise"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    return df.reset_index(drop=True)


# =============================================================================
# 6) CONSOLIDAÇÃO / DEDUPLICAÇÃO
# =============================================================================

def chave_deduplicacao(
    df: pd.DataFrame,
):
    """
    Um lote/galpão pode reaparecer quando os períodos exportados se sobrepõem.

    A versão do arquivo mais recente prevalece.
    """
    candidatos = [
        "Cod Prod",
        "Galpão",
        "Lote",
        "Data de Alojamento",
        "Data de Abate",
        "Data de Acerto",
    ]

    chave = [
        coluna
        for coluna in candidatos
        if coluna in df.columns
    ]

    if len(chave) >= 3:
        return chave

    return [
        coluna
        for coluna in df.columns
        if coluna not in {
            "Arquivo_Origem",
            "Periodo_Arquivo_Inicio",
            "Periodo_Arquivo_Fim",
            "_Arquivo_Modificado_Em",
        }
    ]


def consolidar_base_dinamica():
    arquivos = listar_arquivos_excel(PASTA_ENTRADA_BASE_DINAMICA)

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel da Base Dinâmica encontrado em: "
            f"{PASTA_ENTRADA_BASE_DINAMICA}"
        )

    print()
    print("=" * 80)
    print("TRATANDO ÍNDICE ZOOTÉCNICO")
    print("=" * 80)
    print(
        "Arquivos encontrados:",
        len(arquivos),
    )

    bases = []
    erros = []

    for numero, arquivo in enumerate(
        arquivos,
        start=1,
    ):
        print()
        print(
            f"[{numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        try:
            tratado = tratar_arquivo(
                arquivo
            )

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas |",
                len(tratado.columns),
                "colunas",
            )

            if not tratado.empty:
                bases.append(
                    tratado
                )

        except Exception as erro:
            erros.append(
                (arquivo.name, str(erro))
            )

            print(
                "  ERRO:",
                arquivo.name,
            )

            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo do Índice Zootécnico "
            "foi tratado com sucesso."
        )

    resultado = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    linhas_antes = len(
        resultado
    )

    resultado = resultado.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    chave = chave_deduplicacao(
        resultado
    )

    print()
    print(
        "Chave de deduplicação:",
        " + ".join(chave),
    )

    resultado = resultado.drop_duplicates(
        subset=chave,
        keep="last",
    )

    resultado = resultado.drop(
        columns=[
            "_Arquivo_Modificado_Em"
        ],
        errors="ignore",
    ).reset_index(drop=True)

    print()
    print(
        "Linhas antes da deduplicação:",
        f"{linhas_antes:,}",
    )

    print(
        "Duplicadas removidas:",
        f"{linhas_antes - len(resultado):,}",
    )

    print(
        "Linhas finais:",
        f"{len(resultado):,}",
    )

    print(
        "Colunas finais:",
        len(resultado.columns),
    )

    if "Data de Alojamento" in resultado.columns:
        print(
            "Alojamento mínimo:",
            resultado[
                "Data de Alojamento"
            ].min(),
        )

        print(
            "Alojamento máximo:",
            resultado[
                "Data de Alojamento"
            ].max(),
        )

    if "Data de Abate" in resultado.columns:
        print(
            "Abate mínimo:",
            resultado[
                "Data de Abate"
            ].min(),
        )

        print(
            "Abate máximo:",
            resultado[
                "Data de Abate"
            ].max(),
        )

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) "
            "tiveram erro:"
        )

        for nome, erro in erros:
            print(
                f"  - {nome}: {erro}"
            )

    return resultado



# =============================================================================
# 6.1) MOVIMENTO MORTALIDADE/PESO - LOTES ABERTOS
# =============================================================================

def encontrar_cabecalho_generico(caminho_arquivo: Path, max_rows: int = 120) -> int:
    """Localiza a linha mais provável de cabeçalho do relatório."""
    engine = "openpyxl" if caminho_arquivo.suffix.lower() != ".xls" else None
    preview = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=None,
        nrows=max_rows,
        dtype=object,
        engine=engine,
    )

    melhor_linha = None
    melhor_score = -1

    for index in range(len(preview)):
        valores = [
            clean_col_name(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        ]
        chaves = [header_key(v) for v in valores]

        # Cabeçalho analítico normalmente tem muitas células textuais distintas.
        distintos = len(set(chaves))
        palavras_relevantes = sum(
            1 for chave in chaves
            if any(termo in chave for termo in (
                "produtor", "galp", "lote", "data", "idade",
                "morte", "mort", "peso", "quant", "tecnico",
                "regiao", "sexo", "linhagem"
            ))
        )
        score = distintos + (palavras_relevantes * 4)

        if len(valores) >= 5 and score > melhor_score:
            melhor_score = score
            melhor_linha = index

    if melhor_linha is None:
        raise ValueError(
            f"Não foi possível localizar o cabeçalho em {caminho_arquivo.name}"
        )

    print(
        "  Cabeçalho Movimento Mortalidade/Peso encontrado na linha:",
        melhor_linha + 1,
        f"(score={melhor_score})",
    )
    return melhor_linha


def ler_movimento_mortalidade_peso(caminho_arquivo: Path) -> pd.DataFrame:
    """
    Lê SOMENTE A PRIMEIRA TABELA analítica do relatório Mortalidade/Peso.

    Estrutura observada no Excel oficial:
    - cabeçalho principal: começa por "Semana Ano", "Ano", "Ida Dia",
      "Codigo Granja", "Nome Granja", "Num Lote"...
    - depois dos registros analíticos aparece a linha "Totais --->";
    - abaixo dela existem tabelas/resumos auxiliares como:
      Idade, Peso Medio, %Mortalidade, Resumo Por Semana etc.

    Esses blocos inferiores NÃO pertencem à base analítica e não devem
    ir para o Parquet/Power BI.

    Esta função:
    1. procura especificamente o cabeçalho da PRIMEIRA tabela;
    2. lê a planilha a partir dele;
    3. corta tudo a partir da primeira linha "Totais --->";
    4. mantém somente as linhas analíticas anteriores ao total.
    """
    engine = "openpyxl" if caminho_arquivo.suffix.lower() != ".xls" else None

    preview = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=None,
        nrows=120,
        dtype=object,
        engine=engine,
    )

    header_row = None

    # O cabeçalho correto da primeira tabela possui simultaneamente
    # vários destes campos. Isso evita escolher os resumos de Idade/Peso
    # que aparecem mais abaixo no mesmo Excel.
    campos_esperados = {
        "semana ano",
        "ano",
        "ida dia",
        "codigo granja",
        "nome granja",
        "num lote",
        "galp",
    }

    for index in range(len(preview)):
        chaves = {
            header_key(valor)
            for valor in preview.iloc[index].tolist()
            if clean_col_name(valor)
        }

        encontrados = len(chaves.intersection(campos_esperados))

        if encontrados >= 5:
            header_row = index
            print(
                "  Cabeçalho da PRIMEIRA tabela encontrado na linha:",
                index + 1,
                f"(campos reconhecidos={encontrados})",
            )
            break

    if header_row is None:
        raise ValueError(
            "Não encontrei o cabeçalho da primeira tabela analítica "
            f"em {caminho_arquivo.name}"
        )

    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=header_row,
        dtype=object,
        engine=engine,
    )

    df.columns = make_unique_columns(df.columns.tolist())

    # -----------------------------------------------------------------
    # CORTA O RELATÓRIO NO PRIMEIRO "TOTAIS --->"
    # -----------------------------------------------------------------
    # O Agrosys coloca várias tabelas auxiliares abaixo da tabela principal.
    # A primeira ocorrência de "Totais" marca o fim da tabela que queremos.
    mascara_total = df.astype("string").apply(
        lambda coluna: coluna.str.contains(
            r"^\s*totais?\s*-*>?\s*:?\s*$",
            case=False,
            regex=True,
            na=False,
        )
    ).any(axis=1)

    posicoes_total = [
        posicao
        for posicao, encontrado in enumerate(mascara_total.tolist())
        if encontrado
    ]

    if posicoes_total:
        primeira_posicao_total = posicoes_total[0]

        print(
            "  Fim da primeira tabela localizado antes da linha Excel:",
            header_row + 2 + primeira_posicao_total,
        )

        df = df.iloc[:primeira_posicao_total].copy()
    else:
        print(
            "  AVISO: linha 'Totais --->' não encontrada; "
            "aplicando validação estrutural das linhas."
        )

    # Remove linhas completamente vazias.
    df = df.dropna(axis=0, how="all").copy()

    # Segurança adicional: caso algum cabeçalho/resumo tenha escapado,
    # remove linhas cujo conteúdo seja explicitamente de total/resumo.
    termos_invalidos = re.compile(
        r"^\s*(totais?|subtotal|total geral|resumo por semana)\b",
        flags=re.IGNORECASE,
    )

    def linha_auxiliar(linha):
        for valor in linha:
            texto = clean_col_name(valor)
            if texto and termos_invalidos.search(texto):
                return True
        return False

    if not df.empty:
        mascara_auxiliar = df.apply(linha_auxiliar, axis=1)
        df = df.loc[~mascara_auxiliar].copy()

    # Remove eventual repetição do próprio cabeçalho.
    if len(df.columns):
        primeira_coluna = df.columns[0]
        chave_primeira = header_key(primeira_coluna)

        if chave_primeira:
            df = df[
                df[primeira_coluna].apply(header_key) != chave_primeira
            ].copy()

    print(
        "  Linhas analíticas preservadas da primeira tabela:",
        len(df),
    )

    return df.reset_index(drop=True)


def tratar_movimento_mortalidade_peso(caminho_arquivo: Path) -> pd.DataFrame:
    df = ler_movimento_mortalidade_peso(caminho_arquivo)

    if df.empty:
        return df

    # Datas: somente quando o nome da coluna indicar claramente uma data.
    for coluna in list(df.columns):
        chave = header_key(coluna)
        if "data" in chave:
            convertida = parse_known_dates(df[coluna])
            if convertida.notna().any():
                df[coluna] = convertida

    # Demais colunas object/string são limpas, sem forçar códigos a número.
    for coluna in list(df.columns):
        if (
            pd.api.types.is_object_dtype(df[coluna])
            or pd.api.types.is_string_dtype(df[coluna])
        ):
            df[coluna] = normalize_text(df[coluna])

    periodo_inicio, periodo_fim = extrair_periodo_nome(caminho_arquivo)

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # Identifica a melhor coluna de data disponível para análise.
    colunas_data = [
        coluna for coluna in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[coluna])
    ]

    if colunas_data:
        df["Data_Analise"] = df[colunas_data[0]]
    else:
        df["Data_Analise"] = periodo_fim

    if pd.api.types.is_datetime64_any_dtype(df["Data_Analise"]):
        df["Ano_Analise"] = df["Data_Analise"].dt.year
        df["Mes_Numero_Analise"] = df["Data_Analise"].dt.month
        df["Dia_Analise"] = df["Data_Analise"].dt.day
        df["AnoMes_Analise"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    return df.reset_index(drop=True)


def diagnosticar_data_recepcao(df: pd.DataFrame, prefixo: str = "  "):
    """Exibe o intervalo de Data Recepcao sem filtrar ou alterar os dados."""
    coluna = next((c for c in df.columns if header_key(c) == "data recepcao"), None)

    if coluna is None:
        print(f"{prefixo}AVISO: coluna Data Recepcao não encontrada.")
        return

    datas = parse_known_dates(df[coluna])
    validas = datas.dropna()

    if validas.empty:
        print(f"{prefixo}AVISO: Data Recepcao existe, mas nenhuma data válida foi reconhecida.")
        return

    print(f"{prefixo}Data Recepcao mínima: {validas.min()}")
    print(f"{prefixo}Data Recepcao máxima: {validas.max()}")


def consolidar_mortalidade_peso_abertos():
    arquivos = listar_arquivos_excel(
        PASTA_ENTRADA_MORTALIDADE_PESO_ABERTOS
    )

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Movimento Mortalidade/Peso - Lotes Abertos "
            f"encontrado em: {PASTA_ENTRADA_MORTALIDADE_PESO_ABERTOS}"
        )

    print()
    print("=" * 80)
    print("TRATANDO MOVIMENTO MORTALIDADE/PESO - LOTES ABERTOS")
    print("=" * 80)
    print("Arquivos encontrados:", len(arquivos))

    bases = []
    erros = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print()
        print(f"[{numero}/{len(arquivos)}] {arquivo.name}")

        try:
            tratado = tratar_movimento_mortalidade_peso(arquivo)
            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas |",
                len(tratado.columns),
                "colunas",
            )
            if not tratado.empty:
                diagnosticar_data_recepcao(tratado)
                bases.append(tratado)
        except Exception as erro:
            erros.append((arquivo.name, str(erro)))
            print("  ERRO:", arquivo.name)
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo de Movimento Mortalidade/Peso - Lotes Abertos "
            "foi tratado com sucesso."
        )

    resultado = pd.concat(bases, ignore_index=True, sort=False)
    linhas_antes = len(resultado)

    resultado = resultado.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    # Remove apenas registros 100% repetidos nos campos analíticos.
    # Isso é mais seguro neste relatório novo do que assumir uma chave
    # de negócio antes de validarmos suas colunas.
    ignorar = {
        "Arquivo_Origem",
        "Periodo_Arquivo_Inicio",
        "Periodo_Arquivo_Fim",
        "_Arquivo_Modificado_Em",
    }
    chave = [
        coluna for coluna in resultado.columns
        if coluna not in ignorar
    ]

    if chave:
        resultado = resultado.drop_duplicates(
            subset=chave,
            keep="last",
        )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print()
    print("Linhas antes da deduplicação:", f"{linhas_antes:,}")
    print("Duplicadas removidas:", f"{linhas_antes - len(resultado):,}")
    print("Linhas finais:", f"{len(resultado):,}")
    print("Colunas finais:", len(resultado.columns))

    print()
    print("DIAGNÓSTICO DATA RECEPCAO - LOTES ABERTOS")
    diagnosticar_data_recepcao(resultado, prefixo="  ")

    if erros:
        print()
        print(f"AVISO: {len(erros)} arquivo(s) tiveram erro:")
        for nome, erro in erros:
            print(f"  - {nome}: {erro}")

    return resultado


# =============================================================================
# 6.2) MOVIMENTO MORTALIDADE/PESO - LOTES FECHADOS
# =============================================================================

def consolidar_mortalidade_peso_fechados():
    arquivos = listar_arquivos_excel(
        PASTA_ENTRADA_MORTALIDADE_PESO_FECHADOS
    )

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Movimento Mortalidade/Peso - Lotes Fechados "
            f"encontrado em: {PASTA_ENTRADA_MORTALIDADE_PESO_FECHADOS}"
        )

    print()
    print("=" * 80)
    print("TRATANDO MOVIMENTO MORTALIDADE/PESO - LOTES FECHADOS")
    print("=" * 80)
    print("Arquivos encontrados:", len(arquivos))

    bases = []
    erros = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print()
        print(f"[{numero}/{len(arquivos)}] {arquivo.name}")

        try:
            # O layout é o mesmo relatório wpf531d7; reaproveitamos
            # o tratamento já validado para Mortalidade/Peso.
            tratado = tratar_movimento_mortalidade_peso(arquivo)

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas |",
                len(tratado.columns),
                "colunas",
            )

            if not tratado.empty:
                bases.append(tratado)

        except Exception as erro:
            erros.append((arquivo.name, str(erro)))
            print("  ERRO:", arquivo.name)
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo de Movimento Mortalidade/Peso - Lotes Fechados "
            "foi tratado com sucesso."
        )

    resultado = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    linhas_antes = len(resultado)

    resultado = resultado.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    ignorar = {
        "Arquivo_Origem",
        "Periodo_Arquivo_Inicio",
        "Periodo_Arquivo_Fim",
        "_Arquivo_Modificado_Em",
    }

    chave = [
        coluna
        for coluna in resultado.columns
        if coluna not in ignorar
    ]

    if chave:
        resultado = resultado.drop_duplicates(
            subset=chave,
            keep="last",
        )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print()
    print("Linhas antes da deduplicação:", f"{linhas_antes:,}")
    print("Duplicadas removidas:", f"{linhas_antes - len(resultado):,}")
    print("Linhas finais:", f"{len(resultado):,}")
    print("Colunas finais:", len(resultado.columns))

    if erros:
        print()
        print(f"AVISO: {len(erros)} arquivo(s) tiveram erro:")
        for nome, erro in erros:
            print(f"  - {nome}: {erro}")

    return resultado


# =============================================================================
# 7) PARQUET
# =============================================================================

def normalizar_tipos_para_parquet(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Evita erro do PyArrow em colunas object com tipos misturados.
    """
    resultado = df.copy()

    for coluna in resultado.columns:
        serie = resultado[coluna]

        if pd.api.types.is_datetime64_any_dtype(
            serie
        ):
            continue

        if pd.api.types.is_numeric_dtype(
            serie
        ):
            continue

        if pd.api.types.is_bool_dtype(
            serie
        ):
            continue

        resultado[coluna] = normalize_text(
            serie
        )

    return resultado


def salvar_parquet_seguro(
    df: pd.DataFrame,
    destino: Path,
):
    temporario = destino.with_suffix(
        ".parquet.tmp"
    )

    if temporario.exists():
        temporario.unlink()

    df.to_parquet(
        temporario,
        index=False,
    )

    if (
        not temporario.exists()
        or temporario.stat().st_size <= 0
    ):
        raise RuntimeError(
            "O arquivo temporário do Parquet "
            "não foi criado corretamente."
        )

    if destino.exists():
        destino.unlink()

    temporario.replace(
        destino
    )


# =============================================================================
# 8) MAIN
# =============================================================================

def main():
    inicio = time.time()

    print("=" * 80)
    print("TRATAMENTO ZOOTÉCNICO")
    print("=" * 80)
    print("Entrada Base Dinâmica:", PASTA_ENTRADA_BASE_DINAMICA)
    print(
        "Entrada Mortalidade/Peso - Lotes Abertos:",
        PASTA_ENTRADA_MORTALIDADE_PESO_ABERTOS,
    )
    print(
        "Entrada Mortalidade/Peso - Lotes Fechados:",
        PASTA_ENTRADA_MORTALIDADE_PESO_FECHADOS,
    )
    print("Saída:", PASTA_SAIDA)
    print("=" * 80)

    resultados = []

    # -----------------------------------------------------------------
    # 1. Base de Dados Dinâmica
    # -----------------------------------------------------------------
    base_dinamica = consolidar_base_dinamica()
    base_dinamica = normalizar_tipos_para_parquet(base_dinamica)

    salvar_parquet_seguro(
        base_dinamica,
        ARQUIVO_PARQUET_BASE_DINAMICA,
    )

    resultados.append(
        (
            "Base Dinâmica",
            len(base_dinamica),
            len(base_dinamica.columns),
            ARQUIVO_PARQUET_BASE_DINAMICA,
        )
    )

    # -----------------------------------------------------------------
    # 2. Movimento Mortalidade/Peso - Lotes Abertos
    # -----------------------------------------------------------------
    mortalidade = consolidar_mortalidade_peso_abertos()
    mortalidade = normalizar_tipos_para_parquet(mortalidade)

    salvar_parquet_seguro(
        mortalidade,
        ARQUIVO_PARQUET_MORTALIDADE_PESO_ABERTOS,
    )

    resultados.append(
        (
            "Mortalidade/Peso - Lotes Abertos",
            len(mortalidade),
            len(mortalidade.columns),
            ARQUIVO_PARQUET_MORTALIDADE_PESO_ABERTOS,
        )
    )

    # -----------------------------------------------------------------
    # 3. Movimento Mortalidade/Peso - Lotes Fechados
    # -----------------------------------------------------------------
    mortalidade_fechados = consolidar_mortalidade_peso_fechados()
    mortalidade_fechados = normalizar_tipos_para_parquet(
        mortalidade_fechados
    )

    salvar_parquet_seguro(
        mortalidade_fechados,
        ARQUIVO_PARQUET_MORTALIDADE_PESO_FECHADOS,
    )

    resultados.append(
        (
            "Mortalidade/Peso - Lotes Fechados",
            len(mortalidade_fechados),
            len(mortalidade_fechados.columns),
            ARQUIVO_PARQUET_MORTALIDADE_PESO_FECHADOS,
        )
    )

    duracao = time.time() - inicio

    print()
    print("=" * 80)
    print("TRATAMENTO ZOOTÉCNICO FINALIZADO")
    print("=" * 80)

    for nome, linhas, colunas, arquivo in resultados:
        print()
        print(nome)
        print("  Linhas:", f"{linhas:,}")
        print("  Colunas:", colunas)
        print("  Parquet:", arquivo)
        print(
            "  Tamanho:",
            f"{arquivo.stat().st_size / 1024 / 1024:.2f} MB",
        )

    print()
    print("Tempo total:", f"{duracao:.2f} segundo(s)")
    print("=" * 80)

    return 0


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--completo",
        action="store_true",
        help=(
            "Compatibilidade com o Portal BI. "
            "O tratamento consolida todos os arquivos disponíveis."
        ),
    )

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help=(
            "Não aguarda ENTER ao terminar. "
            "Use no Portal ou servidor."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = 0

    try:
        exit_code = main()

    except Exception:
        exit_code = 1

        print()
        print("=" * 80)
        print(
            "ERRO NO TRATAMENTO ZOOTÉCNICO"
        )
        traceback.print_exc()
        print("=" * 80)

    finally:
        if not args.sem_pausa:
            try:
                pass  # Encerramento automatico: nao aguardar ENTER.
            except EOFError:
                pass

    raise SystemExit(exit_code)
