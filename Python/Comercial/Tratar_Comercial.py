# -*- coding: utf-8 -*-
r"""
TRATAMENTO COMERCIAL — FATURAMENTO POR CFOP

Segue o mesmo padrão utilizado no Tratar_Logistica:
- lê todos os Excel da pasta de exportação;
- encontra automaticamente o cabeçalho da tabela principal;
- mantém todas as linhas analíticas com Data válida;
- remove somente linhas vazias e totais;
- converte datas, códigos, pesos e valores;
- adiciona Empresa, Unidade e Arquivo_Origem;
- consolida todos os arquivos;
- remove duplicidades;
- salva PARQUET e CSV para uso no Power BI.

ENTRADA:
\\\\192.168.1.139\\Controladoria\\BI_Granja\Exportacoes\Comercial\Faturamento por CFOP

SAÍDA:
\\\\192.168.1.139\\Controladoria\\BI_Granja\Tratados\Comercial\comercial_faturamento_cfop_tratado.parquet
\\\\192.168.1.139\\Controladoria\\BI_Granja\Tratados\Comercial\comercial_faturamento_cfop_tratado.csv

Use:
    py Tratar_Comercial.py

No Portal/servidor:
    py Tratar_Comercial.py --sem-pausa
"""

import argparse
import glob
import os
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd


# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

PASTA_FATURAMENTO_CFOP = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Comercial\Faturamento por CFOP"
)

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Comercial"
)

ARQUIVO_PARQUET = (
    PASTA_SAIDA
    / "comercial_faturamento_cfop_tratado.parquet"
)

ARQUIVO_CSV = (
    PASTA_SAIDA
    / "comercial_faturamento_cfop_tratado.csv"
)

PASTA_SAIDA.mkdir(
    parents=True,
    exist_ok=True,
)


# =============================================================================
# MODO DE TRATAMENTO
# =============================================================================

USAR_INCREMENTAL = True


def preparar_incremental_comercial(files):
    """
    Modo diário:
    - reaproveita o Parquet existente;
    - lê apenas Excel novo ou alterado;
    - remove do histórico a versão antiga dos arquivos reprocessados.

    No --completo:
    - relê todos os Excel.
    """
    files = list(files)

    if (
        not USAR_INCREMENTAL
        or not ARQUIVO_PARQUET.exists()
        or ARQUIVO_PARQUET.stat().st_size <= 0
    ):
        print(f"Modo COMPLETO: {len(files)} arquivo(s) serão lidos.")
        return files, None

    try:
        existente = pd.read_parquet(ARQUIVO_PARQUET)
    except Exception as erro:
        print(f"Não foi possível reaproveitar o Parquet: {erro}")
        print("Será feito tratamento COMPLETO.")
        return files, None

    if existente.empty or "Arquivo_Origem" not in existente.columns:
        print("Parquet antigo não possui Arquivo_Origem. Será feito tratamento COMPLETO uma vez.")
        return files, None

    nomes_existentes = set(
        existente["Arquivo_Origem"].dropna().astype("string").astype(str)
    )
    mtime_parquet = ARQUIVO_PARQUET.stat().st_mtime

    pendentes = []
    for arquivo in files:
        try:
            if (
                arquivo.name not in nomes_existentes
                or arquivo.stat().st_mtime > mtime_parquet + 0.5
            ):
                pendentes.append(arquivo)
        except OSError:
            pendentes.append(arquivo)

    if not pendentes:
        print("Modo INCREMENTAL: nenhum Excel novo/alterado.")
        print("Reutilizando o Parquet existente.")
        return [], existente

    nomes_pendentes = {a.name for a in pendentes}
    existente = existente[
        ~existente["Arquivo_Origem"].astype("string").isin(nomes_pendentes)
    ].copy()

    # valor antigo para perder na deduplicação para qualquer linha nova
    existente["_Arquivo_Modificado_Em"] = pd.Timestamp("1900-01-01")

    print(
        f"Modo INCREMENTAL: {len(files)} arquivo(s) na pasta | "
        f"{len(pendentes)} novo(s)/alterado(s) | "
        f"{len(files)-len(pendentes)} reaproveitado(s)."
    )
    return pendentes, existente


