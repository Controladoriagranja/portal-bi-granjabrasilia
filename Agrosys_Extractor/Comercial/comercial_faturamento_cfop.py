# -*- coding: utf-8 -*-
r"""
ROBÔ COMERCIAL — FATURAMENTO POR CFOP

Fluxo:
1. O AgrosysEngine faz login e dispara o relatório sem abrir navegador.
2. O Selenium é iniciado em modo headless (oculto).
3. Os cookies da sessão do AgrosysEngine são copiados para o Selenium.
4. O Selenium abre somente a URL pronta do relatório e executa fexcel().
5. O Excel oficial do Agrosys é baixado.

Regra automática:
- Lê a pasta de exportações.
- Verifica o histórico desde 01/01/2023.
- Lacunas históricas são baixadas em blocos de até 15 dias.
- Identifica a última data já baixada e reprocessa essa data.
- O dia atual também é reprocessado para pegar o fechamento mais recente.

Pasta:
\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Comercial\Faturamento por CFOP
"""

import argparse
import re
import shutil
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException


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
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Comercial\Faturamento por CFOP"
)
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

ARQUIVO_LOG_FALHAS = (
    PASTA_SAIDA / "falhas_faturamento_cfop.log"
)

TERMO_RELATORIO = "faturamento_por_cfop"

DATA_INICIO_HISTORICO = datetime(2023, 1, 1).date()
TAMANHO_BLOCO_HISTORICO = 15
TENTATIVAS_DOWNLOAD_EXCEL = 1
TIMEOUT_AGUARDAR_FEXCEL = 60
TIMEOUT_DOWNLOAD_EXCEL = 180
ESPERA_ENTRE_TENTATIVAS_DOWNLOAD = 15

HOJE = datetime.now().date()

