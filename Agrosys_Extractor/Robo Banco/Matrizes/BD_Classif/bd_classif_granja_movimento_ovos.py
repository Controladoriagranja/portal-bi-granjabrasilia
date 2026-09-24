# -*- coding: utf-8 -*-
"""
BD_Classif.Granja - Movimento de Ovos - Diário

Fonte Agrosys:
- Programa/tela: wgm600d2
- Módulo observado: 22169
- Menu observado: 22291
- Relatório: Movimento de Ovos - Diário
- Modal de processo: wpd007m1
- Reports: wppd004c

V1:
- faz login usando a estrutura existente do Agrosys_Extractor;
- configura empresa/unidade;
- dispara o relatório com o mesmo POST observado no HAR;
- captura o número do processo diretamente da resposta;
- acompanha o processo pela tela Reports;
- baixa o HTML final;
- salva o HTML para diagnóstico;
- registra a carga em PostgreSQL no schema bd_classif.

A tabela analítica bd_classif.granja será montada na V2 após validarmos
a estrutura real do HTML final do relatório.
"""

import argparse
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PASTA_ROBO = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_ROBO))

from banco_bd_classif import (
    garantir_estrutura,
    registrar_carga,
    importar_granja,
)

def localizar_raiz_agrosys() -> Path:
    atual = Path(__file__).resolve().parent
    for pasta in [atual] + list(atual.parents):
        if (pasta / "config.py").exists() and (pasta / "Core").exists():
            return pasta
    raise RuntimeError(
        "Não encontrei config.py + Core na árvore do Agrosys_Extractor."
    )

RAIZ = localizar_raiz_agrosys()
sys.path.insert(0, str(RAIZ))

from Core.agrosys_runtime import BASE_AGROSYS, USUARIO_AGROSYS, SENHA_AGROSYS, PASTA_HTML
from Core.agrosys_engine import AgrosysEngine

CAMINHO_RELATORIO = "/webpro/webprod/wgm600d2"
CAMINHO_REPORTS = "/webpro/webpad/wppd004c"

MODULO = "22169"
MENU = 22291

# Alvos oficiais do BD_Classif.Granja
ALVOS = [
    {"empresa": "2", "unidade": "1", "nome": "Granja Salome"},
    {"empresa": "2", "unidade": "2", "nome": "Fazenda Santa Lucia"},
    {"empresa": "2", "unidade": "5", "nome": "Granja Cascata"},
    {"empresa": "11", "unidade": "1", "nome": "Granja Alvorada"},
]

PASTA_TEMP = (
    Path(tempfile.gettempdir())
    / "BI_Granja"
    / "BD_Classif"
    / "Granja"
    / "Movimento_Ovos_Diario"
)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)


def log(msg, nivel="INFO"):
    print(f"[{datetime.now():%d/%m/%Y %H:%M:%S}] [{nivel}] {msg}", flush=True)


def argumentos():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--somente-empresa",
        default="",
        help="Opcional. Ex.: 2 ou 11. Sem informar, processa todos os alvos.",
    )
    p.add_argument(
        "--somente-unidade",
        default="",
        help="Opcional. Ex.: 1, 2 ou 5. Use junto com --somente-empresa.",
    )
    p.add_argument(
        "--data-inicial",
        default="",
        help="Opcional. Use junto com --data-final para executar um período manual.",
    )
    p.add_argument(
        "--data-final",
        default="",
        help="Opcional. Use junto com --data-inicial para executar um período manual.",
    )
    p.add_argument("--granja", default="")
    p.add_argument("--lote-pai", default="")
    p.add_argument("--lote-filho", default="")
    p.add_argument(
        "--resumido",
        action="store_true",
        help="Marca 'Resumido por Data'. Por padrão fica desmarcado.",
    )
    p.add_argument(
        "--manter-html",
        action="store_true",
        help="Mantém o HTML final na pasta temporária.",
    )
    return p.parse_args()



def listar_periodos_automaticos():
    """
    Regra padrão:
    1) mês anterior completo;
    2) mês atual do dia 1 até hoje.

    Exemplo em 23/09/2026:
    - 01/08/2026 a 31/08/2026
    - 01/09/2026 a 23/09/2026

    Como o banco usa UPSERT, rebaixar o mês anterior atualiza retroativos
    sem duplicar registros.
    """
    hoje = date.today()
    inicio_atual = hoje.replace(day=1)

    fim_anterior = inicio_atual - timedelta(days=1)
    inicio_anterior = fim_anterior.replace(day=1)

    return [
        {
            "nome": "MÊS ANTERIOR",
            "data_inicial": inicio_anterior.strftime("%d/%m/%Y"),
            "data_final": fim_anterior.strftime("%d/%m/%Y"),
        },
        {
            "nome": "MÊS ATUAL",
            "data_inicial": inicio_atual.strftime("%d/%m/%Y"),
            "data_final": hoje.strftime("%d/%m/%Y"),
        },
    ]