# =============================================================================
# UTILITÁRIOS
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
    """
    Converte números vindos do Excel oficial.

    Exemplos:
        1.234,56   -> 1234.56
        1.234,56-  -> -1234.56
        (1.234,56) -> -1234.56
        9.28       -> 9.28
        -1000      -> -1000
    """

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
    """
    Converte datas do Excel, datetime ou texto.

    Trata corretamente números seriais do Excel, evitando que valores como
    46100 sejam interpretados como nanossegundos próximos de 1970.
    """
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
            r"^\s*(total|totais|subtotal)\s*:?\s*$",
            case=False,
            regex=True,
            na=False,
        )
    )

    return df.loc[
        ~total_mask.any(axis=1)
    ].copy()


def listar_arquivos_excel():
    files = []

    for pattern in (
        "*.xlsx",
        "*.xlsm",
        "*.xls",
    ):
        files.extend(
            PASTA_FATURAMENTO_CFOP.glob(pattern)
        )

    return sorted(
        [
            file
            for file in files
            if (
                file.is_file()
                and not file.name.startswith("~$")
            )
        ],
        key=lambda file: (
            file.stat().st_mtime,
            file.name.lower(),
        ),
    )


# =============================================================================
# LEITURA DO EXCEL OFICIAL
# =============================================================================

def encontrar_linha_cabecalho(
    caminho_arquivo: Path,
    max_rows: int = 300,
) -> int:
    """
    Localiza a linha principal:
    Vendedor | Nome | Data | Produto | Valor Total Faturado
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

    required = {
        "vendedor",
        "nome",
        "data",
        "produto",
        "valor total faturado",
    }

    best_line = None
    best_score = 0

    for index in range(len(preview)):
        row_keys = {
            header_key(value)
            for value in preview.iloc[index].tolist()
            if clean_col_name(value)
        }

        if required.issubset(row_keys):
            return index

        score = len(
            required.intersection(row_keys)
        )

        if score > best_score:
            best_score = score
            best_line = index

    if best_line is not None and best_score >= 4:
        print(
            f"AVISO: cabeçalho parcial utilizado "
            f"na linha {best_line + 1} "
            f"({best_score}/5 campos)."
        )
        return best_line

    raise ValueError(
        "Não encontrei o cabeçalho principal "
        f"no arquivo: {caminho_arquivo.name}"
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

    print(
        f"  Cabeçalho encontrado na linha: "
        f"{header_row + 1}"
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

    df = (
        df.dropna(
            axis=1,
            how="all",
        )
        .dropna(
            axis=0,
            how="all",
        )
        .copy()
    )

    # Remove linhas de totais e resumos, mas não limita
    # a leitura à última linha numérica de vendedor.
    df = drop_total_rows(df)

    return df.reset_index(drop=True)


# =============================================================================
# METADADOS DO TOPO
# =============================================================================

def ler_metadados_topo(
    caminho_arquivo: Path,
    header_row: int,
) -> dict:
    """
    Lê os pares de cabeçalho e valor acima da tabela principal.

    No arquivo oficial:
    linha 5 -> Empresa | Descrição | Unidade | Descrição | Início...
    linha 6 -> 1       | Granja... | 10      | Ave Nova | ...
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
        nrows=header_row,
        dtype=object,
        engine=engine,
    )

    metadata = {}

    for row_index in range(
        max(len(raw) - 1, 0)
    ):
        labels = raw.iloc[
            row_index
        ].tolist()

        values = raw.iloc[
            row_index + 1
        ].tolist()

        non_empty_labels = [
            clean_col_name(value)
            for value in labels
            if clean_col_name(value)
        ]

        if len(non_empty_labels) < 2:
            continue

        for column_index, label in enumerate(labels):
            label_text = clean_col_name(label)

            if not label_text:
                continue

            if column_index >= len(values):
                continue

            value = values[column_index]

            if not clean_col_name(value):
                continue

            key = clean_col_name(label_text)

            if key in metadata:
                suffix = 2

                while f"{key}_{suffix}" in metadata:
                    suffix += 1

                key = f"{key}_{suffix}"

            metadata[key] = value

    return metadata


