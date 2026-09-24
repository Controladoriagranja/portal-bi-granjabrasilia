# -*- coding: utf-8 -*-
r"""
TRATAMENTO SUPRIMENTOS — CONTAS PAGAS + ORDENS DE COMPRAS

OBJETIVO
- lê todos os Excel oficiais gerados pelo robô de Contas Pagas;
- identifica automaticamente o cabeçalho da tabela principal;
- trata arquivos de Fornecedor e Rede de Fornecedores;
- adiciona Tipo_Credor_Origem e Arquivo_Origem;
- converte datas, códigos e valores;
- remove linhas vazias, totais e registros repetidos;
- mantém a versão mais recente quando existem períodos sobrepostos;
- gera os Parquets individuais de Contas Pagas, Ordens de Compras, Usuários, Solicitações, Títulos Agrupados e Relação OC x NF;
- trata também o novo relatório Notas Fiscais do Item, organizado por empresa;
- mantém os Parquets-base separados e tratados;
- o desmembramento de AGT e a montagem da base final de Contas Pagas serão feitos no Power Query.

ENTRADA:
\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Contas Pagas

SCRIPT:
\\192.168.1.139\Controladoria\BI_Granja\Python\Suprimentos\Tratar_Suprimentos.py

SAÍDA:
\\192.168.1.139\Controladoria\BI_Granja\Tratados\Suprimentos\suprimentos_contas_pagas_tratado.parquet

USO MANUAL:
    py Tratar_Suprimentos.py

USO PELO PORTAL:
    py Tratar_Suprimentos.py --sem-pausa
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

PASTA_CONTAS_PAGAS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Contas Pagas"
)

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Suprimentos"
)

ARQUIVO_PARQUET = (
    PASTA_SAIDA
    / "suprimentos_contas_pagas_tratado.parquet"
)

PASTA_ORDENS_COMPRAS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Ordens de Compras Emitidas"
)

ARQUIVO_PARQUET_ORDENS = (
    PASTA_SAIDA
    / "suprimentos_ordens_compras_emitidas_tratado.parquet"
)

PASTA_RELATORIO_USUARIOS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Relatorio de Usuarios"
)

ARQUIVO_PARQUET_USUARIOS = (
    PASTA_SAIDA
    / "suprimentos_relatorio_usuarios_tratado.parquet"
)


PASTA_SOLICITACOES_REQUISITANTE = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Solicitacoes por Requisitante"
)

ARQUIVO_PARQUET_SOLICITACOES = (
    PASTA_SAIDA
    / "suprimentos_solicitacoes_requisitante_tratado.parquet"
)


PASTA_TITULOS_AGRUPADOS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Titulos Agrupados"
)

ARQUIVO_PARQUET_TITULOS_AGRUPADOS = (
    PASTA_SAIDA
    / "suprimentos_titulos_agrupados_tratado.parquet"
)

PASTA_RELACAO_OC_NF = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Relacao OC x NF"
)

ARQUIVO_PARQUET_RELACAO_OC_NF = (
    PASTA_SAIDA
    / "suprimentos_relacao_oc_nf_tratado.parquet"
)

PASTA_NOTAS_FISCAIS_ITEM = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Notas Fiscais do Item"
)

ARQUIVO_PARQUET_NOTAS_FISCAIS_ITEM = (
    PASTA_SAIDA
    / "suprimentos_notas_fiscais_item_tratado.parquet"
)



DATA_MINIMA_PERMITIDA = pd.Timestamp("2025-01-01")

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
    """
    Converte números do Excel oficial.

    Exemplos:
        1.234,56   -> 1234.56
        1.234,56-  -> -1234.56
        (1.234,56) -> -1234.56
        1000       -> 1000
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
    Também trata números seriais do Excel.
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
            r"^\s*(total|totais|subtotal|total geral)\s*:?\s*$",
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
            PASTA_CONTAS_PAGAS.glob(pattern)
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


def detectar_tipo_credor(caminho_arquivo: Path) -> str:
    nome = header_key(caminho_arquivo.stem)

    if "contas pagas rede" in nome:
        return "Rede de Fornecedores"

    if "contas pagas fornecedor" in nome:
        return "Fornecedor"

    if "rede" in nome:
        return "Rede de Fornecedores"

    return "Fornecedor"


def extrair_periodo_nome(caminho_arquivo: Path):
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
    max_rows: int = 350,
) -> int:
    """
    Localiza o cabeçalho principal do relatório de Contas a Pagar.

    O relatório normalmente contém campos como:
    Nome, Título, Vencimento Atual, Pagamento, Vl.Nominal e Vl.Pago.
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

    required_groups = [
        {"nome"},
        {"titulo", "título"},
        {"vencimento atual"},
        {"pagamento"},
        {"vl nominal", "vl nominal r"},
        {"vl pago", "vl pago r"},
    ]

    best_line = None
    best_score = 0

    for index in range(len(preview)):
        row_keys = {
            header_key(value)
            for value in preview.iloc[index].tolist()
            if clean_col_name(value)
        }

        score = 0

        for group in required_groups:
            normalized_group = {
                header_key(item)
                for item in group
            }

            if row_keys.intersection(
                normalized_group
            ):
                score += 1

        if score >= 5:
            return index

        if score > best_score:
            best_score = score
            best_line = index

    if best_line is not None and best_score >= 4:
        print(
            f"AVISO: cabeçalho parcial utilizado "
            f"na linha {best_line + 1} "
            f"({best_score}/6 grupos)."
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
        "  Cabeçalho encontrado na linha:",
        header_row + 1,
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

    df = drop_total_rows(df)

    return df.reset_index(drop=True)


# =============================================================================
# 4) PADRONIZAÇÃO DOS NOMES DAS COLUNAS
# =============================================================================

def padronizar_nomes_colunas(
    df: pd.DataFrame,
) -> pd.DataFrame:
    mapping = {
        "uni": "Uni.",
        "unidade": "Uni.",
        "nome grupo": "Nome Grupo",
        "s grupo": "S.Grupo",
        "subgrupo": "S.Grupo",
        "tp pessoa": "Tp.Pessoa",
        "tipo pessoa": "Tp.Pessoa",
        "titulo": "Título",
        "par": "Par.",
        "parcela": "Par.",
        "situacao": "Sit.",
        "sit": "Sit.",
        "codigo": "Código",
        "documento": "Doc.",
        "doc": "Doc.",
        "tipo lanc": "Tipo Lanç.",
        "tipo lancamento": "Tipo Lanç.",
        "numero": "Número",
        "inclusao": "Inclusão",
        "emissao": "Emissão",
        "vencimento original": "Vencimento Original",
        "vencimento atual": "Vencimento Atual",
        "pagamento": "Pagamento",
        "vl nominal": "Vl.Nominal",
        "valor nominal": "Vl.Nominal",
        "vl pago": "Vl.Pago",
        "valor pago": "Vl.Pago",
        "adf dev": "ADF/DEV",
        "outros juros": "Outros Juros",
        "usuario lib": "Usuário Lib.",
        "usuario liberador": "Usuário Lib.",
        "dados banc": "Dados Banc.",
        "dados bancarios": "Dados Banc.",
        "resumo pgto": "Resumo Pgto.",
        "resumo pagamento": "Resumo Pgto.",
    }

    rename = {}

    for column in df.columns:
        key = header_key(column)

        if key in mapping:
            rename[column] = mapping[key]

    return df.rename(
        columns=rename
    )


# =============================================================================
# 5) TRATAMENTO DE UM ARQUIVO
# =============================================================================

def tratar_contas_pagas(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    df = ler_tabela_principal(
        caminho_arquivo
    )

    df = padronizar_nomes_colunas(
        df
    )

    # Ordem de Compra pode conter um único número ou vários números
    # separados por vírgula. Portanto, deve permanecer como texto.
    for column in list(df.columns):
        if header_key(column) in {
            "ord compra",
            "ordem compra",
            "ordem de compra",
        }:
            if column != "Ord.Compra":
                df = df.rename(
                    columns={column: "Ord.Compra"}
                )

    date_columns = [
        "Inclusão",
        "Emissão",
        "Vencimento Original",
        "Vencimento Atual",
        "Pagamento",
    ]

    for column in date_columns:
        if column in df.columns:
            df[column] = parse_known_dates(
                df[column]
            )

    # Pelo relatório estar configurado em "Pagos por Pagamento",
    # a coluna Pagamento é a principal data analítica.
    if "Pagamento" not in df.columns:
        raise ValueError(
            "A coluna Pagamento não foi encontrada em "
            f"{caminho_arquivo.name}"
        )

    linhas_antes = len(df)

    df = df[
        df["Pagamento"].notna()
        & (df["Pagamento"] >= DATA_MINIMA_PERMITIDA)
        & (
            df["Pagamento"]
            <= pd.Timestamp.today().normalize()
            + pd.Timedelta(days=1)
        )
    ].copy()

    removidas = linhas_antes - len(df)

    if removidas:
        print(
            "  Linhas não analíticas removidas:",
            f"{removidas:,}",
        )

    numeric_columns = [
        "Grupo",
        "S.Grupo",
        "Código",
        "Atraso",
        "Vl.Nominal",
        "Vl.Pago",
        "ADF/DEV",
        "Juros",
        "Outros Juros",
        "Desconto",
        "Saldo",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = to_numeric_ptbr(
                df[column]
            )

    text_columns = [
        "Uni.",
        "Nome Grupo",
        "Tp.Pessoa",
        "Título",
        "Par.",
        "Sit.",
        "Tipo",
        "Nome",
        "Doc.",
        "Tipo Lanç.",
        "Número",
        "Projeto",
        "Usuário Lib.",
        "Dados Banc.",
        "Resumo Pgto.",
        "Usuário",
        "Ord.Compra",
    ]

    for column in text_columns:
        if column in df.columns:
            df[column] = normalize_text(
                df[column]
            )

    tipo_credor = detectar_tipo_credor(
        caminho_arquivo
    )

    periodo_inicio, periodo_fim = (
        extrair_periodo_nome(
            caminho_arquivo
        )
    )

    df["Tipo_Credor_Origem"] = tipo_credor
    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # O relatório por Fornecedor será a base principal para cartões e totais.
    # O relatório por Rede fica disponível para análise de rede sem misturar
    # automaticamente os valores nas medidas gerais.
    df["Base_Principal_Flag"] = (
        "Sim"
        if tipo_credor == "Fornecedor"
        else "Não"
    )

    # Colunas auxiliares para o Power BI.
    df["Ano_Pagamento"] = df["Pagamento"].dt.year
    df["Mes_Numero_Pagamento"] = df["Pagamento"].dt.month
    df["Dia_Pagamento"] = df["Pagamento"].dt.day
    df["AnoMes_Pagamento"] = (
        df["Pagamento"].dt.year * 100
        + df["Pagamento"].dt.month
    )

    if "Emissão" in df.columns:
        df["Dias_Emissao_Para_Pagamento"] = (
            df["Pagamento"] - df["Emissão"]
        ).dt.days

    if "Vencimento Atual" in df.columns:
        df["Dias_Vencimento_Para_Pagamento"] = (
            df["Pagamento"]
            - df["Vencimento Atual"]
        ).dt.days

        df["Status_Prazo_Pagamento"] = pd.Series(
            pd.NA,
            index=df.index,
            dtype="string",
        )

        mask = (
            df["Pagamento"].notna()
            & df["Vencimento Atual"].notna()
        )

        df.loc[
            mask
            & (
                df["Pagamento"]
                <= df["Vencimento Atual"]
            ),
            "Status_Prazo_Pagamento",
        ] = "No Prazo"

        df.loc[
            mask
            & (
                df["Pagamento"]
                > df["Vencimento Atual"]
            ),
            "Status_Prazo_Pagamento",
        ] = "Em Atraso"

    if (
        "Vl.Nominal" in df.columns
        and "Vl.Pago" in df.columns
    ):
        df["Diferenca_Nominal_Pago"] = (
            df["Vl.Pago"]
            - df["Vl.Nominal"]
        )

    # Códigos em texto para filtros e relacionamentos.
    for column in [
        "Grupo",
        "S.Grupo",
        "Código",
    ]:
        if column not in df.columns:
            continue

        numeric = pd.to_numeric(
            df[column],
            errors="coerce",
        )

        df[f"{column}_Texto"] = (
            numeric.astype("Float64")
            .astype("Int64")
            .astype("string")
        )

    return df.reset_index(drop=True)


# =============================================================================
# 6) CHAVE E CONSOLIDAÇÃO
# =============================================================================

def chave_deduplicacao(
    df: pd.DataFrame,
):
    """
    Remove duplicidades causadas por:
    - reprocessamento do mês atual;
    - arquivos mensais sobrepostos;
    - nova geração do mesmo período.

    Tipo_Credor_Origem faz parte da chave para não eliminar o registro
    correspondente da visão por Rede.
    """
    candidates = [
        "Tipo_Credor_Origem",
        "Uni.",
        "Título",
        "Par.",
        "Código",
        "Doc.",
        "Número",
        "Pagamento",
        "Vl.Nominal",
        "Vl.Pago",
    ]

    return [
        column
        for column in candidates
        if column in df.columns
    ]


def consolidar_contas_pagas():
    files = listar_arquivos_excel()

    if not files:
        raise FileNotFoundError(
            "Nenhum Excel encontrado em: "
            f"{PASTA_CONTAS_PAGAS}"
        )

    print(
        "Arquivos encontrados:",
        len(files),
    )

    bases = []
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
            treated = tratar_contas_pagas(
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

    result = result.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    key = chave_deduplicacao(
        result
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
                "Periodo_Arquivo_Inicio",
                "Periodo_Arquivo_Fim",
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
        "Linhas antes da deduplicação:",
        f"{lines_before:,}",
    )

    print(
        "Duplicadas removidas:",
        f"{duplicated_removed:,}",
    )

    print(
        "Linhas finais:",
        f"{len(result):,}",
    )

    if "Pagamento" in result.columns:
        print(
            "Pagamento mínimo:",
            result["Pagamento"].min(),
        )

        print(
            "Pagamento máximo:",
            result["Pagamento"].max(),
        )

    for column in [
        "Vl.Nominal",
        "Vl.Pago",
        "Juros",
        "Desconto",
    ]:
        if column in result.columns:
            print(
                f"Total {column}:",
                f"{result[column].sum():,.2f}",
            )

    if "Tipo_Credor_Origem" in result.columns:
        print()
        print("Linhas por origem:")

        for tipo, quantidade in (
            result["Tipo_Credor_Origem"]
            .value_counts(dropna=False)
            .items()
        ):
            print(
                f"  {tipo}: {quantidade:,}"
            )

    if errors:
        print()
        print(
            f"AVISOS: {len(errors)} arquivo(s) "
            "não foram tratados:"
        )

        for file_name, error in errors:
            print(
                f"  - {file_name}: {error}"
            )

    return result


def normalizar_tipos_para_parquet(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Evita erros do PyArrow causados por colunas object com tipos misturados.

    Exemplo:
        Ord.Compra possui alguns valores inteiros e outros como
        "306111, 306165".

    Regra:
    - datetime permanece datetime;
    - números permanecem numéricos;
    - bool permanece bool;
    - colunas object/string viram texto padronizado.
    """
    result = df.copy()

    for column in result.columns:
        series = result[column]

        if pd.api.types.is_datetime64_any_dtype(series):
            continue

        if pd.api.types.is_numeric_dtype(series):
            continue

        if pd.api.types.is_bool_dtype(series):
            continue

        result[column] = normalize_text(
            series
        )

    return result