def listar_periodos(a):
    # Se informar as duas datas, executa somente o período manual.
    if a.data_inicial and a.data_final:
        return [{
            "nome": "PERÍODO MANUAL",
            "data_inicial": a.data_inicial,
            "data_final": a.data_final,
        }]

    if a.data_inicial or a.data_final:
        raise RuntimeError(
            "Para período manual informe --data-inicial e --data-final juntos."
        )

    return listar_periodos_automaticos()


def criar_agrosys():
    ag = AgrosysEngine(
        base_url=BASE_AGROSYS,
        usuario=USUARIO_AGROSYS,
        senha=SENHA_AGROSYS,
        pasta_html=PASTA_HTML,
    )
    ag.login()
    return ag


def ajustar_contexto_sessao(ag, empresa_codigo: str, unidade_codigo: str):
    """
    Ajusta o contexto antes de abrir/disparar o wgm600d2.

    O DevTools mostrou que cookies antigos podem continuar com empresa/unidade
    anteriores, enquanto o POST carrega vemp-empresa/vuni-unidade corretos.
    Para evitar qualquer contaminação entre os 4 alvos, removemos os cookies
    de contexto e recriamos com os valores do alvo atual.
    """
    dominio = "sistema.granjabrasilia.com.br"

    ag.configurar_unidade(
        unidade=str(unidade_codigo),
        menu=MENU,
        modulo=MODULO,
    )

    nomes_contexto = {
        "semp-empresa": str(empresa_codigo),
        "empresa": str(empresa_codigo),
        "suni-unidade": str(unidade_codigo),
        "vpad-modulo": str(MODULO),
        "vpad-codmenu": str(MENU),
    }

    # Remove versões antigas/duplicadas desses cookies.
    for cookie in list(ag.session.cookies):
        if cookie.name in nomes_contexto:
            try:
                ag.session.cookies.clear(
                    domain=cookie.domain,
                    path=cookie.path,
                    name=cookie.name,
                )
            except Exception:
                pass

    # Recria host-only e também com domínio explícito.
    for nome, valor in nomes_contexto.items():
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