# Mantido conforme o script comercial enviado.
UNIDADES = [
    {
        "codigo": "10",
        "filial": "0",
        "nome_filial": "Todas",
        "nome_arquivo": "Avenova",
        "descricao": "010 - AVE NOVA",
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


def parse_data_nome(texto):
    for formato in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except Exception:
            pass
    return None


def extrair_periodo_arquivo(nome_arquivo):
    datas = re.findall(
        r"(\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})",
        nome_arquivo,
    )

    if len(datas) < 2:
        return None

    data_ini = parse_data_nome(datas[0])
    data_fim = parse_data_nome(datas[1])

    if not data_ini or not data_fim:
        return None

    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    return data_ini, data_fim


def iterar_datas(data_ini, data_fim):
    data = data_ini

    while data <= data_fim:
        yield data
        data += timedelta(days=1)


def arquivos_da_unidade(unidade):
    unidade_key = normalizar_nome(unidade["nome_arquivo"])
    termo_key = normalizar_nome(TERMO_RELATORIO)

    encontrados = []

    for arquivo in PASTA_SAIDA.glob("*.xls*"):
        if arquivo.name.startswith("~$"):
            continue

        nome_key = normalizar_nome(arquivo.name)

        if termo_key not in nome_key:
            continue

        if unidade_key not in nome_key:
            continue

        periodo = extrair_periodo_arquivo(arquivo.name)

        if not periodo:
            continue

        encontrados.append((arquivo, periodo))

    return encontrados


def ultima_data_baixada(unidade):
    """
    Retorna a maior data final encontrada nos arquivos reconhecidos da unidade.

    A data é obtida pelo período gravado no nome do arquivo. Exemplo:
    faturamento_por_cfop_Avenova_27-07-2026_ate_27-07-2026.xlsx

    Retorno:
    - date com a maior data final encontrada;
    - None quando não houver arquivo reconhecido.
    """
    arquivos = arquivos_da_unidade(unidade)

    if not arquivos:
        return None

    return max(
        periodo[1]
        for _, periodo in arquivos
    )


def datas_cobertas(unidade, data_ini, data_fim):
    cobertas = set()

    for _, periodo in arquivos_da_unidade(unidade):
        inicio_arquivo, fim_arquivo = periodo

        inicio = max(data_ini, inicio_arquivo)
        fim = min(data_fim, fim_arquivo)

        if inicio <= fim:
            cobertas.update(iterar_datas(inicio, fim))

    return cobertas


def agrupar_datas_em_blocos(datas, maximo_dias=15):
    """
    Agrupa datas consecutivas em períodos de no máximo 15 dias.
    """
    datas = sorted(set(datas))

    if not datas:
        return []

    periodos = []
    inicio = datas[0]
    anterior = datas[0]
    quantidade = 1

    for data_atual in datas[1:]:
        consecutiva = data_atual == anterior + timedelta(days=1)
        cabe_no_bloco = quantidade < maximo_dias

        if consecutiva and cabe_no_bloco:
            anterior = data_atual
            quantidade += 1
            continue

        periodos.append((inicio, anterior))

        inicio = data_atual
        anterior = data_atual
        quantidade = 1

    periodos.append((inicio, anterior))

    return periodos


def listar_periodos_automaticos(unidade, atualizar_hoje=True):
    """
    Regra automática:

    1. De 01/01/2023 até ontem, baixa somente datas faltantes em blocos
       de até 15 dias.
    2. Identifica a última data encontrada nos arquivos da pasta.
    3. Baixa novamente essa última data para corrigir dias incompletos.
    4. Baixa também o dia atual, salvo quando --nao-atualizar-hoje for
       utilizado e o dia já estiver coberto.
    """
    periodos = []
    ontem = HOJE - timedelta(days=1)

    # ================================================================
    # 1. LOCALIZA LACUNAS HISTÓRICAS ATÉ ONTEM
    # ================================================================
    if DATA_INICIO_HISTORICO <= ontem:
        cobertas = datas_cobertas(
            unidade,
            DATA_INICIO_HISTORICO,
            ontem,
        )

        faltantes = [
            data
            for data in iterar_datas(DATA_INICIO_HISTORICO, ontem)
            if data not in cobertas
        ]

        periodos.extend(
            agrupar_datas_em_blocos(
                faltantes,
                maximo_dias=TAMANHO_BLOCO_HISTORICO,
            )
        )

    # ================================================================
    # 2. REPROCESSA A ÚLTIMA DATA ENCONTRADA NA PASTA
    # ================================================================
    datas_para_reprocessar = set()
    ultima_data = ultima_data_baixada(unidade)

    if (
        ultima_data is not None
        and DATA_INICIO_HISTORICO <= ultima_data <= HOJE
    ):
        datas_para_reprocessar.add(ultima_data)

        print(
            "Última data encontrada na pasta:",
            ultima_data.strftime("%d/%m/%Y"),
            flush=True,
        )
        print(
            "Essa data será baixada novamente para garantir "
            "o fechamento completo.",
            flush=True,
        )

    # ================================================================
    # 3. ATUALIZA O DIA ATUAL
    # ================================================================
    if atualizar_hoje:
        datas_para_reprocessar.add(HOJE)
    else:
        hoje_coberto = HOJE in datas_cobertas(
            unidade,
            HOJE,
            HOJE,
        )

        if not hoje_coberto:
            datas_para_reprocessar.add(HOJE)

    # ================================================================
    # 4. ADICIONA REPROCESSAMENTOS COMO PERÍODOS DIÁRIOS
    # ================================================================
    for data in sorted(datas_para_reprocessar):
        periodo_diario = (data, data)

        if periodo_diario not in periodos:
            periodos.append(periodo_diario)

    # Mantém a execução em ordem cronológica.
    return sorted(
        periodos,
        key=lambda periodo: (periodo[0], periodo[1]),
    )

def listar_periodos_historicos(unidade):
    ontem = HOJE - timedelta(days=1)

    if ontem < DATA_INICIO_HISTORICO:
        return []

    cobertas = datas_cobertas(
        unidade,
        DATA_INICIO_HISTORICO,
        ontem,
    )

    faltantes = [
        data
        for data in iterar_datas(DATA_INICIO_HISTORICO, ontem)
        if data not in cobertas
    ]

    return agrupar_datas_em_blocos(
        faltantes,
        maximo_dias=TAMANHO_BLOCO_HISTORICO,
    )


def dividir_periodo(data_ini, data_fim):
    datas = list(iterar_datas(data_ini, data_fim))

    return agrupar_datas_em_blocos(
        datas,
        maximo_dias=TAMANHO_BLOCO_HISTORICO,
    )


# =============================================================================
# SELENIUM OCULTO — SOMENTE PARA O EXCEL OFICIAL
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
    """
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


def montar_filtros(unidade, data_ini, data_fim):
    """
    Filtros mantidos conforme o script comercial fornecido.
    """
    return {
        "vprivez": "x",
        "vdata-ini": data_ini.strftime("%d/%m/%Y"),
        "vdata-fim": data_fim.strftime("%d/%m/%Y"),
        "vfil-filial": unidade["filial"],
        "vfil-nome": unidade["nome_filial"],
        "vuni-unidade": "",
        "vven-codigo-pai": "",
        "vven-codigo": "",
        "vcli-codigo": "",
        "vrede": "",
        "vareacomer": "",
        "vnat-codigo": "",
        "vnae-codcompl": "",
        "vpro-codigo": "",
        "vtcl-codigo": "",
        "vsitopr": "yes",
        "vsituacao": "99",
        "vlog-unid": "yes",
        "vlista-saida": "yes",
        "vlista-entrada": "yes",
        "vlista-exp": "yes",
        "vlista-nfs-venda": "",
        "vvenda-status-devol-total": "",
        "vlista-refaturadas": "",
        "vlista-nfe-devol": "",
        "vlog-st": "yes",
        "vmos-imposto": "",
        "vexp-excel": "",
        "vresumo-item": "",
        "vconceito": "",
        "vquebra": "                        11",
        "vpad-btdisp.x": "Disparar",
    }


def baixar_periodo(
    ag,
    driver,
    unidade,
    data_ini,
    data_fim,
):
    print("=" * 80)
    print(
        "Faturamento por CFOP -",
        unidade["descricao"],
    )
    print(
        "Período:",
        data_ini.strftime("%d/%m/%Y"),
        "até",
        data_fim.strftime("%d/%m/%Y"),
    )
    print("=" * 80)

    filtros = montar_filtros(
        unidade,
        data_ini,
        data_fim,
    )

    html, processo = ag.executar_relatorio(
        caminho="/webpro/webci/wfa009d1-bra",
        menu=16920,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=(
            f"faturamento_por_cfop_"
            f"{unidade['nome_arquivo']}_"
            f"{data_ini.strftime('%d-%m-%Y')}"
        ),
        modulo="14400",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=20,
    )

    if processo is None:
        raise Exception(
            "O Agrosys não retornou o número do processo."
        )

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = (
        PASTA_SAIDA
        / (
            f"faturamento_por_cfop_"
            f"{unidade['nome_arquivo']}_"
            f"{data_ini.strftime('%d-%m-%Y')}_ate_"
            f"{data_fim.strftime('%d-%m-%Y')}.xlsx"
        )
    )

    baixar_excel_oficial(
        driver,
        ag,
        url_relatorio,
        arquivo_destino,
    )

    print("Processo:", processo)

    return arquivo_destino


# =============================================================================
# ARGUMENTOS
# =============================================================================

def parse_data_argumento(texto):
    return datetime.strptime(
        texto,
        "%d/%m/%Y",
    ).date()


def ler_argumentos():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modo",
        choices=[
            "auto",
            "historico",
            "hoje",
            "periodo",
        ],
        default="auto",
        help=(
            "auto = completa histórico desde 2023 e atualiza hoje; "
            "historico = baixa somente lacunas até ontem; "
            "hoje = baixa somente hoje; "
            "periodo = baixa intervalo informado."
        ),
    )

    parser.add_argument(
        "--inicio",
        default=None,
        help="Data inicial dd/mm/aaaa.",
    )

    parser.add_argument(
        "--fim",
        default=None,
        help="Data final dd/mm/aaaa.",
    )

    parser.add_argument(
        "--nao-atualizar-hoje",
        action="store_true",
        help=(
            "No modo automático, não baixa novamente o dia atual "
            "quando ele já estiver coberto."
        ),
    )

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help="Não aguarda ENTER no final.",
    )

    args = parser.parse_args()

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            parser.error(
                "Para --modo periodo, informe --inicio e --fim."
            )

    return args


def registrar_falha_periodo(
    unidade,
    data_ini,
    data_fim,
    erro,
):
    momento = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    linha = (
        f"[{momento}] Unidade={unidade['descricao']} | "
        f"Período={data_ini.strftime('%d/%m/%Y')} até "
        f"{data_fim.strftime('%d/%m/%Y')} | Erro={erro}\n"
    )

    with ARQUIVO_LOG_FALHAS.open(
        "a",
        encoding="utf-8",
    ) as arquivo:
        arquivo.write(linha)


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    args = ler_argumentos()

    print("=" * 80)
    print("ROBÔ COMERCIAL — FATURAMENTO POR CFOP")
    print("Navegador: oculto")
    print(
        "Histórico:",
        DATA_INICIO_HISTORICO.strftime("%d/%m/%Y"),
        "até",
        HOJE.strftime("%d/%m/%Y"),
    )
    print("Pasta:", PASTA_SAIDA)
    print("Modo:", args.modo)
    print("=" * 80)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()

    driver = criar_driver()

    total_arquivos = 0
    total_erros = 0

    try:
        copiar_cookies_para_selenium(driver, ag)

        for unidade in UNIDADES:
            if args.modo == "auto":
                periodos = listar_periodos_automaticos(
                    unidade,
                    atualizar_hoje=(
                        not args.nao_atualizar_hoje
                    ),
                )

            elif args.modo == "historico":
                periodos = listar_periodos_historicos(
                    unidade
                )

            elif args.modo == "hoje":
                periodos = [(HOJE, HOJE)]

            else:
                data_ini = parse_data_argumento(
                    args.inicio
                )
                data_fim = parse_data_argumento(
                    args.fim
                )

                if data_ini > data_fim:
                    data_ini, data_fim = (
                        data_fim,
                        data_ini,
                    )

                periodos = dividir_periodo(
                    data_ini,
                    data_fim,
                )

            print("=" * 80)
            print(unidade["descricao"])
            print(
                "Arquivos reconhecidos:",
                len(arquivos_da_unidade(unidade)),
            )
            print(
                "Períodos para baixar:",
                len(periodos),
            )

            if periodos:
                print(
                    "Primeiro:",
                    periodos[0][0].strftime("%d/%m/%Y"),
                    "até",
                    periodos[0][1].strftime("%d/%m/%Y"),
                )
                print(
                    "Último:",
                    periodos[-1][0].strftime("%d/%m/%Y"),
                    "até",
                    periodos[-1][1].strftime("%d/%m/%Y"),
                )

            print("=" * 80)

            for data_ini, data_fim in periodos:
                try:
                    resultado = baixar_periodo(
                        ag=ag,
                        driver=driver,
                        unidade=unidade,
                        data_ini=data_ini,
                        data_fim=data_fim,
                    )

                    if resultado:
                        total_arquivos += 1

                except Exception as erro:
                    total_erros += 1

                    print("=" * 80)
                    print("AVISO: falha ao baixar período.")
                    print(
                        "Unidade:",
                        unidade["descricao"],
                    )
                    print(
                        "Período:",
                        data_ini.strftime("%d/%m/%Y"),
                        "até",
                        data_fim.strftime("%d/%m/%Y"),
                    )
                    print("Erro:", erro)
                    traceback.print_exc()
                    print("=" * 80)

                    registrar_falha_periodo(
                        unidade,
                        data_ini,
                        data_fim,
                        erro,
                    )

                    # Atualiza os cookies antes do próximo período.
                    try:
                        copiar_cookies_para_selenium(
                            driver,
                            ag,
                        )
                    except Exception:
                        pass

        print("=" * 80)
        print("FATURAMENTO POR CFOP FINALIZADO")
        print(
            "Arquivos gerados/atualizados:",
            total_arquivos,
        )
        print(
            "Erros/avisos:",
            total_erros,
        )
        print(
            "Excel em:",
            PASTA_SAIDA,
        )
        print("=" * 80)

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