# =============================================================================
# 7) GRAVAÇÃO SEGURA DO PARQUET
# =============================================================================

def salvar_parquet_seguro(
    df: pd.DataFrame,
    destination: Path,
):
    """
    Grava primeiro em arquivo temporário.
    O Parquet oficial só é substituído após a gravação terminar.
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

    if not temporary.exists():
        raise RuntimeError(
            "O arquivo temporário do Parquet não foi criado."
        )

    if temporary.stat().st_size == 0:
        raise RuntimeError(
            "O arquivo temporário do Parquet ficou vazio."
        )

    if destination.exists():
        destination.unlink()

    temporary.replace(
        destination
    )



# =============================================================================
# 8) ORDENS DE COMPRAS EMITIDAS
# =============================================================================

def listar_arquivos_ordens_compras():
    arquivos = []

    if not PASTA_ORDENS_COMPRAS.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(
            PASTA_ORDENS_COMPRAS.glob(pattern)
        )

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def extrair_data_ordem_nome(caminho_arquivo: Path):
    """
    Exemplos esperados:
      ordens_compras_emitidas_2026-08-01.xlsx
      ordens_compras_emitidas_2026-08-01_ate_2026-08-31.xlsx
    """
    datas = re.findall(
        r"(20\d{2}-\d{2}-\d{2})",
        caminho_arquivo.name,
    )

    if not datas:
        return pd.NaT, pd.NaT

    try:
        inicio = pd.Timestamp(
            datetime.strptime(
                datas[0],
                "%Y-%m-%d",
            )
        )

        fim = inicio

        if len(datas) >= 2:
            fim = pd.Timestamp(
                datetime.strptime(
                    datas[1],
                    "%Y-%m-%d",
                )
            )

        return inicio, fim

    except Exception:
        return pd.NaT, pd.NaT


def encontrar_linha_cabecalho_ordens(
    caminho_arquivo: Path,
    max_rows: int = 400,
) -> int:
    """
    Localiza o cabeçalho da tabela analítica de Ordens de Compra.

    O relatório pode trazer linhas de título/filtros antes da tabela,
    então não usamos posição fixa.
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
        {"ordem compra", "ordem de compra", "ord compra", "oc", "numero oc"},
        {"fornecedor", "razao social", "nome fornecedor"},
        {"comprador", "usuario", "usuario comprador"},
        {"emissao", "data emissao", "data"},
        {"valor", "valor oc", "valor total", "total"},
    ]

    melhor_linha = None
    melhor_score = 0
    melhor_preenchidos = 0

    for index in range(len(preview)):
        valores = [
            clean_col_name(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        ]

        chaves = {
            header_key(v)
            for v in valores
        }

        score = 0

        for grupo in grupos:
            grupo_norm = {
                header_key(v)
                for v in grupo
            }

            if chaves.intersection(grupo_norm):
                score += 1

        preenchidos = len(valores)

        if score >= 3:
            if (
                score > melhor_score
                or (
                    score == melhor_score
                    and preenchidos > melhor_preenchidos
                )
            ):
                melhor_linha = index
                melhor_score = score
                melhor_preenchidos = preenchidos

    if melhor_linha is not None:
        print(
            "  Cabeçalho Ordens de Compra encontrado na linha:",
            melhor_linha + 1,
            f"(score={melhor_score})",
        )
        return melhor_linha

    raise ValueError(
        "Não encontrei o cabeçalho analítico de Ordens de Compra em "
        f"{caminho_arquivo.name}"
    )


def ler_ordens_compras(caminho_arquivo: Path) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho_ordens(
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

    df = (
        df.dropna(axis=1, how="all")
        .dropna(axis=0, how="all")
        .copy()
    )

    df = drop_total_rows(df)

    return df.reset_index(drop=True)


def padronizar_colunas_ordens(
    df: pd.DataFrame,
) -> pd.DataFrame:
    mapping = {
        "ordem compra": "Ordem_Compra",
        "ordem de compra": "Ordem_Compra",
        "ord compra": "Ordem_Compra",
        "numero oc": "Ordem_Compra",
        "oc": "Ordem_Compra",
        "numero": "Numero",
        "empresa": "Empresa",
        "empresa requisitante": "Empresa_Requisitante",
        "unidade": "Unidade",
        "unidade requisitante": "Unidade_Requisitante",
        "fornecedor": "Fornecedor",
        "razao social": "Fornecedor",
        "nome fornecedor": "Fornecedor",
        "cod fornecedor": "Cod_Fornecedor",
        "codigo fornecedor": "Cod_Fornecedor",
        "comprador": "Comprador",
        "usuario": "Comprador",
        "usuario comprador": "Comprador",
        "grupo comprador": "Grupo_Comprador",
        "grupo item": "Grupo_Item",
        "item": "Item",
        "codigo item": "Cod_Item",
        "cod item": "Cod_Item",
        "descricao": "Descricao_Item",
        "descricao item": "Descricao_Item",
        "emissao": "Emissao",
        "data emissao": "Emissao",
        "data": "Data",
        "situacao": "Situacao",
        "tipo encerramento": "Tipo_Encerramento",
        "tipo compra": "Tipo_Compra",
        "tipo ordem compra": "Tipo_Ordem_Compra",
        "tipo oc": "Tipo_Ordem_Compra",
        "quantidade": "Quantidade",
        "qtd": "Quantidade",
        "qtde": "Quantidade",
        "valor": "Valor",
        "valor oc": "Valor",
        "valor total": "Valor",
        "vl total": "Valor",
        "projeto": "Projeto",
    }

    rename = {}

    for coluna in df.columns:
        chave = header_key(coluna)

        if chave in mapping:
            destino = mapping[chave]

            if destino not in rename.values():
                rename[coluna] = destino

    return df.rename(
        columns=rename
    )


def tratar_ordem_compra_arquivo(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    df = ler_ordens_compras(
        caminho_arquivo
    )

    df = padronizar_colunas_ordens(
        df
    )

    if df.empty:
        return df

    # Datas
    for coluna in list(df.columns):
        chave = header_key(coluna)

        if (
            coluna in {"Emissao", "Data"}
            or "data" in chave
            or "emissao" in chave
        ):
            convertida = parse_known_dates(
                df[coluna]
            )

            if convertida.notna().any():
                df[coluna] = convertida

    # Números e valores
    for coluna in list(df.columns):
        chave = header_key(coluna)

        if (
            coluna in {"Quantidade", "Valor"}
            or "valor" in chave
            or chave in {"qtd", "qtde", "quantidade"}
        ):
            convertida = to_numeric_ptbr(
                df[coluna]
            )

            if convertida.notna().any():
                df[coluna] = convertida

    # Textos
    for coluna in list(df.columns):
        if (
            pd.api.types.is_object_dtype(df[coluna])
            or pd.api.types.is_string_dtype(df[coluna])
        ):
            df[coluna] = normalize_text(
                df[coluna]
            )

    periodo_inicio, periodo_fim = (
        extrair_data_ordem_nome(
            caminho_arquivo
        )
    )

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # Data analítica preferencial.
    if (
        "Emissao" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Emissao"]
        )
    ):
        df["Data_Analise"] = df["Emissao"]

    elif (
        "Data" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Data"]
        )
    ):
        df["Data_Analise"] = df["Data"]

    else:
        df["Data_Analise"] = periodo_inicio

    if pd.api.types.is_datetime64_any_dtype(
        df["Data_Analise"]
    ):
        df["Ano"] = df["Data_Analise"].dt.year
        df["Mes_Numero"] = df["Data_Analise"].dt.month
        df["Dia"] = df["Data_Analise"].dt.day
        df["AnoMes"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    # Campos de relacionamento/filtro permanecem texto.
    for coluna in [
        "Ordem_Compra",
        "Cod_Fornecedor",
        "Cod_Item",
        "Empresa",
        "Empresa_Requisitante",
        "Unidade",
        "Unidade_Requisitante",
    ]:
        if coluna in df.columns:
            df[coluna] = normalize_text(
                df[coluna]
            )

    return df.reset_index(drop=True)


def chave_deduplicacao_ordens(
    df: pd.DataFrame,
):
    candidatos = [
        "Ordem_Compra",
        "Numero",
        "Empresa",
        "Empresa_Requisitante",
        "Unidade",
        "Unidade_Requisitante",
        "Fornecedor",
        "Cod_Fornecedor",
        "Comprador",
        "Cod_Item",
        "Item",
        "Descricao_Item",
        "Emissao",
        "Data",
        "Quantidade",
        "Valor",
    ]

    return [
        coluna
        for coluna in candidatos
        if coluna in df.columns
    ]


def consolidar_ordens_compras():
    arquivos = listar_arquivos_ordens_compras()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Ordens de Compras encontrado em: "
            f"{PASTA_ORDENS_COMPRAS}"
        )

    print()
    print("=" * 80)
    print("TRATANDO ORDENS DE COMPRAS EMITIDAS")
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
            f"[OC {numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        try:
            tratado = tratar_ordem_compra_arquivo(
                arquivo
            )

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas",
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
            "Nenhum arquivo de Ordens de Compras "
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

    chave = chave_deduplicacao_ordens(
        resultado
    )

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
    print(
        "Linhas antes da deduplicação:",
        f"{linhas_antes:,}",
    )

    print(
        "Duplicadas removidas:",
        f"{linhas_antes - len(resultado):,}",
    )

    print(
        "Linhas finais Ordens de Compra:",
        f"{len(resultado):,}",
    )

    if "Valor" in resultado.columns:
        print(
            "Valor total Ordens de Compra:",
            f"{resultado['Valor'].sum():,.2f}",
        )

    if "Data_Analise" in resultado.columns:
        print(
            "Data mínima:",
            resultado["Data_Analise"].min(),
        )
        print(
            "Data máxima:",
            resultado["Data_Analise"].max(),
        )

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) "
            "de Ordens de Compra tiveram erro:"
        )

        for nome, erro in erros:
            print(
                f"  - {nome}: {erro}"
            )

    return resultado



