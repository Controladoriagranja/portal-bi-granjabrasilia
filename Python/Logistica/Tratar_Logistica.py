import os
import argparse
import re
import glob
import time
import unicodedata
import pandas as pd

# =========================
# 1) CONFIG - suas pastas
# =========================
PASTA_DEVOLUCOES   = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Devolucoes"
PASTA_FRETE        = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Frete"
PASTA_SETOR        = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Setor"
PASTA_TRANSP_TIPO  = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Transportador Atacado ou Varejo"

PASTA_VEICULOS       = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Relatorio de Veiculos"
PASTA_CONTROLE_FRETE = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Controle de Frete"
PASTA_PESAGEM        = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Movimento Geral de Pesagem"

PASTA_CAD_VENDEDORES   = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Cadastro de Vendedores"
PASTA_FATURAMENTO_CFOP = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Faturamento por CFOP"

PASTA_OCORRENCIAS   = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Ocorrência de Viagens e Custo"
PASTA_CONTAS_PAGAR  = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Contas a pagar"
PASTA_PALLETS       = r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Controle de pallets"

PASTA_SAIDA = r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Logistica"
os.makedirs(PASTA_SAIDA, exist_ok=True)

TOTAL_ETAPAS_TRATAR = 14

def etapa_tratar(numero: int, descricao: str):
    print("\n" + "=" * 80, flush=True)
    print(f"[TRATAR] {numero}/{TOTAL_ETAPAS_TRATAR} - {descricao}", flush=True)
    print("=" * 80, flush=True)

def resumo_df(nome: str, df: pd.DataFrame):
    linhas = len(df) if df is not None else 0
    print(f"[TRATAR] OK - {nome}: {linhas} linhas", flush=True)


# =========================
# 2) FUNÇÕES UTILITÁRIAS
# =========================
def clean_col_name(c) -> str:
    if c is None:
        return ""
    c = str(c)
    c = c.replace("_x000d_", " ")
    c = c.replace("\n", " ")
    c = re.sub(r"\s+", " ", c).strip()
    return c

def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )

def header_key(text: str) -> str:
    t = clean_col_name(text)
    t = _strip_accents(t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def normalize_text(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"nan": None, "None": None, "": None})
    return s

def to_numeric_ptbr(series: pd.Series) -> pd.Series:
    """
    Converte números pt-BR e mistos de forma segura.

    Exemplos:
    1.234,56 -> 1234.56
    0,3370   -> 0.3370
    0.3370   -> 0.3370
    337      -> 337
    """
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

def corrigir_colunas_valor_kg(series: pd.Series) -> pd.Series:
    """
    Corrige colunas Valor/KG que vieram escaladas 1000x.

    Exemplo:
    337 -> 0.337
    371 -> 0.371
    0.2985 permanece igual
    """
    s = pd.to_numeric(series, errors="coerce")

    mask = (
        s.notna() &
        (s > 10) &
        (s < 1000)
    )

    s.loc[mask] = s.loc[mask] / 1000
    return s

def drop_total_rows(df: pd.DataFrame) -> pd.DataFrame:
    mask_total = df.astype(str).apply(
        lambda col: col.str.contains(r"^\s*Total:?\s*$", case=False, regex=True, na=False)
    )
    return df.loc[~mask_total.any(axis=1)].copy()

def find_header_row_preview(xlsx_path: str, required_headers: set, max_rows: int = 250) -> int | None:
    preview = pd.read_excel(xlsx_path, header=None, nrows=max_rows, engine="openpyxl")
    req = set(header_key(h) for h in required_headers if h)

    # 1) Tenta achar a linha que contém TODOS os cabeçalhos obrigatórios
    for i in range(len(preview)):
        row_vals = set(header_key(v) for v in preview.iloc[i].tolist() if pd.notna(v))
        if req.issubset(row_vals):
            return i

    # 2) Se não achar todos, pega a melhor linha com pelo menos 3 cabeçalhos importantes
    melhor_linha = None
    melhor_score = 0

    for i in range(len(preview)):
        row_vals = set(header_key(v) for v in preview.iloc[i].tolist() if pd.notna(v))
        score = len(req.intersection(row_vals))

        if score > melhor_score:
            melhor_score = score
            melhor_linha = i

    if melhor_score >= 3:
        return melhor_linha

    return None

def read_system_xlsx(xlsx_path: str, required_headers: set) -> pd.DataFrame:
    hdr = find_header_row_preview(xlsx_path, required_headers=required_headers)

    if hdr is None:
        print(f"AVISO: Não achei cabeçalho válido, arquivo ignorado: {xlsx_path}")
        return pd.DataFrame()

    df = pd.read_excel(xlsx_path, header=hdr, engine="openpyxl")
    df.columns = [clean_col_name(c) for c in df.columns]
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all").copy()
    return df

def force_string_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = normalize_text(df[c])
    return df

def force_all_object_to_string(df: pd.DataFrame) -> pd.DataFrame:
    obj_cols = df.select_dtypes(include=["object", "string"]).columns
    for c in obj_cols:
        df[c] = normalize_text(df[c])
    return df

