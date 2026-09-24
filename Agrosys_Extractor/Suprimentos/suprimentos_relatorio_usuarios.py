# -*- coding: utf-8 -*-
import sys, time, shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
sys.path.append(str(RAIZ))
from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

PASTA_SAIDA = Path(r"\\192.168.1.139\Controladoria\BI_Granja\Exportacoes\Suprimentos\Relatorio de Usuarios")
from Core.agrosys_runtime import PASTA_DOWNLOAD
PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_DOWNLOAD.mkdir(parents=True, exist_ok=True)
ARQUIVO_SAIDA = PASTA_SAIDA / "Relatorio_de_Usuarios.xlsx"

def criar_driver():
    o = Options()

    prefs = {
        "download.default_directory": str(PASTA_DOWNLOAD),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }

    o.add_experimental_option("prefs", prefs)
    o.add_argument("--headless=new")
    o.add_argument("--disable-gpu")
    o.add_argument("--window-size=1920,1080")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-extensions")
    o.add_argument("--disable-notifications")
    o.add_argument("--disable-popup-blocking")

    driver = webdriver.Chrome(options=o)

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
    for a in PASTA_DOWNLOAD.glob("*"):
        try:
            if a.is_file(): a.unlink()
        except Exception: pass

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


def baixar_excel_oficial(driver, url_relatorio, destino):
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

    destino.parent.mkdir(parents=True, exist_ok=True)

    if destino.exists():
        destino.unlink()

    shutil.move(str(baixado), str(destino))

    if not destino.exists() or destino.stat().st_size <= 0:
        raise Exception(
            "O Excel foi baixado, mas não foi salvo corretamente na pasta final."
        )

    print(
        f"Excel oficial salvo em {time.time() - inicio_download:.1f}s:",
        destino,
        flush=True,
    )


def main():
    ag=AgrosysEngine(base_url=BASE_AGROSYS, usuario=USUARIO_AGROSYS, senha=SENHA_AGROSYS, pasta_html=PASTA_HTML)
    ag.login(); driver=criar_driver()
    try:
        copiar_cookies_para_selenium(driver, ag)
        filtros={"vativo":"3","vusu-hierarq":"","vemp-empresa":"0","vuni-unidade":"0","vsemlogin":"","vdiasacesso":"","vpad-btdisp.x":"Disparar"}
        html, processo=ag.executar_relatorio(caminho="/webpro/webcad/wppd002d", menu=1194, unidade="1", filtros=filtros, nome_debug="suprimentos_relatorio_usuarios", modulo="1000")
        url=f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{int(processo):010d}.php"
        baixar_excel_oficial(driver,url,ARQUIVO_SAIDA)
        print("RELATÓRIO DE USUÁRIOS FINALIZADO")
    finally: driver.quit()

if __name__ == "__main__": main()
