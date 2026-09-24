# -*- coding: utf-8 -*-
"""
BD_Aproveit.Inc - Aproveitamento Incubatório
Relatório Agrosys: wib166d1

Configuração observada:
- Menu: 22143
- Módulo Matrizes e Poedeiras: 22169
- Programa selecionado: wib166a2.p = Consolidado por Data e Lote
- Período automático: primeiro dia de 6 meses atrás até hoje
- Lote: Todos
- Granja: Todas
- Separar por Tipo: Não
- Consolidar Empresa: Não

V1:
- login;
- abre o relatório;
- calcula período automático;
- dispara;
- captura processo;
- acompanha Reports;
- baixa HTML final;
- salva HTML para diagnóstico;
- registra carga no PostgreSQL.

A tabela analítica bd_aproveit.inc será criada na V2 após mapearmos
o HTML final real do processo.
"""

import argparse
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

PASTA_ROBO = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_ROBO))

from banco_bd_aproveit import garantir_estrutura, registrar_carga


def localizar_raiz_agrosys() -> Path:
    atual = Path(__file__).resolve().parent
    for pasta in [atual] + list(atual.parents):
        if (pasta / "config.py").exists() and (pasta / "Core").exists():
            return pasta
    raise RuntimeError("Não encontrei config.py + Core na árvore do Agrosys_Extractor.")


RAIZ = localizar_raiz_agrosys()
sys.path.insert(0, str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

CAMINHO_RELATORIO = "/webpro/webprod/wib166d1"
CAMINHO_REPORTS = "/webpro/webpad/wppd004c"

MENU = 22143
MODULO = "22087"
PROGRAMA = "wib166a2.p"
EMPRESA = "2"
UNIDADE = "12"  # Incubatório

PASTA_TEMP = (
    Path(tempfile.gettempdir())
    / "BI_Granja"
    / "Matrizes"
    / "BD_Aproveit"
    / "Inc"
)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)


def log(msg, nivel="INFO"):
    print(f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{nivel}] {msg}", flush=True)


def subtrair_meses(data_ref: date, meses: int) -> date:
    ano = data_ref.year
    mes = data_ref.month - meses

    while mes <= 0:
        mes += 12
        ano -= 1

    return date(ano, mes, 1)


def periodo_automatico():
    """
    TESTE:
    mês anterior completo + mês atual até hoje.

    Exemplo em 24/09/2026:
    01/08/2026 até 24/09/2026.
    """
    hoje = date.today()
    inicio = subtrair_meses(hoje, 1)
    return inicio, hoje


def argumentos():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--data-inicial",
        default="",
        help="Opcional. Use junto com --data-final para período manual DD/MM/AAAA.",
    )
    p.add_argument(
        "--data-final",
        default="",
        help="Opcional. Use junto com --data-inicial para período manual DD/MM/AAAA.",
    )
    p.add_argument(
        "--manter-html",
        action="store_true",
        help="Mantém o HTML final para diagnóstico.",
    )
    return p.parse_args()


def resolver_periodo(a):
    if a.data_inicial or a.data_final:
        if not (a.data_inicial and a.data_final):
            raise RuntimeError(
                "Para período manual informe --data-inicial e --data-final juntos."
            )

        ini = datetime.strptime(a.data_inicial, "%d/%m/%Y").date()
        fim = datetime.strptime(a.data_final, "%d/%m/%Y").date()

        if ini > fim:
            raise RuntimeError("A data inicial não pode ser maior que a data final.")

        return ini, fim, "PERÍODO MANUAL"

    ini, fim = periodo_automatico()
    return ini, fim, "TESTE - MÊS ANTERIOR + MÊS ATUAL"


def criar_agrosys():
    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )
    ag.login()
    return ag


def ajustar_contexto_sessao(ag):
    """
    Contexto REAL observado no DevTools do relatório:

    empresa = 2
    unidade = 12 (Incubatório)
    módulo = 22087
    menu = 22143

    O relatório não envia empresa/unidade no POST; portanto esses valores
    precisam estar corretos na sessão/cookies antes de abrir wib166d1.
    """
    dominio = "sistema.granjabrasilia.com.br"

    # Primeiro usa a rotina padrão do AgrosysEngine.
    ag.configurar_unidade(
        unidade=UNIDADE,
        menu=MENU,
        modulo=MODULO,
    )

    contexto = {
        "semp-empresa": EMPRESA,
        "empresa": EMPRESA,
        "suni-unidade": UNIDADE,
        "vpad-modulo": MODULO,
        "vpad-codmenu": str(MENU),
    }

    # Remove versões antigas/duplicadas dos cookies de contexto.
    for cookie in list(ag.session.cookies):
        if cookie.name in contexto:
            try:
                ag.session.cookies.clear(
                    domain=cookie.domain,
                    path=cookie.path,
                    name=cookie.name,
                )
            except Exception:
                pass

    # Regrava contexto como host-only e também no domínio explícito.
    for nome, valor in contexto.items():
        try:
            ag.session.cookies.set(nome, valor, path="/")
        except Exception:
            pass
        try:
            ag.session.cookies.set(
                nome,
                valor,
                domain=dominio,
                path="/",
            )
        except Exception:
            pass

    log(
        f"Contexto Agrosys configurado | "
        f"empresa={EMPRESA} | unidade={UNIDADE} | "
        f"módulo={MODULO} | menu={MENU}"
    )


