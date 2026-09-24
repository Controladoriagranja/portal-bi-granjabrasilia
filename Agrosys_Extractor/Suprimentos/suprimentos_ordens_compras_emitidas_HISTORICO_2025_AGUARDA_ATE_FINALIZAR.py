# -*- coding: utf-8 -*-
"""
SUPRIMENTOS - Ordens de Compras Emitidas no Período
TESTE: baixa somente 1 dia.

Confirmado manualmente no Agrosys:
- Programa: wsu061d2
- Menu: 29088
- Módulo: 27932 (SUPRIMENTOS NOVO)
- Empresa da sessão: 1
- Unidade da sessão: 1
- Tipo de compra: Geral
- Tipo OC: Todos
- Situação: Todas
- Formato Excel: Sim
"""

import argparse
import sys
import time
import shutil
from pathlib import Path
from datetime import date, datetime, timedelta
import calendar
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

CAMINHO_RELATORIO = "/webpro/websup/wsu061d2"
MENU_RELATORIO = 29088
MODULO_RELATORIO = "27932"
UNIDADE_SESSAO = "1"

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Ordens de Compras Emitidas"
)
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TIMEOUT_DOWNLOAD = 900
TENTATIVAS_RELATORIO = 60
ESPERA_RELATORIO = 20
# Este relatório pode levar vários minutos no Agrosys.
# Não abandonar o processo por 404 enquanto ele ainda estiver sendo gerado.
TEMPO_MINIMO_ANTES_DESCARTAR_404 = 604800  # 7 dias
MAX_404_CONSECUTIVOS = 999999999

HISTORICO_INICIO = date(2025, 1, 1)
HISTORICO_FIM = date(2025, 12, 31)


def criar_driver():
    opcoes = Options()

    prefs = {
        "download.default_directory": str(PASTA_DOWNLOAD),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }

    opcoes.add_experimental_option("prefs", prefs)
    opcoes.add_argument("--headless=new")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1920,1080")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-extensions")
    opcoes.add_argument("--disable-notifications")
    opcoes.add_argument("--disable-popup-blocking")

    driver = webdriver.Chrome(options=opcoes)

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


def aguardar_download(timeout=TIMEOUT_DOWNLOAD, inicio_download=None):
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
        timeout=TIMEOUT_DOWNLOAD,
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
    data_ini_br = data_ini.strftime("%d/%m/%Y")
    data_fim_br = data_fim.strftime("%d/%m/%Y")

    return {
        "vdata-ini": data_ini_br,
        "vdata-fim": data_fim_br,
        "vcom-grupo": "",
        "vgru-codigo": "",
        "vemp-empresa": "",
        "vuni-unidade": "",
        "vfor-codigo": "",
        "vusuario": "",
        "vnum-oc": "",
        "vvalor-ini": "",
        "vvalor-fim": "",
        "vpjt-numero": "",
        "vsituacao": "T",
        "vtip-encerr": "T",
        "vtip-compra": "1",
        "vtip-oc": "0",
        "vexcel": "yes",
        "vpad-btdisp.x": "Disparar",
    }



def parse_data_nome_arquivo(valor):
    """
    Aceita os dois padrões que podem existir na pasta:
      YYYY-MM-DD
      DD-MM-YYYY
    """
    valor = str(valor).strip()

    for formato in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            pass

    return None


def intervalos_existentes_na_pasta():
    """
    Lê os nomes dos arquivos já existentes e devolve os períodos cobertos.

    Reconhece:
      ordens_compras_emitidas_2025-01-10.xlsx
      ordens_compras_emitidas_10-01-2025.xlsx

      ordens_compras_emitidas_2025-01-01_ate_2025-01-31.xlsx
      ordens_compras_emitidas_01-01-2025_ate_31-01-2025.xlsx
    """
    if not PASTA_SAIDA.exists():
        return []

    padrao_periodo = re.compile(
        r"^ordens_compras_emitidas_"
        r"(\d{2,4}-\d{2}-\d{2,4})"
        r"_ate_"
        r"(\d{2,4}-\d{2}-\d{2,4})"
        r"\.xlsx$",
        re.IGNORECASE,
    )

    padrao_dia = re.compile(
        r"^ordens_compras_emitidas_"
        r"(\d{2,4}-\d{2}-\d{2,4})"
        r"\.xlsx$",
        re.IGNORECASE,
    )

    intervalos = []

    for arquivo in PASTA_SAIDA.glob("*.xlsx"):
        nome = arquivo.name

        match = padrao_periodo.match(nome)

        if match:
            inicio = parse_data_nome_arquivo(match.group(1))
            fim = parse_data_nome_arquivo(match.group(2))

            if inicio and fim:
                if inicio > fim:
                    inicio, fim = fim, inicio

                intervalos.append(
                    {
                        "arquivo": arquivo.name,
                        "inicio": inicio,
                        "fim": fim,
                    }
                )

            continue

        match = padrao_dia.match(nome)

        if match:
            data_ref = parse_data_nome_arquivo(match.group(1))

            if data_ref:
                intervalos.append(
                    {
                        "arquivo": arquivo.name,
                        "inicio": data_ref,
                        "fim": data_ref,
                    }
                )

    return intervalos


