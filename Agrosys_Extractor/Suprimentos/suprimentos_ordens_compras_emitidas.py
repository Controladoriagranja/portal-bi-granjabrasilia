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

TIMEOUT_DOWNLOAD = 300


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


def primeiro_ultimo_dia_mes_anterior(data_ref):
    primeiro_mes_atual = data_ref.replace(day=1)
    ultimo_mes_anterior = primeiro_mes_atual - timedelta(days=1)
    primeiro_mes_anterior = ultimo_mes_anterior.replace(day=1)

    return primeiro_mes_anterior, ultimo_mes_anterior


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


def ultima_data_diaria_na_pasta():
    """
    Procura somente arquivos diários no formato exato:
      ordens_compras_emitidas_YYYY-MM-DD.xlsx

    Arquivos de período, como:
      ordens_compras_emitidas_2026-07-01_ate_2026-07-31.xlsx
    são ignorados para não confundir a última data da base.
    """
    padrao = re.compile(
        r"^ordens_compras_emitidas_(20\d{2}-\d{2}-\d{2})\.xlsx$",
        re.IGNORECASE,
    )

    datas = []

    if not PASTA_SAIDA.exists():
        return None

    for arquivo in PASTA_SAIDA.glob("*.xlsx"):
        match = padrao.match(arquivo.name)

        if not match:
            continue

        try:
            data_arquivo = datetime.strptime(
                match.group(1),
                "%Y-%m-%d",
            ).date()
        except Exception:
            continue

        # Ignora arquivo futuro por segurança.
        if data_arquivo <= date.today():
            datas.append(data_arquivo)

    return max(datas) if datas else None


def listar_periodos_automaticos():
    """
    REGRA AUTOMÁTICA / "LER PASTA":

    1) Lê a pasta de saída e encontra a ÚLTIMA DATA DIÁRIA já baixada.
    2) Rebaixa essa última data completa.
    3) Baixa TODOS os dias seguintes até HOJE, sem pular sábado/domingo.
    4) Se hoje for dia 15, também rebaixa o MÊS ANTERIOR COMPLETO
       para capturar lançamentos/alterações retroativas.

    Exemplo:
      último arquivo = 14/08/2026
      execução = 17/08/2026

      baixa:
        14/08/2026  <- rebaixa a última data
        15/08/2026
        16/08/2026
        17/08/2026
    """
    hoje = date.today()
    ultima_data = ultima_data_diaria_na_pasta()

    periodos = []

    # Retroativo mensal
    if hoje.day == 15:
        ini_mes_ant, fim_mes_ant = primeiro_ultimo_dia_mes_anterior(hoje)
        periodos.append(
            {
                "tipo": "mes_anterior",
                "inicio": ini_mes_ant,
                "fim": fim_mes_ant,
            }
        )

    # Se ainda não houver base diária, mantém fallback seguro:
    # ontem + hoje.
    if ultima_data is None:
        inicio_diario = hoje - timedelta(days=1)
        print(
            "Nenhum arquivo diário encontrado na pasta. "
            "Fallback: ONTEM + HOJE.",
            flush=True,
        )
    else:
        inicio_diario = ultima_data
        print(
            f"Última data diária encontrada na pasta: "
            f"{ultima_data:%d/%m/%Y}",
            flush=True,
        )
        print(
            f"Vou rebaixar {ultima_data:%d/%m/%Y} e seguir "
            f"dia a dia até {hoje:%d/%m/%Y}.",
            flush=True,
        )

    for data_ref in listar_dias(inicio_diario, hoje):
        periodos.append(
            {
                "tipo": "dia",
                "inicio": data_ref,
                "fim": data_ref,
            }
        )

    return periodos



def ler_argumentos():
    parser = argparse.ArgumentParser(
        description="Suprimentos - Ordens de Compras Emitidas"
    )

    parser.add_argument(
        "--modo",
        choices=["auto", "periodo", "dias"],
        default="auto",
    )
    parser.add_argument("--inicio", type=parse_data_br)
    parser.add_argument("--fim", type=parse_data_br)
    parser.add_argument("--dias", type=int, default=2)

    return parser.parse_args()


def montar_periodos(args):
    hoje = date.today()

    if args.modo == "auto":
        return listar_periodos_automaticos()

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

        # Portal: baixa dia a dia para manter a base incremental.
        return [
            {
                "tipo": "dia",
                "inicio": data_ref,
                "fim": data_ref,
            }
            for data_ref in listar_dias(args.inicio, args.fim)
        ]

    quantidade = max(int(args.dias or 1), 1)
    data_ini = hoje - timedelta(days=quantidade - 1)

    return [
        {
            "tipo": "dia",
            "inicio": data_ref,
            "fim": data_ref,
        }
        for data_ref in listar_dias(data_ini, hoje)
    ]


def nome_arquivo_periodo(tipo, data_ini, data_fim):
    if tipo == "mes_anterior":
        return (
            f"ordens_compras_emitidas_"
            f"{data_ini:%Y-%m-01}_ate_{data_fim:%Y-%m-%d}.xlsx"
        )

    return (
        f"ordens_compras_emitidas_{data_ini:%Y-%m-%d}.xlsx"
    )


def main():
    args = ler_argumentos()
    hoje = date.today()
    periodos = montar_periodos(args)

    print("=" * 80, flush=True)
    print("SUPRIMENTOS - ORDENS DE COMPRAS EMITIDAS NO PERÍODO", flush=True)
    print(f"MODO: {args.modo.upper()}", flush=True)
    print("Programa: wsu061d2", flush=True)
    print("Menu: 29088", flush=True)
    print("Módulo: 27932", flush=True)
    print("Sessão: Empresa 1 / Unidade 1", flush=True)
    if args.modo == "auto":
        print("", flush=True)
        print("REGRA:", flush=True)
        print("  Ler pasta -> rebaixa a ÚLTIMA DATA + todos os dias até HOJE", flush=True)
        print("  Dia 15    -> também rebaixa o MÊS ANTERIOR completo", flush=True)
    else:
        print(
            f"Períodos solicitados pelo Portal: {len(periodos)} dia(s)",
            flush=True,
        )
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
                tentativas=30,
                espera=20,
                tentativas_disparo=8,
                espera_disparo=15,
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