def validar_contexto_sessao(ag):
    """
    Mostra os valores efetivos da sessão antes do disparo.
    """
    valores = {}

    for nome in (
        "semp-empresa",
        "empresa",
        "suni-unidade",
        "vpad-modulo",
        "vpad-codmenu",
    ):
        encontrados = [
            c.value
            for c in ag.session.cookies
            if c.name == nome
        ]
        valores[nome] = encontrados[-1] if encontrados else ""

    log(
        "Cookies efetivos | "
        f"semp-empresa={valores['semp-empresa']} | "
        f"suni-unidade={valores['suni-unidade']} | "
        f"vpad-modulo={valores['vpad-modulo']} | "
        f"vpad-codmenu={valores['vpad-codmenu']}"
    )

    erros = []

    if valores["semp-empresa"] and valores["semp-empresa"] != EMPRESA:
        erros.append(
            f"semp-empresa esperado={EMPRESA}, recebido={valores['semp-empresa']}"
        )

    if valores["suni-unidade"] and valores["suni-unidade"] != UNIDADE:
        erros.append(
            f"suni-unidade esperado={UNIDADE}, recebido={valores['suni-unidade']}"
        )

    if valores["vpad-modulo"] and valores["vpad-modulo"] != MODULO:
        erros.append(
            f"vpad-modulo esperado={MODULO}, recebido={valores['vpad-modulo']}"
        )

    if erros:
        raise RuntimeError(
            "Contexto do Agrosys incorreto antes do disparo: "
            + " | ".join(erros)
        )


def extrair_processo(html: str) -> str:
    html = html or ""

    m = re.search(r"vparam=(\d{7,12})", html, re.I)
    if m:
        return str(int(m.group(1)))

    m = re.search(
        r'id=["\']vbatnump["\'][^>]*value=["\'](\d{7,12})["\']',
        html,
        re.I,
    )
    if m:
        return str(int(m.group(1)))

    return ""


def extrair_processos_reports(html: str):
    soup = BeautifulSoup(html or "", "html.parser")
    tabela = soup.find("table", id="vtabela")
    if tabela is None:
        return []

    saida = []

    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        m_proc = re.search(r"\b(\d{7,12})\b", tds[2].get_text(" ", strip=True))
        if not m_proc:
            continue

        processo = m_proc.group(1)
        descricao = tds[3].get_text(" ", strip=True)
        programa = tds[7].get_text(" ", strip=True)

        img = tds[1].find("img")
        src_img = (img.get("src") or "") if img else ""
        pronto = "verde" in src_img.lower()

        html_proc = str(tds[2])
        m_href = re.search(
            r"(/sistema/reports/[A-Za-z0-9._-]+-\d+\.(?:php|html?))",
            html_proc,
            re.I,
        )

        saida.append({
            "processo": processo,
            "descricao": descricao,
            "programa": programa,
            "pronto": pronto,
            "href": m_href.group(1) if m_href else "",
        })

    return saida


def listar_processos_reports(ag):
    url = f"{BASE_AGROSYS}{CAMINHO_REPORTS}"
    resp = ag.session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{BASE_AGROSYS}/webpro/webpad/wpadmenu",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
        timeout=60,
    )
    resp.raise_for_status()

    processos = extrair_processos_reports(resp.text)
    log(f"Reports: {len(processos)} processo(s) visíveis.")
    return processos



