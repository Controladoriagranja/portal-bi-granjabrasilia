# -*- coding: utf-8 -*-
r"""
ÍNDICE ZOOTÉCNICO - Movimento Mortalidade/Peso - LOTES FECHADOS

Programa Agrosys: wpf531d7
Menu Agrosys: vmen-codigo=17136

REQUEST:
POST /webpro/webprod/wpf531d7?vmen-codigo=17136

CARACTERÍSTICA DESTA EXTRAÇÃO:
- "Lotes Fechados" é enviado como vacertados=on.
- Tipo Data é enviado como vtipo-dt=1 (Data do Acerto).
- Unidade Abate é enviada vazia para considerar todas.
- Replica os demais parâmetros observados no request informado.

SAÍDA:
\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Movimento MortalidadePeso\Lotes Fechados

MODOS:
    py indice_zootecnico_mortalidade_peso_lotes_fechados.py
        -> mês anterior fechado

    py indice_zootecnico_mortalidade_peso_lotes_fechados.py --inicio 01/08/2026 --fim 31/08/2026

    py indice_zootecnico_mortalidade_peso_lotes_fechados.py --dias 30

    py indice_zootecnico_mortalidade_peso_lotes_fechados.py --sem-pausa
"""

import argparse
import calendar
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path


# =============================================================================
# ERRO / DEBUG
# =============================================================================

def registrar_erro_fatal(titulo, erro):
    separador = "=" * 80
    traceback_texto = traceback.format_exc()

    print()
    print(separador, flush=True)
    print(titulo, flush=True)
    print(separador, flush=True)
    print("Tipo:", type(erro).__name__, flush=True)
    print("Erro:", str(erro), flush=True)
    print()
    print("TRACEBACK COMPLETO:", flush=True)
    print(traceback_texto, flush=True)
    print(separador, flush=True)

    try:
        arquivo_log = (
            Path(__file__).resolve().parent
            / "indice_zootecnico_mortalidade_peso_lotes_fechados_ERRO.log"
        )

        arquivo_log.write_text(
            f"{titulo}\n"
            f"{separador}\n"
            f"Data/hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"Tipo: {type(erro).__name__}\n"
            f"Erro: {erro}\n\n"
            f"TRACEBACK COMPLETO:\n{traceback_texto}\n",
            encoding="utf-8",
        )

        print(
            "Log salvo em:",
            arquivo_log,
            flush=True,
        )

    except Exception as erro_log:
        print(
            "Não foi possível salvar o log:",
            erro_log,
            flush=True,
        )


# =============================================================================
# IMPORTS DO PROJETO
# =============================================================================

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    RAIZ = Path(__file__).resolve().parents[1]
    sys.path.append(str(RAIZ))

    from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML, PASTA_DOWNLOAD

    from Core.agrosys_engine import AgrosysEngine

except Exception as erro_importacao:
    registrar_erro_fatal(
        "ERRO AO CARREGAR AS DEPENDÊNCIAS",
        erro_importacao,
    )

    try:
        pass  # Encerramento automatico: nao aguardar ENTER.
    except Exception:
        pass

    raise SystemExit(1)


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

MENU = 17136
PROGRAMA = "wpf531d7"
CAMINHO_RELATORIO = "/webpro/webprod/wpf531d7"
MODULO = "17000"

# Contexto observado no request:
#   semp-empresa=1
#   suni-unidade=52
UNIDADE = "52"

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Movimento MortalidadePeso\Lotes Fechados"
)

# PASTA_DOWNLOAD vem da configuracao isolada desta execucao.

try:
    PASTA_SAIDA.mkdir(
        parents=True,
        exist_ok=True,
    )

    PASTA_DOWNLOAD.mkdir(
        parents=True,
        exist_ok=True,
    )

except Exception as erro_pastas:
    registrar_erro_fatal(
        "ERRO AO PREPARAR AS PASTAS",
        erro_pastas,
    )

    try:
        pass  # Encerramento automatico: nao aguardar ENTER.
    except Exception:
        pass

    raise SystemExit(1)