def validar_alvo_na_resposta(html: str, empresa_codigo: str, unidade_codigo: str):
    """
    Confere se o HTML devolvido pelo Agrosys ficou realmente na empresa/unidade
    solicitadas. Isso evita carregar dados de uma unidade anterior por engano.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    sel_emp = soup.find("select", {"name": "vemp-empresa"})
    sel_uni = soup.find("select", {"name": "vuni-unidade"})

    emp_sel = ""
    uni_sel = ""

    if sel_emp:
        opt = sel_emp.find("option", selected=True)
        if opt:
            emp_sel = str(opt.get("value") or "").strip()

    if sel_uni:
        opt = sel_uni.find("option", selected=True)
        if opt:
            uni_sel = str(opt.get("value") or "").strip()

    if emp_sel and emp_sel != str(empresa_codigo):
        raise RuntimeError(
            f"Empresa incorreta na resposta do Agrosys: esperada "
            f"{empresa_codigo}, retornou {emp_sel}."
        )

    if uni_sel and uni_sel != str(unidade_codigo):
        raise RuntimeError(
            f"Unidade incorreta na resposta do Agrosys: esperada "
            f"{unidade_codigo}, retornou {uni_sel}."
        )

    log(
        f"Contexto validado no HTML | Empresa={emp_sel or empresa_codigo} | "
        f"Unidade={uni_sel or unidade_codigo}"
    )


def extrair_processo_da_resposta(html: str) -> str:
    html = html or ""

    # Forma observada no HAR:
    # wpd007m1?...&vparam=0003825711
    m = re.search(r"vparam=(\d{7,12})", html, re.I)
    if m:
        return str(int(m.group(1)))

    # Fallback: modal já renderizado
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

        m_proc = re.search(
            r"\b(\d{7,12})\b",
            tds[2].get_text(" ", strip=True),
        )
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

        href = m_href.group(1) if m_href else ""

        saida.append({
            "processo": processo,
            "descricao": descricao,
            "programa": programa,
            "pronto": pronto,
            "href": href,
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


def esperar_processo(ag, processo_alvo: str, timeout=600):
    inicio = time.time()

    while time.time() - inicio < timeout:
        try:
            processos = listar_processos_reports(ag)
        except Exception as e:
            log(f"Falha temporária no Reports: {e}", "AVISO")
            time.sleep(10)
            continue

        achado = next(
            (
                p for p in processos
                if str(p["processo"]) == str(processo_alvo)
            ),
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
                f"Processo {processo_alvo} ainda não apareceu no Reports.",
                "INFO",
            )

        time.sleep(10)

    raise TimeoutError(
        f"Processo {processo_alvo} não ficou pronto em {timeout}s."
    )


def baixar_html_final(ag, processo):
    href = processo.get("href") or ""

    if not href:
        # Mesmo padrão já validado nos relatórios do Agrosys.
        usuario = str(USUARIO_AGROSYS).strip()
        href = (
            f"/sistema/reports/"
            f"{usuario}-{int(processo['processo']):010d}.php"
        )

    url = urljoin(BASE_AGROSYS, href)

    for tentativa in range(1, 31):
        resp = ag.session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{BASE_AGROSYS}{CAMINHO_REPORTS}",
                "Cache-Control": "no-cache",
            },
            timeout=60,
        )

        if resp.status_code == 200 and "<html" in (resp.text or "").lower():
            log(
                f"HTML final localizado | processo {processo['processo']} | "
                f"HTTP {resp.status_code}"
            )
            log(f"Página final: {url}")
            return resp.text, url

        log(
            f"HTML final ainda não disponível | tentativa {tentativa}/30 | "
            f"HTTP {resp.status_code}",
            "AVISO",
        )
        time.sleep(5)

    raise TimeoutError(
        f"Não consegui abrir o HTML final do processo {processo['processo']}."
    )


def diagnosticar_html(html: str):
    soup = BeautifulSoup(html or "", "html.parser")
    tabelas = soup.find_all("table")

    log(f"Diagnóstico HTML: {len(tabelas)} tabela(s) encontrada(s).")

    for i, tabela in enumerate(tabelas, start=1):
        linhas = tabela.find_all("tr")
        primeira = ""

        if linhas:
            celulas = linhas[0].find_all(["th", "td"])
            primeira = " | ".join(
                c.get_text(" ", strip=True)
                for c in celulas
            )

        log(
            f"    Tabela {i}: {len(linhas)} linha(s) | "
            f"primeira linha: {primeira[:300]}"
        )



COLUNAS_GRANJA = [
    "data",
    "dia",
    "granja",
    "lote",
    "galpao",
    "linhagem",
    "idade",
    "saldo_femeas",
    "ovos_produzidos",
    "prod_std_pct",
    "prod_real_pct",
    "ninho",
    "ninho_std_pct",
    "ninho_real_pct",
    "cama",
    "cama_std_pct",
    "cama_real_pct",
    "trincado",
    "trincado_std_pct",
    "trincado_real_pct",
    "sujo",
    "sujo_std_pct",
    "sujo_real_pct",
    "duas_gemas",
    "duas_gemas_std_pct",
    "duas_gemas_real_pct",
    "vazado",
    "vazado_std_pct",
    "vazado_real_pct",
    "deformado",
    "deformado_std_pct",
    "deformado_real_pct",
    "pequeno",
    "pequeno_std_pct",
    "pequeno_real_pct",
    "sujoni",
    "sujoni_std_pct",
    "sujoni_real_pct",
    "incubaveis_granja",
    "descarte_incubatorio",
    "perda_pct",
    "incubaveis_incubatorio",
    "aprov_std_pct",
    "aprov_real_pct",
]


def _texto_celula(celula):
    txt = celula.get_text(" ", strip=True)
    txt = txt.replace("\xa0", " ").strip()
    return txt


def _granja_codigo_nome(valor):
    valor = (valor or "").strip()
    m = re.match(r"^\s*(\d+)\s*-\s*(.+?)\s*$", valor)
    if not m:
        return "", valor
    return m.group(1), m.group(2).strip()


def tratar_html_granja(
    html: str,
    processo: str,
    empresa_codigo: str,
    unidade_codigo: str,
):
    """
    Mapeia a tabela principal #tabtop do relatório wgm600r.

    O HTML validado possui:
      - 44 colunas;
      - 3 linhas de cabeçalho;
      - linhas de dados com classe cor1/cor2;
      - uma linha final de Total, que é ignorada.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    tabela = soup.find("table", id="tabtop")

    if tabela is None:
        raise RuntimeError("Não encontrei a tabela principal #tabtop.")

    linhas_saida = []

    for tr in tabela.find_all("tr"):
        classe = tr.get("class") or []

        if not any(c in {"cor1", "cor2"} for c in classe):
            continue

        celulas = tr.find_all(["td", "th"])

        if len(celulas) != 44:
            continue

        valores = [_texto_celula(c) for c in celulas]

        # A primeira coluna precisa ser uma data real.
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", valores[0]):
            continue

        granja_codigo, granja_nome = _granja_codigo_nome(valores[2])

        registro = dict(zip(COLUNAS_GRANJA, valores))
        registro.update({
            "granja_codigo": granja_codigo,
            "granja_nome": granja_nome,
            "empresa_codigo": str(empresa_codigo),
            "unidade_codigo": str(unidade_codigo),
            "processo": str(processo),
        })

        linhas_saida.append(registro)

    if not linhas_saida:
        raise RuntimeError(
            "A tabela #tabtop foi encontrada, mas nenhuma linha analítica "
            "de 44 colunas foi reconhecida."
        )

    log(
        f"HTML analítico tratado | {len(linhas_saida):,} registro(s) | "
        f"primeira data={linhas_saida[0]['data']} | "
        f"última data={linhas_saida[-1]['data']}"
    )

    return linhas_saida


