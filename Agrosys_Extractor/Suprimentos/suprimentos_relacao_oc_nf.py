import argparse
import re
import sys
import time
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

NOME_RELATORIO = "Relação da data emissão entre OC X NF"

CAMINHO_RELATORIO = "/webpro/websup/wsu061d12"
MENU = 29110
MODULO = "27932"
UNIDADE_AGROSYS = "1"

# Caminhos UNC: não dependem do mapeamento da unidade X: no usuário
# que estiver executando o Portal BI / serviço Python.
RAIZ_REDE_BI = Path(r"\\192.168.1.139\Controladoria\BI_Granja")

PASTA_SAIDA = (
    RAIZ_REDE_BI
    / "Exportacoes"
    / "Suprimentos"
    / "Relacao OC x NF"
)

from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TIMEOUT_DOWNLOAD = 300


# =============================================================================
# DATAS
# =============================================================================

def parse_data_br(texto):
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {texto}. Use DD/MM/AAAA."
        ) from erro


def listar_dias(data_ini, data_fim):
    atual = data_ini

    while atual <= data_fim:
        yield atual
        atual += timedelta(days=1)


def ultima_data_na_pasta():
    """
    Reconhece automaticamente os arquivos já existentes:

      relacao_oc_nf_DD-MM-AAAA_ate_DD-MM-AAAA.xlsx

    Exemplos reconhecidos:
      relacao_oc_nf_01-01-2026_ate_31-01-2026.xlsx
      relacao_oc_nf_01-08-2026_ate_01-08-2026.xlsx
      relacao_oc_nf_14-08-2026_ate_14-08-2026.xlsx

    IMPORTANTE:
    - usa sempre a DATA FINAL do arquivo;
    - por isso um arquivo mensal manual também é reconhecido;
    - pega a maior data final encontrada na pasta.
    """
    padrao = re.compile(
        r"^relacao_oc_nf_"
        r"(\d{2}-\d{2}-20\d{2})_ate_"
        r"(\d{2}-\d{2}-20\d{2})\.(xlsx|xls|html)$",
        re.IGNORECASE,
    )

    hoje = date.today()
    datas = []

    for arquivo in PASTA_SAIDA.glob("relacao_oc_nf_*"):
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

        # Ignora qualquer arquivo futuro por segurança.
        if data_final <= hoje:
            datas.append(data_final)

    return max(datas) if datas else None


def listar_periodos_automaticos():
    """
    Lógica automática baseada na pasta:

    1. Lê todos os arquivos existentes.
    2. Encontra a maior DATA FINAL.
    3. Rebaixa essa última data.
    4. Continua dia a dia até HOJE.

    Exemplo:
      maior arquivo = relacao_oc_nf_14-08-2026_ate_14-08-2026.xlsx
      hoje          = 17/08/2026

    O robô fará:
      14/08/2026
      15/08/2026
      16/08/2026
      17/08/2026

    Se existir arquivo mensal manual:
      relacao_oc_nf_01-07-2026_ate_31-07-2026.xlsx

    ele entende que já existe histórico até 31/07/2026.

    Se a pasta estiver vazia:
      baixa ontem e hoje.
    """
    hoje = date.today()
    ultima = ultima_data_na_pasta()

    if ultima is None:
        inicio = hoje - timedelta(days=1)

        print(
            "Nenhum arquivo anterior reconhecido. "
            "Fallback: ONTEM + HOJE.",
            flush=True,
        )

    else:
        inicio = ultima

        print(
            f"Última data reconhecida na pasta: {ultima:%d/%m/%Y}",
            flush=True,
        )

        if ultima == hoje:
            print(
                "A pasta já está atualizada até hoje. "
                "O dia de hoje será rebaixado para atualizar possíveis alterações.",
                flush=True,
            )
        else:
            print(
                f"Rebaixando {ultima:%d/%m/%Y} e seguindo "
                f"dia a dia até {hoje:%d/%m/%Y}.",
                flush=True,
            )

    return [
        (dia, dia)
        for dia in listar_dias(inicio, hoje)
    ]


# =============================================================================
# SELENIUM / EXCEL OFICIAL
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
    for arq in PASTA_DOWNLOAD.glob("*"):
        try:
            if arq.is_file():
                arq.unlink()
            elif arq.is_dir():
                shutil.rmtree(arq)
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

            # ~3 segundos sem alteração no tamanho.
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
    Download oficial do Agrosys via Selenium, no mesmo padrão do Contas a Pagar.
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

    inicio_confirmacao = time.time()
    download_iniciado = False

    while time.time() - inicio_confirmacao < 8:
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
                elementos = driver.find_elements(
                    "css selector",
                    seletor,
                )

                for elemento in elementos:
                    try:
                        if (
                            elemento.is_displayed()
                            and elemento.is_enabled()
                        ):
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
                        if (
                            elemento.is_displayed()
                            and elemento.is_enabled()
                        ):
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

        try:
            titulo_pagina = driver.title
        except Exception:
            titulo_pagina = ""

        raise Exception(
            "Não encontrei o arquivo baixado pelo Excel oficial. "
            f"Arquivos presentes: {presentes} | "
            f"Título da página: {titulo_pagina}"
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
            "O Excel foi baixado, mas não foi salvo corretamente na pasta final."
        )

    print(
        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
        arquivo_destino,
        flush=True,
    )


