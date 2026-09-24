# -*- coding: utf-8 -*-
"""
PCP - Relatório Geral de Condenações
Relatório: Relatório Geral de Condenações
Menu Agrosys: vmen-codigo=18185
Programa: wcf222d1

REGRAS:
- Padrão igual aos robôs da Logística e PCP já validados.
- Usa login automático pelo config.py + AgrosysEngine.
- Usa Selenium apenas para baixar o Excel oficial via fexcel().
- Atualiza somente:
    010 - AVE NOVA
    111 - REAL ALIMENTOS
- Mesmo conceito da Devolução:
    Lê a pasta, identifica a última data por unidade e baixa da última data encontrada até hoje.
- Reprocessa a última data encontrada para pegar fechamento completo.
- Mantém histórico.
- Sobrescreve somente se o arquivo do mesmo período já existir.
"""

import argparse
import re
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Relatorio Geral de Condenacoes")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TERMO_RELATORIO = "relatorio_geral_de_condenacoes"

UNIDADES = [
    {"codigo": "10", "nome_arquivo": "Avenova", "descricao": "010 - AVE NOVA"},
    {"codigo": "111", "nome_arquivo": "Real", "descricao": "111 - REAL ALIMENTOS"},
]

HOJE = datetime.now().date()
DIAS_LOOKBACK = 30


