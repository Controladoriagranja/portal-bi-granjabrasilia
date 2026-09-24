# -*- coding: utf-8 -*-
r"""
ROBÔ COMERCIAL — CLIENTES CADASTRADOS

Fluxo:
1. O AgrosysEngine faz login, dispara e aguarda o relatório ficar pronto.
2. O Selenium é iniciado em modo headless (oculto).
3. Os cookies da sessão do AgrosysEngine são copiados para o Selenium.
4. O Selenium abre a URL pronta do relatório.
5. Aguarda a função fexcel() ficar disponível.
6. Executa fexcel() e baixa o Excel oficial do Agrosys.
7. Repete para as unidades 10, 111, 180 e 102.
8. Consolida os arquivos e remove clientes duplicados pelo código.

Relatório:
- Cadastro Clientes Quebra por Código
- Caminho: /webpro/webci/wad001d50
- Menu: 18439

Saída:
\\\\192.168.1.139\\Controladoria\\BI_Granja\\Exportacoes\\Comercial\\Clientes Cadastrados
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options


# =============================================================================
# ESTRUTURA DO PROJETO
# =============================================================================

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Comercial\Clientes Cadastrados"
)

from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_TRATADOS = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Tratados\Comercial"
)

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)
PASTA_TRATADOS.mkdir(parents=True, exist_ok=True)

ARQUIVO_CONSOLIDADO_XLSX = (
    PASTA_SAIDA / "clientes_cadastrados.xlsx"
)


ARQUIVO_CONSOLIDADO_PARQUET = (
    PASTA_TRATADOS / "clientes_cadastrados.parquet"
)

ARQUIVO_DUPLICADOS = (
    PASTA_SAIDA / "clientes_cadastrados_duplicados_auditoria.xlsx"
)

ARQUIVO_LOG_FALHAS = (
    PASTA_SAIDA / "falhas_clientes_cadastrados.log"
)

TENTATIVAS_DISPARO = 10
ESPERA_DISPARO = 10

TENTATIVAS_DOWNLOAD_EXCEL = 1
TIMEOUT_AGUARDAR_FEXCEL = 60
TIMEOUT_DOWNLOAD_EXCEL = 180
ESPERA_ENTRE_TENTATIVAS_DOWNLOAD = 15

UNIDADES = [
    {
        "codigo": "10",
        "nome_agrosys": "Ave Nova",
        "nome_arquivo": "Avenova",
        "descricao": "010 - AVE NOVA",
        "empresa_padrao": "Ave Nova",
        "prioridade": 1,
    },
    {
        "codigo": "111",
        "nome_agrosys": "Real Alimentos",
        "nome_arquivo": "RealAlimentos",
        "descricao": "111 - REAL ALIMENTOS",
        "empresa_padrao": "Real Alimentos",
        "prioridade": 2,
    },
    {
        "codigo": "180",
        "nome_agrosys": "CD Ribeirão das Neves",
        "nome_arquivo": "CdRibeiraoDasNeves",
        "descricao": "180 - CD RIBEIRÃO DAS NEVES",
        "empresa_padrao": "CD Ribeirão das Neves",
        "prioridade": 3,
    },
    {
        "codigo": "102",
        "nome_agrosys": "CD Januária",
        "nome_arquivo": "CdJanuaria",
        "descricao": "102 - CD JANUÁRIA",
        "empresa_padrao": "CD Januária",
        "prioridade": 4,
    },
]


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def remover_acentos(texto):
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", str(texto))
        if not unicodedata.combining(caractere)
    )


def normalizar_nome(texto):
    texto = remover_acentos(texto).lower()
    return re.sub(r"[^a-z0-9]+", "", texto)


def limpar_texto(valor):
    if valor is None:
        return ""

    texto = str(valor).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", texto).strip()


def chave_coluna(valor):
    return normalizar_nome(limpar_texto(valor))


def colunas_unicas(colunas):
    usados = {}
    resultado = []

    for indice, coluna in enumerate(colunas):
        nome = limpar_texto(coluna)

        if not nome or nome.lower().startswith("unnamed"):
            nome = f"Coluna_{indice + 1}"

        if nome in usados:
            usados[nome] += 1
            nome = f"{nome}_{usados[nome]}"
        else:
            usados[nome] = 0

        resultado.append(nome)

    return resultado


def normalizar_codigo(valor):
    if valor is None or pd.isna(valor):
        return pd.NA

    texto = str(valor).strip()

    if texto in {"", "nan", "None", "<NA>", "NaT"}:
        return pd.NA

    texto = re.sub(r"\.0$", "", texto)

    encontrado = re.match(r"^\s*(\d+)", texto)
    if encontrado:
        return encontrado.group(1)

    return texto


def registrar_falha(unidade, erro):
    momento = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    linha = (
        f"[{momento}] Unidade={unidade['descricao']} | "
        f"Erro={erro}\n"
    )

    with ARQUIVO_LOG_FALHAS.open(
        "a",
        encoding="utf-8",
    ) as arquivo:
        arquivo.write(linha)


# =============================================================================
# SELENIUM OCULTO — DOWNLOAD DO EXCEL OFICIAL
# =============================================================================

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

    # IMPORTANTE:
    # O relatório de Clientes pode ter dezenas de MB em HTML.
    # Com page_load_strategy = "none", driver.get() não fica esperando
    # a tabela inteira terminar de renderizar.
    chrome_options.page_load_strategy = "none"

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")

    driver = webdriver.Chrome(options=chrome_options)

    # Segurança adicional: não deixar um comando GET prender o ChromeDriver
    # por 120 segundos em páginas gigantes.
    try:
        driver.set_page_load_timeout(20)
    except Exception:
        pass

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
    """
    Aguarda o Excel oficial terminar.

    Compatível com baixar_excel_oficial(..., inicio_download=...):
    - ignora arquivos antigos da pasta;
    - aceita .xlsx/.xls final estável;
    - ignora .crdownload/.tmp/.part auxiliares;
    - considera concluído após ~3 segundos sem crescimento.
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

            # Loop a cada 0,5s -> ~3s estável.
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
    driver.get(BASE_AGROSYS)

    for nome, valor in ag.session.cookies.get_dict().items():
        try:
            driver.add_cookie({
                "name": nome,
                "value": valor,
                "domain": "sistema.granjabrasilia.com.br",
                "path": "/",
            })
        except Exception:
            pass


