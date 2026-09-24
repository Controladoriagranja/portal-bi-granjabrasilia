import argparse
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# =============================================================================
# CONFIGURAÇÃO / IMPORTS DO PROJETO
# =============================================================================

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# =============================================================================
# RELATÓRIO
# =============================================================================

NOME_RELATORIO = "Títulos Agrupados"
CAMINHO_RELATORIO = "/webpro/weball/wad350d1"
MENU = 27290
MODULO = "27114"

# Contexto exibido no Agrosys:
# FINANCEIRO -> 01 GRÁNJA BRASÍLIA -> 051 FINANCEIRO ADM
UNIDADE_ENGINE = "51"

# Filtros confirmados pelo HAR:
# vselec=P
# vdt-ini=DD/MM/AAAA
# vdt-fim=DD/MM/AAAA
# vtipo-id=0
# vpad-btdisp.x=Disparar

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Titulos Agrupados"
)
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def parse_data_br(valor):
    valor = str(valor or "").strip()

    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            pass

    raise argparse.ArgumentTypeError(
        f"Data inválida: {valor}. Use DD/MM/AAAA ou AAAA-MM-DD."
    )


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

            # Aproximadamente 3 segundos sem crescimento.
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


def montar_filtros(data_ini, data_fim):
    """
    Filtros capturados diretamente no POST do Agrosys.

    Selecione Filtro = Por Período
    Tipo Credor = Todos
    """
    return {
        "vselec": "P",
        "vdt-ini": data_ini.strftime("%d/%m/%Y"),
        "vdt-fim": data_fim.strftime("%d/%m/%Y"),
        "vtipo-id": "0",
        "vpad-btdisp.x": "Disparar",
    }


def baixar_periodo(ag, driver, data_ini, data_fim):
    print("=" * 80, flush=True)
    print(f"SUPRIMENTOS - {NOME_RELATORIO}", flush=True)
    print(
        f"Período: {data_ini.strftime('%d/%m/%Y')} "
        f"até {data_fim.strftime('%d/%m/%Y')}",
        flush=True,
    )
    print("=" * 80, flush=True)

    filtros = montar_filtros(data_ini, data_fim)

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
        unidade=UNIDADE_ENGINE,
        filtros=filtros,
        nome_debug=(
            "titulos_agrupados_"
            f"{data_ini.strftime('%d-%m-%Y')}_"
            f"{data_fim.strftime('%d-%m-%Y')}"
        ),
        modulo=MODULO,
    )

    print("Processo:", processo, flush=True)

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = (
        PASTA_SAIDA
        / (
            "titulos_agrupados_"
            f"{data_ini.strftime('%d-%m-%Y')}_ate_"
            f"{data_fim.strftime('%d-%m-%Y')}.xlsx"
        )
    )

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    return arquivo_destino


# =============================================================================
# LÓGICA AUTOMÁTICA
# =============================================================================

def listar_dias(data_ini, data_fim):
    atual = data_ini
    while atual <= data_fim:
        yield atual
        atual += timedelta(days=1)


def ultima_data_na_pasta():
    """
    Reconhece:
      titulos_agrupados_DD-MM-AAAA_ate_DD-MM-AAAA.xlsx

    Usa a DATA FINAL do arquivo.
    Assim um arquivo manual/mensal também é reconhecido.
    """
    padrao = re.compile(
        r"^titulos_agrupados_"
        r"(\d{2}-\d{2}-20\d{2})_ate_"
        r"(\d{2}-\d{2}-20\d{2})\.(xlsx|xls|html)$",
        re.IGNORECASE,
    )

    hoje = date.today()
    datas = []

    for arquivo in PASTA_SAIDA.glob("titulos_agrupados_*"):
        match = padrao.match(arquivo.name)
        if not match:
            continue

        try:
            data_final = datetime.strptime(
                match.group(2),
                "%d-%m-%Y",
            ).date()
        except ValueError:
            continue

        if data_final <= hoje:
            datas.append(data_final)

    return max(datas) if datas else None