def tentar_html_final_direto(ag, processo_alvo: str):
    """
    Tenta localizar o relatório final diretamente pelo número do processo.

    A tela Reports pode retornar 0 processos mesmo com o relatório ainda
    sendo processado. Nesse caso NÃO redisparamos.
    """
    proc10 = f"{int(processo_alvo):010d}"

    candidatos = [
        f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{proc10}.php",
        f"{BASE_AGROSYS}/sistema/reports/powerbi-{proc10}.php",
    ]

    for url in candidatos:
        try:
            resp = ag.session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{BASE_AGROSYS}{CAMINHO_REPORTS}",
                    "Cache-Control": "no-cache",
                    "Connection": "close",
                },
                timeout=60,
            )
        except Exception:
            continue

        html = resp.text or ""
        h = html.lower()

        if resp.status_code != 200:
            continue

        # Não confundir páginas de login/erro com relatório pronto.
        if "acesso ao modulo agroweb" in h or "acesso não autorizado" in h:
            continue

        parece_relatorio = (
            "<html" in h
            and "<table" in h
            and (
                "classificação de ovos" in h
                or "classificacao de ovos" in h
                or "wib166" in h
            )
        )

        if parece_relatorio:
            return {
                "processo": str(processo_alvo),
                "descricao": "Classificação de Ovos",
                "programa": PROGRAMA,
                "pronto": True,
                "href": url.replace(BASE_AGROSYS, ""),
                "_html_final_direto": html,
                "_url_final_direto": url,
            }

    return None


def esperar_processo(ag, processo_alvo: str, timeout=3600):
    inicio = time.time()
    reports_vazios = 0

    while time.time() - inicio < timeout:
        # Primeiro tenta o HTML final diretamente.
        direto = tentar_html_final_direto(
            ag=ag,
            processo_alvo=processo_alvo,
        )
        if direto:
            log(
                f"Processo {processo_alvo} localizado diretamente no HTML final. "
                "Considerando PRONTO."
            )
            return direto

        try:
            processos = listar_processos_reports(ag)
        except Exception as e:
            log(f"Falha temporária no Reports: {e}", "AVISO")
            processos = []

        if not processos:
            reports_vazios += 1
            log(
                f"Reports retornou 0 processos "
                f"({reports_vazios} vez(es) consecutiva(s)). "
                "Continuarei aguardando sem redisparar.",
                "AVISO",
            )

            if reports_vazios >= 3:
                log(
                    "Reports segue vazio. Renovando somente a sessão "
                    "e restaurando o contexto do Incubatório.",
                    "AVISO",
                )
                try:
                    ag.login()
                    ajustar_contexto_sessao(ag)
                    validar_contexto_sessao(ag)
                except Exception as e:
                    log(f"Falha ao renovar sessão: {e}", "AVISO")

                reports_vazios = 0

            time.sleep(20)
            continue

        reports_vazios = 0

        achado = next(
            (p for p in processos if str(p["processo"]) == str(processo_alvo)),
            None,
        )

        if achado:
            log(
                f"Processo {processo_alvo} | "
                f"programa={achado.get('programa','')} | "
                f"{'PRONTO' if achado.get('pronto') else 'AGUARDANDO'} | "
                f"{achado.get('descricao','')}"
            )
            if achado.get("pronto"):
                return achado
        else:
            log(
                f"Processo {processo_alvo} não está na lista atual do Reports. "
                "Continuarei testando o HTML final diretamente.",
                "AVISO",
            )

        time.sleep(20)

    raise TimeoutError(
        f"Processo {processo_alvo} não ficou pronto em {timeout}s."
    )

def baixar_html_final(ag, processo):
    if processo.get("_html_final_direto"):
        html = processo["_html_final_direto"]
        url = processo.get("_url_final_direto", "")
        log(
            f"HTML final reutilizado | processo {processo['processo']} | HTTP 200"
        )
        log(f"Página final: {url}")
        return html, url

    href = processo.get("href") or ""

    candidatos = []

    if href:
        candidatos.append(urljoin(BASE_AGROSYS, href))

    proc10 = f"{int(processo['processo']):010d}"
    candidatos.extend([
        f"{BASE_AGROSYS}/sistema/reports/{USUARIO_AGROSYS}-{proc10}.php",
        f"{BASE_AGROSYS}/sistema/reports/powerbi-{proc10}.php",
    ])

    vistos = set()
    candidatos = [x for x in candidatos if not (x in vistos or vistos.add(x))]

    for tentativa in range(1, 121):
        for url in candidatos:
            try:
                resp = ag.session.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": f"{BASE_AGROSYS}{CAMINHO_REPORTS}",
                        "Cache-Control": "no-cache",
                        "Connection": "close",
                    },
                    timeout=60,
                )
            except Exception:
                continue

            html = resp.text or ""

            if resp.status_code == 200 and "<html" in html.lower() and "<table" in html.lower():
                log(
                    f"HTML final localizado | processo {processo['processo']} | "
                    f"HTTP {resp.status_code}"
                )
                log(f"Página final: {url}")
                return html, url

        log(
            f"HTML final ainda não disponível | tentativa {tentativa}/120",
            "AVISO",
        )
        time.sleep(10)

    raise TimeoutError(
        f"Não consegui localizar o HTML final do processo {processo['processo']}."
    )


