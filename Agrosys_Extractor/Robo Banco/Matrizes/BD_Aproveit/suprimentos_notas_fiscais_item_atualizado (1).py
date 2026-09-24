# -*- coding: utf-8 -*-
"""
SUPRIMENTOS - NOTAS FISCAIS DO ITEM
VERSÃO DIÁRIA INCREMENTAL - POST MANUAL ESPECÍFICO

Esta versão NÃO usa o executar_relatorio() genérico para o disparo.
Ela faz:
1) login;
2) configura unidade/menu;
3) abre a tela real pelo Requests;
4) extrai TODOS os inputs/hidden do HTML;
5) altera somente os filtros confirmados no DevTools;
6) remove campos que o navegador manual NÃO envia;
7) dispara o mesmo formulário;
8) captura o processo;
9) aguarda o relatório;
10) baixa o Excel oficial via Selenium/fexcel().

Relatório:
- Programa: wrc250d10
- Menu: 29458
- Módulo: 27932
- Tipo de Saída: S = Relatório Sem Quebra
- Operação: G = Geral
"""

import argparse
import html as html_lib
import re
import shutil
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine


NOME_RELATORIO = "Suprimentos - Notas Fiscais do Item"

CAMINHO_RELATORIO = "/webpro/websup/wrc250d10"
MENU_RELATORIO = 29458
MODULO_RELATORIO = "27932"
UNIDADE_RELATORIO = "1"

PASTA_SAIDA_BASE = Path(
    r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Notas Fiscais do Item"
)
from Core.agrosys_runtime import PASTA_DOWNLOAD

PASTA_SAIDA_BASE.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)

TIMEOUT_DOWNLOAD = 300

# O Agrosys pode demorar para devolver o número do processo após o POST.
# Tenta novamente sem encerrar o robô imediatamente.
TENTATIVAS_ENCONTRAR_PROCESSO = 20
ESPERA_ENTRE_DISPAROS = 15


# =============================================================================
# SELENIUM APENAS PARA O EXCEL OFICIAL
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


def copiar_cookies_para_selenium(driver, ag):
    driver.get(BASE_AGROSYS)
    time.sleep(0.5)

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


def aguardar_download(timeout=TIMEOUT_DOWNLOAD):
    inicio = time.time()
    ultimo = None
    ultimo_tamanho = None
    estavel = 0

    while time.time() - inicio < timeout:
        candidatos = []

        for mascara in ("*.xlsx", "*.xls"):
            candidatos.extend(
                [
                    p for p in PASTA_DOWNLOAD.glob(mascara)
                    if p.is_file() and p.stat().st_size > 0
                ]
            )

        if candidatos:
            atual = max(candidatos, key=lambda p: p.stat().st_mtime)
            tamanho = atual.stat().st_size

            if atual == ultimo and tamanho == ultimo_tamanho:
                estavel += 1
            else:
                ultimo = atual
                ultimo_tamanho = tamanho
                estavel = 0

            if estavel >= 4:
                return atual

        time.sleep(0.5)

    return None


def baixar_excel_oficial(driver, url_relatorio, destino):
    limpar_downloads()

    print("Abrindo relatório pronto no Selenium...", flush=True)
    driver.get(url_relatorio)
    time.sleep(2)

    achou = driver.execute_script(
        """
        if (typeof fexcel === 'function') {
            fexcel();
            return true;
        }
        return false;
        """
    )

    if not achou:
        raise Exception("fexcel() não encontrada no relatório.")

    print("Excel oficial solicitado.", flush=True)

    baixado = aguardar_download()

    if baixado is None:
        raise Exception("Excel oficial não apareceu na pasta de download.")

    if destino.exists():
        destino.unlink()

    shutil.move(str(baixado), str(destino))

    if not destino.exists() or destino.stat().st_size <= 0:
        raise Exception("Excel foi baixado, mas ficou inválido.")

    print("Excel salvo:", destino, flush=True)