def periodos_automaticos():
    """
    Regra automática, igual à lógica incremental que estamos usando:

    - lê a pasta;
    - encontra a maior DATA FINAL existente;
    - rebaixa essa última data;
    - segue dia a dia até hoje;
    - se a pasta estiver vazia: ontem + hoje.

    Isso cobre também final de semana/feriado:
    sexta -> segunda baixa sexta novamente, sábado, domingo e segunda.
    """
    hoje = date.today()
    ultima = ultima_data_na_pasta()

    if ultima is None:
        inicio = hoje - timedelta(days=1)
        print(
            "Nenhum arquivo encontrado. Fallback: ONTEM + HOJE.",
            flush=True,
        )
    else:
        inicio = ultima
        print(
            f"Última data encontrada: {ultima:%d/%m/%Y}",
            flush=True,
        )
        print(
            f"Rebaixando {ultima:%d/%m/%Y} e seguindo "
            f"até {hoje:%d/%m/%Y}.",
            flush=True,
        )

    return [
        {
            "inicio": dia,
            "fim": dia,
            "tipo": "automatico_diario",
        }
        for dia in listar_dias(inicio, hoje)
    ]


# =============================================================================
# ARGUMENTOS
# =============================================================================

def ler_argumentos():
    parser = argparse.ArgumentParser(
        description="Suprimentos - Relatório de Títulos Agrupados"
    )

    parser.add_argument(
        "--modo",
        choices=["auto", "periodo", "dias"],
        default="auto",
    )

    parser.add_argument(
        "--inicio",
        type=parse_data_br,
        default=None,
    )

    parser.add_argument(
        "--fim",
        type=parse_data_br,
        default=None,
    )

    parser.add_argument(
        "--dias",
        type=int,
        default=2,
    )

    args = parser.parse_args()

    if args.inicio or args.fim:
        args.modo = "periodo"

    return args


def montar_periodos(args):
    hoje = date.today()

    if args.modo == "auto":
        return periodos_automaticos()

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            raise ValueError(
                "No modo periodo informe --inicio e --fim."
            )

        if args.inicio > args.fim:
            raise ValueError(
                "A data inicial não pode ser maior que a final."
            )

        if args.fim > hoje:
            raise ValueError(
                "A data final não pode estar no futuro."
            )

        # No modo manual o usuário pediu exatamente esse intervalo.
        return [
            {
                "inicio": args.inicio,
                "fim": args.fim,
                "tipo": "periodo_manual",
            }
        ]

    quantidade = max(int(args.dias or 1), 1)
    inicio = hoje - timedelta(days=quantidade - 1)

    return [
        {
            "inicio": dia,
            "fim": dia,
            "tipo": "dias",
        }
        for dia in listar_dias(inicio, hoje)
    ]


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = ler_argumentos()
    periodos = montar_periodos(args)

    print("=" * 80, flush=True)
    print("SUPRIMENTOS - TÍTULOS AGRUPADOS", flush=True)
    print(f"MODO: {args.modo.upper()}", flush=True)
    print("Programa: wad350d1", flush=True)
    print("Menu: 27290", flush=True)
    print("Módulo: 27114", flush=True)
    print("Unidade: 51 - FINANCEIRO ADM", flush=True)
    print("", flush=True)
    print("OBJETIVO:", flush=True)
    print("  Título -> NF -> OC -> Comprador", flush=True)
    print("=" * 80, flush=True)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()

    driver = criar_driver()

    try:
        copiar_cookies_para_selenium(driver, ag)

        for numero, periodo in enumerate(periodos, start=1):
            data_ini = periodo["inicio"]
            data_fim = periodo["fim"]

            print("", flush=True)
            print("-" * 80, flush=True)
            print(
                f"[{numero}/{len(periodos)}] "
                f"{data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
                flush=True,
            )
            print("-" * 80, flush=True)

            baixar_periodo(
                ag=ag,
                driver=driver,
                data_ini=data_ini,
                data_fim=data_fim,
            )

        print("", flush=True)
        print("=" * 80, flush=True)
        print("ATUALIZAÇÃO FINALIZADA COM SUCESSO", flush=True)
        print("=" * 80, flush=True)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
