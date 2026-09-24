# -*- coding: utf-8 -*-
r"""
ÍNDICE ZOOTÉCNICO - Base de Dados Dinâmica
Relatório: Base de Dados Frango de Corte
Menu Agrosys: vmen-codigo=30118
Programa: wpf800d1

VERSÃO HISTÓRICA + INCREMENTAL + RETOMADA

REGRAS:
- Histórico obrigatório desde 01/01/2023.
- Download sempre mês a mês.
- Meses fechados:
    01/MM/AAAA até último dia do mês.
- Mês atual:
    01/MM/AAAA até hoje.
- Meses fechados já baixados não são gerados novamente.
- O mês atual é atualizado conforme os dias avançam.
- Quando um mês fecha, o robô gera o arquivo definitivo do mês inteiro.
- Se houver falha, o robô:
    * registra a falha em log na pasta de destino;
    * grava um checkpoint em JSON;
    * interrompe a sequência para não criar buracos;
    * na próxima execução retoma do primeiro período pendente.
- A própria pasta de arquivos também é usada como fonte de verdade:
    se o JSON estiver ausente ou desatualizado, arquivos válidos já existentes
    continuam sendo reconhecidos.

SAÍDA:
\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Base de Dados Dinamica
"""

import calendar
import json
import shutil
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# CONFIGURAÇÃO GERAL
# ---------------------------------------------------------------------------

MENU = 30118
PROGRAMA = "wpf800d1"
CAMINHO_RELATORIO = "/webpro/weball/wpf800d1"
MODULO = "17000"
UNIDADE = "52"

DATA_HISTORICA_INICIO = date(2023, 1, 1)

PASTA_SAIDA = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Indice Zootecnico\Base de Dados Dinamica"
)

# PASTA_DOWNLOAD vem da configuracao isolada desta execucao.

ARQUIVO_LOG = PASTA_SAIDA / "base_dados_dinamica.log"
ARQUIVO_ESTADO = PASTA_SAIDA / "estado_base_dados_dinamica.json"

PREFIXO_ARQUIVO = "Base_Dados_Dinamica_"

# Tempo máximo para o download do Excel oficial.
TIMEOUT_DOWNLOAD = 300


# ---------------------------------------------------------------------------
# LOG / CHECKPOINT
# ---------------------------------------------------------------------------

def registrar_log(mensagem, nivel="INFO"):
    """
    Escreve no console e acrescenta uma linha no log da pasta de destino.
    """
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    linha = f"[{agora}] [{nivel}] {mensagem}"

    print(linha, flush=True)

    try:
        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

        with ARQUIVO_LOG.open("a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")

    except Exception as erro_log:
        print(
            f"[AVISO] Não foi possível gravar o log: {erro_log}",
            flush=True,
        )


def carregar_estado():
    """
    Lê o checkpoint anterior, se existir.
    O checkpoint ajuda a explicar onde a execução parou, mas a pasta de
    arquivos continua sendo conferida antes de decidir o que precisa baixar.
    """
    if not ARQUIVO_ESTADO.exists():
        return {}

    try:
        return json.loads(
            ARQUIVO_ESTADO.read_text(encoding="utf-8")
        )
    except Exception as erro:
        registrar_log(
            f"Não foi possível ler o checkpoint anterior: {erro}. "
            "A execução seguirá conferindo os arquivos existentes.",
            "AVISO",
        )
        return {}


def salvar_estado(
    status,
    periodo_inicio=None,
    periodo_fim=None,
    proximo_inicio=None,
    mensagem=None,
):
    """
    Grava o checkpoint de forma atômica para reduzir risco de JSON corrompido.
    """
    dados = {
        "relatorio": "Índice Zootécnico - Base de Dados Dinâmica",
        "status": status,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "inicio_historico": DATA_HISTORICA_INICIO.isoformat(),
    }

    if periodo_inicio is not None:
        dados["ultimo_periodo_inicio"] = periodo_inicio.isoformat()

    if periodo_fim is not None:
        dados["ultimo_periodo_fim"] = periodo_fim.isoformat()

    if proximo_inicio is not None:
        dados["proximo_periodo_inicio"] = proximo_inicio.isoformat()

    if mensagem:
        dados["mensagem"] = mensagem

    temporario = ARQUIVO_ESTADO.with_suffix(".json.tmp")

    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    temporario.replace(ARQUIVO_ESTADO)