# =============================================================================
# ARGUMENTOS
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modo",
        choices=["auto", "dias", "periodo"],
        default="auto",
        help=(
            "auto = primeiro dia do mês atual até hoje; "
            "dias = últimos X dias; "
            "periodo = intervalo manual."
        ),
    )

    parser.add_argument(
        "--dias",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--inicio",
        type=str,
        default=None,
        help="DD/MM/AAAA",
    )

    parser.add_argument(
        "--fim",
        type=str,
        default=None,
        help="DD/MM/AAAA",
    )

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
    )

    args = parser.parse_args()

    if args.inicio or args.fim:
        args.modo = "periodo"

    elif args.dias is not None:
        args.modo = "dias"

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            parser.error(
                "Informe --inicio e --fim."
            )

        try:
            args.data_inicio = datetime.strptime(
                args.inicio,
                "%d/%m/%Y",
            ).date()

            args.data_fim = datetime.strptime(
                args.fim,
                "%d/%m/%Y",
            ).date()

        except ValueError:
            parser.error(
                "Datas devem estar no formato DD/MM/AAAA."
            )

        if args.data_inicio > args.data_fim:
            parser.error(
                "Data inicial maior que a final."
            )

    elif args.modo == "dias":
        quantidade = max(
            int(args.dias or 1),
            1,
        )

        args.data_fim = datetime.now().date()
        args.data_inicio = (
            args.data_fim
            - timedelta(days=quantidade - 1)
        )

    else:
        hoje = datetime.now().date()
        args.data_inicio = hoje.replace(day=1)
        args.data_fim = hoje

    return args


# =============================================================================
# SELENIUM
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

    chrome_options.add_experimental_option(
        "prefs",
        prefs,
    )

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")

    driver = webdriver.Chrome(
        options=chrome_options
    )

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
        except Exception:
            pass


def aguardar_download(
    timeout=300,
    inicio_download=None,
):
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

            if estabilidade >= 6:
                print(
                    "Arquivo final detectado:",
                    arquivo.name,
                    "| tamanho:",
                    f"{tamanho / 1024 / 1024:.2f} MB",
                    flush=True,
                )
                return arquivo

        time.sleep(0.5)

    return None


def copiar_cookies_para_selenium(driver, ag):
    print(
        "Preparando sessão Selenium...",
        flush=True,
    )

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


def baixar_excel_oficial(
    driver,
    url_relatorio,
    arquivo_destino,
):
    limpar_downloads()

    print(
        "Abrindo relatório pronto no Selenium...",
        flush=True,
    )

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
        raise RuntimeError(
            "A página abriu, mas fexcel() não ficou disponível em 60 segundos."
        )

    print(
        f"fexcel() localizado em {time.time() - inicio_abertura:.1f}s.",
        flush=True,
    )

    inicio_download = time.time()

    driver.execute_script(
        "fexcel();"
    )

    print(
        "fexcel() executado.",
        flush=True,
    )

    baixado = aguardar_download(
        timeout=300,
        inicio_download=inicio_download,
    )

    if baixado is None:
        presentes = [
            arquivo.name
            for arquivo in PASTA_DOWNLOAD.glob("*")
            if arquivo.is_file()
        ]

        raise RuntimeError(
            "Não encontrei o Excel oficial baixado. "
            f"Arquivos presentes: {presentes}"
        )

    arquivo_destino.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if arquivo_destino.exists():
        arquivo_destino.unlink()

    shutil.move(
        str(baixado),
        str(arquivo_destino),
    )

    if (
        not arquivo_destino.exists()
        or arquivo_destino.stat().st_size <= 0
    ):
        raise RuntimeError(
            "O Excel foi baixado, mas não foi salvo corretamente."
        )

    print(
        "Excel oficial salvo:",
        arquivo_destino,
        flush=True,
    )


# =============================================================================
# FILTROS - LOTES FECHADOS
# =============================================================================

def montar_filtros(
    data_ini,
    data_fim,
):
    """
    Replica o POST observado para LOTES FECHADOS.

    IMPORTANTE:
    O checkbox:
        vacertados = on
    significa "Lotes Fechados".

    Como a extração solicitada é LOTES FECHADOS,
    vacertados NÃO é enviado.
    """

    filtros = {
        "vdata-ini": data_ini.strftime("%d/%m/%Y"),
        "vdata-fim": data_fim.strftime("%d/%m/%Y"),

        "vregiao": "",
        "vrfo-codigo": "",
        "vrfo-descri": "",
        "vtecinico": "",
        "vlinhagem": "",
        "vicuba": "",
        "vsexo": "",
        "vidade-ini": "",
        "vidade-fim": "",

        "vmort-peso-elim": "T",
        "vmt-100": "QTD",

        "vcli-codigo": "",
        "vgpp-codigo": "",
        "vnuc-nucleo": "",
        "vid-mt-ini": "",
        "vid-mt-fim": "",
        "vlote-mat": "",

        # Lotes Fechados marcado no request real:
        "vacertados": "on",
        # Tipo Data: Data do Acerto
        "vtipo-dt": "1",
        # Unidade Abate: todas
        "vuni-abate": "",

        "vtipo": "S",
        "vtaxa": "S",
        "vpsproj": "no",
        "vdesvio": "S",
        "vdesviops": "S",

        "vordena": "",
        "vtp-granja": "",
        "vtpgalp": "",
        "vempresa": "",
        "vunidade": "",
        "vnutricao": "",

        "vpad-btdisp.x": "Disparar",
    }

    # Nesta versão, vacertados=on é obrigatório para Lotes Fechados.
    # vtipo-dt=1 usa Data do Acerto, conforme o payload capturado.
    # vuni-abate vazio mantém Todas as unidades de abate.

    return filtros


