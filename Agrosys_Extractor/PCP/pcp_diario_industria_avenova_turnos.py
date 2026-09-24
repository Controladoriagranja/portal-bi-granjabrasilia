# -*- coding: utf-8 -*-
"""
PCP - Diário da Indústria - AVE NOVA POR TURNO
Relatório: Diário da Industria
Menu Agrosys: vmen-codigo=18197
Programa: wcf049d1

REGRAS:
- Novo robô exclusivo para 010 - AVE NOVA.
- Baixa o Diário da Indústria separado por Turno 1 e Turno 2.
- Mantém os demais filtros iguais ao robô atual.
- Usa login automático pelo config.py + AgrosysEngine.
- Usa Selenium apenas para baixar o Excel oficial via fexcel().
- O relatório é mensal/acumulado: a DATA define do dia 1 até a data de referência.
- Gera dois arquivos por mês:
    diario_industria_Avenova_turno1_MM-AAAA.xlsx
    diario_industria_Avenova_turno2_MM-AAAA.xlsx
- Se rodar várias vezes no mesmo mês, sobrescreve os arquivos do mês.
"""

import argparse
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


PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Diario Industria\AveNova Turno")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

DATA_ATUAL = datetime.now().date()
DATA_RELATORIO = DATA_ATUAL.strftime("%d/%m/%Y")
MES_ANO = DATA_ATUAL.strftime("%m-%Y")

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

def datas_mensais_para_processar(data_inicio, data_fim):
    """
    Retorna UMA data de referência por mês.

    Regra do Diário da Indústria:
    - o relatório é mensal/acumulado;
    - meses já encerrados usam sempre o último dia do mês;
    - o mês atual usa a última data solicitada, limitada a hoje.
    """
    hoje = datetime.now().date()
    datas = []

    atual = data_inicio.replace(day=1)
    mes_final = data_fim.replace(day=1)

    while atual <= mes_final:
        if atual.month == 12:
            proximo_mes = atual.replace(year=atual.year + 1, month=1, day=1)
        else:
            proximo_mes = atual.replace(month=atual.month + 1, day=1)

        ultimo_dia_mes = proximo_mes - timedelta(days=1)

        if atual.year == hoje.year and atual.month == hoje.month:
            data_relatorio = min(data_fim, hoje)
        else:
            data_relatorio = ultimo_dia_mes

        datas.append(data_relatorio)
        atual = proximo_mes

    return datas


def datas_automaticas_para_processar():
    """
    Execução automática:
    - normalmente baixa somente o mês atual acumulado até hoje;
    - no dia 1º também rebaixa o mês anterior completo.
    """
    hoje = datetime.now().date()
    datas = []

    if hoje.day == 1:
        primeiro_dia_mes_atual = hoje.replace(day=1)
        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
        datas.append(ultimo_dia_mes_anterior)

    datas.append(hoje)
    return datas

UNIDADES = [
    {"codigo": "10", "nome_arquivo": "Avenova", "descricao": "010 - AVE NOVA"},
]

TURNOS = [
    {"valor": "1", "nome_arquivo": "turno1", "descricao": "Turno 1"},
    {"valor": "2", "nome_arquivo": "turno2", "descricao": "Turno 2"},
]


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


def montar_filtros(data_relatorio, turno):
    """
    Payload conforme captura do DevTools.
    Alteramos somente vpardate1 para a data atual.
    """
    return {
        "vparint5": "",          # Árvore Hierárquica: Nenhuma
        "vparint6": "",          # Planilha: Todas
        "vpardate1": data_relatorio.strftime("%d/%m/%Y"),
        "vparint7": turno["valor"],  # Turno 1 ou Turno 2
        "vparint1": "1",         # Opção: Por Peso
        "vparlog1": "yes",       # Inclui Gráfico: Sim
        "vparlog2": "yes",       # Abre por Produto: Sim
        "vparlog3": "yes",       # Mostrar Percentual de Produção: Sim
        "vparint8": "",          # Rendimento por: Todas
        "vparint10": "",         # Grupo Produção: Nenhuma
        "vpad-btdisp.x": "Disparar",
    }