# =============================================================================
# FILTROS EXATOS DO DEVTOOLS MANUAL
# =============================================================================

def filtros_manuais(data_ini, data_fim, empresa_codigo):
    return {
        "verro": "yes",

        "vite-codigo": "0",
        "vtip-codigo": "0",
        "vcfs-codigo": "0",
        "vcfs-descricao": "Todos",
        "vgru-codigo": "0",

        "vsel-grupo": "1",
        "vsel-itens": "1",

        "vpardate1": data_ini.strftime("%d/%m/%Y"),
        "vpardate2": data_fim.strftime("%d/%m/%Y"),

        "valternativaempresa": str(empresa_codigo),

        "vfil-filial": "",
        "vuni-unidade": "0",

        "vfor-codigo": "0",

        # No POST manual vem VAZIO:
        "vtip-forcodigo": "",

        "vtra": "",

        "vsel-pessoa": "T",
        "vest-estado": "",

        "vsel-frete": "1",

        # Geral (Transferências + Compras)
        "vsel-opera": "G",

        "vnat-saida": "0",
        "vnat-entrada": "",

        # CRÍTICO: relatório sem quebra
        "vtip-saida": "S",

        # Total por OC = Não
        "vexb-valoroc": "",

        "vpad-btdisp.x": "Disparar",
    }


# =============================================================================
# PROCESSO
# =============================================================================

def capturar_processo_robusto(ag, html):
    processo = None

    try:
        processo = ag.capturar_processo(html)
    except Exception:
        processo = None

    if processo:
        return str(processo).lstrip("0")

    texto = (
        str(html or "")
        .replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("\\/", "/")
    )

    padroes = [
        r"wpd007m1\?[^\"'<>]*vparam=0*(\d{6,12})",
        r"[?&]vparam=0*(\d{6,12})",
        r"name=[\"']?vbatnump[\"']?[^>]*value=[\"']?0*(\d{6,12})",
        r"id=[\"']?vbatnump[\"']?[^>]*value=[\"']?0*(\d{6,12})",
        r"Processo[^0-9]{0,100}0*(\d{6,12})",
    ]

    for padrao in padroes:
        achou = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if achou:
            return achou.group(1).lstrip("0")

    return None