def processar_alvo(
    a,
    empresa_codigo,
    unidade_codigo,
    data_inicial,
    data_final,
    nome_periodo="",
    nome_alvo="",
):
    log("=" * 90)
    log("BD_Classif.Granja - Movimento de Ovos - Diário")
    log(
        f"Empresa={empresa_codigo} | Unidade={unidade_codigo} | "
        f"{nome_alvo} | {nome_periodo} | "
        f"Período={data_inicial} até {data_final}"
    )

    processo_id = ""
    caminho_html = ""
    url_final = ""

    try:
        ag = criar_agrosys()

        ajustar_contexto_sessao(
            ag,
            empresa_codigo=empresa_codigo,
            unidade_codigo=unidade_codigo,
        )

        url_tela, html_tela = ag.abrir_tela(
            caminho=CAMINHO_RELATORIO,
            menu=MENU,
        )

        log(
            f"Tela wgm600d2 aberta | {len(html_tela or ''):,} caracteres"
        )

        validar_alvo_na_resposta(
            html=html_tela,
            empresa_codigo=empresa_codigo,
            unidade_codigo=unidade_codigo,
        )

        payload = {
            "vdata-ini": data_inicial,
            "vdata-fim": data_final,
            "vcli-codigo": a.granja,
            "vrec-lote-pai": a.lote_pai,
            "vrec-lote": a.lote_filho,
            "vemp-empresa": str(empresa_codigo),
            "vuni-unidade": str(unidade_codigo),
            "vpad-btdisp.x": "Disparar",
        }

        if a.resumido:
            payload["vcheck"] = "yes"

        log(
            f"Payload alvo | Empresa={empresa_codigo} | "
            f"Unidade={unidade_codigo} | "
            f"Data={data_inicial} até {data_final}"
        )

        log(
            "Disparando relatório | "
            f"granja={a.granja or 'TODAS'} | "
            f"lote_pai={a.lote_pai or 'TODOS'} | "
            f"lote_filho={a.lote_filho or 'TODOS'} | "
            f"resumido={'SIM' if a.resumido else 'NÃO'}"
        )

        html_retorno = ag.disparar_relatorio(
            url=url_tela,
            dados=payload,
        )

        validar_alvo_na_resposta(
            html=html_retorno,
            empresa_codigo=empresa_codigo,
            unidade_codigo=unidade_codigo,
        )

        processo_id = extrair_processo_da_resposta(html_retorno)

        if not processo_id:
            debug = PASTA_TEMP / "DEBUG_disparo_sem_processo.html"
            debug.write_text(
                html_retorno or "",
                encoding="utf-8",
                errors="ignore",
            )
            raise RuntimeError(
                "O Agrosys respondeu ao disparo, mas não encontrei o número "
                f"do processo. Resposta salva em: {debug}"
            )

        log(f"Processo criado: {processo_id}")

        registrar_carga(
            processo=processo_id,
            empresa=empresa_codigo,
            unidade=unidade_codigo,
            data_inicial=data_inicial,
            data_final=data_final,
            status="AGUARDANDO",
        )

        processo = esperar_processo(
            ag=ag,
            processo_alvo=processo_id,
        )

        html_final, url_final = baixar_html_final(
            ag=ag,
            processo=processo,
        )

        caminho = (
            PASTA_TEMP
            / f"movimento_ovos_diario_{processo_id}.html"
        )
        caminho.write_text(
            html_final,
            encoding="utf-8",
            errors="ignore",
        )
        caminho_html = str(caminho)

        diagnosticar_html(html_final)

        registros = tratar_html_granja(
            html=html_final,
            processo=processo_id,
            empresa_codigo=empresa_codigo,
            unidade_codigo=unidade_codigo,
        )

        qtd_importada = importar_granja(registros)

        log(
            f"SUCESSO: {qtd_importada:,} registros carregados/atualizados "
            "em bd_classif.granja."
        )

        registrar_carga(
            processo=processo_id,
            empresa=empresa_codigo,
            unidade=unidade_codigo,
            data_inicial=data_inicial,
            data_final=data_final,
            status="PRONTO",
            programa=processo.get("programa", ""),
            descricao=processo.get("descricao", ""),
            url_final=url_final,
            caminho_html=caminho_html,
        )

        log("=" * 90)
        log("CAPTURA CONCLUÍDA COM SUCESSO.")
        log(f"Processo: {processo_id}")
        log(f"HTML salvo em: {caminho_html}")
        log("Tabela analítica atualizada: bd_classif.granja")
        return qtd_importada

    except Exception as e:
        try:
            if processo_id:
                registrar_carga(
                    processo=processo_id,
                    empresa=empresa_codigo,
                    unidade=unidade_codigo,
                    data_inicial=data_inicial,
                    data_final=data_final,
                    status="ERRO",
                    url_final=url_final,
                    caminho_html=caminho_html,
                    erro=str(e),
                )
        except Exception:
            pass

        log(f"{type(e).__name__}: {e}", "ERRO")
        traceback.print_exc()
        raise


