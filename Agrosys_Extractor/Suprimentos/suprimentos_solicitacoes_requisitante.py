# -*- coding: utf-8 -*-
import argparse
import re
import sys
import time
import shutil
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
# CONFIGURAÇÕES DO RELATÓRIO
# =============================================================================

NOME_RELATORIO = "Solicitações por Requisitante"
CAMINHO_RELATORIO = "/webpro/websup/wsu050d6"
MENU = 29062
MODULO = "27932"

# Mantemos empresa/unidade do contexto do Agrosys em 1.
# Dentro do próprio relatório os filtros "Empresa" e "Unid" ficam em "Todas".
UNIDADE_ENGINE = "1"

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Solicitacoes por Requisitante"
)
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

# Tempo de espera para o Agrosys concluir a geração do relatório.
# O processo real testado levou pouco mais de 9 minutos, então deixamos 15 min.
TEMPO_MINIMO_ANTES_DESCARTAR_404 = 900  # 15 minutos
MAX_404_CONSECUTIVOS = 3

# Tempo máximo para o Excel aparecer após o relatório já estar pronto.
TIMEOUT_DOWNLOAD = 900  # 15 minutos


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def data_br(valor):
    """Converte YYYY-MM-DD ou DD/MM/YYYY para DD/MM/YYYY."""
    valor = str(valor).strip()

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor, formato).strftime("%d/%m/%Y")
        except ValueError:
            pass

    raise argparse.ArgumentTypeError(
        f"Data inválida: {valor}. Use YYYY-MM-DD ou DD/MM/YYYY."
    )


def data_nome_arquivo(valor_br):
    return datetime.strptime(valor_br, "%d/%m/%Y").strftime("%Y-%m-%d")



def extrair_periodo_nome(nome):
    """
    Reconhece os padrões que já existem na pasta:
      solicitacoes_requisitante_2026-08-17.xlsx
      solicitacoes_requisitante_14-08-2026_ate_14-08-2026.xlsx
      solicitacoes_requisitante_01-07-2026_ate_31-07-2026.xlsx
      solicitacoes_requisitante_2026-08-01_ate_2026-08-10.xlsx

    Retorna (data_inicial, data_final) ou None.
    """
    nome = Path(nome).name

    padroes = [
        re.compile(
            r"^solicitacoes_requisitante_(\d{4}-\d{2}-\d{2})"
            r"(?:_ate_(\d{4}-\d{2}-\d{2}))?\.(?:xlsx|xls|html)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^solicitacoes_requisitante_(\d{2}-\d{2}-\d{4})"
            r"(?:_ate_(\d{2}-\d{2}-\d{4}))?\.(?:xlsx|xls|html)$",
            re.IGNORECASE,
        ),
    ]

    for i, padrao in enumerate(padroes):
        m = padrao.match(nome)
        if not m:
            continue

        formato = "%Y-%m-%d" if i == 0 else "%d-%m-%Y"
        inicio = datetime.strptime(m.group(1), formato).date()
        fim = (
            datetime.strptime(m.group(2), formato).date()
            if m.group(2)
            else inicio
        )
        return inicio, fim

    return None


def ultima_data_na_pasta():
    """
    Lê a pasta de saída e usa a maior DATA FINAL encontrada.
    Assim reconhece tanto os arquivos antigos mensais quanto os diários.
    """
    hoje = date.today()
    datas = []

    for arquivo in PASTA_SAIDA.glob("solicitacoes_requisitante_*"):
        periodo = extrair_periodo_nome(arquivo.name)
        if not periodo:
            continue

        _, data_final = periodo
        if data_final <= hoje:
            datas.append(data_final)

    return max(datas) if datas else None