def disparar_como_post_manual(ag, data_ini, data_fim, empresa_codigo, empresa_nome):
    """
    Ponto principal desta versão.

    Não monta o POST do zero.
    Primeiro abre a tela e pega todos os inputs/hidden que o Agrosys devolveu.
    Depois substitui SOMENTE os campos observados no DevTools manual.
    """
    print("Configurando contexto do Agrosys...", flush=True)

    ag.configurar_unidade(
        unidade=UNIDADE_RELATORIO,
        menu=MENU_RELATORIO,
        modulo=MODULO_RELATORIO,
    )

    print("Abrindo tela do relatório via AgrosysEngine...", flush=True)

    url, html_tela = ag.abrir_tela(
        caminho=CAMINHO_RELATORIO,
        menu=MENU_RELATORIO,
    )

    print(
        "Tela aberta:",
        url,
        "| HTML:",
        len(html_tela or ""),
        "caracteres",
        flush=True,
    )

    # Esta é a diferença importante:
    # usa todos os campos reais que vieram da própria tela.
    dados = ag.extrair_inputs(html_tela)

    print(
        "Campos extraídos da tela antes do ajuste:",
        len(dados),
        flush=True,
    )

    dados.update(
        filtros_manuais(
            data_ini,
            data_fim,
            empresa_codigo,
        )
    )

    # Campos NÃO enviados pelo navegador manual:
    # - Entrega Futura está disabled
    # - Contrato/OC estão disabled
    # - Apenas a Fixar está desmarcado
    for campo in [
        "vsel-fut",
        "vcfc-codigo",
        "vord-compra",
        "vafixar",
    ]:
        dados.pop(campo, None)

    # Também removemos descrições disabled se a extração do HTML tiver incluído.
    for campo in [
        "vnae-saicompl",
    ]:
        dados.pop(campo, None)

    # Proteções.
    dados["valternativaempresa"] = str(empresa_codigo)
    dados["vsel-opera"] = "G"
    dados["vtip-saida"] = "S"
    dados["vtip-forcodigo"] = ""
    dados["vpad-btdisp.x"] = "Disparar"

    print("", flush=True)
    print(f"EMPRESA: {empresa_codigo} - {empresa_nome}", flush=True)
    print("POST FINAL QUE SERÁ ENVIADO:", flush=True)

    campos_chave = [
        "verro",
        "vite-codigo",
        "vtip-codigo",
        "vcfs-codigo",
        "vcfs-descricao",
        "vgru-codigo",
        "vsel-grupo",
        "vsel-itens",
        "vpardate1",
        "vpardate2",
        "valternativaempresa",
        "vfil-filial",
        "vuni-unidade",
        "vfor-codigo",
        "vtip-forcodigo",
        "vtra",
        "vsel-pessoa",
        "vest-estado",
        "vsel-frete",
        "vsel-opera",
        "vnat-saida",
        "vnat-entrada",
        "vtip-saida",
        "vexb-valoroc",
        "vpad-btdisp.x",
    ]

    for campo in campos_chave:
        print(
            f"  {campo} = {dados.get(campo)!r}",
            flush=True,
        )

    print(
        "Campos extras preservados do próprio HTML:",
        sorted(
            set(dados.keys())
            - set(campos_chave)
        ),
        flush=True,
    )

    # -------------------------------------------------------------------------
    # DISPARO COM ESPERA/REPETIÇÃO
    # -------------------------------------------------------------------------
    # Alguns relatórios pesados do Agrosys respondem HTTP 200 antes de devolver
    # o número do processo. A versão anterior encerrava o robô nesse ponto.
    # Agora aguardamos e repetimos o disparo, como já é feito no AgrosysEngine
    # genérico, até encontrar o processo ou atingir o limite configurado.
    processo = None
    html_disparo = ""

    for tentativa_disparo in range(1, TENTATIVAS_ENCONTRAR_PROCESSO + 1):
        print(
            f"Tentativa {tentativa_disparo}/{TENTATIVAS_ENCONTRAR_PROCESSO} "
            "para disparar e localizar o processo...",
            flush=True,
        )

        html_disparo = ag.disparar_relatorio(
            url=url,
            dados=dados,
        )

        debug = (
            Path(PASTA_HTML)
            / f"notas_fiscais_item_post_manual_disparo_tentativa_{tentativa_disparo}.html"
        )

        try:
            debug.write_text(
                html_disparo,
                encoding="latin1",
                errors="replace",
            )
        except Exception:
            pass

        processo = capturar_processo_robusto(
            ag,
            html_disparo,
        )

        if processo:
            print("Processo encontrado:", processo, flush=True)
            break

        texto_disparo = str(html_disparo or "").upper()
        if (
            "SOLICITAÇÃO EFETUADA COM SUCESSO" in texto_disparo
            or "SOLICITACAO EFETUADA COM SUCESSO" in texto_disparo
        ):
            print(
                "O Agrosys aceitou a solicitação, mas ainda não devolveu "
                "o número do processo.",
                flush=True,
            )
        else:
            print(
                "O POST respondeu, mas o número do processo ainda não apareceu.",
                flush=True,
            )

        if tentativa_disparo < TENTATIVAS_ENCONTRAR_PROCESSO:
            print(
                f"Aguardando {ESPERA_ENTRE_DISPAROS} segundos antes de tentar novamente...",
                flush=True,
            )
            time.sleep(ESPERA_ENTRE_DISPAROS)

    if not processo:
        raise Exception(
            "Não encontrei o número do processo após "
            f"{TENTATIVAS_ENCONTRAR_PROCESSO} tentativas. "
            f"Último HTML salvo em {debug}"
        )

    html_relatorio = ag.baixar_relatorio(
        processo=processo,
        referer=url,
        tentativas=None,
        espera=5,
    )

    rel_debug = (
        Path(PASTA_HTML)
        / f"notas_fiscais_item_{processo}.html"
    )

    try:
        rel_debug.write_text(
            html_relatorio,
            encoding="latin1",
            errors="replace",
        )
    except Exception:
        pass

    return html_relatorio, processo