# =============================================================================
# FILTROS - EXATAMENTE COMO O POST MANUAL DO HAR
# =============================================================================

def montar_filtros(data_ini, data_fim, comprador="T"):
    """
    POST manual confirmado no DevTools/HAR:

    vpardate1=14/08/2026
    vpardate2=14/08/2026
    vuni-unidade=
    vuni-nome=
    vfor-codigo=
    vcli-fantasi=
    vusuario=T
    vpad-btdisp.x=Disparar
    """

    return {
        "vpardate1": data_ini.strftime("%d/%m/%Y"),
        "vpardate2": data_fim.strftime("%d/%m/%Y"),
        "vuni-unidade": "",
        "vuni-nome": "",
        "vfor-codigo": "",
        "vcli-fantasi": "",
        "vusuario": comprador,
        "vpad-btdisp.x": "Disparar",
    }


# =============================================================================
# EXECUÇÃO
# =============================================================================

def nome_arquivo(data_ini, data_fim):
    return (
        "relacao_oc_nf_"
        f"{data_ini:%d-%m-%Y}_ate_{data_fim:%d-%m-%Y}.xlsx"
    )


def baixar_periodo(ag, driver, data_ini, data_fim, comprador="T"):
    print("=" * 80, flush=True)
    print(NOME_RELATORIO, flush=True)
    print(
        f"Período: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
        flush=True,
    )
    print(
        f"Comprador: {'TODOS' if comprador == 'T' else comprador}",
        flush=True,
    )
    print("=" * 80, flush=True)

    filtros = montar_filtros(
        data_ini=data_ini,
        data_fim=data_fim,
        comprador=comprador,
    )

    print("Filtros enviados:", flush=True)
    for chave, valor in filtros.items():
        print(f"  {chave} = {valor}", flush=True)

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
        unidade=UNIDADE_AGROSYS,
        filtros=filtros,
        nome_debug=(
            f"relacao_oc_nf_"
            f"{data_ini:%Y%m%d}_{data_fim:%Y%m%d}"
        ),
        modulo=MODULO,
    )

    if not processo:
        raise Exception(
            "O Agrosys não retornou número do processo."
        )

    print("Processo:", processo, flush=True)

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    print("URL do relatório:", url_relatorio, flush=True)

    destino = PASTA_SAIDA / nome_arquivo(data_ini, data_fim)

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=destino,
    )

    return destino


# =============================================================================
# ARGUMENTOS
# =============================================================================

def ler_argumentos():
    parser = argparse.ArgumentParser(
        description="Robô Suprimentos - Relação OC x NF"
    )

    parser.add_argument(
        "--inicio",
        type=parse_data_br,
        help="Data inicial DD/MM/AAAA",
    )

    parser.add_argument(
        "--fim",
        type=parse_data_br,
        help="Data final DD/MM/AAAA",
    )

    parser.add_argument(
        "--comprador",
        default="T",
        help=(
            "Usuário do comprador no Agrosys. "
            "Padrão T = todos."
        ),
    )

    parser.add_argument(
        "--somente-hoje",
        action="store_true",
        help="No automático, baixa somente hoje.",
    )

    return parser.parse_args()


def montar_periodos(args):
    hoje = date.today()

    if args.inicio or args.fim:
        if args.inicio is None or args.fim is None:
            raise ValueError(
                "Se usar período manual, informe --inicio e --fim."
            )

        if args.inicio > args.fim:
            raise ValueError(
                "A data inicial não pode ser maior que a data final."
            )

        return [(args.inicio, args.fim)]

    if args.somente_hoje:
        return [(hoje, hoje)]

    return listar_periodos_automaticos()


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = ler_argumentos()
    periodos = montar_periodos(args)

    print("=" * 80, flush=True)
    print("ROBÔ SUPRIMENTOS - RELAÇÃO OC X NF", flush=True)
    print(
        f"Caminho: {CAMINHO_RELATORIO} | Menu: {MENU} | Módulo: {MODULO}",
        flush=True,
    )
    print("=" * 80, flush=True)

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    print("Fazendo login no Agrosys...", flush=True)
    ag.login()

    driver = criar_driver()

    ok = 0
    erros = 0

    try:
        copiar_cookies_para_selenium(driver, ag)

        for data_ini, data_fim in periodos:
            try:
                baixar_periodo(
                    ag=ag,
                    driver=driver,
                    data_ini=data_ini,
                    data_fim=data_fim,
                    comprador=args.comprador,
                )
                ok += 1

            except Exception as erro:
                erros += 1
                print(
                    f"ERRO no período "
                    f"{data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}: "
                    f"{erro}",
                    flush=True,
                )

    finally:
        try:
            driver.quit()
        except Exception:
            pass

        try:
            ag.session.close()
        except Exception:
            pass

    print("=" * 80, flush=True)
    print(f"Arquivos OK: {ok}", flush=True)
    print(f"Erros: {erros}", flush=True)
    print(f"Pasta de saída: {PASTA_SAIDA}", flush=True)
    print("=" * 80, flush=True)

    return 0 if erros == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