def dias_cobertos_2025():
    """
    Converte todos os períodos já existentes em um conjunto de dias cobertos
    dentro de 2025.
    """
    cobertos = set()
    intervalos = intervalos_existentes_na_pasta()

    for intervalo in intervalos:
        inicio = max(intervalo["inicio"], HISTORICO_INICIO)
        fim = min(intervalo["fim"], HISTORICO_FIM)

        if inicio > fim:
            continue

        atual = inicio

        while atual <= fim:
            cobertos.add(atual)
            atual += timedelta(days=1)

    return cobertos, intervalos


def agrupar_dias_faltantes_por_mes(dias_faltantes):
    """
    Agrupa dias consecutivos, mas nunca atravessa a virada do mês.

    Exemplo:
      faltam 01/01 a 31/01 -> 1 relatório mensal
      faltam 01/02 a 10/02 e 20/02 a 28/02 -> 2 relatórios
    """
    if not dias_faltantes:
        return []

    dias = sorted(dias_faltantes)
    periodos = []

    inicio = dias[0]
    anterior = dias[0]

    for atual in dias[1:]:
        consecutivo = atual == anterior + timedelta(days=1)
        mesmo_mes = (
            atual.year == anterior.year
            and atual.month == anterior.month
        )

        if consecutivo and mesmo_mes:
            anterior = atual
            continue

        periodos.append(
            {
                "tipo": "historico_2025",
                "inicio": inicio,
                "fim": anterior,
            }
        )

        inicio = atual
        anterior = atual

    periodos.append(
        {
            "tipo": "historico_2025",
            "inicio": inicio,
            "fim": anterior,
        }
    )

    return periodos


def listar_periodos_historico_2025():
    """
    Lê a pasta e baixa SOMENTE o que ainda não está coberto em 2025.
    """
    todos_dias = set()

    atual = HISTORICO_INICIO

    while atual <= HISTORICO_FIM:
        todos_dias.add(atual)
        atual += timedelta(days=1)

    cobertos, intervalos = dias_cobertos_2025()
    faltantes = todos_dias - cobertos

    print("", flush=True)
    print("=" * 80, flush=True)
    print("ANÁLISE DA PASTA - HISTÓRICO 2025", flush=True)
    print("Pasta:", PASTA_SAIDA, flush=True)
    print(
        "Arquivos reconhecidos na pasta:",
        len(intervalos),
        flush=True,
    )
    print(
        "Dias de 2025 já cobertos:",
        len(cobertos),
        "/ 365",
        flush=True,
    )
    print(
        "Dias de 2025 faltantes:",
        len(faltantes),
        flush=True,
    )

    periodos = agrupar_dias_faltantes_por_mes(
        faltantes
    )

    if not periodos:
        print(
            "2025 JÁ ESTÁ COMPLETO. Nenhum download necessário.",
            flush=True,
        )
        print("=" * 80, flush=True)
        return []

    print(
        "Intervalos que serão baixados:",
        len(periodos),
        flush=True,
    )

    for numero, periodo in enumerate(periodos, start=1):
        print(
            f"  {numero:02d}. "
            f"{periodo['inicio']:%d/%m/%Y} "
            f"até {periodo['fim']:%d/%m/%Y}",
            flush=True,
        )

    print("=" * 80, flush=True)

    return periodos


def parse_data_br(valor):
    try:
        return datetime.strptime(valor, "%d/%m/%Y").date()
    except Exception as erro:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {valor}. Use DD/MM/AAAA."
        ) from erro


def listar_dias(data_ini, data_fim):
    atual = data_ini

    while atual <= data_fim:
        yield atual
        atual += timedelta(days=1)