def registrar_erro_fatal(titulo, erro):
    """
    Registra traceback completo no mesmo log da pasta de destino.
    """
    traceback_texto = traceback.format_exc()

    registrar_log("=" * 80, "ERRO")
    registrar_log(titulo, "ERRO")
    registrar_log(
        f"Tipo: {type(erro).__name__} | Erro: {erro}",
        "ERRO",
    )

    try:
        with ARQUIVO_LOG.open("a", encoding="utf-8") as arquivo:
            arquivo.write("\nTRACEBACK COMPLETO:\n")
            arquivo.write(traceback_texto)
            arquivo.write("\n" + "=" * 80 + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# DEPENDÊNCIAS
# ---------------------------------------------------------------------------

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    RAIZ = Path(__file__).resolve().parents[1]
    sys.path.append(str(RAIZ))

    from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML, PASTA_DOWNLOAD

    from Core.agrosys_engine import AgrosysEngine

except Exception as erro_importacao:
    try:
        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    registrar_erro_fatal(
        "ERRO AO CARREGAR AS DEPENDÊNCIAS DO ROBÔ",
        erro_importacao,
    )
    sys.exit(1)


try:
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

except Exception as erro_pastas:
    registrar_erro_fatal(
        "ERRO AO PREPARAR AS PASTAS DO ROBÔ",
        erro_pastas,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# DATAS / PERÍODOS
# ---------------------------------------------------------------------------

def ultimo_dia_mes(ano, mes):
    return calendar.monthrange(ano, mes)[1]


def fim_do_mes(data_inicio):
    return date(
        data_inicio.year,
        data_inicio.month,
        ultimo_dia_mes(data_inicio.year, data_inicio.month),
    )


def proximo_mes(data_atual):
    if data_atual.month == 12:
        return date(data_atual.year + 1, 1, 1)

    return date(data_atual.year, data_atual.month + 1, 1)


def gerar_periodos_mensais(data_inicial, data_final):
    """
    Gera:
        01/01/2023 -> 31/01/2023
        01/02/2023 -> 28/02/2023
        ...
        01/mês atual -> hoje
    """
    atual = date(data_inicial.year, data_inicial.month, 1)

    while atual <= data_final:
        fim = min(fim_do_mes(atual), data_final)

        yield atual, fim

        atual = proximo_mes(atual)


def nome_arquivo_periodo(data_ini, data_fim):
    return (
        f"{PREFIXO_ARQUIVO}"
        f"{data_ini.strftime('%d-%m-%Y')}_"
        f"{data_fim.strftime('%d-%m-%Y')}.xlsx"
    )


def caminho_arquivo_periodo(data_ini, data_fim):
    return PASTA_SAIDA / nome_arquivo_periodo(data_ini, data_fim)


def arquivo_valido(caminho):
    try:
        return (
            caminho.exists()
            and caminho.is_file()
            and caminho.stat().st_size > 0
        )
    except OSError:
        return False


def listar_arquivos_do_mes(data_ini):
    """
    Localiza versões do mesmo mês, inclusive arquivos parciais antigos
    do mês que ainda estava aberto.
    """
    padrao = (
        f"{PREFIXO_ARQUIVO}"
        f"01-{data_ini.strftime('%m-%Y')}_*.xlsx"
    )

    return [
        arquivo
        for arquivo in PASTA_SAIDA.glob(padrao)
        if arquivo.is_file()
    ]


def remover_versoes_antigas_do_mes(data_ini, manter):
    """
    Depois que o novo arquivo foi validado, remove versões antigas do mesmo mês.
    Exemplo:
        Base_01-09-2026_09-09-2026.xlsx
    é removido quando for criado:
        Base_01-09-2026_10-09-2026.xlsx
    ou o arquivo definitivo:
        Base_01-09-2026_30-09-2026.xlsx
    """
    for arquivo in listar_arquivos_do_mes(data_ini):
        try:
            if arquivo.resolve() == manter.resolve():
                continue

            arquivo.unlink()

            registrar_log(
                f"Versão antiga removida: {arquivo.name}"
            )

        except Exception as erro:
            registrar_log(
                f"Não foi possível remover a versão antiga "
                f"{arquivo.name}: {erro}",
                "AVISO",
            )


def primeiro_periodo_pendente(hoje):
    """
    A pasta é a principal fonte de verdade.

    Percorre desde 01/01/2023 e retorna o primeiro mês cujo arquivo
    esperado ainda não existe.

    Para o mês atual, o nome esperado sempre termina em 'hoje'.
    """
    for data_ini, data_fim in gerar_periodos_mensais(
        DATA_HISTORICA_INICIO,
        hoje,
    ):
        destino = caminho_arquivo_periodo(data_ini, data_fim)

        if not arquivo_valido(destino):
            return data_ini, data_fim

    return None


# ---------------------------------------------------------------------------
# SELENIUM / DOWNLOAD
# ---------------------------------------------------------------------------

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


def aguardar_download(timeout=TIMEOUT_DOWNLOAD, inicio_download=None):
    """
    Aguarda .xlsx/.xls final e estável.
    Ignora .crdownload, .tmp e .part.
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
                key=lambda item: item.stat().st_mtime,
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

            if estabilidade >= 6:
                auxiliares = [
                    item.name
                    for item in PASTA_DOWNLOAD.glob("*")
                    if item.is_file()
                    and (
                        item.name.endswith(".crdownload")
                        or item.suffix.lower() in {".tmp", ".part"}
                    )
                ]

                registrar_log(
                    "Arquivo final detectado: "
                    f"{arquivo.name} | "
                    f"{tamanho / 1024 / 1024:.2f} MB"
                )

                if auxiliares:
                    registrar_log(
                        f"Arquivos auxiliares ignorados: {auxiliares}"
                    )

                return arquivo

        time.sleep(0.5)

    return None


def copiar_cookies_para_selenium(driver, ag):
    registrar_log("Preparando sessão Selenium...")

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

    registrar_log(
        f"Sessão Selenium pronta. Cookies copiados: {len(cookies)}"
    )


def baixar_excel_oficial(driver, url_relatorio, arquivo_destino):
    """
    Abre o relatório processado e executa fexcel().
    """
    limpar_downloads()

    registrar_log("Abrindo relatório pronto no Selenium...")

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
        raise RuntimeError(
            "A página abriu, mas a função fexcel() "
            "não ficou disponível em 60 segundos."
        )

    registrar_log(
        f"fexcel() localizado em "
        f"{time.time() - inicio_abertura:.1f}s. "
        "Solicitando Excel oficial..."
    )

    inicio_download = time.time()

    driver.execute_script("fexcel();")

    registrar_log("fexcel() executado.")

    inicio_confirmacao = time.time()
    download_iniciado = False

    while time.time() - inicio_confirmacao < 8:
        temporarios = [
            arquivo
            for arquivo in PASTA_DOWNLOAD.glob("*.crdownload")
            if arquivo.is_file()
        ]

        excels = [
            arquivo
            for mascara in ("*.xlsx", "*.xls")
            for arquivo in PASTA_DOWNLOAD.glob(mascara)
            if arquivo.is_file()
        ]

        if temporarios or excels:
            download_iniciado = True
            registrar_log(
                "Download detectado na pasta temporária."
            )
            break

        time.sleep(0.5)

    if not download_iniciado:
        registrar_log(
            "fexcel() não iniciou arquivo em 8s. "
            "Continuarei aguardando.",
            "AVISO",
        )

    baixado = aguardar_download(
        timeout=TIMEOUT_DOWNLOAD,
        inicio_download=inicio_download,
    )

    if baixado is None:
        presentes = [
            arquivo.name
            for arquivo in PASTA_DOWNLOAD.glob("*")
            if arquivo.is_file()
        ]

        raise TimeoutError(
            "Não encontrei o Excel oficial dentro do tempo limite. "
            f"Arquivos presentes: {presentes}"
        )

    arquivo_destino.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Só apaga o destino exato se já existir e estiver sendo refeito.
    if arquivo_destino.exists():
        arquivo_destino.unlink()

    shutil.move(
        str(baixado),
        str(arquivo_destino),
    )

    if not arquivo_valido(arquivo_destino):
        raise RuntimeError(
            "O Excel foi baixado, mas não foi salvo corretamente."
        )

    registrar_log(
        f"Excel salvo em "
        f"{time.time() - inicio_download:.1f}s: "
        f"{arquivo_destino.name}"
    )


# ---------------------------------------------------------------------------
# AGROSYS
# ---------------------------------------------------------------------------

def baixar_base_dinamica(ag, driver, data_ini, data_fim):
    registrar_log("=" * 80)
    registrar_log(
        "ÍNDICE ZOOTÉCNICO - BASE DE DADOS DINÂMICA"
    )
    registrar_log(
        f"Período: "
        f"{data_ini.strftime('%d/%m/%Y')} "
        f"até {data_fim.strftime('%d/%m/%Y')}"
    )

    filtros = {
        "vdat-inicial": data_ini.strftime("%d/%m/%Y"),
        "vdat-final": data_fim.strftime("%d/%m/%Y"),
        "vdinamico": "yes",
        "vpad-btdisp.x": "Disparar",
    }

    registrar_log(
        f"Disparando POST "
        f"{CAMINHO_RELATORIO}?vmen-codigo={MENU}"
    )

    html, processo = ag.executar_relatorio(
        caminho=CAMINHO_RELATORIO,
        menu=MENU,
        unidade=UNIDADE,
        filtros=filtros,
        nome_debug=(
            "indice_zootecnico_base_dinamica_"
            f"{data_ini.strftime('%d-%m-%Y')}_"
            f"{data_fim.strftime('%d-%m-%Y')}"
        ),
        modulo=MODULO,
        tentativas=30,
        espera=20,
        tentativas_disparo=8,
        espera_disparo=15,
    )

    registrar_log(
        f"Processo Agrosys localizado: {processo}"
    )

    url_relatorio = (
        f"{BASE_AGROSYS}/sistema/reports/"
        f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
    )

    arquivo_destino = caminho_arquivo_periodo(
        data_ini,
        data_fim,
    )

    registrar_log(
        f"Destino: {arquivo_destino}"
    )

    baixar_excel_oficial(
        driver=driver,
        url_relatorio=url_relatorio,
        arquivo_destino=arquivo_destino,
    )

    return arquivo_destino


# ---------------------------------------------------------------------------
# EXECUÇÃO HISTÓRICA / INCREMENTAL
# ---------------------------------------------------------------------------

def executar_periodo(ag, data_ini, data_fim):
    """
    Cria um Chrome novo para cada mês.

    Isso é intencional: evita que uma carga histórica muito longa acumule
    memória/cache do navegador durante dezenas de períodos.
    """
    driver = None

    try:
        driver = criar_driver()
        copiar_cookies_para_selenium(driver, ag)

        return baixar_base_dinamica(
            ag=ag,
            driver=driver,
            data_ini=data_ini,
            data_fim=data_fim,
        )

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    hoje = datetime.now().date()

    registrar_log("")
    registrar_log("=" * 80)
    registrar_log(
        "INICIANDO ÍNDICE ZOOTÉCNICO - BASE DE DADOS DINÂMICA"
    )
    registrar_log(
        f"Histórico obrigatório: "
        f"{DATA_HISTORICA_INICIO.strftime('%d/%m/%Y')} até hoje"
    )
    registrar_log(
        "Estratégia: mês a mês + checkpoint + retomada."
    )
    registrar_log(
        f"Pasta de saída: {PASTA_SAIDA}"
    )
    registrar_log("=" * 80)

    estado_anterior = carregar_estado()

    if estado_anterior:
        registrar_log(
            "Checkpoint anterior localizado: "
            f"status={estado_anterior.get('status', 'desconhecido')} | "
            f"próximo={estado_anterior.get('proximo_periodo_inicio', 'não informado')}"
        )

    pendente = primeiro_periodo_pendente(hoje)

    if pendente is None:
        registrar_log(
            "Nenhum período pendente. A base já está atualizada até hoje."
        )

        salvar_estado(
            status="atualizado",
            periodo_inicio=date(hoje.year, hoje.month, 1),
            periodo_fim=hoje,
            mensagem="Nenhum download necessário nesta execução.",
        )

        return 0

    primeiro_inicio, primeiro_fim = pendente

    registrar_log(
        "Primeiro período pendente identificado: "
        f"{primeiro_inicio.strftime('%d/%m/%Y')} até "
        f"{primeiro_fim.strftime('%d/%m/%Y')}"
    )

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    registrar_log("Realizando login no Agrosys...")
    ag.login()
    registrar_log("Login realizado.")

    iniciou = False
    ultimo_inicio = None
    ultimo_fim = None

    for data_ini, data_fim in gerar_periodos_mensais(
        primeiro_inicio,
        hoje,
    ):
        iniciou = True

        destino = caminho_arquivo_periodo(
            data_ini,
            data_fim,
        )

        # Reconfere antes de cada período.
        if arquivo_valido(destino):
            registrar_log(
                f"{data_ini.strftime('%m/%Y')} já está concluído "
                f"({destino.name}). Ignorando."
            )

            ultimo_inicio = data_ini
            ultimo_fim = data_fim
            continue

        registrar_log(
            f"INICIANDO {data_ini.strftime('%m/%Y')}: "
            f"{data_ini.strftime('%d/%m/%Y')} até "
            f"{data_fim.strftime('%d/%m/%Y')}"
        )

        salvar_estado(
            status="em_execucao",
            periodo_inicio=ultimo_inicio,
            periodo_fim=ultimo_fim,
            proximo_inicio=data_ini,
            mensagem=(
                f"Processando {data_ini.strftime('%m/%Y')}."
            ),
        )

        try:
            arquivo_gerado = executar_periodo(
                ag=ag,
                data_ini=data_ini,
                data_fim=data_fim,
            )

            if not arquivo_valido(arquivo_gerado):
                raise RuntimeError(
                    "O arquivo retornado pelo período não é válido."
                )

            # Só depois do novo arquivo estar confirmado removemos versões
            # parciais/antigas daquele mesmo mês.
            remover_versoes_antigas_do_mes(
                data_ini,
                manter=arquivo_gerado,
            )

            ultimo_inicio = data_ini
            ultimo_fim = data_fim

            proximo_inicio = proximo_mes(data_ini)

            registrar_log(
                f"{data_ini.strftime('%m/%Y')} CONCLUÍDO COM SUCESSO."
            )

            salvar_estado(
                status="periodo_concluido",
                periodo_inicio=data_ini,
                periodo_fim=data_fim,
                proximo_inicio=(
                    proximo_inicio
                    if proximo_inicio <= hoje
                    else None
                ),
                mensagem=(
                    f"{data_ini.strftime('%m/%Y')} concluído."
                ),
            )

        except Exception as erro:
            registrar_log(
                f"EXECUÇÃO INTERROMPIDA EM "
                f"{data_ini.strftime('%B/%Y').upper()} "
                f"({data_ini.strftime('%m/%Y')}).",
                "ERRO",
            )

            registrar_log(
                f"Na próxima execução o robô tentará novamente "
                f"{data_ini.strftime('%d/%m/%Y')} até "
                f"{data_fim.strftime('%d/%m/%Y')}.",
                "ERRO",
            )

            registrar_log(
                f"Motivo técnico: {type(erro).__name__}: {erro}",
                "ERRO",
            )

            salvar_estado(
                status="interrompido",
                periodo_inicio=ultimo_inicio,
                periodo_fim=ultimo_fim,
                proximo_inicio=data_ini,
                mensagem=(
                    f"Parado em {data_ini.strftime('%m/%Y')}: "
                    f"{type(erro).__name__}: {erro}"
                ),
            )

            registrar_erro_fatal(
                "ERRO DURANTE A CARGA HISTÓRICA/INCREMENTAL",
                erro,
            )

            # Importante: não pula o mês com erro.
            # Para aqui para evitar buracos silenciosos.
            return 1

    if iniciou:
        registrar_log("=" * 80)
        registrar_log(
            "BASE DE DADOS DINÂMICA ATUALIZADA COM SUCESSO."
        )
        registrar_log(
            f"Último período processado/verificado: "
            f"{ultimo_inicio.strftime('%d/%m/%Y')} até "
            f"{ultimo_fim.strftime('%d/%m/%Y')}"
        )
        registrar_log("=" * 80)

        salvar_estado(
            status="atualizado",
            periodo_inicio=ultimo_inicio,
            periodo_fim=ultimo_fim,
            mensagem=(
                f"Base atualizada até {ultimo_fim.strftime('%d/%m/%Y')}."
            ),
        )

    return 0


if __name__ == "__main__":
    try:
        codigo_saida = main()

    except KeyboardInterrupt as erro:
        registrar_log(
            "Execução interrompida manualmente pelo usuário.",
            "ERRO",
        )

        try:
            pendente = primeiro_periodo_pendente(
                datetime.now().date()
            )

            salvar_estado(
                status="interrompido_manualmente",
                proximo_inicio=pendente[0] if pendente else None,
                mensagem=(
                    "Execução interrompida manualmente. "
                    "A próxima execução retomará do primeiro período pendente."
                ),
            )
        except Exception:
            pass

        codigo_saida = 1

    except BaseException as erro_fatal:
        registrar_erro_fatal(
            "ERRO FATAL NÃO TRATADO",
            erro_fatal,
        )

        try:
            pendente = primeiro_periodo_pendente(
                datetime.now().date()
            )

            salvar_estado(
                status="erro_fatal",
                proximo_inicio=pendente[0] if pendente else None,
                mensagem=(
                    f"{type(erro_fatal).__name__}: {erro_fatal}"
                ),
            )
        except Exception:
            pass

        codigo_saida = 1

    sys.exit(codigo_saida)