# =============================================================================
# EXTRAÇÃO
# =============================================================================

def baixar_relatorio(
    ag,
    driver,
    data_ini,
    data_fim,
):
    print()
    print("=" * 80, flush=True)
    print(
        "ÍNDICE ZOOTÉCNICO - MOVIMENTO MORTALIDADE/PESO - LOTES FECHADOS",
        flush=True,
    )
    print(
        f"Programa: {PROGRAMA}",
        flush=True,
    )
    print(
        f"Menu: {MENU}",
        flush=True,
    )
    print(
        "Lotes Fechados (vacertados): on",
        flush=True,
    )
    print(
        "Período:",
        data_ini.strftime("%d/%m/%Y"),
        "até",
        data_fim.strftime("%d/%m/%Y"),
        flush=True,
    )
    print("=" * 80, flush=True)

    filtros = montar_filtros(
        data_ini,
        data_fim,
    )

    print(
        "Disparando relatório...",
        flush=True,
    )

    print(
        "POST:",
        f"{CAMINHO_RELATORIO}?vmen-codigo={MENU}",
        flush=True,
    )

    print(
        "Filtros enviados:",
        filtros,
        flush=True,
    )

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
        unidade=UNIDADE,
        filtros=filtros,
        nome_debug=(
            "indice_zootecnico_mortalidade_peso_lotes_fechados_"
            f"{data_ini.strftime('%d-%m-%Y')}_"
            f"{data_fim.strftime('%d-%m-%Y')}"
        ),
        modulo=MODULO,
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )

    print(
        "Processo localizado:",
        processo,
        flush=True,
    )

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = (
        PASTA_SAIDA
        / (
            "Movimento_Mortalidade_Peso_Lotes_Fechados_"
            f"{data_ini.strftime('%d-%m-%Y')}_"
            f"{data_fim.strftime('%d-%m-%Y')}.xlsx"
        )
    )

    print(
        "URL relatório:",
        url_relatorio,
        flush=True,
    )

    print(
        "Destino:",
        arquivo_destino,
        flush=True,
    )

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    return arquivo_destino


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = parse_args()
    inicio = time.time()

    print("=" * 80, flush=True)
    print(
        "INICIANDO EXTRAÇÃO - MOVIMENTO MORTALIDADE/PESO - LOTES FECHADOS",
        flush=True,
    )
    print(
        "Pasta:",
        PASTA_SAIDA,
        flush=True,
    )
    print(
        "Período:",
        args.data_inicio.strftime("%d/%m/%Y"),
        "até",
        args.data_fim.strftime("%d/%m/%Y"),
        flush=True,
    )
    print("=" * 80, flush=True)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    driver = None

    try:
        print(
            "Realizando login no Agrosys...",
            flush=True,
        )

        ag.login()

        print(
            "Login realizado.",
            flush=True,
        )

        driver = criar_driver()

        copiar_cookies_para_selenium(
            driver,
            ag,
        )

        resultado = baixar_relatorio(
            ag=ag,
            driver=driver,
            data_ini=args.data_inicio,
            data_fim=args.data_fim,
        )

        print()
        print("=" * 80, flush=True)
        print(
            "EXTRAÇÃO LOTES FECHADOS FINALIZADA COM SUCESSO",
            flush=True,
        )
        print(
            "Arquivo:",
            resultado,
            flush=True,
        )
        print(
            "Tempo:",
            f"{time.time() - inicio:.1f}s",
            flush=True,
        )
        print("=" * 80, flush=True)

        return 0

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    codigo_saida = 0

    try:
        codigo_saida = main()

    except BaseException as erro:
        if isinstance(erro, KeyboardInterrupt):
            print(
                "\nExecução cancelada pelo usuário.",
                flush=True,
            )
            codigo_saida = 130

        elif isinstance(erro, SystemExit):
            raise

        else:
            registrar_erro_fatal(
                "ERRO NA EXTRAÇÃO - LOTES FECHADOS",
                erro,
            )
            codigo_saida = 1

    if "--sem-pausa" not in sys.argv:
        try:
            pass  # Encerramento automatico: nao aguardar ENTER.
        except Exception:
            pass

    raise SystemExit(codigo_saida)