def main():
    a = argumentos()
    garantir_estrutura()

    alvos = list(ALVOS)

    if a.somente_empresa:
        alvos = [
            x for x in alvos
            if str(x["empresa"]) == str(a.somente_empresa)
        ]

    if a.somente_unidade:
        alvos = [
            x for x in alvos
            if str(x["unidade"]) == str(a.somente_unidade)
        ]

    if not alvos:
        raise RuntimeError(
            "Nenhum alvo corresponde aos filtros informados. "
            "Alvos válidos: Empresa 2/Unidades 1,2,5 e Empresa 11/Unidade 1."
        )

    periodos = listar_periodos(a)

    log("=" * 90)
    log("INICIANDO CARGA COMPLETA BD_Classif.Granja")
    log(
        "Alvos: "
        + ", ".join(
            f"Emp {x['empresa']} / Uni {x['unidade']}"
            for x in alvos
        )
    )
    log(
        "Períodos: "
        + " | ".join(
            f"{p['nome']}: {p['data_inicial']} a {p['data_final']}"
            for p in periodos
        )
    )

    total = 0
    falhas = []
    total_execucoes = len(periodos) * len(alvos)
    execucao = 0

    # Primeiro rebaixa o mês anterior inteiro; depois atualiza o mês atual.
    for periodo in periodos:
        log("=" * 90)
        log(
            f"INICIANDO {periodo['nome']} | "
            f"{periodo['data_inicial']} a {periodo['data_final']}"
        )

        for alvo in alvos:
            execucao += 1
            log("=" * 90)
            log(
                f"EXECUÇÃO {execucao}/{total_execucoes} | "
                f"{periodo['nome']} | "
                f"Empresa {alvo['empresa']} / Unidade {alvo['unidade']} | "
                f"{alvo['nome']}"
            )

            try:
                total += processar_alvo(
                    a=a,
                    empresa_codigo=alvo["empresa"],
                    unidade_codigo=alvo["unidade"],
                    data_inicial=periodo["data_inicial"],
                    data_final=periodo["data_final"],
                    nome_periodo=periodo["nome"],
                    nome_alvo=alvo["nome"],
                )
            except Exception as e:
                falha = (
                    f"{periodo['nome']} | Empresa {alvo['empresa']} / "
                    f"Unidade {alvo['unidade']}: "
                    f"{type(e).__name__}: {e}"
                )
                falhas.append(falha)
                log(falha, "ERRO")

    log("=" * 90)
    log(f"FINALIZADO | Total carregado/atualizado: {total:,}")

    if falhas:
        log(f"Falhas: {len(falhas)}", "ERRO")
        for f in falhas:
            log(f"  {f}", "ERRO")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