def listar_periodos_automaticos():
    """
    Rebaixa a última data reconhecida e segue dia a dia até hoje.
    Não pula sábado nem domingo.

    Exemplo:
      última data = 17/08/2026
      hoje        = 24/08/2026

    Baixa:
      17, 18, 19, 20, 21, 22, 23 e 24/08/2026.
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
                "A pasta já chega até hoje. "
                "O dia de hoje será rebaixado para atualizar possíveis alterações.",
                flush=True,
            )
        else:
            print(
                f"Rebaixando {ultima:%d/%m/%Y} e seguindo "
                f"dia a dia até {hoje:%d/%m/%Y}.",
                flush=True,
            )

    periodos = []
    atual = inicio

    while atual <= hoje:
        periodos.append((atual, atual))
        atual += timedelta(days=1)

    return periodos



def dividir_periodo_por_mes(inicio, fim):
    """
    Divide um período personalizado em blocos mensais.

    Exemplo:
      01/01/2026 até 27/08/2026

    Retorna:
      01/01/2026 até 31/01/2026
      01/02/2026 até 28/02/2026
      ...
      01/08/2026 até 27/08/2026

    Isso é usado para atualizações retroativas pelo Portal BI.
    """
    periodos = []
    atual = inicio

    while atual <= fim:
        if atual.month == 12:
            primeiro_dia_proximo_mes = date(
                atual.year + 1,
                1,
                1,
            )
        else:
            primeiro_dia_proximo_mes = date(
                atual.year,
                atual.month + 1,
                1,
            )

        ultimo_dia_mes = primeiro_dia_proximo_mes - timedelta(days=1)
        fim_bloco = min(ultimo_dia_mes, fim)

        periodos.append(
            (
                atual,
                fim_bloco,
            )
        )

        atual = fim_bloco + timedelta(days=1)

    return periodos


def criar_driver():
    chrome_options = Options()

    prefs = {
        "download.default_directory": str(PASTA_DOWNLOAD),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }

    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=chrome_options)

    # Garante download no Chrome headless.
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {
            "behavior": "allow",
            "downloadPath": str(PASTA_DOWNLOAD),
        },
    )

    return driver


def limpar_downloads():
    for arq in PASTA_DOWNLOAD.glob("*"):
        try:
            if arq.is_file():
                arq.unlink()
        except Exception:
            pass


def aguardar_download(inicio_download, timeout=TIMEOUT_DOWNLOAD):
    """
    Aguarda um Excel NOVO depois do clique em fexcel().

    IMPORTANTE:
    O Chrome/Agrosys pode deixar um .crdownload residual
    mesmo quando o relatorio.xlsx já terminou.

    Por isso:
    - não bloqueamos mais pela existência de .crdownload;
    - procuramos um Excel novo;
    - validamos se o tamanho ficou estável;
    - se ficou estável por algumas verificações, aceitamos o arquivo.
    """
    limite = time.time() + timeout
    ultimo_log = 0

    arquivo_em_teste = None
    tamanho_anterior = None
    estabilidade = 0
    ESTABILIDADE_NECESSARIA = 3

    while time.time() < limite:
        temporarios = [
            arq
            for arq in PASTA_DOWNLOAD.glob("*.crdownload")
            if arq.is_file()
        ]

        candidatos = []

        for extensao in ("*.xlsx", "*.xls"):
            for arq in PASTA_DOWNLOAD.glob(extensao):
                try:
                    if (
                        arq.is_file()
                        and arq.stat().st_mtime >= inicio_download - 1
                        and arq.stat().st_size > 0
                    ):
                        candidatos.append(arq)
                except OSError:
                    pass

        if candidatos:
            arquivo = max(
                candidatos,
                key=lambda p: p.stat().st_mtime
            )

            try:
                tamanho_atual = arquivo.stat().st_size

                if arquivo_em_teste != arquivo:
                    arquivo_em_teste = arquivo
                    tamanho_anterior = tamanho_atual
                    estabilidade = 0

                    print(
                        f"Excel encontrado: {arquivo.name} | "
                        f"{tamanho_atual:,} bytes",
                        flush=True,
                    )
                else:
                    if (
                        tamanho_anterior is not None
                        and tamanho_atual == tamanho_anterior
                        and tamanho_atual > 0
                    ):
                        estabilidade += 1
                    else:
                        estabilidade = 0

                    tamanho_anterior = tamanho_atual

                print(
                    f"Validando Excel... "
                    f"{arquivo.name} | "
                    f"{tamanho_atual:,} bytes | "
                    f"estabilidade {estabilidade}/"
                    f"{ESTABILIDADE_NECESSARIA} | "
                    f"temporarios={len(temporarios)}",
                    flush=True,
                )

                if estabilidade >= ESTABILIDADE_NECESSARIA:
                    print(
                        f"Excel concluído: {arquivo.name} | "
                        f"{tamanho_atual:,} bytes",
                        flush=True,
                    )

                    if temporarios:
                        print(
                            "AVISO: existe .crdownload residual, "
                            "mas o Excel está estável e será utilizado.",
                            flush=True,
                        )

                    return arquivo

            except OSError:
                arquivo_em_teste = None
                tamanho_anterior = None
                estabilidade = 0

        agora = time.time()
        if agora - ultimo_log >= 10:
            print(
                f"Aguardando Excel oficial... "
                f"temporarios={len(temporarios)} | "
                f"excels={len(candidatos)}",
                flush=True,
            )
            ultimo_log = agora

        time.sleep(2)

    return None

def copiar_cookies_para_selenium(driver, ag):
    driver.get(BASE_AGROSYS)

    for nome, valor in ag.session.cookies.get_dict().items():
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


def baixar_excel_oficial(driver, url_relatorio, arquivo_destino):
    limpar_downloads()

    print("Abrindo relatório oficial:", url_relatorio)
    driver.get(url_relatorio)

    # Espera a página e a função fexcel().
    limite = time.time() + 60

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

        time.sleep(1)

    else:
        raise Exception(
            "A página abriu, mas a função fexcel() "
            "não ficou disponível em 60 segundos."
        )

    inicio_download = time.time()

    print("Solicitando Excel oficial...")
    driver.execute_script("fexcel();")

    baixado = aguardar_download(
        inicio_download=inicio_download,
        timeout=TIMEOUT_DOWNLOAD,
    )

    if baixado is None:
        restantes = [
            arq.name
            for arq in PASTA_DOWNLOAD.glob("*")
            if arq.is_file()
        ]

        raise Exception(
            f"Não encontrei o Excel oficial após {TIMEOUT_DOWNLOAD} segundos. "
            f"Arquivos presentes no download: {restantes}"
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

    print("Excel oficial salvo:", arquivo_destino)


# =============================================================================
# RELATÓRIO
# =============================================================================

def montar_filtros(data_inicial, data_final):
    """
    Filtros exatamente equivalentes à tela mostrada:
    - Todas as empresas
    - Todas as unidades
    - Todos os compradores
    - Todos os tipos SC
    - Situação = Todas
    - Solicitação Para = Todos
    - Demais campos em branco
    """
    return {
        "vpardate1": data_inicial,
        "vpardate2": data_final,

        "vemp-empresa": "0",
        "vparint5": "0",

        "vparint4": "",       # Solicitação
        "vparint1": "",       # Requisitante
        "vtip-codigo": "",    # Tipo Item
        "vgru-codigo": "",    # Grupo Item
        "vparint2": "",       # Item
        "vpjt-numero": "",    # Projeto
        "vequi-codigo": "",   # Equipamento
        "vusuario": "",       # Usuário
        "vccu-ccusto": "",    # Centro de custo

        "vcomprador": "0",    # Todos
        "vparint8": "",       # Tipo SC = Todos
        "vparint3": "10",     # Situação = Todas
        "vparint6": "1",      # Solicitação Para = Todos

        # Checkboxes vparlog1/vparlog2/vparlog3 ficam ausentes,
        # pois estão desmarcados na tela.

        "vpad-btdisp.x": "Disparar",
    }


def baixar_periodo(ag, driver, data_inicial, data_final):
    print("=" * 80)
    print(f"{NOME_RELATORIO}")
    print(f"Período: {data_inicial} até {data_final}")
    print("=" * 80)

    filtros = montar_filtros(
        data_inicial=data_inicial,
        data_final=data_final,
    )

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
        unidade=UNIDADE_ENGINE,
        filtros=filtros,
        nome_debug=(
            "solicitacoes_requisitante_"
            f"{data_nome_arquivo(data_inicial)}_"
            f"{data_nome_arquivo(data_final)}"
        ),
        modulo=MODULO,
        max_404_consecutivos=MAX_404_CONSECUTIVOS,
        tempo_minimo_antes_descartar_404=TEMPO_MINIMO_ANTES_DESCARTAR_404,
    )

    print("Processo:", processo)

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    inicio_nome = data_nome_arquivo(data_inicial)
    fim_nome = data_nome_arquivo(data_final)

    if inicio_nome == fim_nome:
        nome_arquivo = (
            f"solicitacoes_requisitante_{inicio_nome}.xlsx"
        )
    else:
        nome_arquivo = (
            f"solicitacoes_requisitante_"
            f"{inicio_nome}_ate_{fim_nome}.xlsx"
        )

    arquivo_destino = PASTA_SAIDA / nome_arquivo

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    return arquivo_destino


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Baixa o Relatório de Solicitações por Requisitante "
            "do Agrosys em Excel oficial."
        )
    )

    parser.add_argument(
        "--modo",
        choices=["periodo", "automatico", "hoje"],
        default=None,
        help=(
            "Modo de execução usado pelo Portal BI. "
            "'periodo' usa --inicio/--fim; "
            "'automatico' lê a pasta e segue até hoje; "
            "'hoje' baixa somente o dia atual."
        ),
    )

    parser.add_argument(
        "--inicio",
        type=data_br,
        default=None,
        help="Data inicial: DD/MM/YYYY ou YYYY-MM-DD.",
    )

    parser.add_argument(
        "--fim",
        type=data_br,
        default=None,
        help="Data final: DD/MM/YYYY ou YYYY-MM-DD.",
    )

    parser.add_argument(
        "--somente-hoje",
        action="store_true",
        help="Ignora a pasta e baixa somente o dia de hoje.",
    )

    return parser.parse_args()


def montar_periodos(args):
    hoje = date.today()

    # Compatibilidade com o Portal BI:
    # --modo periodo --inicio DD/MM/YYYY --fim DD/MM/YYYY
    #
    # IMPORTANTE:
    # Período personalizado = RETROATIVO.
    # Se atravessar mais de um mês, o robô divide mês a mês.
    if args.modo == "periodo" or args.inicio or args.fim:
        if args.inicio is None or args.fim is None:
            raise ValueError(
                "Para período manual, informe --inicio e --fim."
            )

        inicio = datetime.strptime(args.inicio, "%d/%m/%Y").date()
        fim = datetime.strptime(args.fim, "%d/%m/%Y").date()

        if inicio > fim:
            raise ValueError(
                "A data inicial não pode ser maior que a data final."
            )

        periodos = dividir_periodo_por_mes(
            inicio=inicio,
            fim=fim,
        )

        print(
            "Modo RETROATIVO: período personalizado será processado mês a mês.",
            flush=True,
        )

        for i, (data_ini, data_fim) in enumerate(periodos, start=1):
            print(
                f"  Bloco {i}/{len(periodos)}: "
                f"{data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
                flush=True,
            )

        return periodos

    if args.modo == "hoje" or args.somente_hoje:
        return [(hoje, hoje)]

    # Sem modo, ou com --modo automatico:
    # mantém a lógica automática já existente:
    # lê a última data da pasta e segue DIA A DIA até hoje.
    return listar_periodos_automaticos()


def main():
    args = parse_args()
    periodos = montar_periodos(args)

    print("=" * 80, flush=True)
    print("ROBÔ SUPRIMENTOS - SOLICITAÇÕES POR REQUISITANTE", flush=True)
    print(f"Pasta monitorada: {PASTA_SAIDA}", flush=True)
    print(f"Períodos a baixar: {len(periodos)}", flush=True)
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
        copiar_cookies_para_selenium(
            driver=driver,
            ag=ag,
        )

        for data_ini, data_fim in periodos:
            data_ini_br = data_ini.strftime("%d/%m/%Y")
            data_fim_br = data_fim.strftime("%d/%m/%Y")

            try:
                arquivo = baixar_periodo(
                    ag=ag,
                    driver=driver,
                    data_inicial=data_ini_br,
                    data_final=data_fim_br,
                )

                if not arquivo.exists() or arquivo.stat().st_size <= 0:
                    raise Exception(
                        "O período terminou sem um Excel válido na pasta final."
                    )

                ok += 1
                print(
                    f"OK: {data_ini:%d/%m/%Y} -> {arquivo.name}",
                    flush=True,
                )

            except Exception as erro:
                erros += 1
                print(
                    f"ERRO no período {data_ini:%d/%m/%Y} "
                    f"até {data_fim:%d/%m/%Y}: {erro}",
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

    # Fundamental para o Portal:
    # não mostrar "Sucesso" quando algum período falhou.
    return 0 if erros == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