def localizar_metadata(
    metadata: dict,
    *names,
):
    normalized = {
        header_key(key): value
        for key, value in metadata.items()
    }

    for name in names:
        key = header_key(name)

        if key in normalized:
            return normalized[key]

    return None


def definir_empresa(
    caminho_arquivo: Path,
    metadata: dict,
):
    empresa_codigo = localizar_metadata(
        metadata,
        "Empresa",
    )

    empresa_descricao = localizar_metadata(
        metadata,
        "Descrição",
    )

    unidade_codigo = localizar_metadata(
        metadata,
        "Unidade",
    )

    # Como existem duas colunas chamadas Descrição no topo,
    # a segunda normalmente vira Descrição_2.
    unidade_descricao = localizar_metadata(
        metadata,
        "Descrição_2",
        "Unidade Descrição",
        "Descrição Unidade",
    )

    search_text = strip_accents(
        " ".join(
            [
                clean_col_name(caminho_arquivo.name),
                clean_col_name(empresa_descricao),
                clean_col_name(unidade_descricao),
            ]
        )
    ).lower()

    if (
        "avenova" in search_text
        or "ave nova" in search_text
    ):
        empresa = "Ave Nova"

    elif "ribeirao" in search_text:
        empresa = "CD Ribeirão das Neves"

    elif "januaria" in search_text:
        empresa = "CD Januária"

    elif "real" in search_text:
        empresa = "Real Alimentos"

    else:
        empresa = (
            clean_col_name(unidade_descricao)
            or clean_col_name(empresa_descricao)
            or "Não Identificada"
        )

    return {
        "Empresa": empresa,
        "Empresa_Codigo": empresa_codigo,
        "Empresa_Descricao": empresa_descricao,
        "Unidade_Codigo": unidade_codigo,
        "Unidade_Descricao": unidade_descricao,
    }


# =============================================================================
# TRATAMENTO CFOP
# =============================================================================

