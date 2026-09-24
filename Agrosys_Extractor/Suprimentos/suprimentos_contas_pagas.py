import argparse
import calendar
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


# ============================================================
# 1) ESTRUTURA DO PROJETO
# ============================================================

# Este arquivo deve ficar em:
# \\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_contas_pagas.py
#
# parents[0] = Suprimentos
# parents[1] = Agrosys_Extractor
RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# ============================================================
# 2) PASTAS
# ============================================================

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Contas Pagas"
)

from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)


# ============================================================
# 3) CONFIGURAÇÃO DO RELATÓRIO AGROSYS
# ============================================================

CAMINHO_RELATORIO = "/webpro/webfin/wad048d9"
MENU_RELATORIO = 27274
MODULO_RELATORIO = "27114"
UNIDADE_RELATORIO = "51"

DATA_INICIAL_HISTORICO = date(2026, 1, 1)

MAX_TENTATIVAS = 5
PAUSA_ENTRE_TENTATIVAS = 15
TIMEOUT_DOWNLOAD = 300

TIPOS_CREDOR = [
    {
        "codigo": "FOR",
        "nome_arquivo": "fornecedor",
        "descricao": "Fornecedor",
        "campo_codigo": "vcod-id",
    },
    {
        "codigo": "REDE",
        "nome_arquivo": "rede",
        "descricao": "Rede de Fornecedores",
        "campo_codigo": "vcod-red",
    },
]


# ============================================================
# 4) DATAS E PERÍODOS
# ============================================================

def parse_data_br(valor: str) -> date:
    try:
        return datetime.strptime(valor, "%d/%m/%Y").date()
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {valor}. Use DD/MM/AAAA."
        ) from erro


def primeiro_dia_mes(data_ref: date) -> date:
    return data_ref.replace(day=1)


def ultimo_dia_mes(data_ref: date) -> date:
    ultimo = calendar.monthrange(data_ref.year, data_ref.month)[1]
    return data_ref.replace(day=ultimo)


def proximo_mes(data_ref: date) -> date:
    if data_ref.month == 12:
        return date(data_ref.year + 1, 1, 1)
    return date(data_ref.year, data_ref.month + 1, 1)


def mes_anterior(data_ref: date) -> date:
    if data_ref.month == 1:
        return date(data_ref.year - 1, 12, 1)
    return date(data_ref.year, data_ref.month - 1, 1)


def listar_periodos_mensais(data_ini: date, data_fim: date):
    periodos = []
    cursor = primeiro_dia_mes(data_ini)

    while cursor <= data_fim:
        inicio = max(cursor, data_ini)
        fim = min(ultimo_dia_mes(cursor), data_fim)
        periodos.append((inicio, fim))
        cursor = proximo_mes(cursor)

    return periodos


def dividir_periodo_15_dias(data_ini: date, data_fim: date):
    blocos = []
    cursor = data_ini

    while cursor <= data_fim:
        fim = min(cursor + timedelta(days=14), data_fim)
        blocos.append((cursor, fim))
        cursor = fim + timedelta(days=1)

    return blocos


# ============================================================
# 5) LEITURA DOS ARQUIVOS JÁ BAIXADOS
# ============================================================

def nome_arquivo(tipo_credor: dict, data_ini: date, data_fim: date) -> str:
    return (
        f"contas_pagas_{tipo_credor['nome_arquivo']}_"
        f"{data_ini:%d-%m-%Y}_ate_{data_fim:%d-%m-%Y}.xlsx"
    )


def caminho_arquivo(tipo_credor: dict, data_ini: date, data_fim: date) -> Path:
    return PASTA_SAIDA / nome_arquivo(tipo_credor, data_ini, data_fim)


def extrair_periodo_arquivo(nome: str):
    datas = re.findall(r"(\d{2}-\d{2}-\d{4})", nome)

    if len(datas) < 2:
        return None

    try:
        data_ini = datetime.strptime(datas[0], "%d-%m-%Y").date()
        data_fim = datetime.strptime(datas[1], "%d-%m-%Y").date()
    except ValueError:
        return None

    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    return data_ini, data_fim