# =============================================================================
# 8) RELATÓRIO DE USUÁRIOS
# =============================================================================

def listar_arquivos_relatorio_usuarios():
    arquivos = []

    if not PASTA_RELATORIO_USUARIOS.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(
            PASTA_RELATORIO_USUARIOS.glob(pattern)
        )

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def encontrar_linha_cabecalho_usuarios(
    caminho_arquivo: Path,
    max_rows: int = 200,
) -> int:
    """
    Localiza o cabeçalho analítico do Relatório de Usuários.

    Cabeçalho esperado:
    Usuário | Nome | Emp | Uni | CPF | Apelido | E-mail | Ramal | Impressora | Setor
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

    for index in range(len(preview)):
        chaves = {
            header_key(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        }

        if (
            "usuario" in chaves
            and "nome" in chaves
            and (
                "cpf" in chaves
                or "e mail" in chaves
                or "email" in chaves
            )
        ):
            return index

    raise ValueError(
        "Não encontrei o cabeçalho do Relatório de Usuários em "
        f"{caminho_arquivo.name}"
    )


def padronizar_colunas_usuarios(
    df: pd.DataFrame,
) -> pd.DataFrame:
    mapping = {
        "usuario": "Usuario",
        "nome": "Nome",
        "emp": "Emp",
        "empresa": "Emp",
        "uni": "Uni",
        "unidade": "Uni",
        "cpf": "CPF",
        "apelido": "Apelido",
        "e mail": "Email",
        "email": "Email",
        "ramal": "Ramal",
        "impressora": "Impressora",
        "setor": "Setor",
    }

    rename = {}

    for coluna in df.columns:
        chave = header_key(coluna)

        if chave in mapping:
            destino = mapping[chave]

            if destino not in rename.values():
                rename[coluna] = destino

    return df.rename(columns=rename)


def tratar_relatorio_usuarios_arquivo(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho_usuarios(
        caminho_arquivo
    )

    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    print(
        "  Cabeçalho Usuários encontrado na linha:",
        header_row + 1,
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
        df.dropna(axis=1, how="all")
        .dropna(axis=0, how="all")
        .copy()
    )

    df = drop_total_rows(df)
    df = padronizar_colunas_usuarios(df)

    if "Usuario" not in df.columns:
        raise ValueError(
            "A coluna Usuario não foi encontrada em "
            f"{caminho_arquivo.name}"
        )

    for coluna in [
        "Usuario",
        "Nome",
        "Emp",
        "Uni",
        "CPF",
        "Apelido",
        "Email",
        "Ramal",
        "Impressora",
        "Setor",
    ]:
        if coluna in df.columns:
            df[coluna] = normalize_text(
                df[coluna]
            )

    # Normaliza a chave usada nos relacionamentos.
    df["Usuario"] = (
        df["Usuario"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    # Remove linhas sem usuário.
    df = df[
        df["Usuario"].notna()
        & (df["Usuario"].str.len() > 0)
    ].copy()

    # Campos úteis no Power BI.
    if "Nome" in df.columns:
        df["Usuario_Nome"] = (
            df["Nome"].fillna(df["Usuario"])
        )
    else:
        df["Usuario_Nome"] = df["Usuario"]

    df["Usuario_Filtro"] = (
        df["Usuario_Nome"]
        .fillna(df["Usuario"])
    )

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    return df.reset_index(drop=True)


def consolidar_relatorio_usuarios():
    arquivos = listar_arquivos_relatorio_usuarios()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel do Relatório de Usuários encontrado em: "
            f"{PASTA_RELATORIO_USUARIOS}"
        )

    print()
    print("=" * 80)
    print("TRATANDO RELATÓRIO DE USUÁRIOS")
    print("=" * 80)
    print(
        "Arquivos encontrados:",
        len(arquivos),
    )

    bases = []

    for numero, arquivo in enumerate(
        arquivos,
        start=1,
    ):
        print()
        print(
            f"[USU {numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        tratado = tratar_relatorio_usuarios_arquivo(
            arquivo
        )

        print(
            "  OK:",
            f"{len(tratado):,}",
            "linhas",
        )

        bases.append(tratado)

    resultado = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    resultado = resultado.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    # Como o robô sempre substitui o mesmo Excel,
    # normalmente haverá só um arquivo. Mesmo assim,
    # a deduplicação deixa a base segura.
    resultado = resultado.drop_duplicates(
        subset=["Usuario"],
        keep="last",
    )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print(
        "Usuários finais:",
        f"{len(resultado):,}",
    )

    return resultado


def adicionar_nome_comprador_ordens(
    ordens_compras: pd.DataFrame,
    usuarios: pd.DataFrame,
) -> pd.DataFrame:
    """
    Mantém o campo Comprador original e acrescenta:
    - Comprador Nome
    - Comprador Filtro

    Assim o Power BI pode mostrar o nome completo sem perder
    a chave original do usuário Agrosys.
    """
    resultado = ordens_compras.copy()

    if (
        "Comprador" not in resultado.columns
        or "Usuario" not in usuarios.columns
    ):
        return resultado

    resultado["Comprador"] = (
        resultado["Comprador"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    cadastro = usuarios[
        [
            coluna
            for coluna in [
                "Usuario",
                "Nome",
                "Usuario_Nome",
                "Setor",
                "Email",
            ]
            if coluna in usuarios.columns
        ]
    ].copy()

    rename = {
        "Usuario": "_UsuarioCadastro",
        "Nome": "Comprador Nome",
        "Usuario_Nome": "Comprador Nome Completo",
        "Setor": "Comprador Setor",
        "Email": "Comprador Email",
    }

    cadastro = cadastro.rename(
        columns=rename
    )

    resultado = resultado.merge(
        cadastro,
        how="left",
        left_on="Comprador",
        right_on="_UsuarioCadastro",
    )

    resultado["Comprador Filtro"] = (
        resultado.get(
            "Comprador Nome",
            pd.Series(
                pd.NA,
                index=resultado.index,
                dtype="string",
            ),
        )
        .fillna(resultado["Comprador"])
    )

    resultado = resultado.drop(
        columns=["_UsuarioCadastro"],
        errors="ignore",
    )

    return resultado




# =============================================================================
# 9) SOLICITAÇÕES POR REQUISITANTE
# =============================================================================

def listar_arquivos_solicitacoes_requisitante():
    arquivos = []

    if not PASTA_SOLICITACOES_REQUISITANTE.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(
            PASTA_SOLICITACOES_REQUISITANTE.glob(pattern)
        )

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def extrair_periodo_solicitacoes_nome(caminho_arquivo: Path):
    """
    Reconhece o padrão atual:
      solicitacoes_requisitante_01-08-2026_ate_01-08-2026.xlsx

    Também aceita, por compatibilidade:
      solicitacoes_requisitante_2026-08-01.xlsx
      solicitacoes_requisitante_2026-08-01_ate_2026-08-31.xlsx
    """
    nome = caminho_arquivo.name

    datas_br = re.findall(
        r"(\d{2}-\d{2}-\d{4})",
        nome,
    )

    if datas_br:
        try:
            inicio = pd.Timestamp(
                datetime.strptime(
                    datas_br[0],
                    "%d-%m-%Y",
                )
            )

            fim = inicio

            if len(datas_br) >= 2:
                fim = pd.Timestamp(
                    datetime.strptime(
                        datas_br[1],
                        "%d-%m-%Y",
                    )
                )

            return inicio, fim

        except Exception:
            pass

    datas_iso = re.findall(
        r"(20\d{2}-\d{2}-\d{2})",
        nome,
    )

    if datas_iso:
        try:
            inicio = pd.Timestamp(
                datetime.strptime(
                    datas_iso[0],
                    "%Y-%m-%d",
                )
            )

            fim = inicio

            if len(datas_iso) >= 2:
                fim = pd.Timestamp(
                    datetime.strptime(
                        datas_iso[1],
                        "%Y-%m-%d",
                    )
                )

            return inicio, fim

        except Exception:
            pass

    return pd.NaT, pd.NaT


def encontrar_linha_cabecalho_solicitacoes(
    caminho_arquivo: Path,
    max_rows: int = 450,
) -> int:
    """
    Localiza a tabela analítica do Relatório de Solicitações por Requisitante.

    Não usa posição fixa porque o Excel oficial pode trazer títulos/filtros
    antes da tabela.
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
        {"solicitacao", "numero solicitacao", "num solicitacao", "sc"},
        {"requisitante", "nome requisitante"},
        {"item", "codigo item", "cod item"},
        {"grupo item", "grupo"},
        {"comprador"},
        {"situacao", "status"},
    ]

    melhor_linha = None
    melhor_score = 0
    melhor_preenchidos = 0

    for index in range(len(preview)):
        valores = [
            clean_col_name(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        ]

        chaves = {
            header_key(v)
            for v in valores
        }

        score = 0

        for grupo in grupos:
            grupo_norm = {
                header_key(v)
                for v in grupo
            }

            if chaves.intersection(grupo_norm):
                score += 1

        preenchidos = len(valores)

        # Normalmente o cabeçalho analítico terá várias colunas.
        if score >= 3 and preenchidos >= 5:
            if (
                score > melhor_score
                or (
                    score == melhor_score
                    and preenchidos > melhor_preenchidos
                )
            ):
                melhor_linha = index
                melhor_score = score
                melhor_preenchidos = preenchidos

    if melhor_linha is not None:
        print(
            "  Cabeçalho Solicitações encontrado na linha:",
            melhor_linha + 1,
            f"(score={melhor_score})",
        )
        return melhor_linha

    raise ValueError(
        "Não encontrei o cabeçalho analítico de Solicitações por Requisitante em "
        f"{caminho_arquivo.name}"
    )


def ler_solicitacoes_requisitante(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho_solicitacoes(
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

    df = (
        df.dropna(axis=1, how="all")
        .dropna(axis=0, how="all")
        .copy()
    )

    df = drop_total_rows(df)

    return df.reset_index(drop=True)


def padronizar_colunas_solicitacoes(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Padroniza somente os nomes conhecidos.
    Colunas adicionais do Agrosys são preservadas.
    """
    mapping = {
        "solicitacao": "Solicitacao",
        "numero solicitacao": "Solicitacao",
        "num solicitacao": "Solicitacao",
        "sc": "Solicitacao",

        "data solicitacao": "Data_Solicitacao",
        "dt solicitacao": "Data_Solicitacao",
        "data": "Data",

        "empresa": "Empresa",
        "unidade": "Unidade",

        "requisitante": "Requisitante",
        "nome requisitante": "Requisitante_Nome",

        "tipo item": "Tipo_Item",
        "codigo tipo item": "Cod_Tipo_Item",
        "cod tipo item": "Cod_Tipo_Item",

        "grupo item": "Grupo_Item",
        "codigo grupo item": "Cod_Grupo_Item",
        "cod grupo item": "Cod_Grupo_Item",
        "grupo": "Grupo_Item",

        "item": "Item",
        "codigo item": "Cod_Item",
        "cod item": "Cod_Item",
        "descricao item": "Descricao_Item",
        "descricao": "Descricao_Item",

        "projeto": "Projeto",
        "equipamento": "Equipamento",

        "usuario": "Usuario",
        "centro de custo": "Centro_Custo",
        "centro custo": "Centro_Custo",
        "ccusto": "Centro_Custo",

        "comprador": "Comprador",

        "tipo sc": "Tipo_SC",
        "situacao": "Situacao",
        "status": "Situacao",
        "solicitacao para": "Solicitacao_Para",

        "quantidade": "Quantidade",
        "qtd": "Quantidade",
        "qtde": "Quantidade",
        "un": "UN",
        "unidade medida": "UN",
        "unidade de medida": "UN",

        "valor": "Valor",
        "valor total": "Valor",
        "valor unitario": "Valor_Unitario",

        "observacao": "Observacao",
        "uso": "Uso",
    }

    rename = {}

    for coluna in df.columns:
        chave = header_key(coluna)

        if chave in mapping:
            destino = mapping[chave]

            if destino not in rename.values():
                rename[coluna] = destino

    return df.rename(columns=rename)


def tratar_solicitacao_requisitante_arquivo(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    df = ler_solicitacoes_requisitante(
        caminho_arquivo
    )

    df = padronizar_colunas_solicitacoes(
        df
    )

    if df.empty:
        return df

    # Datas encontradas no relatório.
    for coluna in list(df.columns):
        chave = header_key(coluna)

        if (
            coluna in {"Data_Solicitacao", "Data"}
            or "data" in chave
            or "emissao" in chave
            or "inclusao" in chave
        ):
            convertida = parse_known_dates(
                df[coluna]
            )

            if convertida.notna().any():
                df[coluna] = convertida

    # Números/valores conhecidos.
    for coluna in list(df.columns):
        chave = header_key(coluna)

        if (
            coluna in {
                "Quantidade",
                "Valor",
                "Valor_Unitario",
            }
            or "valor" in chave
            or chave in {"qtd", "qtde", "quantidade"}
        ):
            convertida = to_numeric_ptbr(
                df[coluna]
            )

            if convertida.notna().any():
                df[coluna] = convertida

    # Textos.
    for coluna in list(df.columns):
        if (
            pd.api.types.is_object_dtype(df[coluna])
            or pd.api.types.is_string_dtype(df[coluna])
        ):
            df[coluna] = normalize_text(
                df[coluna]
            )

    periodo_inicio, periodo_fim = (
        extrair_periodo_solicitacoes_nome(
            caminho_arquivo
        )
    )

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # Data analítica:
    # 1º Data_Solicitacao do próprio relatório;
    # 2º Data genérica;
    # 3º data inicial do arquivo.
    if (
        "Data_Solicitacao" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Data_Solicitacao"]
        )
    ):
        df["Data_Analise"] = df["Data_Solicitacao"]

    elif (
        "Data" in df.columns
        and pd.api.types.is_datetime64_any_dtype(
            df["Data"]
        )
    ):
        df["Data_Analise"] = df["Data"]

    else:
        df["Data_Analise"] = periodo_inicio

    if pd.api.types.is_datetime64_any_dtype(
        df["Data_Analise"]
    ):
        df["Ano"] = df["Data_Analise"].dt.year
        df["Mes_Numero"] = df["Data_Analise"].dt.month
        df["Dia"] = df["Data_Analise"].dt.day
        df["AnoMes"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    # Chaves e filtros permanecem texto.
    for coluna in [
        "Solicitacao",
        "Empresa",
        "Unidade",
        "Requisitante",
        "Cod_Tipo_Item",
        "Cod_Grupo_Item",
        "Cod_Item",
        "Projeto",
        "Equipamento",
        "Usuario",
        "Centro_Custo",
        "Comprador",
        "Tipo_SC",
        "Situacao",
        "Solicitacao_Para",
        "UN",
    ]:
        if coluna in df.columns:
            df[coluna] = normalize_text(
                df[coluna]
            )

    return df.reset_index(drop=True)


def chave_deduplicacao_solicitacoes(
    df: pd.DataFrame,
):
    """
    A base pode conter arquivos mensais + diários sobrepostos.
    A chave procura preservar linhas diferentes da mesma solicitação/item.
    """
    candidatos = [
        "Solicitacao",
        "Empresa",
        "Unidade",
        "Requisitante",
        "Comprador",
        "Cod_Item",
        "Item",
        "Descricao_Item",
        "Quantidade",
        "UN",
        "Projeto",
        "Equipamento",
        "Centro_Custo",
        "Situacao",
        "Data_Analise",
    ]

    return [
        coluna
        for coluna in candidatos
        if coluna in df.columns
    ]


def consolidar_solicitacoes_requisitante():
    arquivos = listar_arquivos_solicitacoes_requisitante()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Solicitações por Requisitante encontrado em: "
            f"{PASTA_SOLICITACOES_REQUISITANTE}"
        )

    print()
    print("=" * 80)
    print("TRATANDO SOLICITAÇÕES POR REQUISITANTE")
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
            f"[SC {numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        try:
            tratado = tratar_solicitacao_requisitante_arquivo(
                arquivo
            )

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas",
            )

            if not tratado.empty:
                bases.append(tratado)

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
            "Nenhum arquivo de Solicitações por Requisitante "
            "foi tratado com sucesso."
        )

    resultado = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    linhas_antes = len(resultado)

    # Mais novo prevalece quando houver sobreposição.
    resultado = resultado.sort_values(
        "_Arquivo_Modificado_Em",
        ascending=True,
        kind="stable",
    )

    chave = chave_deduplicacao_solicitacoes(
        resultado
    )

    if chave:
        resultado = resultado.drop_duplicates(
            subset=chave,
            keep="last",
        )
    else:
        subset = [
            coluna
            for coluna in resultado.columns
            if coluna not in {
                "Arquivo_Origem",
                "_Arquivo_Modificado_Em",
                "Periodo_Arquivo_Inicio",
                "Periodo_Arquivo_Fim",
            }
        ]

        resultado = resultado.drop_duplicates(
            subset=subset,
            keep="last",
        )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
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
        "Linhas finais Solicitações:",
        f"{len(resultado):,}",
    )

    if "Data_Analise" in resultado.columns:
        print(
            "Data mínima:",
            resultado["Data_Analise"].min(),
        )
        print(
            "Data máxima:",
            resultado["Data_Analise"].max(),
        )

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) "
            "de Solicitações tiveram erro:"
        )

        for nome, erro in erros:
            print(
                f"  - {nome}: {erro}"
            )

    return resultado


def adicionar_nome_comprador_solicitacoes(
    solicitacoes: pd.DataFrame,
    usuarios: pd.DataFrame,
) -> pd.DataFrame:
    """
    Acrescenta nome/setor/e-mail do comprador usando o mesmo cadastro
    de usuários já utilizado nas Ordens de Compras.
    """
    resultado = solicitacoes.copy()

    if (
        "Comprador" not in resultado.columns
        or "Usuario" not in usuarios.columns
    ):
        return resultado

    resultado["Comprador"] = (
        resultado["Comprador"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    cadastro = usuarios[
        [
            coluna
            for coluna in [
                "Usuario",
                "Nome",
                "Usuario_Nome",
                "Setor",
                "Email",
            ]
            if coluna in usuarios.columns
        ]
    ].copy()

    cadastro = cadastro.rename(
        columns={
            "Usuario": "_UsuarioCadastro",
            "Nome": "Comprador Nome",
            "Usuario_Nome": "Comprador Nome Completo",
            "Setor": "Comprador Setor",
            "Email": "Comprador Email",
        }
    )

    resultado = resultado.merge(
        cadastro,
        how="left",
        left_on="Comprador",
        right_on="_UsuarioCadastro",
    )

    resultado["Comprador Filtro"] = (
        resultado.get(
            "Comprador Nome",
            pd.Series(
                pd.NA,
                index=resultado.index,
                dtype="string",
            ),
        )
        .fillna(resultado["Comprador"])
    )

    resultado = resultado.drop(
        columns=["_UsuarioCadastro"],
        errors="ignore",
    )

    return resultado



# =============================================================================
# 10) TÍTULOS AGRUPADOS
# =============================================================================

def listar_arquivos_titulos_agrupados():
    arquivos = []

    if not PASTA_TITULOS_AGRUPADOS.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(PASTA_TITULOS_AGRUPADOS.glob(pattern))

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def extrair_periodo_titulos_nome(caminho_arquivo: Path):
    datas = re.findall(
        r"(\d{2}-\d{2}-\d{4})",
        caminho_arquivo.name,
    )

    if not datas:
        return pd.NaT, pd.NaT

    try:
        inicio = pd.Timestamp(
            datetime.strptime(datas[0], "%d-%m-%Y")
        )
        fim = inicio

        if len(datas) >= 2:
            fim = pd.Timestamp(
                datetime.strptime(datas[1], "%d-%m-%Y")
            )

        return inicio, fim

    except Exception:
        return pd.NaT, pd.NaT


def _texto_chave(valor):
    if valor is None:
        return pd.NA

    try:
        if pd.isna(valor):
            return pd.NA
    except Exception:
        pass

    texto = str(valor).strip()

    if not texto:
        return pd.NA

    # Remove somente o .0 criado pelo Excel/Pandas em códigos inteiros.
    if re.fullmatch(r"-?\d+\.0", texto):
        texto = texto[:-2]

    return texto


def tratar_titulos_agrupados_arquivo(caminho_arquivo: Path) -> pd.DataFrame:
    """
    O relatório Títulos Agrupados possui dois níveis:

    Nível 1:
      Vencimento | Título | Código | Nome | ... | Situ | Usuário

    Nível 2:
      Tp.Ori | Ori | Tp.Doc | Título | Dt Emissão | ... | Dt Venc | Situ

    Cada linha do nível 2 herda o Título/Credor do nível 1.
    Isso cria a ponte:
        Título pago -> Nota Fiscal de origem
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
        dtype=object,
        engine=engine,
    )

    periodo_inicio, periodo_fim = extrair_periodo_titulos_nome(
        caminho_arquivo
    )

    registros = []
    titulo_atual = None

    for _, linha in raw.iterrows():
        valores = linha.tolist()

        while len(valores) < 12:
            valores.append(None)

        primeiro = valores[0]

        # Linha do título agrupador.
        eh_data = isinstance(
            primeiro,
            (pd.Timestamp, datetime),
        )

        if eh_data:
            segundo = valores[1]
            terceiro = valores[2]
            quarto = valores[3]

            # Evita confundir com a linha de filtros:
            # Data Inicial | Data Final | Tipo Credor...
            if (
                segundo is not None
                and not isinstance(segundo, (pd.Timestamp, datetime))
                and pd.notna(segundo)
                and pd.notna(terceiro)
                and pd.notna(quarto)
            ):
                titulo_atual = {
                    "Vencimento_Agrupado": primeiro,
                    "Titulo_Agrupado": _texto_chave(segundo),
                    "Credor_Codigo": _texto_chave(terceiro),
                    "Credor_Nome": clean_col_name(quarto),
                    "Valor_Nominal_Agrupado": valores[4],
                    "Desconto_Agrupado": valores[5],
                    "Juros_Agrupado": valores[6],
                    "Var_Cambial_Agrupado": valores[7],
                    "Saldo_Agrupado": valores[8],
                    "Situacao_Agrupado": valores[9],
                    "Usuario_Agrupado": valores[10],
                }

                continue

        if titulo_atual is None:
            continue

        chave_primeiro = header_key(primeiro)

        # Ignora cabeçalhos internos.
        if chave_primeiro in {
            "tp ori",
            "vencimento",
            "data inicial",
            "total",
        }:
            continue

        # Linha analítica de origem.
        if not clean_col_name(primeiro):
            continue

        # O primeiro campo do detalhe normalmente é NFF/NFE/etc.
        # Exige também Origem e Título de origem para evitar linhas de total.
        if (
            pd.isna(valores[1])
            or pd.isna(valores[3])
        ):
            continue

        registro = dict(titulo_atual)

        registro.update({
            "Tp_Ori": clean_col_name(valores[0]),
            "Origem_NF": _texto_chave(valores[1]),
            "Tp_Doc": clean_col_name(valores[2]),
            "Titulo_Origem": _texto_chave(valores[3]),
            "Dt_Emissao_Origem": valores[4],
            "Valor_Nominal_Origem": valores[5],
            "Desconto_Origem": valores[6],
            "Juros_Origem": valores[7],
            "Var_Cambial_Origem": valores[8],
            "Saldo_Origem": valores[9],
            "Dt_Vencimento_Origem": valores[10],
            "Situacao_Origem": valores[11],
            "Arquivo_Origem": caminho_arquivo.name,
            "Periodo_Arquivo_Inicio": periodo_inicio,
            "Periodo_Arquivo_Fim": periodo_fim,
            "_Arquivo_Modificado_Em": datetime.fromtimestamp(
                caminho_arquivo.stat().st_mtime
            ),
        })

        registros.append(registro)

    if not registros:
        raise ValueError(
            "Não encontrei linhas analíticas de Títulos Agrupados em "
            f"{caminho_arquivo.name}"
        )

    df = pd.DataFrame(registros)

    for coluna in [
        "Vencimento_Agrupado",
        "Dt_Emissao_Origem",
        "Dt_Vencimento_Origem",
    ]:
        if coluna in df.columns:
            df[coluna] = parse_known_dates(df[coluna])

    for coluna in [
        "Valor_Nominal_Agrupado",
        "Desconto_Agrupado",
        "Juros_Agrupado",
        "Var_Cambial_Agrupado",
        "Saldo_Agrupado",
        "Valor_Nominal_Origem",
        "Desconto_Origem",
        "Juros_Origem",
        "Var_Cambial_Origem",
        "Saldo_Origem",
    ]:
        if coluna in df.columns:
            df[coluna] = to_numeric_ptbr(df[coluna])

    for coluna in [
        "Titulo_Agrupado",
        "Credor_Codigo",
        "Credor_Nome",
        "Situacao_Agrupado",
        "Usuario_Agrupado",
        "Tp_Ori",
        "Origem_NF",
        "Tp_Doc",
        "Titulo_Origem",
        "Situacao_Origem",
    ]:
        if coluna in df.columns:
            df[coluna] = normalize_text(df[coluna])

    return df.reset_index(drop=True)


def consolidar_titulos_agrupados():
    arquivos = listar_arquivos_titulos_agrupados()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Títulos Agrupados encontrado em: "
            f"{PASTA_TITULOS_AGRUPADOS}"
        )

    print()
    print("=" * 80)
    print("TRATANDO TÍTULOS AGRUPADOS")
    print("=" * 80)
    print("Arquivos encontrados:", len(arquivos))

    bases = []
    erros = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print()
        print(
            f"[TIT {numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        try:
            tratado = tratar_titulos_agrupados_arquivo(
                arquivo
            )

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas",
            )

            if not tratado.empty:
                bases.append(tratado)

        except Exception as erro:
            erros.append((arquivo.name, str(erro)))
            print("  ERRO:", arquivo.name)
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo de Títulos Agrupados "
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

    chave = [
        coluna
        for coluna in [
            "Titulo_Agrupado",
            "Credor_Codigo",
            "Tp_Ori",
            "Origem_NF",
            "Tp_Doc",
            "Titulo_Origem",
        ]
        if coluna in resultado.columns
    ]

    resultado = resultado.drop_duplicates(
        subset=chave,
        keep="last",
    )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print(
        "Linhas antes da deduplicação:",
        f"{linhas_antes:,}",
    )
    print(
        "Duplicadas removidas:",
        f"{linhas_antes - len(resultado):,}",
    )
    print(
        "Linhas finais Títulos Agrupados:",
        f"{len(resultado):,}",
    )

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) "
            "de Títulos Agrupados tiveram erro:"
        )
        for nome, erro in erros:
            print(f"  - {nome}: {erro}")

    return resultado