def baixar_excel_oficial(driver, ag, url_relatorio, arquivo_destino):
    """
    Selenium é usado SOMENTE para baixar o Excel oficial.

    Para Clientes Cadastrados, o HTML do relatório pode ter dezenas de MB.
    Por isso:
    - driver.get() usa page_load_strategy='none';
    - não esperamos a tabela inteira carregar;
    - assim que fexcel() existir, interrompemos o carregamento da página;
    - executamos fexcel() imediatamente.
    """
    limpar_downloads()
    copiar_cookies_para_selenium(driver, ag)

    print("Abrindo relatório oficial sem aguardar HTML completo:", url_relatorio, flush=True)

    inicio_abertura = time.time()

    try:
        driver.get(url_relatorio)
    except Exception as erro:
        # Com page_load_strategy none normalmente não cai aqui,
        # mas se houver timeout de navegação continuamos e tentamos fexcel().
        print(
            "Aviso ao abrir página no Selenium:",
            erro,
            "| vou tentar localizar fexcel() mesmo assim.",
            flush=True,
        )

    limite = time.time() + 45
    pronto = False

    while time.time() < limite:
        try:
            pronto = driver.execute_script(
                "return typeof fexcel === 'function';"
            )

            if pronto:
                break
        except Exception:
            pass

        time.sleep(0.25)

    if not pronto:
        raise TimeoutException(
            "fexcel() não ficou disponível em 45 segundos."
        )

    print(
        f"fexcel() localizado em {time.time() - inicio_abertura:.1f}s.",
        flush=True,
    )

    # Para de carregar/renderizar a tabela gigante.
    try:
        driver.execute_script("window.stop();")
        print(
            "Carregamento do HTML interrompido; não vou esperar a tabela inteira.",
            flush=True,
        )
    except Exception:
        pass

    inicio_download = time.time()

    driver.execute_script("fexcel();")
    print("fexcel() executado.", flush=True)

    # Confirma rapidamente que algum download nasceu.
    inicio_confirmacao = time.time()
    download_iniciado = False

    while time.time() - inicio_confirmacao < 10:
        temporarios = [
            a for a in PASTA_DOWNLOAD.glob("*.crdownload")
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
            "Ainda não detectei arquivo em 10s; vou continuar aguardando o Excel.",
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
            "Excel oficial não foi concluído em 300 segundos. "
            f"Arquivos encontrados: {presentes}"
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


# =============================================================================
# DISPARO DO RELATÓRIO
# =============================================================================

def montar_filtros(unidade):
    """
    Filtros exatamente conforme o formulário/Payload validado no Agrosys.
    Selenium NÃO participa do preenchimento/disparo.
    """
    return {
        "vcheck-come": "yes",
        "vdtini": "",
        "vdtfim": "",
        "vemp-empresa": "1",
        "vemp-nome": "Granja Brasilia Agroindustrial Avicola Ltda",
        "vuni-unidade": unidade["codigo"],
        "vuni-nome": unidade["nome_agrosys"],
        "vsel": "1",
        "vcli-codigo": "",
        "vcli-razsoc": "Todos os Clientes",
        "vcli-situ": "1",
        "vcli-pessoa": "",
        "vven-situ": "1",
        "vcons-sefaz": "",
        "vquebra": "1",
        "vpad-btdisp.x": "Disparar",
    }


def capturar_processo_clientes(html):
    """
    Captura especificamente o processo retornado pelo Cadastro de Clientes.

    Exemplo real do Agrosys:
    fpad_form("/webpro/webpad/wpd007m1?vpad-modo=INC&vmodal=1&vparam=0003771684", ...)
    """
    if not html:
        return None

    html = (
        str(html)
        .replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("%26", "&")
        .replace("%3D", "=")
        .replace("%3d", "=")
    )

    padroes = [
        r'fpad_form\s*\(\s*["\'][^"\']*vparam\s*=\s*0*(\d{6,12})',
        r'wpd007m1\?[^"\'<>]*vparam\s*=\s*0*(\d{6,12})',
        r'[?&]vparam\s*=\s*0*(\d{6,12})',
        r'N[ºo°.]?\s*(?:do\s+)?Processo[^0-9]{0,100}0*(\d{6,12})',
        r'vbatnump[^>]*value\s*=\s*["\']?0*(\d{6,12})',
    ]

    for padrao in padroes:
        encontrado = re.search(
            padrao,
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if encontrado:
            processo = encontrado.group(1).lstrip("0")
            if processo:
                print(
                    "Processo capturado no retorno do Cadastro de Clientes:",
                    processo,
                    flush=True,
                )
                return processo

    return None


def disparar_relatorio_clientes(
    ag,
    unidade,
):
    """
    Disparo próprio deste relatório.

    IMPORTANTE:
    - Requests/AgrosysEngine configura unidade, abre tela e faz POST.
    - Selenium NÃO preenche formulário e NÃO dispara.
    - Selenium só será usado depois, para abrir a URL pronta e executar fexcel().
    """
    filtros = montar_filtros(unidade)
    ultimo_erro = None

    for tentativa in range(
        1,
        TENTATIVAS_DISPARO + 1,
    ):
        print(
            f"Disparo Clientes: tentativa "
            f"{tentativa}/{TENTATIVAS_DISPARO}",
            flush=True,
        )

        try:
            # 1) Configura corretamente a unidade.
            ag.configurar_unidade(
                unidade=unidade["codigo"],
                menu=18439,
                modulo="14400",
            )

            # 2) Abre a tela via requests.
            url, html_tela = ag.abrir_tela(
                caminho="/webpro/webci/wad001d50",
                menu=18439,
            )

            # 3) Extrai os inputs originais.
            dados = ag.extrair_inputs(html_tela)

            # Checkbox desmarcado não é enviado pelo navegador.
            # Removemos para reproduzir exatamente o POST manual.
            campos_nao_enviar = (
                "vchk-excel",
                "vdir-excel",
                "varq-excel",
                "vcheck-cobr",
                "vcheck-logi",
                "vcheck-mark",
                "vcheck-cont",
                "vcheck-fisc",
            )

            for campo in campos_nao_enviar:
                dados.pop(campo, None)

            # 4) Sobrescreve somente os filtros desejados.
            dados.update(filtros)

            for campo in campos_nao_enviar:
                dados.pop(campo, None)

            print(
                "Enviando filtros:",
                f"Unidade={dados.get('vuni-unidade')}",
                f"ClienteAtivo={dados.get('vcli-situ')}",
                f"VendedorAtivo={dados.get('vven-situ')}",
                f"Quebra={dados.get('vquebra')}",
                flush=True,
            )

            # 5) Dispara via requests/Engine.
            html_disparo = ag.disparar_relatorio(
                url=url,
                dados=dados,
            )

            # Guarda o retorno integral para conferência.
            debug = (
                Path(PASTA_HTML)
                / (
                    f"clientes_cadastrados_"
                    f"{unidade['nome_arquivo']}_disparo.html"
                )
            )

            debug.write_text(
                html_disparo,
                encoding="latin1",
                errors="replace",
            )

            # 6) Captura processo com regra específica deste relatório.
            processo = capturar_processo_clientes(
                html_disparo
            )

            if processo:
                print(
                    "Processo encontrado:",
                    processo,
                    flush=True,
                )
                return processo

            mensagem = re.sub(
                r"\s+",
                " ",
                html_disparo[-800:],
            )

            ultimo_erro = (
                "Número do processo não encontrado no retorno específico "
                f"do Cadastro de Clientes. Final da resposta: {mensagem}"
            )

            print(
                ultimo_erro,
                flush=True,
            )

        except Exception as erro:
            ultimo_erro = erro
            print(
                "Erro no disparo Clientes:",
                erro,
                flush=True,
            )

        # Renova login periodicamente sem envolver Selenium.
        if tentativa in (3, 6, 9):
            print(
                "Refazendo login do Agrosys...",
                flush=True,
            )
            ag.login()

        if tentativa < TENTATIVAS_DISPARO:
            time.sleep(ESPERA_DISPARO)

    raise Exception(
        "Não foi possível obter o processo do Cadastro de Clientes. "
        f"Último erro: {ultimo_erro}"
    )


def baixar_unidade(
    ag,
    driver,
    unidade,
):
    print("=" * 90)
    print(
        "CLIENTES CADASTRADOS -",
        unidade["descricao"],
    )
    print("Clientes: ativos")
    print("Vendedores: ativos")
    print("Quebra: Código do Cliente")
    print("=" * 90)

    # -------------------------------------------------------------
    # 1) DISPARA VIA ENGINE/REQUESTS
    # -------------------------------------------------------------
    processo = disparar_relatorio_clientes(
        ag=ag,
        unidade=unidade,
    )

    if not processo:
        raise Exception(
            "O Agrosys não retornou o número do processo."
        )

    print(
        f"Processo {processo} capturado. "
        "Agora vou aguardar o Agrosys terminar de gerar o relatório.",
        flush=True,
    )

    # -------------------------------------------------------------
    # 2) AGUARDA O RELATÓRIO FICAR REALMENTE PRONTO
    # -------------------------------------------------------------
    referer = (
        f"{BASE_AGROSYS}/webpro/webci/"
        f"wad001d50?vmen-codigo=18439"
    )

    html_relatorio = ag.baixar_relatorio(
        processo=processo,
        referer=referer,
        tentativas=30,
        espera=20,
        max_404_consecutivos=3,
        tempo_minimo_antes_descartar_404=300,
    )

    if html_relatorio is None:
        raise Exception(
            f"O processo {processo} não ficou disponível no Agrosys."
        )

    # Salva o HTML pronto para auditoria/debug.
    try:
        rel_path = (
            Path(PASTA_HTML)
            / (
                f"clientes_cadastrados_"
                f"{unidade['nome_arquivo']}_"
                f"{processo}.html"
            )
        )
        rel_path.write_text(
            html_relatorio,
            encoding="latin1",
            errors="replace",
        )
    except Exception:
        pass

    print(
        f"Relatório do processo {processo} confirmado como pronto.",
        flush=True,
    )

    # -------------------------------------------------------------
    # 3) SOMENTE AGORA O SELENIUM ENTRA PARA O EXCEL OFICIAL
    # -------------------------------------------------------------
    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_base = (
        PASTA_SAIDA
        / (
            f"clientes_cadastrados_"
            f"{unidade['nome_arquivo']}.xlsx"
        )
    )

    arquivo_baixado = baixar_excel_oficial(
        driver=driver,
        ag=ag,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_base,
    )

    print("Processo:", processo)
    print("URL utilizada:", url_relatorio)

    return arquivo_baixado


# =============================================================================
# LEITURA E CONSOLIDAÇÃO
# =============================================================================

def localizar_cabecalho_excel(bruto):
    """
    Localiza o cabeçalho real do Excel oficial do Agrosys.

    Esse relatório pode ter:
    - título nas primeiras linhas;
    - cabeçalho dividido em duas ou três linhas;
    - células mescladas;
    - nomes vazios que o pandas transforma em NaN.

    Retorna:
        indice inicial do cabeçalho
        quantidade de linhas usadas no cabeçalho
    """
    palavras_cabecalho = {
        "codigo",
        "codcliente",
        "codigocliente",
        "cliente",
        "razaosocial",
        "fantasia",
        "nomefantasia",
        "tipopessoa",
        "cpf",
        "cnpj",
        "cpfcnpj",
        "inscricaoestadual",
        "situacao",
        "status",
        "cidade",
        "municipio",
        "uf",
        "estado",
        "cep",
        "telefone",
        "celular",
        "email",
        "latitude",
        "longitude",
        "datacadastro",
        "vendedor",
        "supervisor",
        "ramoatividade",
        "areacomercial",
    }

    melhor = None
    limite = min(len(bruto), 120)

    for indice in range(limite):
        for quantidade_linhas in (1, 2, 3):
            if indice + quantidade_linhas > len(bruto):
                continue

            bloco = bruto.iloc[
                indice : indice + quantidade_linhas
            ].copy()

            textos = []

            for valor in bloco.to_numpy().flatten():
                if pd.isna(valor):
                    continue

                texto = limpar_texto(valor)

                if texto:
                    textos.append(texto)

            if not textos:
                continue

            chaves = {
                chave_coluna(texto)
                for texto in textos
                if texto
            }

            acertos = len(
                chaves.intersection(palavras_cabecalho)
            )

            # Pontos extras para termos que identificam fortemente a tabela.
            fortes = sum(
                1
                for termo in (
                    "codigo",
                    "codcliente",
                    "codigocliente",
                    "razaosocial",
                    "cliente",
                    "vendedor",
                    "supervisor",
                )
                if termo in chaves
            )

            preenchidos_por_coluna = (
                bloco.notna().any(axis=0).sum()
            )

            pontuacao = (
                acertos * 20
                + fortes * 30
                + int(preenchidos_por_coluna)
            )

            candidato = (
                pontuacao,
                acertos,
                fortes,
                preenchidos_por_coluna,
                -indice,
                indice,
                quantidade_linhas,
            )

            if melhor is None or candidato > melhor:
                melhor = candidato

    if melhor is None:
        raise Exception(
            "Não foi possível localizar o cabeçalho do Excel."
        )

    _, acertos, fortes, _, _, indice, quantidade = melhor

    if acertos < 2 and fortes < 1:
        raise Exception(
            "O Excel foi baixado, mas o cabeçalho real não foi "
            "identificado. Salve uma cópia do arquivo para conferência."
        )

    return indice, quantidade


def montar_cabecalho_multilinha(bruto, inicio, quantidade):
    """
    Combina até três linhas de cabeçalho.

    Para cada coluna:
    - remove valores vazios;
    - elimina repetições;
    - junta os níveis com ' - ';
    - cria nomes genéricos apenas quando realmente não há nome.
    """
    bloco = bruto.iloc[
        inicio : inicio + quantidade
    ].copy()

    cabecalho = []

    for numero_coluna in range(bruto.shape[1]):
        partes = []

        for numero_linha in range(quantidade):
            valor = bloco.iloc[
                numero_linha,
                numero_coluna,
            ]

            if pd.isna(valor):
                continue

            texto = limpar_texto(valor)

            if not texto:
                continue

            if texto.lower() in {
                "nan",
                "none",
                "<na>",
            }:
                continue

            if not partes or partes[-1] != texto:
                partes.append(texto)

        if partes:
            nome = " - ".join(partes)
        else:
            nome = f"Coluna_{numero_coluna + 1}"

        cabecalho.append(nome)

    return colunas_unicas(cabecalho)


def remover_linhas_de_cabecalho_repetido(df):
    """
    Remove cabeçalhos que o Agrosys repete no meio da planilha.
    """
    nomes = {
        chave_coluna(coluna)
        for coluna in df.columns
    }

    def linha_repetida(linha):
        valores = {
            chave_coluna(valor)
            for valor in linha.tolist()
            if pd.notna(valor)
            and limpar_texto(valor)
        }

        coincidencias = len(
            nomes.intersection(valores)
        )

        return coincidencias >= max(
            2,
            min(5, len(nomes) // 4),
        )

    if df.empty:
        return df

    mascara = df.apply(
        linha_repetida,
        axis=1,
    )

    return df.loc[~mascara].copy()


def ler_arquivo_oficial(arquivo):
    extensao = arquivo.suffix.lower()

    if extensao == ".csv":
        tentativas = [
            {"sep": ";", "encoding": "utf-8-sig"},
            {"sep": ";", "encoding": "latin1"},
            {"sep": ",", "encoding": "utf-8-sig"},
            {"sep": ",", "encoding": "latin1"},
        ]

        ultimo_erro = None

        for parametros in tentativas:
            try:
                df = pd.read_csv(
                    arquivo,
                    dtype=str,
                    **parametros,
                )

                if not df.empty:
                    df.columns = colunas_unicas(
                        df.columns
                    )
                    return df

            except Exception as erro:
                ultimo_erro = erro

        raise Exception(
            f"Não foi possível ler o CSV {arquivo}: "
            f"{ultimo_erro}"
        )

    bruto = pd.read_excel(
        arquivo,
        header=None,
        dtype=str,
    )

    if bruto.empty:
        return bruto

    indice_cabecalho, linhas_cabecalho = (
        localizar_cabecalho_excel(bruto)
    )

    nomes_colunas = montar_cabecalho_multilinha(
        bruto=bruto,
        inicio=indice_cabecalho,
        quantidade=linhas_cabecalho,
    )

    df = bruto.iloc[
        indice_cabecalho + linhas_cabecalho :
    ].copy()

    df.columns = nomes_colunas
    df = df.dropna(
        how="all"
    ).reset_index(
        drop=True
    )

    df = remover_linhas_de_cabecalho_repetido(
        df
    )

    # Remove colunas totalmente vazias.
    colunas_vazias = [
        coluna
        for coluna in df.columns
        if df[coluna].isna().all()
    ]

    df = df.drop(
        columns=colunas_vazias,
        errors="ignore",
    )

    # Limpeza de texto sem transformar os códigos em número.
    for coluna in df.columns:
        df[coluna] = (
            df[coluna]
            .astype("string")
            .str.strip()
            .replace(
                {
                    "": pd.NA,
                    "nan": pd.NA,
                    "None": pd.NA,
                    "<NA>": pd.NA,
                }
            )
        )

    print(
        "Cabeçalho localizado na linha:",
        indice_cabecalho + 1,
        "| linhas usadas:",
        linhas_cabecalho,
        flush=True,
    )

    print(
        "Colunas identificadas:",
        list(df.columns),
        flush=True,
    )

    return df


def encontrar_coluna_codigo_cliente(df):
    mapa = {
        chave_coluna(coluna): coluna
        for coluna in df.columns
    }

    candidatos = [
        "codcliente",
        "codigocliente",
        "clienteCodigo",
        "codigo",
        "cliente",
    ]

    for candidato in candidatos:
        chave = normalizar_nome(candidato)

        if chave in mapa:
            return mapa[chave]

    for coluna in df.columns:
        chave = chave_coluna(coluna)

        if "cliente" in chave and (
            "cod" in chave
            or "codigo" in chave
        ):
            return coluna

    return None


def preparar_base_unidade(
    arquivo,
    unidade,
):
    df = ler_arquivo_oficial(arquivo)

    if df.empty:
        raise Exception(
            f"O arquivo da unidade {unidade['descricao']} está vazio."
        )

    df.columns = colunas_unicas(df.columns)

    # Remove totais e cabeçalhos repetidos.
    texto_linha = (
        df.astype("string")
        .fillna("")
        .agg(" | ".join, axis=1)
        .str.strip()
    )

    mascara_total = texto_linha.str.contains(
        r"(^|\|)\s*(total|subtotal)\s*:?\s*(\||$)",
        case=False,
        regex=True,
        na=False,
    )

    df = df.loc[~mascara_total].copy()

    coluna_codigo = encontrar_coluna_codigo_cliente(df)

    if coluna_codigo is None:
        raise Exception(
            "Não encontrei a coluna Código do Cliente. "
            f"Colunas recebidas: {list(df.columns)}"
        )

    df["Codigo_Cliente_Normalizado"] = (
        df[coluna_codigo]
        .apply(normalizar_codigo)
        .astype("string")
        .str.strip()
    )

    df = df[
        df["Codigo_Cliente_Normalizado"].notna()
        & (df["Codigo_Cliente_Normalizado"] != "")
    ].copy()

    df.insert(0, "Empresa_Origem", unidade["empresa_padrao"])
    df.insert(1, "Unidade_Codigo", unidade["codigo"])
    df.insert(2, "Unidade_Descricao", unidade["descricao"])
    df.insert(3, "Prioridade_Unidade", unidade["prioridade"])
    df["Arquivo_Origem"] = arquivo.name
    df["Data_Processamento"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return df


def consolidar_arquivos(arquivos_baixados):
    bases = []

    for unidade, arquivo in arquivos_baixados:
        print(
            "Tratando:",
            unidade["descricao"],
            "|",
            arquivo,
            flush=True,
        )

        bases.append(
            preparar_base_unidade(
                arquivo=arquivo,
                unidade=unidade,
            )
        )

    if not bases:
        raise Exception(
            "Nenhuma unidade possui arquivo válido para consolidar."
        )

    geral = pd.concat(
        bases,
        ignore_index=True,
        sort=False,
    )

    geral["Prioridade_Unidade"] = pd.to_numeric(
        geral["Prioridade_Unidade"],
        errors="coerce",
    ).fillna(999)

    geral = geral.sort_values(
        by=[
            "Prioridade_Unidade",
            "Codigo_Cliente_Normalizado",
        ],
        kind="stable",
    )

    unidades_encontradas = (
        geral.groupby(
            "Codigo_Cliente_Normalizado",
            dropna=False,
        )["Unidade_Codigo"]
        .agg(
            lambda valores: ", ".join(
                dict.fromkeys(
                    str(valor)
                    for valor in valores
                    if pd.notna(valor)
                )
            )
        )
        .rename("Unidades_Encontradas")
    )

    quantidade_registros = (
        geral.groupby(
            "Codigo_Cliente_Normalizado",
            dropna=False,
        )
        .size()
        .rename("Quantidade_Registros_Originais")
    )

    geral = geral.join(
        unidades_encontradas,
        on="Codigo_Cliente_Normalizado",
    )

    geral = geral.join(
        quantidade_registros,
        on="Codigo_Cliente_Normalizado",
    )

    duplicados = geral[
        geral["Quantidade_Registros_Originais"] > 1
    ].copy()

    consolidado = geral.drop_duplicates(
        subset=["Codigo_Cliente_Normalizado"],
        keep="first",
    ).copy()

    consolidado = consolidado.drop(
        columns=["Prioridade_Unidade"],
        errors="ignore",
    )

    duplicados = duplicados.drop(
        columns=["Prioridade_Unidade"],
        errors="ignore",
    )

    return (
        consolidado.reset_index(drop=True),
        duplicados.reset_index(drop=True),
        geral,
    )


def salvar_consolidado(
    consolidado,
    duplicados,
    geral,
):
    for arquivo in (
        ARQUIVO_CONSOLIDADO_XLSX,
        ARQUIVO_CONSOLIDADO_PARQUET,
        ARQUIVO_DUPLICADOS,
    ):
        if arquivo.exists():
            arquivo.unlink()

    consolidado.to_excel(
        ARQUIVO_CONSOLIDADO_XLSX,
        index=False,
    )

    consolidado.to_parquet(
        ARQUIVO_CONSOLIDADO_PARQUET,
        index=False,
    )

    if duplicados.empty:
        pd.DataFrame(
            {
                "Mensagem": [
                    "Nenhum cliente duplicado foi encontrado."
                ]
            }
        ).to_excel(
            ARQUIVO_DUPLICADOS,
            index=False,
        )
    else:
        duplicados.to_excel(
            ARQUIVO_DUPLICADOS,
            index=False,
        )

    print("=" * 90)
    print("CONSOLIDAÇÃO FINALIZADA")
    print("Registros antes da remoção:", len(geral))
    print("Clientes únicos:", len(consolidado))
    print("Linhas na auditoria de duplicados:", len(duplicados))
    print("Excel:", ARQUIVO_CONSOLIDADO_XLSX)
    print("Parquet:", ARQUIVO_CONSOLIDADO_PARQUET)
    print("Auditoria:", ARQUIVO_DUPLICADOS)
    print("=" * 90)


# =============================================================================
# ARGUMENTOS E EXECUÇÃO
# =============================================================================

def ler_argumentos():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help="Não aguarda ENTER ao finalizar.",
    )

    return parser.parse_args()


def main():
    args = ler_argumentos()

    print("=" * 90)
    print("ROBÔ COMERCIAL — CLIENTES CADASTRADOS")
    print("Disparo: AgrosysEngine/requests | Selenium: somente download Excel oficial")
    print("Unidades: 10, 111, 180 e 102")
    print("Pasta:", PASTA_SAIDA)
    print("=" * 90)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()

    driver = criar_driver()
    arquivos_baixados = []
    total_erros = 0

    try:
        copiar_cookies_para_selenium(
            driver,
            ag,
        )

        for unidade in UNIDADES:
            try:
                arquivo = baixar_unidade(
                    ag=ag,
                    driver=driver,
                    unidade=unidade,
                )

                arquivos_baixados.append(
                    (unidade, arquivo)
                )

            except Exception as erro:
                total_erros += 1

                print("=" * 90)
                print(
                    "ERRO NA UNIDADE:",
                    unidade["descricao"],
                )
                print("Erro:", erro)
                traceback.print_exc()
                print("=" * 90)

                registrar_falha(
                    unidade,
                    erro,
                )

                # Renova sessão antes da próxima unidade.
                try:
                    ag.login()
                    copiar_cookies_para_selenium(
                        driver,
                        ag,
                    )
                except Exception:
                    pass

        if not arquivos_baixados:
            raise Exception(
                "Nenhuma unidade foi baixada com sucesso."
            )

        consolidado, duplicados, geral = consolidar_arquivos(
            arquivos_baixados
        )

        salvar_consolidado(
            consolidado=consolidado,
            duplicados=duplicados,
            geral=geral,
        )

        print("=" * 90)
        print("CLIENTES CADASTRADOS FINALIZADO")
        print(
            "Unidades baixadas:",
            len(arquivos_baixados),
        )
        print(
            "Erros/avisos:",
            total_erros,
        )
        print("=" * 90)

        return 0 if total_erros == 0 else 1

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    codigo_saida = 1

    try:
        codigo_saida = main()

    except Exception:
        print("\nERRO GERAL NO ROBÔ")
        traceback.print_exc()
        codigo_saida = 1

    finally:
        if "--sem-pausa" not in sys.argv:
            try:
                pass  # Encerramento automatico: nao aguardar ENTER.
            except EOFError:
                pass

    raise SystemExit(codigo_saida)