def ler_argumentos():
    parser = argparse.ArgumentParser(
        description=(
            "Suprimentos - Ordens de Compras Emitidas "
            "- Histórico 2025"
        )
    )

    parser.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "Ignora o que já existe e rebaixa janeiro a dezembro/2025 "
            "em períodos mensais completos."
        ),
    )

    return parser.parse_args()


def periodos_mensais_2025():
    periodos = []

    for mes in range(1, 13):
        ultimo_dia = calendar.monthrange(
            2025,
            mes,
        )[1]

        periodos.append(
            {
                "tipo": "historico_2025",
                "inicio": date(2025, mes, 1),
                "fim": date(2025, mes, ultimo_dia),
            }
        )

    return periodos


def montar_periodos(args):
    if args.forcar:
        print(
            "MODO --FORCAR: rebaixando os 12 meses completos de 2025.",
            flush=True,
        )
        return periodos_mensais_2025()

    return listar_periodos_historico_2025()


def nome_arquivo_periodo(tipo, data_ini, data_fim):
    return (
        f"ordens_compras_emitidas_"
        f"{data_ini:%Y-%m-%d}_ate_{data_fim:%Y-%m-%d}.xlsx"
    )


def main():
    args = ler_argumentos()
    periodos = montar_periodos(args)

    print("=" * 80, flush=True)
    print("SUPRIMENTOS - ORDENS DE COMPRAS EMITIDAS - HISTÓRICO 2025", flush=True)
    print("Programa: wsu061d2", flush=True)
    print("Menu: 29088", flush=True)
    print("Módulo: 27932", flush=True)
    print("Sessão: Empresa 1 / Unidade 1", flush=True)
    print("Regra: LER PASTA -> BAIXAR SOMENTE O QUE FALTA EM 2025", flush=True)
    print("Geração do relatório: AGUARDAR O MESMO PROCESSO ATÉ FICAR PRONTO", flush=True)
    print("404 durante geração NÃO descarta o processo nem dispara outro relatório", flush=True)
    print("Espera máxima pelo download Excel, após ficar pronto: 15 minutos", flush=True)
    print("=" * 80, flush=True)

    if not periodos:
        print(
            "Nada para baixar. Encerrando sem abrir navegador.",
            flush=True,
        )
        return

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()

    driver = criar_driver()

    try:
        for numero, periodo in enumerate(periodos, start=1):
            tipo = periodo["tipo"]
            data_ini = periodo["inicio"]
            data_fim = periodo["fim"]

            print("", flush=True)
            print("-" * 80, flush=True)
            print(
                f"[{numero}/{len(periodos)}] "
                f"{tipo.upper()} | "
                f"{data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
                flush=True,
            )
            print("-" * 80, flush=True)

            filtros = montar_filtros(
                data_ini,
                data_fim,
            )

            html, processo = ag.executar_relatorio(
                caminho=CAMINHO_RELATORIO,
                menu=MENU_RELATORIO,
                unidade=UNIDADE_SESSAO,
                filtros=filtros,
                nome_debug=(
                    f"ordens_compras_emitidas_"
                    f"{data_ini:%Y-%m-%d}_"
                    f"{data_fim:%Y-%m-%d}"
                ),
                modulo=MODULO_RELATORIO,
                tentativas=TENTATIVAS_RELATORIO,
                espera=ESPERA_RELATORIO,
                tentativas_disparo=8,
                espera_disparo=15,
                max_404_consecutivos=MAX_404_CONSECUTIVOS,
                tempo_minimo_antes_descartar_404=TEMPO_MINIMO_ANTES_DESCARTAR_404,
            )

            print("Processo:", processo, flush=True)

            url_relatorio = (
                f"{BASE_AGROSYS}/sistema/reports/"
                f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
            )

            print("URL relatório:", url_relatorio, flush=True)

            copiar_cookies_para_selenium(
                driver,
                ag,
            )

            arquivo_destino = (
                PASTA_SAIDA
                / nome_arquivo_periodo(
                    tipo,
                    data_ini,
                    data_fim,
                )
            )

            baixar_excel_oficial(
                driver,
                url_relatorio,
                arquivo_destino,
            )

        print("", flush=True)
        print("=" * 80, flush=True)
        print("ATUALIZAÇÃO FINALIZADA COM SUCESSO", flush=True)
        print("=" * 80, flush=True)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