def arquivo_existe_valido(tipo_credor: dict, data_ini: date, data_fim: date) -> bool:
    arquivo = caminho_arquivo(tipo_credor, data_ini, data_fim)
    return arquivo.exists() and arquivo.stat().st_size > 0


def listar_periodos_auto(tipo_credor: dict):
    """
    REGRA AUTOMÁTICA ATUALIZADA

    1. Procura meses fechados faltantes desde 01/01/2026.
    2. Não baixa novamente meses antigos que já estejam completos na pasta.
    3. Em TODOS os dias, atualiza o mês atual do dia 01 até hoje.
    4. Se hoje for DIA 01:
       - rebaixa o ÚLTIMO DIA do mês anterior;
       - baixa o dia 01 do mês atual.
    5. Se hoje for DIA 15:
       - rebaixa o MÊS ANTERIOR COMPLETO;
       - atualiza normalmente o mês atual do dia 01 até hoje.

    Exemplos:
      01/09/2026:
        31/08/2026 até 31/08/2026
        01/09/2026 até 01/09/2026

      15/09/2026:
        01/08/2026 até 31/08/2026
        01/09/2026 até 15/09/2026

      17/09/2026:
        01/09/2026 até 17/09/2026
    """
    hoje = date.today()
    inicio_mes_atual = primeiro_dia_mes(hoje)

    inicio_mes_anterior = mes_anterior(inicio_mes_atual)
    fim_mes_anterior = ultimo_dia_mes(inicio_mes_anterior)

    periodos = []

    # --------------------------------------------------------
    # A) Meses antigos faltantes desde 01/01/2026
    # --------------------------------------------------------
    # Não inclui:
    # - mês atual, pois ele será atualizado abaixo;
    # - mês anterior, pois ele pode receber tratamento especial
    #   no dia 01 ou dia 15.
    for data_ini, data_fim in listar_periodos_mensais(
        DATA_INICIAL_HISTORICO,
        hoje,
    ):
        if data_ini in {inicio_mes_anterior, inicio_mes_atual}:
            continue

        if not arquivo_existe_valido(
            tipo_credor,
            data_ini,
            data_fim,
        ):
            periodos.append((data_ini, data_fim))

    # --------------------------------------------------------
    # B) DIA 01 -> último dia do mês anterior
    # --------------------------------------------------------
    if hoje.day == 1:
        periodos.append(
            (fim_mes_anterior, fim_mes_anterior)
        )

    # --------------------------------------------------------
    # C) DIA 15 -> mês anterior completo
    # --------------------------------------------------------
    if hoje.day == 15:
        periodos.append(
            (inicio_mes_anterior, fim_mes_anterior)
        )

    # --------------------------------------------------------
    # D) Sempre atualiza o mês atual do dia 01 até hoje
    # --------------------------------------------------------
    periodos.append(
        (inicio_mes_atual, hoje)
    )

    # --------------------------------------------------------
    # E) Remove duplicidades preservando a ordem
    # --------------------------------------------------------
    periodos_unicos = []
    chaves = set()

    for data_ini, data_fim in periodos:
        chave = (data_ini, data_fim)

        if chave not in chaves:
            chaves.add(chave)
            periodos_unicos.append((data_ini, data_fim))

    return periodos_unicos


