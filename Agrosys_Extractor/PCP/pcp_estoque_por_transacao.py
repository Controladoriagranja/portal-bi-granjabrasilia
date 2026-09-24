# -*- coding: utf-8 -*-
"""
PCP - Estoque por Transação
Relatório: Estoque por Transação
Menu Agrosys: vmen-codigo=18289
Programa: wci077d1

REGRAS:
- Padrão igual aos robôs da Logística e PCP já validados.
- Usa login automático pelo config.py + AgrosysEngine.
- Usa Selenium apenas para baixar o Excel oficial via fexcel().
- Atualiza somente:
    010 - AVE NOVA
    111 - REAL ALIMENTOS
- Mesmo conceito da Devolução:
    Lê a pasta, identifica a última data por unidade/local e baixa da última data encontrada até hoje.
- Reprocessa a última data encontrada para pegar fechamento completo.
- Mantém histórico.
- Sobrescreve somente se o arquivo do mesmo período/local já existir.
- Para Ave Nova roda todos os locais 110, 141 até 151.
- Para Real Alimentos roda todos os locais 111, 121 até 132.
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


PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\PCP\Estoque por Transacao")
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

HOJE = datetime.now().date()
DIAS_LOOKBACK = 30
DIAS_VERIFICACAO_FALTANTES = 20

UNIDADES = [
    {
        "codigo": "10",
        "nome_arquivo": "Avenova",
        "descricao": "010 - AVE NOVA",
        "locais": [
            {"codigo": "110", "nome": "110 - Camara Produto Acabado"},
            {"codigo": "141", "nome": "141-01 - Tunel Congelamento Ave Nova"},
            {"codigo": "142", "nome": "142-02 - Tunel Congelamento Ave Nova"},
            {"codigo": "143", "nome": "143-03 - Tunel Congelamento Ave Nova"},
            {"codigo": "144", "nome": "144-04 - Tunel Congelamento Ave Nova"},
            {"codigo": "145", "nome": "145-05 - Tunel Congelamento Ave Nova"},
            {"codigo": "146", "nome": "146-06 - Tunel Congelamento Ave Nova"},
            {"codigo": "147", "nome": "147-07 - Tunel Congelamento Ave Nova"},
            {"codigo": "148", "nome": "148-08 - Tunel Congelamento Ave Nova"},
            {"codigo": "149", "nome": "149-09 - Tunel Congelamento Ave Nova"},
            {"codigo": "150", "nome": "150-10 - Tunel Congelamento Ave Nova"},
            {"codigo": "151", "nome": "151-11 - Tunel Congelamento Ave Nova"},
        ],
    },
    {
        "codigo": "111",
        "nome_arquivo": "Real",
        "descricao": "111 - REAL ALIMENTOS",
        "locais": [
            {"codigo": "111", "nome": "111 - Estocagem Prod Acabado Real Alimentos"},
            {"codigo": "121", "nome": "121-01 - Tunel Congelamento Real"},
            {"codigo": "122", "nome": "122-02 - Tunel Congelamento Real"},
            {"codigo": "123", "nome": "123-03 - Tunel Congelamento Real"},
            {"codigo": "124", "nome": "124-04 - Tunel Congelamento Real"},
            {"codigo": "125", "nome": "125-05 - Tunel Congelamento Real"},
            {"codigo": "126", "nome": "126-06 - Tunel Congelamento Real"},
            {"codigo": "127", "nome": "127-07 - Tunel Congelamento Real"},
            {"codigo": "128", "nome": "128-08 - Tunel Congelamento Real"},
            {"codigo": "129", "nome": "129-09 - Tunel Congelamento Real"},
            {"codigo": "130", "nome": "130-10 - Tunel Congelamento Real"},
            {"codigo": "131", "nome": "131-11 - Tunel Congelamento Real"},
            {"codigo": "132", "nome": "132-12 - Tunel Congelamento Real"},
        ],
    },
]


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


def nome_arquivo_seguro(txt: str):
    txt = str(txt)
    trocas = {
        "Á": "A", "À": "A", "Â": "A", "Ã": "A",
        "á": "a", "à": "a", "â": "a", "ã": "a",
        "É": "E", "Ê": "E", "é": "e", "ê": "e",
        "Í": "I", "í": "i",
        "Ó": "O", "Ô": "O", "Õ": "O", "ó": "o", "ô": "o", "õ": "o",
        "Ú": "U", "ú": "u",
        "Ç": "C", "ç": "c",
        "º": "", "ª": "",
    }
    for a, b in trocas.items():
        txt = txt.replace(a, b)

    txt = re.sub(r'[\\/:*?"<>|]', " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


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


def arquivos_do_local(pasta_saida: Path, local_nome: str, unidade_nome: str):
    local_key = normalizar_nome(local_nome)
    unidade_key = normalizar_nome(unidade_nome)

    arquivos = []

    for arq in pasta_saida.glob("*.xls*"):
        nome_key = normalizar_nome(arq.name)

        if local_key not in nome_key:
            continue

        # Alguns arquivos antigos não tinham "Avenova" no nome do local 110.
        # Para não perder histórico, o local principal 110/111 usa só o local.
        if unidade_key not in nome_key and not local_nome.strip().startswith(("110", "111")):
            continue

        periodo = extrair_periodo_arquivo(arq.name)
        if not periodo:
            continue

        arquivos.append((arq, periodo))

    return arquivos


def listar_datas_para_atualizar(pasta_saida: Path, local_nome: str, unidade_nome: str, dias=None):
    """
    Regras de atualização:
    - Se --dias for informado, baixa os últimos X dias.
    - No modo automático, verifica dia a dia os últimos
      DIAS_VERIFICACAO_FALTANTES dias.
    - Se um arquivo diário tiver sido apagado dentro dessa janela,
      a data é reconhecida como faltante e baixada novamente.
    - Reprocessa também a última data existente e o dia de hoje,
      para garantir fechamento e atualização corrente.
    """
    if dias is not None:
        dias = max(int(dias), 1)
        inicio = HOJE - timedelta(days=dias - 1)
        return [
            inicio + timedelta(days=i)
            for i in range((HOJE - inicio).days + 1)
        ]

    arquivos = arquivos_do_local(pasta_saida, local_nome, unidade_nome)

    # Sem histórico: baixa a janela inicial padrão.
    if not arquivos:
        inicio = HOJE - timedelta(days=DIAS_LOOKBACK - 1)
        return [
            inicio + timedelta(days=i)
            for i in range((HOJE - inicio).days + 1)
        ]

    inicio_janela = HOJE - timedelta(days=DIAS_VERIFICACAO_FALTANTES - 1)

    # Monta todas as datas já cobertas pelos arquivos do local.
    datas_cobertas = set()
    datas_fim = []

    for _, (data_ini, data_fim) in arquivos:
        datas_fim.append(data_fim)

        inicio_periodo = max(data_ini, inicio_janela)
        fim_periodo = min(data_fim, HOJE)

        if inicio_periodo > fim_periodo:
            continue

        data = inicio_periodo
        while data <= fim_periodo:
            datas_cobertas.add(data)
            data += timedelta(days=1)

    # Descobre qualquer buraco nos últimos 20 dias.
    datas_faltantes = []
    data = inicio_janela
    while data <= HOJE:
        if data not in datas_cobertas:
            datas_faltantes.append(data)
        data += timedelta(days=1)

    # Mantém o comportamento de reprocessar o último dia encontrado
    # e também o dia atual.
    ultima_data = max(datas_fim) if datas_fim else None

    datas_atualizar = set(datas_faltantes)
    datas_atualizar.add(HOJE)

    if ultima_data and inicio_janela <= ultima_data <= HOJE:
        datas_atualizar.add(ultima_data)

    return sorted(datas_atualizar)


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


def baixar_periodo_local(ag, driver, unidade, local, data_ini, data_fim):
    print("=" * 80, flush=True)
    print(f"PCP Estoque por Transação - {unidade['descricao']}", flush=True)
    print(f"Local: {local['nome']}", flush=True)
    print(f"Período: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}", flush=True)
    print("=" * 80, flush=True)

    filtros = {
        "vparint1": str(local["codigo"]).rjust(8),
        "vparint3": "",
        "vpardate1": data_ini.strftime("%d/%m/%Y"),
        "vpardate2": data_fim.strftime("%d/%m/%Y"),
        "vtransacao": "",
        "vturno": "0",
        "vpad-btdisp.x": "Disparar",
    }

    html, processo = ag.executar_relatorio(
        caminho="/webpro/webci/wci077d1",
        menu=18289,
        unidade=unidade["codigo"],
        filtros=filtros,
        nome_debug=f"pcp_estoque_transacao_{unidade['nome_arquivo']}_{local['codigo']}_{data_ini.strftime('%d-%m-%Y')}",
        modulo="17611",
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )

    url_relatorio = f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"

    local_nome = nome_arquivo_seguro(local["nome"])

    arquivo_destino = (
        PASTA_SAIDA
        / f"{local_nome}_{unidade['nome_arquivo']}_{data_ini.strftime('%d-%m-%Y')}_ate_{data_fim.strftime('%d-%m-%Y')}.xlsx"
    )

    baixar_excel_oficial(driver, url_relatorio, arquivo_destino)

    print("Processo:", processo, flush=True)
    return arquivo_destino


def main():
    args = ler_argumentos()

    print("=" * 80, flush=True)
    print("INICIANDO PCP - ESTOQUE POR TRANSAÇÃO", flush=True)
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
            for local in unidade["locais"]:
                if args.modo == "periodo":
                    datas = []
                    data = args.data_inicio
                    while data <= args.data_fim:
                        datas.append(data)
                        data += timedelta(days=1)
                else:
                    datas = listar_datas_para_atualizar(
                        PASTA_SAIDA,
                        local["nome"],
                        unidade["nome_arquivo"],
                        dias=args.dias if args.modo == "dias" else None,
                    )

                print("=" * 80, flush=True)
                print(
                    f"{unidade['descricao']} | {local['nome']} - dias: {len(datas)}",
                    flush=True,
                )
                print("=" * 80, flush=True)

                for data_ref in datas:
                    try:
                        resultado = baixar_periodo_local(
                            ag=ag,
                            driver=driver,
                            unidade=unidade,
                            local=local,
                            data_ini=data_ref,
                            data_fim=data_ref,
                        )
                        total_arquivos += 1 if resultado else 0
                        total_erros += 0 if resultado else 1
                    except Exception as e:
                        total_erros += 1
                        print("AVISO: falha ao baixar dia/local.", flush=True)
                        print("Unidade:", unidade["descricao"], flush=True)
                        print("Local:", local["nome"], flush=True)
                        print("Data:", data_ref.strftime("%d/%m/%Y"), flush=True)
                        print("Erro:", e, flush=True)

        print("=" * 80, flush=True)
        print("PCP ESTOQUE POR TRANSAÇÃO FINALIZADO", flush=True)
        print("Arquivos gerados/atualizados:", total_arquivos, flush=True)
        print("Erros/avisos:", total_erros, flush=True)
        print("=" * 80, flush=True)
        return 0 if total_erros == 0 else 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