# =============================================================================
# EMPRESAS / ORGANIZAÇÃO DE PASTAS
# =============================================================================

def nome_pasta_seguro(nome):
    """
    Mantém o nome legível da empresa, removendo apenas caracteres inválidos
    para pasta no Windows.
    """
    nome = html_lib.unescape(str(nome or "")).strip()
    nome = re.sub(r'[<>:"/\\|?*]+', " ", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    return nome or "Empresa_Sem_Nome"


def extrair_empresas_do_html(html_tela):
    """
    Lê dinamicamente as opções do select valternativaempresa.
    Assim não precisamos manter códigos das empresas manualmente no robô.
    """
    html_tela = str(html_tela or "")

    bloco = re.search(
        r'<select\b[^>]*(?:id|name)=["\']valternativaempresa["\'][^>]*>(.*?)</select>',
        html_tela,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not bloco:
        raise Exception(
            "Não encontrei o select 'valternativaempresa' na tela do relatório."
        )

    empresas = []

    for valor, descricao in re.findall(
        r'<option\b[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>',
        bloco.group(1),
        flags=re.IGNORECASE | re.DOTALL,
    ):
        valor = html_lib.unescape(valor).strip()
        descricao = re.sub(r"<[^>]+>", "", descricao)
        descricao = html_lib.unescape(descricao)
        descricao = re.sub(r"\s+", " ", descricao).strip()

        # Ignora "<-- Todos -->" e opções vazias.
        if not valor or valor == "0":
            continue

        if "todos" in descricao.casefold() and not re.search(r"\d", descricao):
            continue

        empresas.append(
            {
                "codigo": valor,
                "nome": descricao or f"Empresa {valor}",
            }
        )

    if not empresas:
        raise Exception(
            "A lista de empresas foi localizada, mas nenhuma empresa válida foi encontrada."
        )

    return empresas


def carregar_empresas(ag):
    """
    Abre uma vez a tela real e descobre as empresas disponíveis no próprio
    Agrosys. Isso evita inventar ou manter uma lista fixa.
    """
    ag.configurar_unidade(
        unidade=UNIDADE_RELATORIO,
        menu=MENU_RELATORIO,
        modulo=MODULO_RELATORIO,
    )

    _, html_tela = ag.abrir_tela(
        caminho=CAMINHO_RELATORIO,
        menu=MENU_RELATORIO,
    )

    empresas = extrair_empresas_do_html(html_tela)

    print("", flush=True)
    print("EMPRESAS ENCONTRADAS NO AGROSYS:", flush=True)

    for empresa in empresas:
        print(
            f"  {empresa['codigo']} - {empresa['nome']}",
            flush=True,
        )

    return empresas


def pasta_empresa(empresa):
    pasta = (
        PASTA_SAIDA_BASE
        / nome_pasta_seguro(empresa["nome"])
    )

    pasta.mkdir(
        parents=True,
        exist_ok=True,
    )

    return pasta


def datas_existentes_na_pasta(pasta):
    """
    Procura as datas finais já baixadas pelos nomes dos arquivos.
    Aceita os dois formatos de nome usados no projeto.
    """
    datas = []

    padroes = [
        re.compile(
            r"_ate_(\d{2})-(\d{2})-(\d{4})\.xlsx$",
            re.IGNORECASE,
        ),
        re.compile(
            r"_ate_(\d{4})-(\d{2})-(\d{2})\.xlsx$",
            re.IGNORECASE,
        ),
    ]

    for arquivo in pasta.glob("*.xlsx"):
        nome = arquivo.name

        m = padroes[0].search(nome)
        if m:
            try:
                datas.append(
                    date(
                        int(m.group(3)),
                        int(m.group(2)),
                        int(m.group(1)),
                    )
                )
            except ValueError:
                pass
            continue

        m = padroes[1].search(nome)
        if m:
            try:
                datas.append(
                    date(
                        int(m.group(1)),
                        int(m.group(2)),
                        int(m.group(3)),
                    )
                )
            except ValueError:
                pass

    return datas


def periodos_auto_empresa(empresa):
    """
    REGRA DIÁRIA INCREMENTAL por empresa:

    - usa EXATAMENTE os mesmos filtros/hidden da versão EMPRESAS_AUTO;
    - lê a última data existente na pasta daquela empresa;
    - rebaixa essa última data completa;
    - depois baixa UM ARQUIVO POR DIA até HOJE;
    - não mistura a leitura de uma empresa com outra.

    Regra automática por empresa:

    - lê SOMENTE a pasta daquela empresa;
    - se já existe histórico, rebaixa a última data e segue dia a dia até hoje;
    - se ainda não existe nenhum arquivo, começa no dia 01 do mês atual;
    - cada dia vira um Excel separado.

    Dessa forma cada empresa evolui de maneira independente.
    """
    hoje = date.today()
    pasta = pasta_empresa(empresa)

    datas = datas_existentes_na_pasta(pasta)

    if datas:
        inicio = max(datas)

        if inicio > hoje:
            inicio = hoje

        print(
            f"Última data encontrada para {empresa['nome']}: "
            f"{inicio:%d/%m/%Y}",
            flush=True,
        )
        print(
            "Regra: rebaixar essa data e completar até hoje.",
            flush=True,
        )
    else:
        inicio = hoje.replace(day=1)

        print(
            f"Nenhum arquivo anterior encontrado para {empresa['nome']}.",
            flush=True,
        )
        print(
            f"Primeira carga automática: {inicio:%d/%m/%Y} até {hoje:%d/%m/%Y}.",
            flush=True,
        )

    periodos = []
    atual = inicio

    while atual <= hoje:
        periodos.append((atual, atual))
        atual += timedelta(days=1)

    return periodos


def filtrar_empresas(empresas, valor):
    """
    --empresa pode receber o código exato ou parte do nome.
    Sem --empresa, processa TODAS.
    """
    if not valor:
        return empresas

    alvo = str(valor).strip().casefold()

    por_codigo = [
        e for e in empresas
        if str(e["codigo"]).strip().casefold() == alvo
    ]

    if por_codigo:
        return por_codigo

    por_nome = [
        e for e in empresas
        if alvo in e["nome"].casefold()
    ]

    if not por_nome:
        raise ValueError(
            f"Empresa não encontrada: {valor}"
        )

    return por_nome


def nome_arquivo_empresa(empresa, data_ini, data_fim):
    return (
        "notas_fiscais_item_sem_quebra_"
        f"{data_ini:%d-%m-%Y}_ate_"
        f"{data_fim:%d-%m-%Y}.xlsx"
    )


# =============================================================================
# ARGUMENTOS / EXECUÇÃO
# =============================================================================

def parse_data_br(valor):
    try:
        return datetime.strptime(valor, "%d/%m/%Y").date()
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            "Use DD/MM/AAAA."
        ) from erro


def ler_argumentos():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modo",
        choices=["auto", "periodo", "dias"],
        default="auto",
    )

    parser.add_argument("--inicio", type=parse_data_br)
    parser.add_argument("--fim", type=parse_data_br)
    parser.add_argument("--dias", type=int, default=2)
    parser.add_argument(
        "--empresa",
        type=str,
        default=None,
        help="Código ou parte do nome. Sem informar, baixa todas as empresas.",
    )

    return parser.parse_args()