# ============================================================
# 6) SELENIUM - MESMO PADRÃO DOS ROBÔS EXISTENTES
# ============================================================

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
    """Aceita o Excel final estável mesmo com .crdownload/.tmp auxiliares."""
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
                    if inicio_download is not None and arquivo.stat().st_mtime < inicio_download - 1:
                        continue
                    if arquivo.stat().st_size <= 0:
                        continue
                    prontos.append(arquivo)
                except OSError:
                    pass

        if prontos:
            arquivo = max(prontos, key=lambda p: p.stat().st_mtime)

            try:
                tamanho = arquivo.stat().st_size
            except OSError:
                tamanho = None

            if arquivo == ultimo_arquivo and tamanho == ultimo_tamanho and tamanho:
                estabilidade += 1
            else:
                ultimo_arquivo = arquivo
                ultimo_tamanho = tamanho
                estabilidade = 0

            # ~3 segundos sem alteração no tamanho.
            if estabilidade >= 6:
                auxiliares = [
                    a.name for a in PASTA_DOWNLOAD.glob("*")
                    if a.is_file()
                    and (a.name.endswith(".crdownload") or a.suffix.lower() in {".tmp", ".part"})
                ]

                print(
                    "Arquivo final detectado:",
                    arquivo.name,
                    "| tamanho:",
                    f"{tamanho / 1024 / 1024:.2f} MB",
                    flush=True,
                )

                if auxiliares:
                    print("Arquivos auxiliares ignorados:", auxiliares, flush=True)

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


