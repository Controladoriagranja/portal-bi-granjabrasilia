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


PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Logistica\Controle de Frete")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TERMO_RELATORIO = "controle_frete"

UNIDADES = [{'codigo': '10', 'nome_arquivo': 'avenova', 'descricao': '010 - AVE NOVA'}, {'codigo': '111', 'nome_arquivo': 'Real', 'descricao': '111 - REAL ALIMENTOS'}, {'codigo': '180', 'nome_arquivo': 'CdRibeiraoDasNeves', 'descricao': '180 - CD RIBEIRÃO DAS NEVES'}]


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

        # Reprocessa a última data já existente para pegar fechamento completo.
        inicio = ultima_data

        # Segurança: nunca volta mais que 30 dias no modo automático.
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
    chrome_options.add_argument("--disable-features=DownloadBubble")
    chrome_options.add_argument("--disable-features=DownloadBubbleV2")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-default-apps")

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
            arquivo = max(prontos, key=lambda p: p.stat().st_mtime)

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
    Download oficial do Agrosys via Selenium.
    Possui retry automático caso o Chrome deixe downloads.htm.crdownload
    ou outro .crdownload parado sem concluir o Excel.
    """
    MAX_TENTATIVAS = 2
    TIMEOUT_DOWNLOAD = 600
    LIMITE_CRDOWNLOAD_PARADO = 60

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        print("=" * 80, flush=True)
        print(f"Tentativa de download {tentativa}/{MAX_TENTATIVAS}", flush=True)

        limpar_downloads()

        print("Abrindo relatório pronto no Selenium...", flush=True)
        inicio_abertura = time.time()
        driver.get(url_relatorio)

        limite = time.time() + 90
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

            time.sleep(0.5)

        if not pronto:
            print("AVISO: fexcel() não ficou disponível.", flush=True)

            if tentativa < MAX_TENTATIVAS:
                print("Tentando abrir o relatório novamente...", flush=True)
                time.sleep(3)
                continue

            raise Exception(
                "A página abriu, mas a função fexcel() não ficou disponível."
            )

        print(
            f"fexcel() localizado em {time.time() - inicio_abertura:.1f}s. ",
            "Solicitando Excel oficial...",
            flush=True,
        )

        # Reforça a permissão de download no Chrome headless.
        try:
            driver.execute_cdp_cmd(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(PASTA_DOWNLOAD),
                    "eventsEnabled": True,
                },
            )
        except Exception:
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

        inicio_download = time.time()
        print("Executando fexcel()...", flush=True)
        driver.execute_script("fexcel();")
        print("fexcel() executado.", flush=True)
        print("Aguardando conclusão do Excel oficial...", flush=True)

        inicio_espera = time.time()
        ultimo_temporario = None
        ultimo_tamanho = None
        parado_desde = time.time()

        while time.time() - inicio_espera < TIMEOUT_DOWNLOAD:
            excels = []

            for mascara in ("*.xlsx", "*.xls"):
                for arquivo in PASTA_DOWNLOAD.glob(mascara):
                    try:
                        if not arquivo.is_file():
                            continue
                        if arquivo.stat().st_mtime < inicio_download - 1:
                            continue
                        if arquivo.stat().st_size <= 0:
                            continue
                        excels.append(arquivo)
                    except OSError:
                        pass

            if excels:
                arquivo = max(excels, key=lambda p: p.stat().st_mtime)

                try:
                    tamanho1 = arquivo.stat().st_size
                    time.sleep(2)
                    tamanho2 = arquivo.stat().st_size
                except OSError:
                    tamanho1 = 0
                    tamanho2 = 0

                if tamanho1 == tamanho2 and tamanho2 > 0:
                    print(
                        "Excel final detectado:",
                        arquivo.name,
                        "| tamanho:",
                        f"{tamanho2 / 1024 / 1024:.2f} MB",
                        flush=True,
                    )

                    arquivo_destino.parent.mkdir(parents=True, exist_ok=True)

                    if arquivo_destino.exists():
                        arquivo_destino.unlink()

                    shutil.move(str(arquivo), str(arquivo_destino))

                    if (
                        not arquivo_destino.exists()
                        or arquivo_destino.stat().st_size <= 0
                    ):
                        raise Exception(
                            "O Excel foi baixado, mas não foi salvo corretamente."
                        )

                    # Remove temporários que eventualmente tenham sobrado.
                    for temporario in PASTA_DOWNLOAD.glob("*.crdownload"):
                        try:
                            temporario.unlink()
                        except Exception:
                            pass

                    print(
                        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
                        arquivo_destino,
                        flush=True,
                    )

                    return arquivo_destino

            temporarios = [
                a for a in PASTA_DOWNLOAD.glob("*.crdownload") if a.is_file()
            ]

            if temporarios:
                temporario = max(temporarios, key=lambda p: p.stat().st_mtime)

                try:
                    tamanho = temporario.stat().st_size
                except OSError:
                    tamanho = None

                if temporario == ultimo_temporario and tamanho == ultimo_tamanho:
                    tempo_parado = time.time() - parado_desde

                    if tempo_parado >= LIMITE_CRDOWNLOAD_PARADO:
                        print(
                            f"AVISO: {temporario.name} ficou parado por mais de "
                            f"{LIMITE_CRDOWNLOAD_PARADO}s.",
                            flush=True,
                        )
                        break
                else:
                    ultimo_temporario = temporario
                    ultimo_tamanho = tamanho
                    parado_desde = time.time()

            time.sleep(1)

        presentes = [
            a.name for a in PASTA_DOWNLOAD.glob("*") if a.is_file()
        ]

        print("Download não concluiu nesta tentativa.", flush=True)
        print("Arquivos presentes:", presentes, flush=True)

        if tentativa < MAX_TENTATIVAS:
            print(
                "Limpando download incompleto e tentando novamente...",
                flush=True,
            )
            limpar_downloads()
            time.sleep(5)
            continue

    presentes = [
        a.name for a in PASTA_DOWNLOAD.glob("*") if a.is_file()
    ]

    raise Exception(
        "Não encontrei o arquivo baixado pelo Excel oficial "
        f"após {MAX_TENTATIVAS} tentativas. "
        f"Arquivos presentes: {presentes}"
    )


def ler_argumentos():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modo",
        choices=["auto", "dias"],
        default="auto",
        help="auto = lê última data da pasta; dias = usa quantidade fixa de dias.",
    )

    parser.add_argument(
        "--dias",
        type=int,
        default=None,
        help="Quantidade de dias para atualizar. Ex.: 1 hoje, 2 ontem+hoje, 7 últimos 7 dias.",
    )

    args = parser.parse_args()

    if args.dias is not None:
        args.modo = "dias"

    return args


def baixar_periodo(ag, driver, unidade, data_ini, data_fim):
    print("=" * 80)
    print(f"Controle de Frete - {unidade['descricao']}")
    print(f"Período: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}")
    print("=" * 80)

    filtros = {
        "vdt-ini": data_ini.strftime("%d/%m/%Y"),
        "vdt-fim": data_fim.strftime("%d/%m/%Y"),
        "vcar-codigo": "",
        "vredesp": "",
        "vtra-codigo": "",
        "vtra-nome": "",
        "vmot-codigo": "",
        "vmot-nome": "",
        "vcar-placa": "",
        "vrot-codigo": "",
        "vrot-nome": "",
        "vcheck": "",
        "vpad-btdisp.x": "Disparar",
    }

    html, processo = ag.executar_relatorio(
        caminho="/webpro/webci/wlg016d2",
        menu=23782,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"controle_frete_{unidade['nome_arquivo']}_{data_ini.strftime('%d-%m-%Y')}",
        modulo="23451",
    )

    url_relatorio = f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"

    arquivo_destino = (
        PASTA_SAIDA
        / f"controle_frete_{unidade['nome_arquivo']}_{data_ini.strftime('%d-%m-%Y')}_ate_{data_fim.strftime('%d-%m-%Y')}.xlsx"
    )

    baixar_excel_oficial(driver, url_relatorio, arquivo_destino)

    print("Processo:", processo)
    return arquivo_destino


def main():
    args = ler_argumentos()

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
            if args.modo == "dias":
                datas_para_atualizar = listar_datas_para_atualizar(
                    PASTA_SAIDA,
                    unidade["nome_arquivo"],
                    TERMO_RELATORIO,
                    modo="dias",
                    dias=args.dias,
                )
            else:
                datas_para_atualizar = listar_datas_para_atualizar(
                    PASTA_SAIDA,
                    unidade["nome_arquivo"],
                    TERMO_RELATORIO,
                    modo="auto",
                    dias=None,
                )

            print("=" * 80)
            print(f"{unidade['descricao']} - datas para atualizar: {len(datas_para_atualizar)}")
            print(f"Modo: {args.modo} | Dias: {args.dias if args.dias else 'AUTO'}")
            if datas_para_atualizar:
                print("De:", datas_para_atualizar[0].strftime("%d/%m/%Y"))
                print("Até:", datas_para_atualizar[-1].strftime("%d/%m/%Y"))
            print("=" * 80)

            if not datas_para_atualizar:
                print(f"{unidade['descricao']} não tem datas para atualizar.")
                continue

            for data_atual in datas_para_atualizar:
                try:
                    resultado = baixar_periodo(
                        ag=ag,
                        driver=driver,
                        unidade=unidade,
                        data_ini=data_atual,
                        data_fim=data_atual,
                    )

                    if resultado:
                        total_arquivos += 1
                    else:
                        total_erros += 1

                except Exception as e:
                    total_erros += 1
                    print("AVISO: falha ao baixar período.")
                    print("Unidade:", unidade["descricao"])
                    print("Período:", data_atual.strftime("%d/%m/%Y"))
                    print("Erro:", e)

        print("=" * 80)
        print("CONTROLE DE FRETE FINALIZADO")
        print("Arquivos gerados/atualizados:", total_arquivos)
        print("Erros/avisos:", total_erros)
        print("=" * 80)

        return 0

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