def montar_periodos(args, empresa):
    hoje = date.today()

    if args.modo == "periodo":
        if not args.inicio or not args.fim:
            raise ValueError("Informe --inicio e --fim.")

        if args.inicio > args.fim:
            raise ValueError("A data inicial não pode ser maior que a final.")

        return [(args.inicio, args.fim)]

    if args.modo == "dias":
        dias = max(args.dias, 1)

        inicio = hoje - timedelta(days=dias - 1)

        return [
            (inicio, hoje)
        ]

    return periodos_auto_empresa(empresa)



def main():
    args = ler_argumentos()

    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )

    ag.login()

    empresas = carregar_empresas(ag)
    empresas = filtrar_empresas(
        empresas,
        args.empresa,
    )

    print("", flush=True)
    print("=" * 80, flush=True)
    print(
        f"EMPRESAS A PROCESSAR: {len(empresas)}",
        flush=True,
    )
    print(
        f"Pasta base: {PASTA_SAIDA_BASE}",
        flush=True,
    )
    print("=" * 80, flush=True)

    driver = criar_driver()

    try:
        copiar_cookies_para_selenium(driver, ag)

        for numero_empresa, empresa in enumerate(empresas, start=1):
            empresa_codigo = empresa["codigo"]
            empresa_nome = empresa["nome"]
            pasta_destino = pasta_empresa(empresa)

            periodos = montar_periodos(
                args,
                empresa,
            )

            print("", flush=True)
            print("#" * 80, flush=True)
            print(
                f"EMPRESA {numero_empresa}/{len(empresas)}: "
                f"{empresa_codigo} - {empresa_nome}",
                flush=True,
            )
            print(
                "Pasta:",
                pasta_destino,
                flush=True,
            )
            print(
                f"Períodos a processar: {len(periodos)}",
                flush=True,
            )
            print("#" * 80, flush=True)

            for numero_periodo, (data_ini, data_fim) in enumerate(
                periodos,
                start=1,
            ):
                print("", flush=True)
                print("=" * 80, flush=True)
                print(NOME_RELATORIO, flush=True)
                print(
                    f"Empresa: {empresa_codigo} - {empresa_nome}",
                    flush=True,
                )
                print(
                    f"Período {numero_periodo}/{len(periodos)}: "
                    f"{data_ini:%d/%m/%Y} até {data_fim:%d/%m/%Y}",
                    flush=True,
                )
                print("Operação: Geral (G)", flush=True)
                print("Tipo de Saída: Relatório Sem Quebra (S)", flush=True)
                print("=" * 80, flush=True)

                html_relatorio, processo = disparar_como_post_manual(
                    ag,
                    data_ini,
                    data_fim,
                    empresa_codigo,
                    empresa_nome,
                )

                url_relatorio = (
                    f"{BASE_AGROSYS}/sistema/reports/"
                    f"{USUARIO_AGROSYS}-{int(processo):010d}.php"
                )

                destino = (
                    pasta_destino
                    / nome_arquivo_empresa(
                        empresa,
                        data_ini,
                        data_fim,
                    )
                )

                # Sincroniza novamente cookies antes de abrir o Excel,
                # pois o POST pode atualizar algum cookie de sessão/contexto.
                copiar_cookies_para_selenium(
                    driver,
                    ag,
                )

                baixar_excel_oficial(
                    driver,
                    url_relatorio,
                    destino,
                )

        print("", flush=True)
        print("=" * 80, flush=True)
        print("ATUALIZAÇÃO FINALIZADA COM SUCESSO", flush=True)
        print("=" * 80, flush=True)

    finally:
        try:
            driver.quit()
        except Exception:
            pass



if __name__ == "__main__":
    main()