def diagnosticar_html(html: str):
    soup = BeautifulSoup(html or "", "html.parser")
    tabelas = soup.find_all("table")

    log(f"Diagnóstico HTML: {len(tabelas)} tabela(s) encontrada(s).")

    for i, tabela in enumerate(tabelas, start=1):
        linhas = tabela.find_all("tr")
        amostra = ""

        for tr in linhas[:5]:
            cels = tr.find_all(["th", "td"])
            texto = " | ".join(c.get_text(" ", strip=True) for c in cels)
            if texto.strip():
                amostra = texto
                break

        log(
            f"    Tabela {i}: {len(linhas)} linha(s) | "
            f"amostra: {amostra[:400]}"
        )


def main():
    a = argumentos()
    garantir_estrutura()

    inicio, fim, nome_periodo = resolver_periodo(a)

    log("=" * 90)
    log("BD_Aproveit.Inc - Aproveitamento Incubatório")
    log(
        f"{nome_periodo}: {inicio:%d/%m/%Y} até {fim:%d/%m/%Y}"
    )
    log("Relatório: Consolidado por Data e Lote | timeout máximo do processo: 60 minutos")
    log("Lote=TODOS | Granja=TODAS | Separar por Tipo=NÃO | Consolidar Empresa=NÃO")
    log(f"Contexto fixo: Empresa {EMPRESA} | Unidade {UNIDADE} - Incubatório | Módulo {MODULO}")

    processo_id = ""
    caminho_html = ""
    url_final = ""

    try:
        ag = criar_agrosys()
        ajustar_contexto_sessao(ag)
        validar_contexto_sessao(ag)

        url_tela, html_tela = ag.abrir_tela(
            caminho=CAMINHO_RELATORIO,
            menu=MENU,
        )

        log(
            f"Tela wib166d1 aberta | {len(html_tela or ''):,} caracteres"
        )

        payload = {
            "vpardate1": inicio.strftime("%d/%m/%Y"),
            "vpardate2": fim.strftime("%d/%m/%Y"),
            "vprograma": PROGRAMA,
            "vparchar1": "",
            "vparint1": "",
            # vparlog1 omitido = Separar por Tipo NÃO
            # vcon-emp omitido  = Consolidar Empresa NÃO
            "vpad-btdisp.x": "Disparar",
        }

        log(
            "Payload | "
            f"vpardate1={payload['vpardate1']} | "
            f"vpardate2={payload['vpardate2']} | "
            f"vprograma={payload['vprograma']}"
        )

        html_retorno = ag.disparar_relatorio(
            url=url_tela,
            dados=payload,
        )

        processo_id = extrair_processo(html_retorno)

        if not processo_id:
            debug = PASTA_TEMP / "DEBUG_disparo_sem_processo.html"
            debug.write_text(
                html_retorno or "",
                encoding="utf-8",
                errors="ignore",
            )
            raise RuntimeError(
                "O Agrosys respondeu ao disparo, mas não encontrei o processo. "
                f"Resposta salva em: {debug}"
            )

        log(f"Processo criado: {processo_id}")

        registrar_carga(
            processo=processo_id,
            data_inicial=inicio,
            data_final=fim,
            status="AGUARDANDO",
            programa=PROGRAMA,
        )

        processo = esperar_processo(
            ag=ag,
            processo_alvo=processo_id,
        )

        html_final, url_final = baixar_html_final(
            ag=ag,
            processo=processo,
        )

        caminho = PASTA_TEMP / f"bd_aproveit_inc_{processo_id}.html"
        caminho.write_text(
            html_final,
            encoding="utf-8",
            errors="ignore",
        )
        caminho_html = str(caminho)

        diagnosticar_html(html_final)

        registrar_carga(
            processo=processo_id,
            data_inicial=inicio,
            data_final=fim,
            status="PRONTO",
            programa=processo.get("programa") or PROGRAMA,
            descricao=processo.get("descricao", ""),
            url_final=url_final,
            caminho_html=caminho_html,
        )

        log("=" * 90)
        log("CAPTURA CONCLUÍDA COM SUCESSO.")
        log(f"Processo: {processo_id}")
        log(f"HTML salvo em: {caminho_html}")
        log("Próximo passo: mapear o HTML final para bd_aproveit.inc.")

    except Exception as e:
        try:
            if processo_id:
                registrar_carga(
                    processo=processo_id,
                    data_inicial=inicio,
                    data_final=fim,
                    status="ERRO",
                    programa=PROGRAMA,
                    url_final=url_final,
                    caminho_html=caminho_html,
                    erro=str(e),
                )
        except Exception:
            pass

        log(f"{type(e).__name__}: {e}", "ERRO")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