# =============================================================================
# 11) RELAÇÃO OC X NF
# =============================================================================

def listar_arquivos_relacao_oc_nf():
    arquivos = []

    if not PASTA_RELACAO_OC_NF.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(PASTA_RELACAO_OC_NF.glob(pattern))

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            arquivo.name.lower(),
        ),
    )


def extrair_periodo_relacao_oc_nf_nome(caminho_arquivo: Path):
    datas = re.findall(
        r"(\d{2}-\d{2}-\d{4})",
        caminho_arquivo.name,
    )

    if not datas:
        return pd.NaT, pd.NaT

    try:
        inicio = pd.Timestamp(
            datetime.strptime(datas[0], "%d-%m-%Y")
        )
        fim = inicio

        if len(datas) >= 2:
            fim = pd.Timestamp(
                datetime.strptime(datas[1], "%d-%m-%Y")
            )

        return inicio, fim

    except Exception:
        return pd.NaT, pd.NaT


def encontrar_linha_cabecalho_relacao_oc_nf(
    caminho_arquivo: Path,
    max_rows: int = 120,
) -> int:
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

    for index in range(len(preview)):
        chaves = {
            header_key(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        }

        if (
            "nota fiscal" in chaves
            and "ordem compra" in chaves
            and "item" in chaves
            and "requisitante" in chaves
        ):
            return index

    raise ValueError(
        "Não encontrei o cabeçalho da Relação OC x NF em "
        f"{caminho_arquivo.name}"
    )


def tratar_relacao_oc_nf_arquivo(
    caminho_arquivo: Path,
) -> pd.DataFrame:
    header_row = encontrar_linha_cabecalho_relacao_oc_nf(
        caminho_arquivo
    )

    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    print(
        "  Cabeçalho Relação OC x NF encontrado na linha:",
        header_row + 1,
    )

    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=header_row,
        dtype=object,
        engine=engine,
    )

    df.columns = make_unique_columns(df.columns.tolist())

    df = (
        df.dropna(axis=1, how="all")
        .dropna(axis=0, how="all")
        .copy()
    )

    df = drop_total_rows(df)

    mapping = {
        "emp": "Empresa",
        "unid": "Unidade",
        "fornecedor": "Fornecedor_Codigo",
        "nome": "Fornecedor_Nome",
        "nome 1": "Requisitante_Nome",
        "nota fiscal": "Nota_Fiscal",
        "serie": "Serie",
        "nr": "NR",
        "dt emissao nf": "Data_Emissao_NF",
        "ordem compra": "Ordem_Compra",
        "dt emissao oc": "Data_Emissao_OC",
        "dt aprov solic": "Data_Aprov_Solicitacao",
        "lead time": "Lead_Time",
        "item": "Item",
        "descricao": "Descricao_Item",
        "qt recebida": "Quantidade_Recebida",
        "qt comprada": "Quantidade_Comprada",
        "un medida": "UN",
        "valor item": "Valor_Item",
        "requisitante": "Requisitante",
        "comprador": "Comprador",
        "tipo oc": "Tipo_OC",
        "dt vencimento oc": "Data_Vencimento_OC",
        "dt entrada nf": "Data_Entrada_NF",
    }

    rename = {}

    # Há duas colunas "Nome": fornecedor e requisitante.
    nomes_encontrados = 0

    for coluna in df.columns:
        chave = header_key(coluna)

        if chave == "nome":
            nomes_encontrados += 1
            if nomes_encontrados == 1:
                rename[coluna] = "Fornecedor_Nome"
            else:
                rename[coluna] = "Requisitante_Nome"
            continue

        if chave in mapping:
            destino = mapping[chave]
            if destino not in rename.values():
                rename[coluna] = destino

    df = df.rename(columns=rename)

    for coluna in [
        "Data_Emissao_NF",
        "Data_Emissao_OC",
        "Data_Aprov_Solicitacao",
        "Data_Vencimento_OC",
        "Data_Entrada_NF",
    ]:
        if coluna in df.columns:
            df[coluna] = parse_known_dates(df[coluna])

    for coluna in [
        "Lead_Time",
        "Quantidade_Recebida",
        "Quantidade_Comprada",
        "Valor_Item",
    ]:
        if coluna in df.columns:
            df[coluna] = to_numeric_ptbr(df[coluna])

    for coluna in [
        "Empresa",
        "Unidade",
        "Fornecedor_Codigo",
        "Fornecedor_Nome",
        "Nota_Fiscal",
        "Serie",
        "NR",
        "Ordem_Compra",
        "Item",
        "Descricao_Item",
        "UN",
        "Requisitante",
        "Requisitante_Nome",
        "Comprador",
        "Tipo_OC",
    ]:
        if coluna in df.columns:
            df[coluna] = normalize_text(df[coluna])

    periodo_inicio, periodo_fim = (
        extrair_periodo_relacao_oc_nf_nome(
            caminho_arquivo
        )
    )

    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    if "Data_Emissao_OC" in df.columns:
        df["Data_Analise"] = df["Data_Emissao_OC"]
    else:
        df["Data_Analise"] = periodo_inicio

    if pd.api.types.is_datetime64_any_dtype(
        df["Data_Analise"]
    ):
        df["Ano"] = df["Data_Analise"].dt.year
        df["Mes_Numero"] = df["Data_Analise"].dt.month
        df["Dia"] = df["Data_Analise"].dt.day
        df["AnoMes"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    return df.reset_index(drop=True)


def consolidar_relacao_oc_nf():
    arquivos = listar_arquivos_relacao_oc_nf()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel da Relação OC x NF encontrado em: "
            f"{PASTA_RELACAO_OC_NF}"
        )

    print()
    print("=" * 80)
    print("TRATANDO RELAÇÃO OC X NF")
    print("=" * 80)
    print("Arquivos encontrados:", len(arquivos))

    bases = []
    erros = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print()
        print(
            f"[OCNF {numero}/{len(arquivos)}] "
            f"{arquivo.name}"
        )

        try:
            tratado = tratar_relacao_oc_nf_arquivo(
                arquivo
            )

            print(
                "  OK:",
                f"{len(tratado):,}",
                "linhas",
            )

            if not tratado.empty:
                bases.append(tratado)

        except Exception as erro:
            erros.append((arquivo.name, str(erro)))
            print("  ERRO:", arquivo.name)
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo da Relação OC x NF "
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

    chave = [
        coluna
        for coluna in [
            "Empresa",
            "Unidade",
            "Fornecedor_Codigo",
            "Nota_Fiscal",
            "Serie",
            "NR",
            "Ordem_Compra",
            "Item",
            "Valor_Item",
        ]
        if coluna in resultado.columns
    ]

    resultado = resultado.drop_duplicates(
        subset=chave,
        keep="last",
    )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print(
        "Linhas antes da deduplicação:",
        f"{linhas_antes:,}",
    )
    print(
        "Duplicadas removidas:",
        f"{linhas_antes - len(resultado):,}",
    )
    print(
        "Linhas finais Relação OC x NF:",
        f"{len(resultado):,}",
    )

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) "
            "da Relação OC x NF tiveram erro:"
        )
        for nome, erro in erros:
            print(f"  - {nome}: {erro}")

    return resultado