def baixar_excel_oficial(driver, url_relatorio, arquivo_destino):
    """
    Download oficial do Agrosys via Selenium.

    Estratégia:
    1) abre o relatório pronto;
    2) aguarda fexcel();
    3) dispara fexcel();
    4) espera alguns segundos por .crdownload/.xlsx;
    5) se nada começar, procura e clica no botão/link Excel na página;
    6) aguarda até o arquivo terminar;
    7) salva na pasta final.
    """
    limpar_downloads()

    print("Abrindo relatório pronto no Selenium...", flush=True)
    inicio_abertura = time.time()
    driver.get(url_relatorio)

    limite = time.time() + 30
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
        raise Exception(
            "A página abriu, mas a função fexcel() "
            "não ficou disponível em 30 segundos."
        )

    print(
        f"fexcel() localizado em {time.time() - inicio_abertura:.1f}s. "
        "Solicitando Excel oficial...",
        flush=True,
    )

    inicio_download = time.time()
    driver.execute_script("fexcel();")
    print("fexcel() executado.", flush=True)

    # Espera curta para confirmar se o download realmente começou.
    inicio_confirmacao = time.time()
    download_iniciado = False

    while time.time() - inicio_confirmacao < 8:
        temporarios = [
            a for a in PASTA_DOWNLOAD.glob("*.crdownload")
            if a.is_file()
        ]
        excels = [
            a for mascara in ("*.xlsx", "*.xls")
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

    # Fallback: tenta localizar e clicar no botão/link Excel.
    if not download_iniciado:
        print(
            "fexcel() não iniciou arquivo em 8s. "
            "Tentando localizar e clicar no botão Excel...",
            flush=True,
        )

        clicou = False

        seletores = [
            "a[href*='excel']",
            "a[onclick*='fexcel']",
            "input[onclick*='fexcel']",
            "button[onclick*='fexcel']",
            "img[alt*='Excel']",
            "img[title*='Excel']",
            "a[title*='Excel']",
            "button[title*='Excel']",
            "input[value*='Excel']",
            "input[value*='EXCEL']",
        ]

        for seletor in seletores:
            try:
                elementos = driver.find_elements("css selector", seletor)
                for elemento in elementos:
                    try:
                        if elemento.is_displayed() and elemento.is_enabled():
                            driver.execute_script(
                                "arguments[0].click();",
                                elemento,
                            )
                            clicou = True
                            print(
                                f"Botão/link Excel clicado via seletor: {seletor}",
                                flush=True,
                            )
                            break
                    except Exception:
                        pass
                if clicou:
                    break
            except Exception:
                pass

        # Segundo fallback: inspeciona elementos por texto/título.
        if not clicou:
            try:
                elementos = driver.find_elements(
                    "xpath",
                    "//*[contains(translate(normalize-space(text()), "
                    "'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'EXCEL') "
                    "or contains(translate(@title, "
                    "'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'EXCEL') "
                    "or contains(translate(@alt, "
                    "'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'EXCEL')]"
                )

                for elemento in elementos:
                    try:
                        if elemento.is_displayed() and elemento.is_enabled():
                            driver.execute_script(
                                "arguments[0].click();",
                                elemento,
                            )
                            clicou = True
                            print(
                                "Botão/link Excel clicado pelo texto/título.",
                                flush=True,
                            )
                            break
                    except Exception:
                        pass
            except Exception:
                pass

        if not clicou:
            print(
                "Não encontrei botão Excel clicável. "
                "Vou continuar aguardando o download iniciado pelo fexcel().",
                flush=True,
            )

    print(
        "Aguardando conclusão do Excel oficial...",
        flush=True,
    )

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

        # Diagnóstico adicional da página
        try:
            titulo_pagina = driver.title
        except Exception:
            titulo_pagina = ""

        raise Exception(
            "Não encontrei o arquivo baixado pelo Excel oficial. "
            f"Arquivos presentes: {presentes} | "
            f"Título da página: {titulo_pagina}"
        )

    arquivo_destino.parent.mkdir(parents=True, exist_ok=True)

    if arquivo_destino.exists():
        arquivo_destino.unlink()

    shutil.move(str(baixado), str(arquivo_destino))

    if not arquivo_destino.exists() or arquivo_destino.stat().st_size <= 0:
        raise Exception(
            "O Excel foi baixado, mas não foi salvo corretamente na pasta final."
        )

    print(
        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
        arquivo_destino,
        flush=True,
    )


def montar_filtros(tipo_credor: dict, data_ini: date, data_fim: date):
    filtros = {
        "vconsolida": "S",
        "vstatus": "P",
        "vtipo-per": "P",
        "vdtini": data_ini.strftime("%d/%m/%Y"),
        "vdtfim": data_fim.strftime("%d/%m/%Y"),
        "vdtemissaoini": "",
        "vdtemissaofim": "",
        "vpagfor": "1",
        "vtipo-id": tipo_credor["codigo"],
        tipo_credor["campo_codigo"]: "",
        "vcdgru": "",
        "vprojeto": "",
        "vmercado": "3",
        "vanasint": "A",
        "vclassif": "D",
        "vquebra-pag": "N",
        "vlistentreemp": "N",
        "vlistitagru": "N",
        "vlisforpagto": "N",
        "vlisbanco": "N",
        "vlistotdia": "N",
        "vlistaobs": "0",
        "vlistaord": "S",
        "vtpinc": "",
        "vpad-btdisp.x": "Disparar",
    }

    return filtros


# ============================================================
# 8) EXECUÇÃO PELO AGROSYSENGINE
# ============================================================

def criar_agrosys():
    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()
    return ag


def baixar_periodo(
    ag,
    driver,
    tipo_credor: dict,
    data_ini: date,
    data_fim: date,
):
    print("=" * 80, flush=True)
    print(
        f"Suprimentos - Contas Pagas - {tipo_credor['descricao']}",
        flush=True,
    )
    print(
        f"Período: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
        flush=True,
    )
    print("=" * 80, flush=True)

    filtros = montar_filtros(
        tipo_credor=tipo_credor,
        data_ini=data_ini,
        data_fim=data_fim,
    )

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU_RELATORIO,
        unidade=UNIDADE_RELATORIO,
        filtros=filtros,
        nome_debug=(
            f"contas_pagas_{tipo_credor['nome_arquivo']}_"
            f"{data_ini:%d-%m-%Y}_ate_{data_fim:%d-%m-%Y}"
        ),
        modulo=MODULO_RELATORIO,
    )

    if not processo:
        raise Exception(
            "O Agrosys não retornou o número do processo."
        )

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = caminho_arquivo(
        tipo_credor,
        data_ini,
        data_fim,
    )

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    print("Processo:", processo, flush=True)
    return arquivo_destino