def baixar_unidade(ag, driver, unidade, data_relatorio, turno):
    print("=" * 80, flush=True)
    print(f"Diário da Indústria - {unidade['descricao']}", flush=True)
    print(f"Data do relatório: {data_relatorio.strftime('%d/%m/%Y')}", flush=True)
    print(f"Turno: {turno['descricao']}", flush=True)
    print(f"Arquivo mensal: {data_relatorio.strftime('%m-%Y')}", flush=True)
    print("=" * 80, flush=True)

    filtros = montar_filtros(data_relatorio, turno)

    html, processo = ag.executar_relatorio(
        caminho="/webpro/webci/wcf049d1",
        menu=18197,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"pcp_diario_industria_{unidade['nome_arquivo']}_{turno['nome_arquivo']}_{data_relatorio.strftime('%m-%Y')}",
        modulo="17611",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )

    url_relatorio = f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"

    arquivo_destino = (
        PASTA_SAIDA
        / f"diario_industria_{unidade['nome_arquivo']}_{turno['nome_arquivo']}_{data_relatorio.strftime('%m-%Y')}.xlsx"
    )

    baixar_excel_oficial(driver, url_relatorio, arquivo_destino)

    print("Processo:", processo, flush=True)
    return arquivo_destino


def main():
    args = ler_argumentos()

    if args.modo == "periodo":
        datas_relatorio = datas_mensais_para_processar(
            args.data_inicio,
            args.data_fim,
        )

    elif args.modo == "dias":
        quantidade = max(int(args.dias or 1), 1)
        hoje = datetime.now().date()
        data_inicio = hoje - timedelta(days=quantidade - 1)

        datas_relatorio = datas_mensais_para_processar(
            data_inicio,
            hoje,
        )

        if hoje.day == 1:
            ultimo_dia_mes_anterior = hoje.replace(day=1) - timedelta(days=1)
            if ultimo_dia_mes_anterior not in datas_relatorio:
                datas_relatorio.insert(0, ultimo_dia_mes_anterior)

    else:
        datas_relatorio = datas_automaticas_para_processar()

    datas_relatorio = list(dict.fromkeys(datas_relatorio))

    print("=" * 80, flush=True)
    print("INICIANDO PCP - DIÁRIO DA INDÚSTRIA - AVE NOVA POR TURNO", flush=True)
    print("Empresa: AVE NOVA", flush=True)
    print("Turnos: TURNO 1 e TURNO 2", flush=True)
    print("Atualização MENSAL / ACUMULADA", flush=True)
    print("Quantidade de mês(es):", len(datas_relatorio), flush=True)

    if datas_relatorio:
        print(
            "Datas de referência:",
            ", ".join(d.strftime("%d/%m/%Y") for d in datas_relatorio),
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

    total_arquivos = 0
    total_erros = 0

    try:
        copiar_cookies_para_selenium(driver, ag)

        for data_relatorio in datas_relatorio:
            for unidade in UNIDADES:
                for turno in TURNOS:
                    try:
                        resultado = baixar_unidade(
                            ag=ag,
                            driver=driver,
                            unidade=unidade,
                            data_relatorio=data_relatorio,
                            turno=turno,
                        )
                        total_arquivos += 1 if resultado else 0
                        total_erros += 0 if resultado else 1
                    except Exception as e:
                        total_erros += 1
                        print("AVISO: falha ao baixar unidade/mês/turno.", flush=True)
                        print("Unidade:", unidade["descricao"], flush=True)
                        print("Turno:", turno["descricao"], flush=True)
                        print("Data:", data_relatorio.strftime("%d/%m/%Y"), flush=True)
                        print("Erro:", e, flush=True)

        print("=" * 80, flush=True)
        print("PCP DIÁRIO DA INDÚSTRIA - AVE NOVA POR TURNO FINALIZADO", flush=True)
        print("Arquivos gerados/atualizados:", total_arquivos, flush=True)
        print("Erros/avisos:", total_erros, flush=True)
        print("=" * 80, flush=True)
        return 0 if total_erros == 0 else 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