def adicionar_nome_comprador_relacao_oc_nf(
    relacao: pd.DataFrame,
    usuarios: pd.DataFrame,
) -> pd.DataFrame:
    resultado = relacao.copy()

    if (
        "Comprador" not in resultado.columns
        or "Usuario" not in usuarios.columns
    ):
        return resultado

    resultado["Comprador"] = (
        resultado["Comprador"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    cadastro = usuarios[
        [
            coluna
            for coluna in [
                "Usuario",
                "Nome",
                "Usuario_Nome",
                "Setor",
                "Email",
            ]
            if coluna in usuarios.columns
        ]
    ].copy()

    cadastro = cadastro.rename(
        columns={
            "Usuario": "_UsuarioCadastro",
            "Nome": "Comprador Nome",
            "Usuario_Nome": "Comprador Nome Completo",
            "Setor": "Comprador Setor",
            "Email": "Comprador Email",
        }
    )

    resultado = resultado.merge(
        cadastro,
        how="left",
        left_on="Comprador",
        right_on="_UsuarioCadastro",
    )

    resultado["Comprador Filtro"] = (
        resultado.get(
            "Comprador Nome",
            pd.Series(
                pd.NA,
                index=resultado.index,
                dtype="string",
            ),
        )
        .fillna(resultado["Comprador"])
    )

    return resultado.drop(
        columns=["_UsuarioCadastro"],
        errors="ignore",
    )


# =============================================================================
# 12) NOTAS FISCAIS DO ITEM
# =============================================================================

def listar_arquivos_notas_fiscais_item():
    arquivos = []

    if not PASTA_NOTAS_FISCAIS_ITEM.exists():
        return arquivos

    for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
        arquivos.extend(
            PASTA_NOTAS_FISCAIS_ITEM.rglob(pattern)
        )

    return sorted(
        [
            arquivo
            for arquivo in arquivos
            if arquivo.is_file()
            and not arquivo.name.startswith("~$")
        ],
        key=lambda arquivo: (
            arquivo.stat().st_mtime,
            str(arquivo).lower(),
        ),
    )


def extrair_periodo_notas_item_nome(caminho_arquivo: Path):
    nome = caminho_arquivo.name

    datas_br = re.findall(
        r"(\d{2}-\d{2}-\d{4})",
        nome,
    )

    if datas_br:
        try:
            inicio = pd.Timestamp(
                datetime.strptime(datas_br[0], "%d-%m-%Y")
            )
            fim = inicio
            if len(datas_br) >= 2:
                fim = pd.Timestamp(
                    datetime.strptime(datas_br[1], "%d-%m-%Y")
                )
            return inicio, fim
        except Exception:
            pass

    datas_iso = re.findall(
        r"(20\d{2}-\d{2}-\d{2})",
        nome,
    )

    if datas_iso:
        try:
            inicio = pd.Timestamp(
                datetime.strptime(datas_iso[0], "%Y-%m-%d")
            )
            fim = inicio
            if len(datas_iso) >= 2:
                fim = pd.Timestamp(
                    datetime.strptime(datas_iso[1], "%Y-%m-%d")
                )
            return inicio, fim
        except Exception:
            pass

    return pd.NaT, pd.NaT


def _ler_planilha_notas_item_bruta(caminho_arquivo: Path) -> pd.DataFrame:
    """Lê a primeira planilha inteira sem assumir linha fixa de cabeçalho."""
    engine = (
        "openpyxl"
        if caminho_arquivo.suffix.lower() != ".xls"
        else None
    )

    return pd.read_excel(
        caminho_arquivo,
        sheet_name=0,
        header=None,
        dtype=object,
        engine=engine,
    )


def encontrar_linha_cabecalho_notas_item(
    caminho_arquivo: Path,
    max_rows: int = 250,
    planilha_bruta: pd.DataFrame | None = None,
) -> int | None:
    """
    Localiza o cabeçalho da TABELA PRINCIPAL.

    No relatório oficial ele começa em:
    Item | Descrição | Empresa | Unidade | Comprador | Emissão | Entrada | ...

    Arquivos sem movimento podem não trazer a tabela principal; nesse caso
    retorna None para que o arquivo seja ignorado sem gerar erro.
    """
    preview = (
        planilha_bruta
        if planilha_bruta is not None
        else _ler_planilha_notas_item_bruta(caminho_arquivo)
    )

    preview = preview.head(max_rows)

    for index in range(len(preview)):
        chaves = {
            header_key(v)
            for v in preview.iloc[index].tolist()
            if clean_col_name(v)
        }

        # Reconhecimento propositalmente simples e fiel ao Excel oficial.
        # "Item" sozinho aparece também no bloco de filtros superior, então
        # exigimos Descrição + Empresa + Unidade na mesma linha.
        if {
            "item",
            "descricao",
            "empresa",
            "unidade",
        }.issubset(chaves):
            return index

    return None


def extrair_parametros_superiores_notas_item(
    planilha_bruta: pd.DataFrame,
) -> dict:
    """
    Extrai o bloco superior do relatório e transforma os filtros em colunas.

    Exemplo do Excel:
      Empresa | Unidade | Item | Data Inicial | Data Final | Tipo de Saída | Grupo | Operação
      1 - ... | Todas   | Todos| 01/08/2026   | 01/08/2026 | ...           | Todos | ...

    Os nomes recebem o prefixo Parametro_ para não colidir com Empresa,
    Unidade e Item da tabela principal.
    """
    aliases = {
        "empresa": "Parametro_Empresa",
        "unidade": "Parametro_Unidade",
        "item": "Parametro_Item",
        "data inicial": "Parametro_Data_Inicial",
        "data final": "Parametro_Data_Final",
        "tipo de saida": "Parametro_Tipo_Saida",
        "grupo": "Parametro_Grupo",
        "operacao": "Parametro_Operacao",
    }

    for index in range(max(0, len(planilha_bruta) - 1)):
        linha = planilha_bruta.iloc[index].tolist()
        chaves = [header_key(v) for v in linha]

        # É o bloco superior quando possui Empresa/Unidade/Item e as datas.
        conjunto = {chave for chave in chaves if chave}
        if not {
            "empresa",
            "unidade",
            "item",
            "data inicial",
            "data final",
        }.issubset(conjunto):
            continue

        valores = planilha_bruta.iloc[index + 1].tolist()
        parametros = {}

        for posicao, chave in enumerate(chaves):
            if chave not in aliases:
                continue

            valor = valores[posicao] if posicao < len(valores) else None
            parametros[aliases[chave]] = valor

        # Datas do bloco superior já saem prontas para o Power BI.
        for coluna in [
            "Parametro_Data_Inicial",
            "Parametro_Data_Final",
        ]:
            if coluna in parametros:
                serie = pd.Series([parametros[coluna]], dtype=object)
                convertido = parse_known_dates(serie).iloc[0]
                parametros[coluna] = convertido

        return parametros

    return {}


def padronizar_colunas_notas_item(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza os 42 campos da tabela principal sem excluir nenhum campo."""
    mapping = {
        "item": "Item",
        "descricao": "Descricao_Item",
        "empresa": "Empresa",
        "unidade": "Unidade",
        "comprador": "Comprador",
        "emissao": "Emissao",
        "entrada": "Entrada",
        "vencimento": "Vencimento",
        "numero nf": "Numero_NF",
        "codigo": "Fornecedor_Codigo",
        "razao social fornecedor": "Fornecedor",
        "tp frete": "Tipo_Frete",
        "vl frete": "Valor_Frete",
        "cfop nf": "CFOP_NF",
        "cfop livro": "CFOP_Livro",
        "qtd nf": "Quantidade_NF",
        "n ticket": "Numero_Ticket",
        "numero ticket": "Numero_Ticket",
        "qtd ticket": "Quantidade_Ticket",
        "quebra": "Quebra",
        "um": "UM",
        "valor item": "Valor_Item",
        "valor unit item": "Valor_Unitario_Item",
        "ipi": "IPI",
        "despesas": "Despesas",
        "frete p item": "Frete_Item",
        "descto": "Desconto",
        "valor pis": "Valor_PIS",
        "valor cofins": "Valor_COFINS",
        "valor icms": "Valor_ICMS",
        "valor liq item": "Valor_Liquido_Item",
        "valor unit liq": "Valor_Unitario_Liquido",
        "nf prod": "NF_Prod",
        "cef": "CEF",
        "c custo": "Centro_Custo",
        "oc": "Ordem_Compra",
        "valor oc": "Valor_OC",
        "emissao oc": "Emissao_OC",
        "cod cond pagto": "Codigo_Condicao_Pagamento",
        "descricao cond pagto": "Descricao_Condicao_Pagamento",
        "proj": "Projeto",
        "contrato": "Contrato",
        "placa": "Placa",
    }

    rename = {}

    for coluna in df.columns:
        chave = header_key(coluna)
        if chave in mapping:
            destino = mapping[chave]
            if destino not in rename.values():
                rename[coluna] = destino

    return df.rename(columns=rename)


def tratar_notas_fiscais_item_arquivo(caminho_arquivo: Path) -> pd.DataFrame:
    # Lemos uma única vez para localizar cabeçalho, parâmetros e fim da tabela.
    planilha_bruta = _ler_planilha_notas_item_bruta(caminho_arquivo)

    header_row = encontrar_linha_cabecalho_notas_item(
        caminho_arquivo,
        planilha_bruta=planilha_bruta,
    )

    # Arquivos sem movimento podem conter somente o cabeçalho superior.
    if header_row is None:
        print("  SEM DADOS: tabela principal não encontrada; arquivo ignorado.")
        return pd.DataFrame()

    print(
        "  Cabeçalho Notas Fiscais do Item encontrado na linha:",
        header_row + 1,
    )

    parametros = extrair_parametros_superiores_notas_item(
        planilha_bruta
    )

    # A tabela principal termina no primeiro espaço totalmente vazio após
    # o cabeçalho. Assim não entram o rodapé de totais nem seus valores.
    fim_dados = len(planilha_bruta)

    for index in range(header_row + 1, len(planilha_bruta)):
        linha = planilha_bruta.iloc[index]
        if linha.isna().all():
            fim_dados = index
            break

    cabecalho = make_unique_columns(
        planilha_bruta.iloc[header_row].tolist()
    )

    df = planilha_bruta.iloc[
        header_row + 1:fim_dados
    ].copy()
    df.columns = cabecalho

    # Mantém TODAS as colunas da tabela principal, inclusive as que estejam
    # totalmente vazias em um determinado dia. Isso preserva a estrutura
    # fixa do relatório no Parquet e evita sumir campo no Power BI.
    df = df.dropna(axis=0, how="all").copy()

    df = padronizar_colunas_notas_item(df)

    if "Item" not in df.columns:
        raise ValueError(
            "A coluna Item não foi encontrada em "
            f"{caminho_arquivo.name}"
        )

    # Segurança adicional: somente linhas analíticas da tabela principal.
    item_texto = normalize_text(df["Item"])
    df = df[
        item_texto.notna()
        & ~item_texto.str.lower().str.startswith("total", na=False)
    ].copy()

    if df.empty:
        print("  SEM DADOS: tabela principal encontrada, porém sem itens.")
        return df

    # Datas da tabela principal.
    for coluna in [
        "Emissao",
        "Entrada",
        "Vencimento",
        "Emissao_OC",
    ]:
        if coluna in df.columns:
            df[coluna] = parse_known_dates(df[coluna])

    # Valores/quantidades. Códigos permanecem como texto para filtros/chaves.
    colunas_numericas = [
        "Valor_Frete",
        "Quantidade_NF",
        "Quantidade_Ticket",
        "Quebra",
        "Valor_Item",
        "Valor_Unitario_Item",
        "IPI",
        "Despesas",
        "Frete_Item",
        "Desconto",
        "Valor_PIS",
        "Valor_COFINS",
        "Valor_ICMS",
        "Valor_Liquido_Item",
        "Valor_Unitario_Liquido",
        "Valor_OC",
    ]

    for coluna in colunas_numericas:
        if coluna in df.columns:
            df[coluna] = to_numeric_ptbr(df[coluna])

    # Campos de código/chave em texto para não perder zeros ou formato.
    colunas_codigo_texto = [
        "Item",
        "Empresa",
        "Unidade",
        "Comprador",
        "Numero_NF",
        "Fornecedor_Codigo",
        "CFOP_NF",
        "CFOP_Livro",
        "Numero_Ticket",
        "UM",
        "NF_Prod",
        "CEF",
        "Centro_Custo",
        "Ordem_Compra",
        "Codigo_Condicao_Pagamento",
        "Projeto",
        "Contrato",
        "Placa",
    ]

    for coluna in colunas_codigo_texto:
        if coluna in df.columns:
            df[coluna] = normalize_text(df[coluna])

    # Demais objetos viram texto limpo.
    for coluna in list(df.columns):
        if (
            pd.api.types.is_object_dtype(df[coluna])
            or pd.api.types.is_string_dtype(df[coluna])
        ):
            df[coluna] = normalize_text(df[coluna])

    # Replica os parâmetros do topo em todas as linhas analíticas.
    for coluna, valor in parametros.items():
        df[coluna] = valor

    periodo_inicio, periodo_fim = extrair_periodo_notas_item_nome(
        caminho_arquivo
    )

    try:
        empresa_pasta = caminho_arquivo.parent.relative_to(
            PASTA_NOTAS_FISCAIS_ITEM
        ).parts[0]
    except Exception:
        empresa_pasta = caminho_arquivo.parent.name

    df["Empresa_Origem_Pasta"] = empresa_pasta
    df["Arquivo_Origem"] = caminho_arquivo.name
    df["Caminho_Origem"] = str(caminho_arquivo)
    df["Periodo_Arquivo_Inicio"] = periodo_inicio
    df["Periodo_Arquivo_Fim"] = periodo_fim
    df["_Arquivo_Modificado_Em"] = datetime.fromtimestamp(
        caminho_arquivo.stat().st_mtime
    )

    # Data analítica preferencial: Entrada; depois Emissão; depois data do arquivo.
    if (
        "Entrada" in df.columns
        and pd.api.types.is_datetime64_any_dtype(df["Entrada"])
    ):
        df["Data_Analise"] = df["Entrada"]
    elif (
        "Emissao" in df.columns
        and pd.api.types.is_datetime64_any_dtype(df["Emissao"])
    ):
        df["Data_Analise"] = df["Emissao"]
    else:
        df["Data_Analise"] = periodo_inicio

    if pd.api.types.is_datetime64_any_dtype(df["Data_Analise"]):
        df["Ano"] = df["Data_Analise"].dt.year
        df["Mes_Numero"] = df["Data_Analise"].dt.month
        df["Dia"] = df["Data_Analise"].dt.day
        df["AnoMes"] = (
            df["Data_Analise"].dt.year * 100
            + df["Data_Analise"].dt.month
        )

    return df.reset_index(drop=True)

def chave_deduplicacao_notas_item(df: pd.DataFrame):
    candidatos = [
        "Empresa",
        "Unidade",
        "Item",
        "Numero_NF",
        "Fornecedor_Codigo",
        "Fornecedor",
        "Comprador",
        "Emissao",
        "Entrada",
        "Vencimento",
        "Ordem_Compra",
        "Quantidade_NF",
        "Valor_Item",
        "Valor_Liquido_Item",
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
            "Caminho_Origem",
            "Empresa_Origem_Pasta",
            "Periodo_Arquivo_Inicio",
            "Periodo_Arquivo_Fim",
            "_Arquivo_Modificado_Em",
        }
    ]


def consolidar_notas_fiscais_item():
    arquivos = listar_arquivos_notas_fiscais_item()

    if not arquivos:
        raise FileNotFoundError(
            "Nenhum Excel de Notas Fiscais do Item encontrado em: "
            f"{PASTA_NOTAS_FISCAIS_ITEM}"
        )

    print()
    print("=" * 80)
    print("TRATANDO NOTAS FISCAIS DO ITEM")
    print("=" * 80)
    print("Arquivos encontrados:", len(arquivos))

    bases = []
    erros = []

    for numero, arquivo in enumerate(arquivos, start=1):
        print()
        print(
            f"[NFI {numero}/{len(arquivos)}] "
            f"{arquivo.parent.name} / {arquivo.name}"
        )

        try:
            tratado = tratar_notas_fiscais_item_arquivo(arquivo)
            print("  OK:", f"{len(tratado):,}", "linhas")
            if not tratado.empty:
                bases.append(tratado)
        except Exception as erro:
            erros.append((str(arquivo), str(erro)))
            print("  ERRO:", arquivo)
            traceback.print_exc()

    if not bases:
        raise RuntimeError(
            "Nenhum arquivo de Notas Fiscais do Item foi tratado com sucesso."
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

    chave = chave_deduplicacao_notas_item(resultado)

    resultado = resultado.drop_duplicates(
        subset=chave,
        keep="last",
    )

    resultado = resultado.drop(
        columns=["_Arquivo_Modificado_Em"],
        errors="ignore",
    ).reset_index(drop=True)

    print("Linhas antes da deduplicação:", f"{linhas_antes:,}")
    print("Duplicadas removidas:", f"{linhas_antes - len(resultado):,}")
    print("Linhas finais Notas Fiscais do Item:", f"{len(resultado):,}")

    if "Data_Analise" in resultado.columns:
        print("Data mínima:", resultado["Data_Analise"].min())
        print("Data máxima:", resultado["Data_Analise"].max())

    if erros:
        print()
        print(
            f"AVISO: {len(erros)} arquivo(s) de Notas Fiscais do Item tiveram erro:"
        )
        for nome, erro in erros:
            print(f"  - {nome}: {erro}")

    return resultado



# =============================================================================
# 13) MAIN
# =============================================================================

def main():
    start = time.time()

    print("=" * 80)
    print("TRATAMENTO SUPRIMENTOS")
    print("=" * 80)
    print("1) Contas Pagas")
    print("2) Relatório de Usuários")
    print("3) Ordens de Compras Emitidas")
    print("4) Solicitações por Requisitante")
    print("5) Títulos Agrupados")
    print("6) Relação OC x NF")
    print("7) Notas Fiscais do Item")
    print("=" * 80)

    # -----------------------------------------------------------------
    # RELATÓRIO DE USUÁRIOS
    # -----------------------------------------------------------------
    usuarios = consolidar_relatorio_usuarios()

    usuarios = normalizar_tipos_para_parquet(
        usuarios
    )

    salvar_parquet_seguro(
        usuarios,
        ARQUIVO_PARQUET_USUARIOS,
    )

    print(
        "Parquet Relatório de Usuários salvo:",
        ARQUIVO_PARQUET_USUARIOS,
    )

    # -----------------------------------------------------------------
    # TÍTULOS AGRUPADOS
    # -----------------------------------------------------------------
    titulos_agrupados = consolidar_titulos_agrupados()

    titulos_agrupados = normalizar_tipos_para_parquet(
        titulos_agrupados
    )

    salvar_parquet_seguro(
        titulos_agrupados,
        ARQUIVO_PARQUET_TITULOS_AGRUPADOS,
    )

    print(
        "Parquet Títulos Agrupados salvo:",
        ARQUIVO_PARQUET_TITULOS_AGRUPADOS,
    )

    # -----------------------------------------------------------------
    # RELAÇÃO OC X NF
    # -----------------------------------------------------------------
    relacao_oc_nf = consolidar_relacao_oc_nf()

    relacao_oc_nf = adicionar_nome_comprador_relacao_oc_nf(
        relacao_oc_nf,
        usuarios,
    )

    relacao_oc_nf = normalizar_tipos_para_parquet(
        relacao_oc_nf
    )

    salvar_parquet_seguro(
        relacao_oc_nf,
        ARQUIVO_PARQUET_RELACAO_OC_NF,
    )

    print(
        "Parquet Relação OC x NF salvo:",
        ARQUIVO_PARQUET_RELACAO_OC_NF,
    )

    # -----------------------------------------------------------------
    # NOTAS FISCAIS DO ITEM
    # -----------------------------------------------------------------
    notas_fiscais_item = consolidar_notas_fiscais_item()

    notas_fiscais_item = normalizar_tipos_para_parquet(
        notas_fiscais_item
    )

    salvar_parquet_seguro(
        notas_fiscais_item,
        ARQUIVO_PARQUET_NOTAS_FISCAIS_ITEM,
    )

    print(
        "Parquet Notas Fiscais do Item salvo:",
        ARQUIVO_PARQUET_NOTAS_FISCAIS_ITEM,
    )

    # -----------------------------------------------------------------
    # CONTAS PAGAS
    # -----------------------------------------------------------------
    contas_pagas = consolidar_contas_pagas()

    contas_pagas = normalizar_tipos_para_parquet(
        contas_pagas
    )

    salvar_parquet_seguro(
        contas_pagas,
        ARQUIVO_PARQUET,
    )

    print(
        "Parquet Contas Pagas salvo:",
        ARQUIVO_PARQUET,
    )


    # -----------------------------------------------------------------
    # ORDENS DE COMPRAS
    # -----------------------------------------------------------------
    ordens_compras = consolidar_ordens_compras()

    ordens_compras = adicionar_nome_comprador_ordens(
        ordens_compras,
        usuarios,
    )

    ordens_compras = normalizar_tipos_para_parquet(
        ordens_compras
    )

    salvar_parquet_seguro(
        ordens_compras,
        ARQUIVO_PARQUET_ORDENS,
    )

    print(
        "Parquet Ordens de Compras salvo:",
        ARQUIVO_PARQUET_ORDENS,
    )

    # -----------------------------------------------------------------
    # SOLICITAÇÕES POR REQUISITANTE
    # -----------------------------------------------------------------
    solicitacoes = consolidar_solicitacoes_requisitante()

    solicitacoes = adicionar_nome_comprador_solicitacoes(
        solicitacoes,
        usuarios,
    )

    solicitacoes = normalizar_tipos_para_parquet(
        solicitacoes
    )

    salvar_parquet_seguro(
        solicitacoes,
        ARQUIVO_PARQUET_SOLICITACOES,
    )

    print(
        "Parquet Solicitações por Requisitante salvo:",
        ARQUIVO_PARQUET_SOLICITACOES,
    )

    duration = time.time() - start

    print()
    print("=" * 80)
    print("TRATAMENTO SUPRIMENTOS FINALIZADO")
    print("=" * 80)
    print("Contas Pagas:", f"{len(contas_pagas):,}", "linhas")
    print("Ordens de Compras:", f"{len(ordens_compras):,}", "linhas")
    print("Relatório de Usuários:", f"{len(usuarios):,}", "linhas")
    print("Solicitações por Requisitante:", f"{len(solicitacoes):,}", "linhas")
    print("Títulos Agrupados:", f"{len(titulos_agrupados):,}", "linhas")
    print("Relação OC x NF:", f"{len(relacao_oc_nf):,}", "linhas")
    print("Notas Fiscais do Item:", f"{len(notas_fiscais_item):,}", "linhas")
    print("Tempo:", f"{duration / 60:.2f} minuto(s)")
    print("=" * 80)

    return 0


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--completo",
        action="store_true",
        help=(
            "Compatibilidade com o Portal BI. O tratamento atual já consolida "
            "todos os arquivos disponíveis."
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
            "ERRO NO TRATAMENTO SUPRIMENTOS"
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