def executar_com_tentativas(
    tipo_credor: dict,
    data_ini: date,
    data_fim: date,
):
    """
    Cada nova tentativa recria login, sessão e navegador.
    Isso protege contra sessão vencida e processo não encontrado.
    """
    ultimo_erro = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        ag = None
        driver = None

        try:
            print(
                f"Tentativa {tentativa}/{MAX_TENTATIVAS}",
                flush=True,
            )

            ag = criar_agrosys()
            driver = criar_driver()
            copiar_cookies_para_selenium(driver, ag)

            baixar_periodo(
                ag=ag,
                driver=driver,
                tipo_credor=tipo_credor,
                data_ini=data_ini,
                data_fim=data_fim,
            )

            return True

        except Exception as erro:
            ultimo_erro = erro

            print("AVISO: falha ao baixar período.", flush=True)
            print("Tipo:", tipo_credor["descricao"], flush=True)
            print(
                "Período:",
                data_ini.strftime("%d/%m/%Y"),
                "até",
                data_fim.strftime("%d/%m/%Y"),
                flush=True,
            )
            print("Erro:", erro, flush=True)

            if tentativa < MAX_TENTATIVAS:
                print(
                    "Recriando login, sessão e navegador...",
                    flush=True,
                )
                time.sleep(PAUSA_ENTRE_TENTATIVAS)

        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

            if ag is not None:
                try:
                    ag.session.close()
                except Exception:
                    pass

    print("FALHA DEFINITIVA:", ultimo_erro, flush=True)
    return False



def validar_periodo_2026(data_ini: date, data_fim: date):
    """
    Trava definitiva: este robô nunca pode baixar datas anteriores
    a 01/01/2026.
    """
    limite = DATA_INICIAL_HISTORICO

    if data_fim < limite:
        raise ValueError(
            f"Período bloqueado: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}. "
            f"Este robô inicia somente em {limite:%d/%m/%Y}."
        )

    if data_ini < limite:
        data_ini = limite

    return data_ini, data_fim


def executar_com_fallback(
    tipo_credor: dict,
    data_ini: date,
    data_fim: date,
):
    data_ini, data_fim = validar_periodo_2026(
        data_ini,
        data_fim,
    )

    """
    Primeiro tenta baixar o período completo.

    Se falhar após 5 tentativas e tiver mais de 15 dias,
    divide automaticamente em períodos de 15 dias.
    """
    if executar_com_tentativas(
        tipo_credor,
        data_ini,
        data_fim,
    ):
        return 1, 0

    quantidade_dias = (data_fim - data_ini).days + 1

    if quantidade_dias <= 15:
        return 0, 1

    print(
        "Período completo falhou. Dividindo em blocos de 15 dias.",
        flush=True,
    )

    sucessos = 0
    erros = 0

    for bloco_ini, bloco_fim in dividir_periodo_15_dias(
        data_ini,
        data_fim,
    ):
        if executar_com_tentativas(
            tipo_credor,
            bloco_ini,
            bloco_fim,
        ):
            sucessos += 1
        else:
            erros += 1

    return sucessos, erros


# ============================================================
# 9) ARGUMENTOS
# ============================================================

def ler_argumentos():
    parser = argparse.ArgumentParser(
        description="Suprimentos - Contas Pagas"
    )

    parser.add_argument(
        "--modo",
        choices=["auto", "historico", "periodo"],
        default="auto",
        help=(
            "auto = meses faltantes + mês atual; no dia 01 rebaixa o último dia do mês anterior; "
            "no dia 15 rebaixa o mês anterior completo; "
            "historico = todos os meses desde 2026; "
            "periodo = datas informadas."
        ),
    )

    parser.add_argument(
        "--inicio",
        type=parse_data_br,
        help="Data inicial no formato DD/MM/AAAA.",
    )

    parser.add_argument(
        "--fim",
        type=parse_data_br,
        help="Data final no formato DD/MM/AAAA.",
    )

    parser.add_argument(
        "--mes",
        help="Mês específico no formato MM/AAAA.",
    )

    return parser.parse_args()