def parse_known_dates_only(series: pd.Series) -> pd.Series:
    s = normalize_text(series)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")

    if s.isna().all():
        return out

    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
    if iso.any():
        out.loc[iso] = pd.to_datetime(s.loc[iso], errors="coerce", format="%Y-%m-%d %H:%M:%S")
        missing = iso & out.isna()
        if missing.any():
            out.loc[missing] = pd.to_datetime(s.loc[missing], errors="coerce", format="%Y-%m-%d")

    br = (~iso) & s.str.match(r"^\d{2}/\d{2}/\d{4}", na=False)
    if br.any():
        out.loc[br] = pd.to_datetime(s.loc[br], errors="coerce", format="%d/%m/%Y %H:%M:%S")
        missing = br & out.isna()
        if missing.any():
            out.loc[missing] = pd.to_datetime(s.loc[missing], errors="coerce", format="%d/%m/%Y")

    br2 = out.isna() & s.str.match(r"^\d{2}-\d{2}-\d{4}", na=False)
    if br2.any():
        out.loc[br2] = pd.to_datetime(s.loc[br2], errors="coerce", format="%d-%m-%Y %H:%M:%S")
        missing = br2 & out.isna()
        if missing.any():
            out.loc[missing] = pd.to_datetime(s.loc[missing], errors="coerce", format="%d-%m-%Y")

    br3 = out.isna() & s.str.match(r"^\d{2}/\d{2}/\d{2}$", na=False)
    if br3.any():
        out.loc[br3] = pd.to_datetime(s.loc[br3], errors="coerce", format="%d/%m/%y")

    return out

def add_date_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col not in df.columns:
        return df

    raw = normalize_text(df[col])
    parsed = parse_known_dates_only(raw)

    df[col] = parsed
    df[f"{col}_RAW"] = raw.where(parsed.isna() & raw.notna(), None)
    return df

def placa_norm(series: pd.Series) -> pd.Series:
    s = normalize_text(series)
    return (
        s.astype(str)
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
        .replace({"NAN": None, "NONE": None, "": None, "nan": None, "None": None})
    )

def time_to_minutes(series: pd.Series) -> pd.Series:
    s = normalize_text(series)
    s = s.replace({None: ""}).fillna("")
    m = s.str.extract(r"^(?P<h>\d{1,2}):(?P<min>\d{2})(:(?P<sec>\d{2}))?$")
    h = pd.to_numeric(m["h"], errors="coerce")
    mi = pd.to_numeric(m["min"], errors="coerce")
    sec = pd.to_numeric(m["sec"], errors="coerce")
    sec = sec.fillna(0)
    return h * 60 + mi + (sec / 60)

def limpar_observacao(texto: str) -> str:
    if texto is None or pd.isna(texto):
        return None

    texto = str(texto)

    # Remove ponto entre números → 630.328 → 630328
    texto = re.sub(r'(?<=\d)\.(?=\d)', '', texto)

    # Remove ponto final
    texto = re.sub(r'\.+$', '', texto)

    # Remove espaços duplicados
    texto = re.sub(r'\s+', ' ', texto)

    return texto.strip()

# =========================
# 3) TRATAMENTO DEVOLUÇÃO
# =========================
def tratar_devolucao(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)

    df = add_date_column(df, "Data Entrada")
    if "Data Entrada" in df.columns:
        df = df[df["Data Entrada"].notna()].copy()

    for col in ["Valor NF", "Valor R$ da Devolução", "Peso (Kg)"]:
        if col in df.columns:
            df[col] = to_numeric_ptbr(df[col])

    df = force_string_columns(df, [
        "Pedido", "Nota", "NF Origem", "Cliente",
        "Série", "Serie", "Nome Fantasia"
    ])

    ren = {
        "Codigo Mot.Devol": "Codigo Motivo Devol",
        "Cidade/UF": "Cidade UF",
        "Serie": "Série"
    }
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    return df