def normalizar_nome(txt: str):
    return (
        str(txt).lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def parse_data_nome(txt: str):
    try:
        if txt.startswith("20"):
            return datetime.strptime(txt, "%Y-%m-%d").date()
        return datetime.strptime(txt, "%d-%m-%Y").date()
    except Exception:
        return None


def extrair_periodo_arquivo(nome_arquivo: str):
    datas = re.findall(r"(\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})", nome_arquivo)

    if len(datas) < 2:
        return None

    data_ini = parse_data_nome(datas[0])
    data_fim = parse_data_nome(datas[1])

    if not data_ini or not data_fim:
        return None

    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    return data_ini, data_fim


def arquivos_da_unidade(pasta_saida: Path, unidade_nome: str, termo_relatorio: str):
    unidade_key = normalizar_nome(unidade_nome)
    termo_key = normalizar_nome(termo_relatorio)

    arquivos = []

    for arq in pasta_saida.glob("*.xls*"):
        nome_key = normalizar_nome(arq.name)

        if termo_key not in nome_key:
            continue

        if unidade_key not in nome_key:
            continue

        periodo = extrair_periodo_arquivo(arq.name)
        if not periodo:
            continue

        arquivos.append((arq, periodo))

    return arquivos


def listar_datas_para_atualizar(pasta_saida: Path, unidade_nome: str, termo_relatorio: str, modo="auto", dias=None):
    """
    Modos:
    - --dias 1: baixa somente hoje.
    - --dias 2: baixa ontem e hoje.
    - --dias 7: baixa últimos 7 dias.
    - --modo auto: lê a pasta e baixa da última data encontrada até hoje.
      Se não houver arquivo, baixa últimos 30 dias.

    Igual Devolução/Logística:
    - Reprocessa a última data já existente.
    """
    if dias is not None:
        dias = int(dias)
        if dias < 1:
            dias = 1

        inicio = HOJE - timedelta(days=dias - 1)

        datas = []
        data = inicio
        while data <= HOJE:
            datas.append(data)
            data += timedelta(days=1)

        return datas

    arquivos = arquivos_da_unidade(pasta_saida, unidade_nome, termo_relatorio)
    datas_fim = [periodo[1] for _, periodo in arquivos]

    if not datas_fim:
        inicio = HOJE - timedelta(days=DIAS_LOOKBACK - 1)
    else:
        ultima_data = max(datas_fim)
        inicio = ultima_data

        limite = HOJE - timedelta(days=DIAS_LOOKBACK - 1)
        if inicio < limite:
            inicio = limite

    datas = []
    data = inicio
    while data <= HOJE:
        datas.append(data)
        data += timedelta(days=1)

    return datas


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
    for arq in PASTA_DOWNLOAD.glob("*"):
        try:
            arq.unlink()
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


def baixar_excel_oficial(driver, url_relatorio, arquivo_destino):
    """
    Download oficial do Agrosys via Selenium,
    no mesmo padrão validado no Suprimentos.
    """
    limpar_downloads()

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
        raise Exception(
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

        raise Exception(
            "Não encontrei o arquivo baixado pelo Excel oficial. "
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
        raise Exception(
            "O Excel foi baixado, mas não foi salvo corretamente."
        )

    print(
        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
        arquivo_destino,
        flush=True,
    )


def ler_argumentos():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modo",
        choices=["auto", "dias", "periodo"],
        default="auto",
        help="auto = lê a pasta/regra padrão; dias = últimos X dias; periodo = intervalo manual.",
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=None,
        help="Quantidade de dias para atualizar.",
    )
    parser.add_argument(
        "--inicio",
        type=str,
        default=None,
        help="Data inicial no formato DD/MM/AAAA.",
    )
    parser.add_argument(
        "--fim",
        type=str,
        default=None,
        help="Data final no formato DD/MM/AAAA.",
    )

    args = parser.parse_args()

    if args.inicio or args.fim:
        args.modo = "periodo"
    elif args.dias is not None:
        args.modo = "dias"

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            parser.error("No modo periodo, informe --inicio DD/MM/AAAA e --fim DD/MM/AAAA.")

        try:
            args.data_inicio = datetime.strptime(args.inicio, "%d/%m/%Y").date()
            args.data_fim = datetime.strptime(args.fim, "%d/%m/%Y").date()
        except ValueError:
            parser.error("As datas devem estar no formato DD/MM/AAAA.")

        if args.data_inicio > args.data_fim:
            parser.error("A data inicial não pode ser maior que a data final.")
    else:
        args.data_inicio = None
        args.data_fim = None

    return args


def baixar_periodo(ag, driver, unidade, data_ini, data_fim):
    print("=" * 80, flush=True)
    print(f"PCP Relatório Geral de Condenações - {unidade['descricao']}", flush=True)
    print(f"Data Abate: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}", flush=True)
    print("=" * 80, flush=True)

    filtros = {
        "vpardate1": data_ini.strftime("%d/%m/%Y"),
        "vpardate2": data_fim.strftime("%d/%m/%Y"),
        "vparint1": "1",
        "vparint2": "999999",
        "vparchar1": "",
        "vparint3": "1",
        "vparint4": "9999",
        "vparint6": "2",
        "vparint5": "1",
        "vparchar2": "",
        "vpad-btdisp.x": "Disparar",
    }

    html, processo = ag.executar_relatorio(
        caminho="/webpro/webci/wcf222d1",
        menu=18185,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"pcp_relatorio_geral_condenacoes_{unidade['nome_arquivo']}_{data_ini.strftime('%d-%m-%Y')}",
        modulo="17611",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )

    url_relatorio = f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"

    arquivo_destino = (
        PASTA_SAIDA
        / f"Relatório Geral de Condenações_{unidade['nome_arquivo']}_{data_ini.strftime('%d-%m-%Y')}_ate_{data_fim.strftime('%d-%m-%Y')}.xlsx"
    )

    baixar_excel_oficial(driver, url_relatorio, arquivo_destino)

    print("Processo:", processo, flush=True)
    return arquivo_destino


def main():
    args = ler_argumentos()

    print("=" * 80, flush=True)
    print("INICIANDO PCP - RELATÓRIO GERAL DE CONDENAÇÕES", flush=True)
    print("Empresas: AVE NOVA e REAL ALIMENTOS", flush=True)
    if args.modo == "periodo":
        print(
            f"Período manual DIA A DIA: {args.data_inicio.strftime('%d/%m/%Y')} até "
            f"{args.data_fim.strftime('%d/%m/%Y')}",
            flush=True,
        )
    else:
        print(f"Modo: {args.modo} | Dias: {args.dias if args.dias else 'AUTO'}", flush=True)
    print("=" * 80, flush=True)

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
            if args.modo == "periodo":
                datas = []
                data = args.data_inicio
                while data <= args.data_fim:
                    datas.append(data)
                    data += timedelta(days=1)
            else:
                datas = listar_datas_para_atualizar(
                    PASTA_SAIDA,
                    unidade["nome_arquivo"],
                    TERMO_RELATORIO,
                    modo=args.modo,
                    dias=args.dias if args.modo == "dias" else None,
                )

            print("=" * 80, flush=True)
            print(f"{unidade['descricao']} - dias para atualizar: {len(datas)}", flush=True)
            if datas:
                print("De:", datas[0].strftime("%d/%m/%Y"), flush=True)
                print("Até:", datas[-1].strftime("%d/%m/%Y"), flush=True)
            print("=" * 80, flush=True)

            for data_ref in datas:
                try:
                    resultado = baixar_periodo(
                        ag=ag,
                        driver=driver,
                        unidade=unidade,
                        data_ini=data_ref,
                        data_fim=data_ref,
                    )
                    total_arquivos += 1 if resultado else 0
                    total_erros += 0 if resultado else 1
                except Exception as e:
                    total_erros += 1
                    print("AVISO: falha ao baixar o dia.", flush=True)
                    print("Unidade:", unidade["descricao"], flush=True)
                    print("Data:", data_ref.strftime("%d/%m/%Y"), flush=True)
                    print("Erro:", e, flush=True)

        print("=" * 80, flush=True)
        print("PCP RELATÓRIO GERAL DE CONDENAÇÕES FINALIZADO", flush=True)
        print("Arquivos gerados/atualizados:", total_arquivos, flush=True)
        print("Erros/avisos:", total_erros, flush=True)
        print("=" * 80, flush=True)
        return 0 if total_erros == 0 else 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