def montar_periodos(args, tipo_credor: dict):
    hoje = date.today()

    if args.mes:
        try:
            mes, ano = map(int, args.mes.split("/"))
            data_ini = date(ano, mes, 1)
            data_fim = min(ultimo_dia_mes(data_ini), hoje)
        except Exception as erro:
            raise ValueError(
                "Mês inválido. Use MM/AAAA."
            ) from erro

        if data_ini > hoje:
            raise ValueError("O mês informado está no futuro.")

        return [(data_ini, data_fim)]

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            raise ValueError(
                "Informe --inicio e --fim no modo período."
            )

        if args.inicio > args.fim:
            raise ValueError(
                "A data inicial não pode ser maior que a final."
            )

        if args.fim > hoje:
            raise ValueError(
                "A data final não pode estar no futuro."
            )

        return [(args.inicio, args.fim)]

    if args.modo == "historico":
        return listar_periodos_mensais(
            DATA_INICIAL_HISTORICO,
            hoje,
        )

    return listar_periodos_auto(tipo_credor)


def aguardar_fechamento_manual():
    """
    Mantém a janela aberta quando o robô é executado manualmente
    em um terminal interativo.

    Quando executado pelo Portal, normalmente não existe terminal
    interativo; nesse caso o processo termina normalmente para que
    o Portal receba o código de retorno e marque a execução como finalizada.
    """
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            pass  # Encerramento automatico: nao aguardar ENTER.
    except (EOFError, KeyboardInterrupt):
        pass


# ============================================================
# 10) MAIN
# ============================================================

def main():
    args = ler_argumentos()

    print("=" * 80, flush=True)
    print("CONFIGURAÇÃO EFETIVA DO ROBÔ", flush=True)
    print(
        "Data inicial permitida:",
        DATA_INICIAL_HISTORICO.strftime("%d/%m/%Y"),
        flush=True,
    )
    print("=" * 80, flush=True)

    total_arquivos = 0
    total_erros = 0

    for tipo_credor in TIPOS_CREDOR:
        try:
            periodos = montar_periodos(
                args=args,
                tipo_credor=tipo_credor,
            )
        except Exception as erro:
            print("ERRO DE PARÂMETRO:", erro, flush=True)
            return 2

        print("\n" + "=" * 80, flush=True)
        print(
            f"{tipo_credor['descricao']} - períodos: {len(periodos)}",
            flush=True,
        )
        print("Modo:", args.modo, flush=True)

        if args.modo == "auto":
            hoje = date.today()
            print("Regra automática:", flush=True)
            print("  - Sempre: mês atual do dia 01 até hoje", flush=True)
            if hoje.day == 1:
                print("  - Hoje é dia 01: também baixa o último dia do mês anterior", flush=True)
            if hoje.day == 15:
                print("  - Hoje é dia 15: também rebaixa o mês anterior completo", flush=True)

        if periodos:
            print(
                "De:",
                periodos[0][0].strftime("%d/%m/%Y"),
                flush=True,
            )
            print(
                "Até:",
                periodos[-1][1].strftime("%d/%m/%Y"),
                flush=True,
            )

        print("=" * 80, flush=True)

        if not periodos:
            print(
                f"{tipo_credor['descricao']}: não há períodos pendentes.",
                flush=True,
            )
            continue

        for numero, (data_ini, data_fim) in enumerate(
            periodos,
            start=1,
        ):
            print(
                f"\nPeríodo {numero}/{len(periodos)}",
                flush=True,
            )

            sucessos, erros = executar_com_fallback(
                tipo_credor=tipo_credor,
                data_ini=data_ini,
                data_fim=data_fim,
            )

            total_arquivos += sucessos
            total_erros += erros

    print("\n" + "=" * 80, flush=True)
    print("SUPRIMENTOS - CONTAS PAGAS FINALIZADO", flush=True)
    print(
        "Arquivos gerados/atualizados:",
        total_arquivos,
        flush=True,
    )
    print("Erros/avisos:", total_erros, flush=True)
    print("Pasta:", PASTA_SAIDA, flush=True)
    print("=" * 80, flush=True)

    return 0 if total_erros == 0 else 1


if __name__ == "__main__":
    codigo_saida = main()
    aguardar_fechamento_manual()
    raise SystemExit(codigo_saida)