def padronizar_nomes_colunas(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    O Excel possui duas colunas chamadas Descrição:
    - primeira: descrição do produto;
    - segunda: descrição do CFOP.
    """
    rename = {}

    description_columns = [
        column
        for column in df.columns
        if header_key(column) == "descricao"
        or header_key(column).startswith("descricao ")
    ]

    if description_columns:
        rename[description_columns[0]] = (
            "Descrição Produto"
        )

    if len(description_columns) >= 2:
        rename[description_columns[1]] = (
            "Descrição CFOP"
        )

    direct_mapping = {
        "mes": "Mes",
        "oc principal": "OC Principal",
        "rota cliente": "Rota Cliente",
        "rota pedido": "Rota Pedido",
        "tipo de cliente": "Tipo de Cliente",
        "pre base": "Pre.Base",
        "preco praticado": "Preço Praticado",
        "valor produto": "Valor Produto",
        "desconto comercial": "Desconto Comercial",
        "valor total faturado": "Valor Total Faturado",
        "desc finan": "Desc. Finan.",
        "frete kg": "Frete/Kg",
        "nota refaturada": "Nota Refaturada",
        "romaneio refaturada": "Romaneio Refaturada",
        "nota devolucao": "Nota Devolução",
        "cliente original": "Cliente Original",
        "cond pag cliente": "Cond. Pag. Cliente",
        "cond pag nota": "Cond. Pag. Nota",
    }

    for column in df.columns:
        key = header_key(column)

        if key in direct_mapping:
            rename[column] = direct_mapping[key]

    return df.rename(
        columns=rename
    )


def tratar_faturamento_cfop(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho(
        caminho_arquivo
    )

    metadata = ler_metadados_topo(
        caminho_arquivo,
        header_row,
    )

    company_data = definir_empresa(
        caminho_arquivo,
        metadata,
    )

    df = ler_tabela_principal(
        caminho_arquivo
    )

    df = padronizar_nomes_colunas(df)

    if "Data" not in df.columns:
        raise ValueError(
            "A coluna Data não foi encontrada em "
            f"{caminho_arquivo.name}"
        )

    # A tabela analítica é definida pelas linhas com Data válida.
    # Assim todas as linhas de faturamento são preservadas,
    # inclusive vendedor 0 ou campos de vendedor vazios.
    df["Data"] = parse_known_dates(
        df["Data"]
    )

    linhas_antes_data = len(df)

    data_minima_valida = pd.Timestamp("2000-01-01")
    data_maxima_valida = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)

    df = df[
        df["Data"].notna()
        & df["Data"].between(
            data_minima_valida,
            data_maxima_valida,
        )
    ].copy()

    linhas_sem_data = (
        linhas_antes_data - len(df)
    )

    if linhas_sem_data:
        print(
            f"  Linhas não analíticas removidas "
            f"(sem Data válida): {linhas_sem_data:,}"
        )

    numeric_columns = [
        "Vendedor",
        "Mes",
        "Uni",
        "Série",
        "Número",
        "Pedido",
        "Redespacho",
        "Romaneio",
        "Frete",
        "Cliente",
        "Rede",
        "Rota Cliente",
        "Rota Pedido",
        "Produto",
        "Volumes",
        "Peso",
        "Lista",
        "Ocorr",
        "Pre.Base",
        "Preço Praticado",
        "Valor Produto",
        "Desconto Comercial",
        "Valor Total Faturado",
        "Desc. Finan.",
        "Frete/Kg",
        "Nota Refaturada",
        "Romaneio Refaturada",
        "Nota Devolução",
        "Cliente Original",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = to_numeric_ptbr(
                df[column]
            )

    text_columns = [
        "Nome",
        "Meio Venda",
        "Devolução",
        "OC Principal",
        "Razão Social",
        "Tipo de Cliente",
        "Nome Fantasia",
        "Cidade",
        "UF",
        "Ramo Ativ.",
        "Descrição Produto",
        "UM",
        "Família",
        "CFOP",
        "Descrição CFOP",
        "Cond. Pag. Cliente",
        "Cond. Pag. Nota",
    ]

    for column in text_columns:
        if column in df.columns:
            df[column] = normalize_text(
                df[column]
            )

    # CFOP deve permanecer como texto, pois possui hífen e zeros.
    if "CFOP" in df.columns:
        df["CFOP"] = normalize_text(
            df["CFOP"]
        )

    # Colunas de origem
    for column, value in company_data.items():
        df[column] = value

    df["Arquivo_Origem"] = (
        caminho_arquivo.name
    )

    df["_Arquivo_Modificado_Em"] = (
        datetime.fromtimestamp(
            caminho_arquivo.stat().st_mtime
        )
    )

    # Colunas auxiliares para o Power BI
    df["Ano"] = df["Data"].dt.year
    df["Mes_Numero"] = df["Data"].dt.month
    df["Dia"] = df["Data"].dt.day
    df["AnoMes"] = (
        df["Data"].dt.year * 100
        + df["Data"].dt.month
    )

    if "Valor Total Faturado" in df.columns:
        df["Valor_Faturado_Liquido"] = (
            df["Valor Total Faturado"]
        )

        df["Valor_Faturado_Absoluto"] = (
            df["Valor Total Faturado"].abs()
        )

    if "Peso" in df.columns:
        df["Peso_KG"] = df["Peso"]
        df["Peso_KG_Absoluto"] = (
            df["Peso"].abs()
        )

    if (
        "Valor Total Faturado" in df.columns
        and "Peso" in df.columns
    ):
        df["Preco_Medio_Calculado"] = (
            df["Valor Total Faturado"]
            .div(df["Peso"])
            .where(df["Peso"].ne(0))
        )

    if "CFOP" in df.columns:
        primeiro_digito = (
            df["CFOP"]
            .astype("string")
            .str.strip()
            .str[:1]
        )

        df["Tipo_Movimento"] = (
            primeiro_digito.map(
                {
                    "1": "Entrada",
                    "2": "Entrada",
                    "3": "Entrada",
                    "5": "Saída",
                    "6": "Saída",
                    "7": "Saída",
                }
            )
            .fillna("Não Identificado")
        )

    # Códigos em texto para filtros e relacionamentos no Power BI.
    code_columns = [
        "Vendedor",
        "Uni",
        "Série",
        "Número",
        "Pedido",
        "Cliente",
        "Rede",
        "Produto",
        "Nota Devolução",
    ]

    for column in code_columns:
        if column not in df.columns:
            continue

        df[f"{column}_Texto"] = (
            df[column]
            .astype("Float64")
            .astype("Int64")
            .astype("string")
        )

    return df.reset_index(drop=True)


# =============================================================================
# CONSOLIDAÇÃO
# =============================================================================

def chave_deduplicacao(
    df: pd.DataFrame,
):
    """
    Chave de negócio para evitar duplicidade quando:
    - um período de 15 dias é substituído por arquivos diários;
    - o mesmo dia é baixado novamente;
    - arquivos sobrepostos existem na pasta.
    """
    candidates = [
        "Empresa",
        "Data",
        "Vendedor",
        "Série",
        "Número",
        "Pedido",
        "Cliente",
        "Produto",
        "CFOP",
        "Volumes",
        "Peso",
        "Valor Produto",
        "Valor Total Faturado",
        "Nota Devolução",
    ]

    return [
        column
        for column in candidates
        if column in df.columns
    ]


def consolidar_faturamento_cfop():
    files_todos = listar_arquivos_excel()

    if not files_todos:
        raise FileNotFoundError(
            "Nenhum Excel encontrado em: "
            f"{PASTA_FATURAMENTO_CFOP}"
        )

    files, base_existente = preparar_incremental_comercial(files_todos)

    if not files and base_existente is not None:
        return base_existente.reset_index(drop=True)

    print(
        f"Arquivos que serão processados agora: {len(files)}"
    )

    bases = []
    if base_existente is not None and not base_existente.empty:
        bases.append(base_existente)

    errors = []

    for index, file in enumerate(
        files,
        start=1,
    ):
        print()
        print("=" * 80)
        print(
            f"[{index}/{len(files)}] "
            f"Processando: {file.name}"
        )
        print("=" * 80)

        try:
            treated = tratar_faturamento_cfop(
                file
            )

            print(
                f"OK: {file.name} "
                f"-> {len(treated):,} linhas"
            )

            if not treated.empty:
                bases.append(treated)

        except Exception as error:
            errors.append(
                (file.name, str(error))
            )

            print(
                f"ERRO: {file.name}"
            )
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo foi tratado com sucesso."
        )

    print()
    print("=" * 80)
    print("CONSOLIDANDO TODOS OS ARQUIVOS")
    print("=" * 80)

    result = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    lines_before = len(result)

    key = chave_deduplicacao(result)

    result = result.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    if key:
        result = result.drop_duplicates(
            subset=key,
            keep="last",
        )
    else:
        subset = [
            column
            for column in result.columns
            if column not in {
                "Arquivo_Origem",
                "_Arquivo_Modificado_Em",
            }
        ]

        result = result.drop_duplicates(
            subset=subset,
            keep="last",
        )

    result = result.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    duplicated_removed = (
        lines_before - len(result)
    )

    print(
        f"Linhas antes da deduplicação: "
        f"{lines_before:,}"
    )

    print(
        f"Duplicadas removidas: "
        f"{duplicated_removed:,}"
    )

    print(
        f"Linhas finais: "
        f"{len(result):,}"
    )

    if "Data" in result.columns:
        print(
            "Data mínima:",
            result["Data"].min(),
        )

        print(
            "Data máxima:",
            result["Data"].max(),
        )

    if "Peso" in result.columns:
        print(
            "Peso total:",
            f"{result['Peso'].sum():,.2f}",
        )

    if "Valor Total Faturado" in result.columns:
        print(
            "Faturamento total:",
            f"{result['Valor Total Faturado'].sum():,.2f}",
        )

    if errors:
        print()
        print(
            f"AVISOS: {len(errors)} arquivo(s) "
            f"não foram tratados:"
        )

        for file_name, error in errors:
            print(
                f"  - {file_name}: {error}"
            )

    return result


# =============================================================================
# GRAVAÇÃO SEGURA
# =============================================================================

def salvar_parquet_seguro(
    df: pd.DataFrame,
    destination: Path,
):
    """
    Grava primeiro em arquivo temporário.
    Só substitui o Parquet oficial após concluir.
    """
    temporary = destination.with_suffix(
        ".parquet.tmp"
    )

    if temporary.exists():
        temporary.unlink()

    df.to_parquet(
        temporary,
        index=False,
    )

    if destination.exists():
        destination.unlink()

    temporary.replace(destination)


def salvar_csv_seguro(
    df: pd.DataFrame,
    destination: Path,
):
    temporary = destination.with_suffix(
        ".csv.tmp"
    )

    if temporary.exists():
        temporary.unlink()

    df.to_csv(
        temporary,
        index=False,
        sep=";",
        encoding="utf-8-sig",
    )

    if destination.exists():
        destination.unlink()

    temporary.replace(destination)


# =============================================================================
# MAIN
# =============================================================================

def main():
    start = time.time()

    print("=" * 80)
    print(
        "TRATAMENTO COMERCIAL — "
        "FATURAMENTO POR CFOP"
    )
    print(
        "Entrada:",
        PASTA_FATURAMENTO_CFOP,
    )
    print(
        "Saída:",
        PASTA_SAIDA,
    )
    print("=" * 80)

    faturamento = (
        consolidar_faturamento_cfop()
    )

    print()
    print("=" * 80)
    print("GERANDO PARQUET")
    print("=" * 80)

    salvar_parquet_seguro(
        faturamento,
        ARQUIVO_PARQUET,
    )

    print(
        "Parquet salvo:",
        ARQUIVO_PARQUET,
    )

    print()
    print("=" * 80)
    print("GERANDO CSV DE CONFERÊNCIA")
    print("=" * 80)

    salvar_csv_seguro(
        faturamento,
        ARQUIVO_CSV,
    )

    print(
        "CSV salvo:",
        ARQUIVO_CSV,
    )

    duration = time.time() - start

    print()
    print("=" * 80)
    print(
        "TRATAMENTO COMERCIAL FINALIZADO"
    )
    print(
        "Linhas finais:",
        f"{len(faturamento):,}",
    )
    print(
        "Tempo:",
        f"{duration / 60:.2f} minuto(s)",
    )
    print(
        "Parquet:",
        ARQUIVO_PARQUET,
    )
    print(
        "CSV:",
        ARQUIVO_CSV,
    )
    print("=" * 80)

    return 0


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help=(
            "Não aguarda ENTER ao terminar. "
            "Use no Portal ou servidor."
        ),
    )

    parser.add_argument(
        "--completo",
        action="store_true",
        help="Relê todos os Excel e reconstrói a base completa.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    USAR_INCREMENTAL = not args.completo

    print(
        "Modo de tratamento:",
        "INCREMENTAL - somente Excel novo/alterado"
        if USAR_INCREMENTAL
        else "COMPLETO - todos os Excel",
        flush=True,
    )

    exit_code = 0

    try:
        exit_code = main()

    except Exception:
        exit_code = 1

        print()
        print("=" * 80)
        print(
            "ERRO NO TRATAMENTO COMERCIAL"
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