# =========================
# 4) TRATAMENTO FRETE
# =========================
def tratar_frete(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    for c in ["Data de Entrega", "Data de Vencimento", "Data de Pagamento"]:
        df = add_date_column(df, c)

    cols_num = [
        "ICMS (%)", "ICMS (R$)", "Frete (R$)", "Pedagio (R$)", "Descarga (R$)",
        "Frete Total (R$)", "Peso Bruto (KG)", "Valor/KG Bruto(R$)",
        "Peso Líquido (KG)", "Valor/KG Liq(R$)"
    ]
    for c in cols_num:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    for c in ["Valor/KG Bruto(R$)", "Valor/KG Liq(R$)"]:
        if c in df.columns:
            df[c] = corrigir_colunas_valor_kg(df[c])

    df = force_string_columns(df, [
        "Ordem de Carga", "Conhecimento", "Nota", "Título",
        "NF. de Serviço", "Romaneio", "Resumo de Frete",
        "Série", "Serie", "Transportador"
    ])

    ren = {"Serie": "Série"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    return df

# =========================
# 5) TRATAMENTO CONTROLE DE FRETE
# =========================
def tratar_controle_frete(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    df = add_date_column(df, "Data de Entrega")

    cols_num = [
        "Entregas (Quant.)",
        "Valor Total Pedágio",
        "Diária(R$)",
        "Descarga (R$)",
        "Ocor.Custo (R$)",
        "Frete (R$)",
        "Total Frete (R$)",
        "Peso Bruto (KG)",
        "Valor/KG (R$)",
        "Peso Líquido (KG)",
        "Valor/KG Liq(R$)",
        "Valor/KG Tabela(R$)",
        "Frete Tabela(R$)",
        "Ocup(%)",
        "Desvio(%)",
        "Pedag +Frete",
        "Pedag + Frete/Peso Resumo",
    ]
    for c in cols_num:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    for c in [
        "Valor/KG (R$)",
        "Valor/KG Liq(R$)",
        "Valor/KG Tabela(R$)"
    ]:
        if c in df.columns:
            df[c] = corrigir_colunas_valor_kg(df[c])

    df = force_string_columns(df, [
        "Ordem Carga", "Tp Carga", "Data de Entrega", "Base", "Transportador",
        "Placa", "Tp. Veículo", "Rota", "UF", "Viagem"
    ])

    if "Placa" in df.columns:
        df["Placa_Norm"] = placa_norm(df["Placa"])

    return df

# =========================
# 6) TRATAMENTO VEÍCULOS
# =========================
def tratar_veiculos(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    if "Capacidade Kg" in df.columns:
        df["Capacidade Kg"] = to_numeric_ptbr(df["Capacidade Kg"])

    df = force_string_columns(df, [
        "Placa", "Nome", "Motorista", "Código", "Transportador",
        "Tipo", "Tipo Produto Transportado"
    ])

    if "Placa" in df.columns:
        df["Placa_Norm"] = placa_norm(df["Placa"])

    if "Código" in df.columns:
        df["Código"] = (
            df["Código"].astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .replace({"nan": None, "None": None, "": None})
        )

    return df

# =========================
# 7) TRATAMENTO PESAGEM
# =========================
def tratar_pesagem(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    for c in ["Dt.Tara", "Dt.Bruto"]:
        df = add_date_column(df, c)

    for c in ["Hr.Tara", "Hr.Bruto", "Time"]:
        if c in df.columns:
            df[f"{c}_Minutos"] = time_to_minutes(df[c])

    for c in ["Peso Bruto", "Peso Tara", "Peso Liquido"]:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    df = force_string_columns(df, [
        "Pesagem", "NF.Saida", "Operação", "Placa", "Motorista",
        "Granja/Fornecedor", "Lote", "Silo", "Item", "Descrição Item",
        "Seq", "Refer", "Lacre", "Obs", "Usuario", "Captura"
    ])

    if "Placa" in df.columns:
        df["Placa_Norm"] = placa_norm(df["Placa"])

    return df

# =========================
# 8) TRATAMENTO CADASTRO VENDEDORES
# =========================
def tratar_cadastro_vendedores(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    cols_num = ["Código", "Matrícula", "Código SM", "%Com. Padrão", "%Comis. Caractere", "%Desconto"]
    for c in cols_num:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    df = force_string_columns(df, [
        "Nome", "Usuário Logado", "Situação", "E-mail", "Telefone",
        "Tipo Vendedor", "Fornecedor", "Nome Fornecedor", "Função",
        "Supervisor", "Nome Supervisor", "Vendedor Pai", "Nome Vendedor Pai",
        "Comissionado", "Tipo Comissão", "Coletor", "Usuário Liberador"
    ])

    if "E-mail" in df.columns:
        df["E-mail"] = df["E-mail"].str.lower()

    if "Situação" in df.columns:
        df["Situação"] = df["Situação"].str.upper()

    if "Usuário Logado" in df.columns:
        df["Usuario_Logado_Norm"] = (
            normalize_text(df["Usuário Logado"])
            .str.lower()
            .str.replace(" ", "", regex=False)
        )

    return df

# =========================
# 9) TRATAMENTO FATURAMENTO POR CFOP
# =========================
def tratar_faturamento_cfop(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    df = add_date_column(df, "Data")

    cols_num = [
        "Vendedor", "Mês", "Série", "Número", "Pedido", "Redespacho", "Romaneio",
        "Cliente", "Rede", "Produto", "CFOP", "Volumes", "Peso", "Lista", "Ocorr",
        "Pre.Base", "Preço Praticado", "Valor Produto", "Desconto Comercial",
        "Valor Total Faturado", "Desc. Finan.", "Frete/Kg", "Nota Refaturada",
        "Romaneio Refaturada", "Nota Devolução", "Cliente Original"
    ]
    for c in cols_num:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    if "Frete/Kg" in df.columns:
        df["Frete/Kg"] = corrigir_colunas_valor_kg(df["Frete/Kg"])

    df = force_string_columns(df, [
        "Nome", "Meio Venda", "Devolução", "Uni", "OC Principal", "Frete",
        "Razão Social", "Tipo de Cliente", "Nome Fantasia", "Rota Cliente",
        "Rota Pedido", "Cidade", "UF", "Ramo Ativ.", "Descrição", "UM",
        "Família", "Descrição.1", "Cond. Pag. Cliente", "Cond. Pag. Nota"
    ])

    ren = {
        "Descrição.1": "Descrição CFOP"
    }
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})

    if "Vendedor" in df.columns:
        df["Vendedor_Codigo"] = df["Vendedor"]

    return df

# =========================
# 10) TRATAMENTO OCORRÊNCIAS DE VIAGENS E CUSTO
# =========================
def read_ocorrencias_xlsx(xlsx_path: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, header=None, engine="openpyxl")

def extrair_nfs_observacao(texto: str) -> list[str]:
    if texto is None or pd.isna(texto):
        return []

    texto_original = limpar_observacao(str(texto).upper())
    texto_norm = _strip_accents(texto_original).upper()
    texto_norm = re.sub(r"\s+", " ", texto_norm).strip()

    nfs_extraidas = []

    # 1) intervalos tipo 625251 A 625273 / 625251 ATE 625273 / 625251 À 625273
    padrao_intervalo = re.finditer(r'(\d{6})\s*(?:A|ATE)\s*(\d{6})', texto_norm)

    spans_consumidos = []
    for m in padrao_intervalo:
        ini = int(m.group(1))
        fim = int(m.group(2))

        if ini > fim:
            ini, fim = fim, ini

        # trava de segurança
        if (fim - ini) <= 5000:
            for nf in range(ini, fim + 1):
                nfs_extraidas.append(str(nf))

        spans_consumidos.append((m.start(), m.end()))

    # remove trechos já tratados
    texto_restante = texto_norm
    for inicio, fim in sorted(spans_consumidos, reverse=True):
        texto_restante = texto_restante[:inicio] + " " + texto_restante[fim:]

    # 2) NFs avulsas restantes
    nfs_avulsas = re.findall(r'\d{6}', texto_restante)
    nfs_extraidas.extend(nfs_avulsas)

    # remove duplicados preservando ordem
    nfs_unicas = list(dict.fromkeys(nfs_extraidas))

    return nfs_unicas

def tratar_ocorrencias_viagens(df: pd.DataFrame) -> pd.DataFrame:
    linhas_saida = []
    rota_atual = None
    cabecalho_atual = None

    for _, row in df.iterrows():
        valores = row.tolist()
        valores_limpos = [clean_col_name(v) for v in valores]

        primeira = clean_col_name(valores[0]) if len(valores) > 0 else ""

        if re.match(r"^\d+\s-\s.+", primeira):
            rota_atual = primeira
            cabecalho_atual = None
            continue

        if all(v == "" for v in valores_limpos):
            continue

        linha_join = " | ".join(valores_limpos).upper()

        if "OCORRÊNCIAS DE VIAGENS E CUSTOS" in linha_join:
            continue
        if linha_join.strip() == "EMPRESA":
            continue
        if "OCORRÊNCIA DE CUSTO" in linha_join:
            continue

        expected_headers = {
            "Tipo", "Cliente", "Nome", "Descrição", "OC", "Ocorrência",
            "Seq.", "Data", "Valor (R$)", "Observação", "Frete Adc."
        }
        row_header_set = set(v for v in valores_limpos if v)

        if expected_headers.issubset(row_header_set):
            cabecalho_atual = valores_limpos
            continue

        if cabecalho_atual is None or rota_atual is None:
            continue

        dados = {}
        for i, col in enumerate(cabecalho_atual):
            if col != "":
                dados[col] = valores[i] if i < len(valores) else None

        if not dados:
            continue

        if any(
            re.match(r"^\s*Total:?\s*$", str(v), flags=re.IGNORECASE)
            for v in dados.values() if pd.notna(v)
        ):
            continue

        if pd.isna(dados.get("Data")) or pd.isna(dados.get("Valor (R$)")):
            continue

        valor_original = to_numeric_ptbr(pd.Series([dados.get("Valor (R$)")])).iloc[0]
        if pd.isna(valor_original):
            continue

        observacao = limpar_observacao(dados.get("Observação", None))
        nfs = extrair_nfs_observacao(observacao)

        if len(nfs) == 0:
            nfs = [None]

        qtd_nfs = len(nfs)
        valor_dividido = valor_original / qtd_nfs

        for nf in nfs:
            nova = dados.copy()
            nova["Rota"] = rota_atual
            nova["Observação"] = observacao
            nova["NF"] = nf
            nova["Qtd NFs Observação"] = qtd_nfs
            nova["Lista NFs Extraídas"] = ", ".join([str(x) for x in nfs[:50] if x is not None])
            nova["Valor Original (R$)"] = valor_original
            nova["Valor (R$)"] = valor_dividido
            linhas_saida.append(nova)

    if not linhas_saida:
        return pd.DataFrame(columns=[
            "Rota", "Tipo", "Cliente", "Nome", "Descrição", "OC",
            "Ocorrência", "Seq.", "Data", "Valor Original (R$)",
            "Valor (R$)", "Qtd NFs Observação", "Lista NFs Extraídas",
            "Observação", "NF", "Frete Adc."
        ])

    df_final = pd.DataFrame(linhas_saida)
    df_final.columns = [clean_col_name(c) for c in df_final.columns]
    df_final = add_date_column(df_final, "Data")

    for c in ["Valor Original (R$)", "Valor (R$)"]:
        if c in df_final.columns:
            df_final[c] = to_numeric_ptbr(df_final[c])

    df_final = force_string_columns(df_final, [
        "Rota", "Tipo", "Cliente", "Nome", "Descrição", "OC",
        "Ocorrência", "Seq.", "Observação", "NF", "Frete Adc.",
        "Lista NFs Extraídas"
    ])

    if "Observação" in df_final.columns:
        df_final["Observação"] = df_final["Observação"].apply(limpar_observacao)

    return df_final

# =========================
# 11) TRATAMENTO CONTAS A PAGAR
# =========================
def tratar_contas_pagar(df: pd.DataFrame) -> pd.DataFrame:
    df = drop_total_rows(df)
    df.columns = [clean_col_name(c) for c in df.columns]

    for c in ["Inclusão", "Emissão", "Vencimento Original", "Vencimento Atual", "Pagamento"]:
        df = add_date_column(df, c)

    cols_num = [
        "Vl.Nominal", "Vl.Pago", "ADF/DEV", "Juros",
        "Outros Juros", "Desconto", "Saldo", "Atraso"
    ]
    for c in cols_num:
        if c in df.columns:
            df[c] = to_numeric_ptbr(df[c])

    df = force_string_columns(df, [
        "Uni.", "Grupo", "Nome Grupo", "S.Grupo", "Tp.Pessoa",
        "Título", "Par.", "Sit.", "Tipo", "Código", "Nome", "Doc.",
        "Tipo Lanç.", "Número", "Projeto", "Usuário Lib.", "Dados Banc.",
        "Resumo Pgto.", "Usuário"
    ])

    if "Saldo" in df.columns:
        df["Status_Titulo"] = df["Saldo"].apply(
            lambda x: "Aberto" if pd.notna(x) and x > 0 else "Pago"
        )

    if "Saldo" in df.columns and "Vencimento Atual" in df.columns:
        hoje = pd.Timestamp.today().normalize()

        df["Atrasado_Flag"] = df.apply(
            lambda r: "Sim"
            if pd.notna(r["Saldo"]) and r["Saldo"] > 0
            and pd.notna(r["Vencimento Atual"])
            and r["Vencimento Atual"] < hoje
            else "Não",
            axis=1
        )

        df["Dias_Atraso_Calc"] = (hoje - df["Vencimento Atual"]).dt.days

    return df

# =========================
# 12) TRATAMENTO CONTROLE DE PALLETS
# =========================
def read_pallets_xlsx(xlsx_path: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, header=None, engine="openpyxl")

def normalizar_descricao_unidade(texto: str) -> str | None:
    if texto is None or pd.isna(texto):
        return None

    txt_original = clean_col_name(texto)
    txt = _strip_accents(txt_original).lower()
    txt = re.sub(r"[^a-z0-9 ]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()

    if "ave" in txt and "nova" in txt:
        return "Ave Nova"

    if "real" in txt and "alimento" in txt:
        return "Real Alimentos"

    return None

def extrair_descricao_unidade_pallets(df_raw: pd.DataFrame, nome_arquivo: str | None = None) -> str | None:
    """
    Procura 'Ave Nova' ou 'Real Alimentos' no topo da planilha.
    Se não achar, usa o nome do arquivo como fallback.
    """
    limite_linhas = min(20, len(df_raw))
    limite_cols = min(10, len(df_raw.columns))

    for i in range(limite_linhas):
        for j in range(limite_cols):
            valor = clean_col_name(df_raw.iat[i, j])
            unidade = normalizar_descricao_unidade(valor)
            if unidade:
                return unidade

    if nome_arquivo:
        nome = _strip_accents(nome_arquivo).lower()
        nome = re.sub(r"[^a-z0-9]+", " ", nome)

        if "avenova" in nome.replace(" ", "") or ("ave" in nome and "nova" in nome):
            return "Ave Nova"

        if "realalimentos" in nome.replace(" ", "") or ("real" in nome and "alimento" in nome):
            return "Real Alimentos"

    return None

def tratar_pallets(df: pd.DataFrame, nome_arquivo: str | None = None) -> pd.DataFrame:
    df_raw = df.copy()

    for c in df_raw.columns:
        df_raw[c] = df_raw[c].apply(clean_col_name)

    descricao_unidade = extrair_descricao_unidade_pallets(df_raw, nome_arquivo=nome_arquivo)

    idx_produto = None
    for i in df_raw.index:
        linha_txt = " | ".join([clean_col_name(v) for v in df_raw.loc[i].tolist()])
        if "359905 - PALLETE PBR REFORMADO" in linha_txt.upper():
            idx_produto = i
            break

    if idx_produto is None:
        return pd.DataFrame(columns=[
            "Descricao_Unidade", "Transportador", "Descrição", "Endereço", "Saldo", "Saldo Mês"
        ])

    idx_header = None
    for i in range(idx_produto + 1, len(df_raw)):
        linha = [clean_col_name(v) for v in df_raw.loc[i].tolist()]

        if "Transportador" in linha and "Descrição" in linha and "Saldo" in linha and "Saldo Mês" in linha:
            idx_header = i
            break

    if idx_header is None:
        return pd.DataFrame(columns=[
            "Descricao_Unidade", "Transportador", "Descrição", "Endereço", "Saldo", "Saldo Mês"
        ])

    header_vals = [clean_col_name(v) for v in df_raw.loc[idx_header].tolist()]

    pos_transportador = None
    pos_descricao = None
    pos_endereco = None
    pos_saldo = None
    pos_saldo_mes = None

    for idx, col in enumerate(header_vals):
        col_norm = header_key(col)

        if col_norm == "transportador":
            pos_transportador = idx
        elif col_norm == "descricao":
            pos_descricao = idx
        elif col_norm == "endereco":
            pos_endereco = idx
        elif col_norm == "saldo":
            pos_saldo = idx
        elif col_norm == "saldo mes":
            pos_saldo_mes = idx

    idx_fim = None
    for i in range(idx_header + 1, len(df_raw)):
        primeira = clean_col_name(
            df_raw.iat[i, pos_transportador]
            if pos_transportador is not None and pos_transportador < len(df_raw.columns)
            else ""
        )

        if primeira.upper() == "TOTAL":
            idx_fim = i
            break

        linha_txt = " | ".join([clean_col_name(v) for v in df_raw.loc[i].tolist()])
        if "VALE PEDAGIO" in linha_txt.upper():
            idx_fim = i
            break

    if idx_fim is None:
        idx_fim = len(df_raw)

    linhas = []
    for i in range(idx_header + 1, idx_fim):
        transportador = clean_col_name(df.iat[i, pos_transportador]) if pos_transportador is not None else None
        descricao = clean_col_name(df.iat[i, pos_descricao]) if pos_descricao is not None else None
        endereco = clean_col_name(df.iat[i, pos_endereco]) if pos_endereco is not None else None
        saldo = df.iat[i, pos_saldo] if pos_saldo is not None else None
        saldo_mes = df.iat[i, pos_saldo_mes] if pos_saldo_mes is not None else None

        if transportador in [None, "", "TOTAL"]:
            continue

        linhas.append({
            "Descricao_Unidade": descricao_unidade,
            "Transportador": transportador,
            "Descrição": descricao,
            "Endereço": endereco,
            "Saldo": saldo,
            "Saldo Mês": saldo_mes
        })

    bloco = pd.DataFrame(linhas)

    if bloco.empty:
        return pd.DataFrame(columns=[
            "Descricao_Unidade", "Transportador", "Descrição", "Endereço", "Saldo", "Saldo Mês"
        ])

    for c in ["Saldo", "Saldo Mês"]:
        if c in bloco.columns:
            bloco[c] = to_numeric_ptbr(bloco[c])

    bloco = force_string_columns(bloco, [
        "Descricao_Unidade", "Transportador", "Descrição", "Endereço"
    ])

    if "Saldo" in bloco.columns:
        bloco["Status_Pallet"] = bloco["Saldo"].apply(
            lambda x: "A Receber" if pd.notna(x) and x > 0 else (
                "A Devolver" if pd.notna(x) and x < 0 else "OK"
            )
        )

    if "Saldo" in bloco.columns and "Saldo Mês" in bloco.columns:
        bloco["Diferença"] = bloco["Saldo"] - bloco["Saldo Mês"]

    ordem = [
        "Descricao_Unidade", "Transportador", "Descrição",
        "Endereço", "Saldo", "Saldo Mês", "Status_Pallet", "Diferença"
    ]
    ordem_existente = [c for c in ordem if c in bloco.columns]
    bloco = bloco[ordem_existente].copy()

    return bloco.reset_index(drop=True)

# =========================
# 12.1) MODO INCREMENTAL
# =========================
USAR_INCREMENTAL = True


def preparar_incremental_logistica(arquivos, caminho_parquet, nome_base):
    """
    Reaproveita o Parquet e retorna apenas arquivos novos/alterados.
    """
    arquivos = list(arquivos)

    if (
        not USAR_INCREMENTAL
        or not os.path.exists(caminho_parquet)
        or os.path.getsize(caminho_parquet) <= 0
    ):
        print(f"[TRATAR] {nome_base}: modo COMPLETO ({len(arquivos)} arquivos).", flush=True)
        return arquivos, None

    try:
        existente = pd.read_parquet(caminho_parquet)
    except Exception as erro:
        print(f"[TRATAR] {nome_base}: falha ao ler Parquet existente: {erro}", flush=True)
        return arquivos, None

    if existente.empty or "Arquivo_Origem" not in existente.columns:
        print(
            f"[TRATAR] {nome_base}: Parquet antigo sem Arquivo_Origem; "
            "tratamento completo será feito uma vez.",
            flush=True,
        )
        return arquivos, None

    nomes_existentes = set(
        existente["Arquivo_Origem"].dropna().astype("string").astype(str)
    )
    mtime_parquet = os.path.getmtime(caminho_parquet)

    pendentes = []
    for arq in arquivos:
        try:
            if (
                os.path.basename(arq) not in nomes_existentes
                or os.path.getmtime(arq) > mtime_parquet + 0.5
            ):
                pendentes.append(arq)
        except OSError:
            pendentes.append(arq)

    if not pendentes:
        print(
            f"[TRATAR] {nome_base}: nenhum arquivo novo/alterado; "
            "reutilizando Parquet.",
            flush=True,
        )
        return [], existente

    nomes_pendentes = {os.path.basename(a) for a in pendentes}
    existente = existente[
        ~existente["Arquivo_Origem"].astype("string").isin(nomes_pendentes)
    ].copy()

    print(
        f"[TRATAR] {nome_base}: {len(arquivos)} arquivo(s) | "
        f"{len(pendentes)} novo(s)/alterado(s) | "
        f"{len(arquivos)-len(pendentes)} reaproveitado(s).",
        flush=True,
    )
    return pendentes, existente


def _juntar_incremental(base_existente, dfs):
    partes = []
    if base_existente is not None and not base_existente.empty:
        partes.append(base_existente)
    partes.extend([df for df in dfs if df is not None and not df.empty])

    if not partes:
        return pd.DataFrame()

    return pd.concat(partes, ignore_index=True, sort=False).drop_duplicates()


# =========================
# 13) CONSOLIDAÇÃO
# =========================
def consolidar_pasta(
    pasta: str,
    required_headers: set,
    func_tratar,
    caminho_parquet: str,
    nome_base: str,
) -> pd.DataFrame:
    arquivos_todos = sorted(
        glob.glob(os.path.join(pasta, "*.xlsx")) +
        glob.glob(os.path.join(pasta, "*.xls"))
    )
    if not arquivos_todos:
        raise FileNotFoundError(f"Nenhum Excel encontrado em: {pasta}")

    arquivos, base_existente = preparar_incremental_logistica(
        arquivos_todos, caminho_parquet, nome_base
    )

    if not arquivos and base_existente is not None:
        return base_existente.reset_index(drop=True)

    dfs = []
    for arq in arquivos:
        df = read_system_xlsx(arq, required_headers=required_headers)

        if df.empty:
            print(f"IGNORADO: {os.path.basename(arq)} -> sem dados ou sem cabeçalho válido")
            continue

        df = func_tratar(df)

        if df.empty:
            print(f"IGNORADO: {os.path.basename(arq)} -> 0 linhas após tratamento")
            continue

        df["Arquivo_Origem"] = os.path.basename(arq)
        dfs.append(df)
        print(f"OK: {os.path.basename(arq)} -> {len(df)} linhas")

    return _juntar_incremental(base_existente, dfs)


def consolidar_pasta_ocorrencias(
    pasta: str,
    func_tratar,
    caminho_parquet: str,
    nome_base: str,
) -> pd.DataFrame:
    arquivos_todos = sorted(
        glob.glob(os.path.join(pasta, "*.xlsx")) +
        glob.glob(os.path.join(pasta, "*.xls"))
    )
    if not arquivos_todos:
        raise FileNotFoundError(f"Nenhum Excel encontrado em: {pasta}")

    arquivos, base_existente = preparar_incremental_logistica(
        arquivos_todos, caminho_parquet, nome_base
    )

    if not arquivos and base_existente is not None:
        return base_existente.reset_index(drop=True)

    dfs = []
    for arq in arquivos:
        df = read_ocorrencias_xlsx(arq)
        df = func_tratar(df)
        if df is None or df.empty:
            continue
        df["Arquivo_Origem"] = os.path.basename(arq)
        dfs.append(df)
        print(f"OK: {os.path.basename(arq)} -> {len(df)} linhas")

    return _juntar_incremental(base_existente, dfs)


def consolidar_pasta_pallets(
    pasta: str,
    func_tratar,
    caminho_parquet: str,
    nome_base: str,
) -> pd.DataFrame:
    arquivos_todos = sorted(
        glob.glob(os.path.join(pasta, "*.xlsx")) +
        glob.glob(os.path.join(pasta, "*.xls"))
    )
    if not arquivos_todos:
        raise FileNotFoundError(f"Nenhum Excel encontrado em: {pasta}")

    arquivos, base_existente = preparar_incremental_logistica(
        arquivos_todos, caminho_parquet, nome_base
    )

    if not arquivos and base_existente is not None:
        return base_existente.reset_index(drop=True)

    dfs = []
    for arq in arquivos:
        df = read_pallets_xlsx(arq)
        df = func_tratar(df, nome_arquivo=os.path.basename(arq))
        if df is None or df.empty:
            continue
        df["Arquivo_Origem"] = os.path.basename(arq)
        dfs.append(df)
        print(f"OK: {os.path.basename(arq)} -> {len(df)} linhas")

    return _juntar_incremental(base_existente, dfs)


# =========================
# 14) ARGUMENTOS / RUN
# =========================
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-pausa", action="store_true")
    parser.add_argument(
        "--completo",
        action="store_true",
        help="Relê todos os Excel e reconstrói todas as bases da Logística.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    USAR_INCREMENTAL = not args.completo

    print(
        "[TRATAR] Modo:",
        "INCREMENTAL - somente arquivos novos/alterados"
        if USAR_INCREMENTAL
        else "COMPLETO - todos os arquivos",
        flush=True,
    )

    inicio_tratar = time.time()
    etapa_tratar(1, "Lendo e tratando Devoluções")
    # DEVOLUÇÃO
    required_dev = {"Data Entrada", "Pedido", "Nota", "NF Origem", "Motivo", "Peso (Kg)"}
    devolucao = consolidar_pasta(
        PASTA_DEVOLUCOES,
        required_headers=required_dev,
        func_tratar=tratar_devolucao
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "devolucao_tratada.parquet"),
        nome_base="Devoluções"
    )

    resumo_df("Devoluções", devolucao)

    etapa_tratar(2, "Lendo e tratando Frete")
    # FRETE
    required_frete = {"Transportador", "Peso Líquido (KG)", "Frete Total (R$)", "Data de Entrega"}
    frete = consolidar_pasta(
        PASTA_FRETE,
        required_headers=required_frete,
        func_tratar=tratar_frete
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "frete_tratado.parquet"),
        nome_base="Frete"
    )

    resumo_df("Frete", frete)

    etapa_tratar(3, "Lendo e tratando Controle de Frete")
    # CONTROLE FRETE
    required_controle = {
        "Ordem Carga", "Tp Carga", "Data de Entrega", "Base",
        "Transportador", "Placa", "Total Frete (R$)", "Peso Líquido (KG)"
    }
    controle_frete = consolidar_pasta(
        PASTA_CONTROLE_FRETE,
        required_headers=required_controle,
        func_tratar=tratar_controle_frete
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "controle_frete_tratado.parquet"),
        nome_base="Controle de Frete"
    )

    resumo_df("Controle de Frete", controle_frete)

    etapa_tratar(4, "Lendo e tratando Relatório de Veículos")
    # VEÍCULOS
    required_veic = {"Placa", "Nome", "Motorista", "Código", "Transportador", "Tipo", "Capacidade Kg"}
    veiculos = consolidar_pasta(
        PASTA_VEICULOS,
        required_headers=required_veic,
        func_tratar=tratar_veiculos
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "veiculos_tratado.parquet"),
        nome_base="Veículos"
    )

    resumo_df("Veículos", veiculos)

    etapa_tratar(5, "Lendo e tratando Movimento Geral de Pesagem")
    # PESAGEM
    required_pesagem = {"Dt.Tara", "Pesagem", "NF.Saida", "Placa", "Peso Liquido"}
    pesagem = consolidar_pasta(
        PASTA_PESAGEM,
        required_headers=required_pesagem,
        func_tratar=tratar_pesagem
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "pesagem_tratada.parquet"),
        nome_base="Pesagem"
    )

    resumo_df("Pesagem", pesagem)

    etapa_tratar(6, "Lendo e tratando Cadastro de Vendedores")
    # CADASTRO VENDEDORES
    required_vendedores = {"Código", "Nome", "Usuário Logado", "Matrícula"}
    cadastro_vendedores = consolidar_pasta(
        PASTA_CAD_VENDEDORES,
        required_headers=required_vendedores,
        func_tratar=tratar_cadastro_vendedores
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "cadastro_vendedores_tratado.parquet"),
        nome_base="Cadastro Vendedores"
    )

    resumo_df("Cadastro Vendedores", cadastro_vendedores)

    etapa_tratar(7, "Lendo e tratando Faturamento por CFOP")
    # FATURAMENTO POR CFOP
    required_fat_cfop = {"Vendedor", "Nome", "Data", "Mês", "Meio Venda", "Produto", "Valor Total Faturado"}
    faturamento_cfop = consolidar_pasta(
        PASTA_FATURAMENTO_CFOP,
        required_headers=required_fat_cfop,
        func_tratar=tratar_faturamento_cfop
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "faturamento_cfop_tratado.parquet"),
        nome_base="Faturamento CFOP"
    )

    resumo_df("Faturamento CFOP", faturamento_cfop)

    etapa_tratar(8, "Lendo e tratando Ocorrências de Viagens e Custo")
    # OCORRÊNCIAS DE VIAGENS E CUSTO
    ocorrencias_viagens = consolidar_pasta_ocorrencias(
        PASTA_OCORRENCIAS,
        func_tratar=tratar_ocorrencias_viagens
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "ocorrencias_viagens_tratado.parquet"),
        nome_base="Ocorrências Viagens"
    )

    resumo_df("Ocorrências Viagens", ocorrencias_viagens)

    etapa_tratar(9, "Lendo e tratando Contas a Pagar")
    # CONTAS A PAGAR
    required_contas = {"Nome", "Vencimento Atual", "Saldo"}
    contas_pagar = consolidar_pasta(
        PASTA_CONTAS_PAGAR,
        required_headers=required_contas,
        func_tratar=tratar_contas_pagar
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "contas_pagar_tratado.parquet"),
        nome_base="Contas a Pagar"
    )

    resumo_df("Contas a Pagar", contas_pagar)

    etapa_tratar(10, "Lendo e tratando Controle de Pallets")
    # PALLETS
    pallets = consolidar_pasta_pallets(
        PASTA_PALLETS,
        func_tratar=tratar_pallets
    ,
        caminho_parquet=os.path.join(PASTA_SAIDA, "pallets_tratado.parquet"),
        nome_base="Pallets"
    )

    resumo_df("Pallets", pallets)

    etapa_tratar(11, "Normalizando campos de texto")
    # Normaliza strings
    devolucao           = force_all_object_to_string(devolucao)
    frete               = force_all_object_to_string(frete)
    controle_frete      = force_all_object_to_string(controle_frete)
    veiculos            = force_all_object_to_string(veiculos)
    pesagem             = force_all_object_to_string(pesagem)
    cadastro_vendedores = force_all_object_to_string(cadastro_vendedores)
    faturamento_cfop    = force_all_object_to_string(faturamento_cfop)
    ocorrencias_viagens = force_all_object_to_string(ocorrencias_viagens)
    contas_pagar        = force_all_object_to_string(contas_pagar)
    pallets             = force_all_object_to_string(pallets)

    print("[TRATAR] Textos normalizados com sucesso.", flush=True)

    etapa_tratar(12, "Gerando arquivos PARQUET")
    # SAÍDAS (PARQUET)
    out_dev_parquet         = os.path.join(PASTA_SAIDA, "devolucao_tratada.parquet")
    out_frete_parquet       = os.path.join(PASTA_SAIDA, "frete_tratado.parquet")
    out_controle_parquet    = os.path.join(PASTA_SAIDA, "controle_frete_tratado.parquet")
    out_veiculos_parquet    = os.path.join(PASTA_SAIDA, "veiculos_tratado.parquet")
    out_pesagem_parquet     = os.path.join(PASTA_SAIDA, "pesagem_tratada.parquet")
    out_vendedores_parquet  = os.path.join(PASTA_SAIDA, "cadastro_vendedores_tratado.parquet")
    out_fat_cfop_parquet    = os.path.join(PASTA_SAIDA, "faturamento_cfop_tratado.parquet")
    out_ocorrencias_parquet = os.path.join(PASTA_SAIDA, "ocorrencias_viagens_tratado.parquet")
    out_contas_parquet      = os.path.join(PASTA_SAIDA, "contas_pagar_tratado.parquet")
    out_pallets_parquet     = os.path.join(PASTA_SAIDA, "pallets_tratado.parquet")

    devolucao.to_parquet(out_dev_parquet, index=False)
    frete.to_parquet(out_frete_parquet, index=False)
    controle_frete.to_parquet(out_controle_parquet, index=False)
    veiculos.to_parquet(out_veiculos_parquet, index=False)
    pesagem.to_parquet(out_pesagem_parquet, index=False)
    cadastro_vendedores.to_parquet(out_vendedores_parquet, index=False)
    faturamento_cfop.to_parquet(out_fat_cfop_parquet, index=False)
    ocorrencias_viagens.to_parquet(out_ocorrencias_parquet, index=False)
    contas_pagar.to_parquet(out_contas_parquet, index=False)
    pallets.to_parquet(out_pallets_parquet, index=False)

    print("[TRATAR] PARQUET gerado com sucesso.", flush=True)

    etapa_tratar(13, "Gerando arquivos CSV")
    # SAÍDAS (CSV)
    devolucao.to_csv(os.path.join(PASTA_SAIDA, "devolucao_tratada.csv"), index=False, sep=";", encoding="utf-8-sig")
    frete.to_csv(os.path.join(PASTA_SAIDA, "frete_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    controle_frete.to_csv(os.path.join(PASTA_SAIDA, "controle_frete_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    veiculos.to_csv(os.path.join(PASTA_SAIDA, "veiculos_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    pesagem.to_csv(os.path.join(PASTA_SAIDA, "pesagem_tratada.csv"), index=False, sep=";", encoding="utf-8-sig")
    cadastro_vendedores.to_csv(os.path.join(PASTA_SAIDA, "cadastro_vendedores_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    faturamento_cfop.to_csv(os.path.join(PASTA_SAIDA, "faturamento_cfop_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    ocorrencias_viagens.to_csv(os.path.join(PASTA_SAIDA, "ocorrencias_viagens_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    contas_pagar.to_csv(os.path.join(PASTA_SAIDA, "contas_pagar_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")
    pallets.to_csv(os.path.join(PASTA_SAIDA, "pallets_tratado.csv"), index=False, sep=";", encoding="utf-8-sig")

    print("[TRATAR] CSV gerado com sucesso.", flush=True)

    etapa_tratar(14, "Resumo final do tratamento")
    print("\n==============================")
    print("OK! Arquivos gerados em:", PASTA_SAIDA)
    print("Devolução:", len(devolucao), "linhas")
    print("Frete:", len(frete), "linhas")
    print("Controle Frete:", len(controle_frete), "linhas")
    print("Veículos:", len(veiculos), "linhas")
    print("Pesagem:", len(pesagem), "linhas")
    print("Cadastro Vendedores:", len(cadastro_vendedores), "linhas")
    print("Faturamento CFOP:", len(faturamento_cfop), "linhas")
    print("Ocorrências Viagens:", len(ocorrencias_viagens), "linhas")
    print("Contas a Pagar:", len(contas_pagar), "linhas")
    print("Pallets:", len(pallets), "linhas")
    print("Tempo total:", time.strftime("%H:%M:%S", time.gmtime(time.time() - inicio_tratar)))
    print("==============================\n")