# -*- coding: utf-8 -*-
"""
Índice Zootécnico - Movimento Mortalidade/Peso
Relatório: Movimento Mortalidade/Peso
Menu Agrosys: vmen-codigo=17136
Programa: wpf531d7

REGRAS:
- Relatório mensal.
- Pasta: Índice Zootécnico > Movimento MortalidadePeso > Lotes Aberto.
- Cada mês gera somente 1 arquivo.
- Meses anteriores: baixa do dia 01 até o último dia do mês.
- Mês atual: baixa do dia 01 até HOJE.
- O mês atual é sempre rebaixado e sobrescrito, sem duplicar.
- Quando o mês fecha, o mesmo arquivo mensal passa a conter 01 até o último dia.
- Retroativos faltantes são baixados mês a mês.
- Por padrão, o histórico começa em 01/01/2023.
- Para outro início, use --inicio DD/MM/AAAA.
- Usa login automático pelo config.py + AgrosysEngine.
- Selenium é usado apenas para baixar o Excel oficial via fexcel().
"""

import argparse
import calendar
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


PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Movimento MortalidadePeso\Lotes Aberto")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TERMO_RELATORIO = "movimento_mortalidade_peso"

# Este relatório pertence à Produção Avícola (unidade 052), conforme a captura.
UNIDADES = [
    {"codigo": "52", "nome_arquivo": "Producao_Avicola", "descricao": "052 - PRODUCAO AVICOLA"},
]

HOJE = datetime.now().date()
DATA_INICIO_HISTORICO = HOJE.replace(day=1)
DIAS_LOOKBACK = 30
MAX_TENTATIVAS_DIA = 3
ESPERA_ENTRE_TENTATIVAS = 10


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
        "--inicio",
        type=str,
        default=None,
        help="Data inicial no formato DD/MM/AAAA. Padrão: primeiro dia do mês atual.",
    )
    parser.add_argument(
        "--fim",
        type=str,
        default=None,
        help="Data final no formato DD/MM/AAAA. Padrão: hoje.",
    )
    parser.add_argument(
        "--forcar-todos",
        action="store_true",
        help="Rebaixa também os meses históricos que já existem.",
    )

    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    try:
        args.data_inicio = (
            datetime.strptime(args.inicio, "%d/%m/%Y").date()
            if args.inicio
            else DATA_INICIO_HISTORICO
        )
        args.data_fim = (
            datetime.strptime(args.fim, "%d/%m/%Y").date()
            if args.fim
            else HOJE
        )
    except ValueError:
        parser.error("As datas devem estar no formato DD/MM/AAAA.")

    if args.data_inicio > args.data_fim:
        parser.error("A data inicial não pode ser maior que a data final.")

    return args


def ultimo_dia_mes(data):
    return calendar.monthrange(data.year, data.month)[1]


def nome_arquivo_mensal(unidade, data_mes, data_fim=None):
    if data_fim is None:
        ultimo_dia = calendar.monthrange(data_mes.year, data_mes.month)[1]
        data_fim = data_mes.replace(day=ultimo_dia)

    return (
        PASTA_SAIDA
        / (
            f"Movimento_Mortalidade_Peso_Lotes_Abertos_"
            f"{data_mes:%d-%m-%Y}_{data_fim:%d-%m-%Y}.xlsx"
        )
    )


def meses_entre(data_inicio, data_fim):
    """Retorna o primeiro dia de cada mês entre início e fim."""
    atual = data_inicio.replace(day=1)
    ultimo = data_fim.replace(day=1)
    meses = []

    while atual <= ultimo:
        meses.append(atual)

        if atual.month == 12:
            atual = atual.replace(year=atual.year + 1, month=1, day=1)
        else:
            atual = atual.replace(month=atual.month + 1, day=1)

    return meses


def periodos_mensais_para_processar(args, unidade):
    """
    Regra mensal:
    - mês histórico: 01 até último dia do mês;
    - mês atual: 01 até hoje;
    - histórico já existente é pulado;
    - mês atual é SEMPRE rebaixado e sobrescrito;
    - --forcar-todos rebaixa todos os meses.
    """
    periodos = []

    for mes in meses_entre(args.data_inicio, args.data_fim):
        data_ini = mes.replace(day=1)

        ultimo_dia = ultimo_dia_mes(mes)
        fim_natural_mes = mes.replace(day=ultimo_dia)

        # Respeita a data final informada.
        data_fim = min(fim_natural_mes, args.data_fim)

        arquivo = nome_arquivo_mensal(unidade, data_ini, data_fim)

        eh_mes_atual = (
            mes.year == HOJE.year
            and mes.month == HOJE.month
        )

        # Mês atual sempre atualiza: 01 até hoje.
        if eh_mes_atual:
            data_fim = min(HOJE, args.data_fim)
            periodos.append((data_ini, data_fim, arquivo, "MES ATUAL - SOBRESCREVER"))
            continue

        # Retroativo: só baixa se ainda não existir,
        # a menos que --forcar-todos tenha sido informado.
        if arquivo.exists() and not args.forcar_todos:
            print(
                f"RETROATIVO JÁ EXISTE - pulando: {arquivo.name}",
                flush=True,
            )
            continue

        periodos.append((data_ini, data_fim, arquivo, "RETROATIVO"))

    return periodos


def montar_filtros(data_ini, data_fim):
    # Valores reproduzidos da tela/Payload enviado pelo usuário.
    # Checkboxes desmarcados são enviados vazios para não herdar estado da sessão.
    return {
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
        "vckpendente": "",
        "vcmaq": "",
        "vstd": "",
        "vcli-codigo": "",
        "vgpp-codigo": "",
        "vnuc-nucleo": "",
        "vid-mt-ini": "",
        "vid-mt-fim": "",
        "vlote-mat": "",
        "vmat-100": "",
        "vcompos": "",
        "vgrafico": "",
        "vacertados": "",
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


def baixar_periodo(ag, driver, unidade, data_ini, data_fim, arquivo_destino=None):
    print("=" * 80, flush=True)
    print(f"Índice Zootécnico - Movimento Mortalidade/Peso - {unidade['descricao']}", flush=True)
    print(f"Período: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}", flush=True)
    print("Filtros: Todos | Quantidade | Semanal | Taxa Peso Sim | Projetar Peso Não", flush=True)
    print("=" * 80, flush=True)

    filtros = montar_filtros(data_ini, data_fim)
    html, processo = ag.executar_relatorio(
        caminho="/webpro/webprod/wpf531d7",
        menu=17136,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"indice_zootecnico_movimento_mortalidade_peso_{data_ini:%d-%m-%Y}_ate_{data_fim:%d-%m-%Y}",
        modulo="17136",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )
    url_relatorio = f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"
    if arquivo_destino is None:
        arquivo_destino = nome_arquivo_mensal(unidade, data_ini, data_fim)
    baixar_excel_oficial(driver, url_relatorio, arquivo_destino)
    print("Processo:", processo, flush=True)
    return arquivo_destino


def main():
    args = ler_argumentos()

    print("=" * 80, flush=True)
    print("INICIANDO ÍNDICE ZOOTÉCNICO - MOVIMENTO MORTALIDADE/PESO", flush=True)
    print("MODO: MÊS ATUAL", flush=True)
    print("Menu 17136 | Programa wpf531d7 | Unidade 052 - PRODUCAO AVICOLA", flush=True)
    print(f"Histórico: {args.data_inicio:%d/%m/%Y} até {args.data_fim:%d/%m/%Y}", flush=True)
    print("Regra atual: baixa somente do dia 01 do mês atual até hoje e sobrescreve o mesmo arquivo mensal", flush=True)
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
            periodos = periodos_mensais_para_processar(args, unidade)

            print(
                f"{unidade['descricao']} | meses que serão baixados: {len(periodos)}",
                flush=True,
            )

            for data_ini, data_fim, arquivo_destino, tipo in periodos:
                sucesso = False
                ultimo_erro = None

                print("-" * 80, flush=True)
                print(
                    f"{tipo}: {data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
                    flush=True,
                )
                print(f"Arquivo: {arquivo_destino.name}", flush=True)

                for tentativa in range(1, MAX_TENTATIVAS_DIA + 1):
                    try:
                        resultado = baixar_periodo(
                            ag,
                            driver,
                            unidade,
                            data_ini,
                            data_fim,
                            arquivo_destino=arquivo_destino,
                        )

                        arq = Path(resultado)

                        if not arq.exists() or arq.stat().st_size < 1024:
                            raise RuntimeError(
                                f"Arquivo ausente ou suspeito: {arq}"
                            )

                        print(
                            f"OK: {arq.name} | {arq.stat().st_size} bytes",
                            flush=True,
                        )

                        total_arquivos += 1
                        sucesso = True
                        break

                    except Exception as e:
                        ultimo_erro = e

                        print(
                            f"AVISO tentativa {tentativa}/{MAX_TENTATIVAS_DIA}: {e!r}",
                            flush=True,
                        )

                        try:
                            driver.quit()
                        except Exception:
                            pass

                        if tentativa < MAX_TENTATIVAS_DIA:
                            time.sleep(ESPERA_ENTRE_TENTATIVAS)
                            driver = criar_driver()
                            copiar_cookies_para_selenium(driver, ag)

                if not sucesso:
                    total_erros += 1
                    print(
                        f"FALHA DEFINITIVA NO MÊS {data_ini:%m/%Y}: {ultimo_erro!r}",
                        flush=True,
                    )

        print("=" * 80, flush=True)
        print(
            "FINALIZADO | Arquivos atualizados:",
            total_arquivos,
            "| Erros:",
            total_erros,
            flush=True,
        )
        print("=" * 80, flush=True)

        # Se não havia retroativo faltante, isso não é erro:
        # o mês atual normalmente será sempre processado.
        return 0 if total_erros == 0 else 1

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
