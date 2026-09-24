"""Portal BI Agent — Granja Brasília.
Versão com todos os robôs cadastrados na whitelist local.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

RAIZ_AGROSYS = Path(__file__).resolve().parents[2] / "Agrosys_Extractor"
sys.path.insert(0, str(RAIZ_AGROSYS))
from Core.agrosys_contas import carregar_config, contas_configuradas

def carregar_env():
    env_file = Path(__file__).resolve().with_name(".env")
    if not env_file.is_file():
        return env_file, False
    with env_file.open("r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            chave = chave.strip()
            valor = valor.strip()
            if chave.lower().startswith("export "):
                chave = chave[7:].strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {'"', "'"}:
                valor = valor[1:-1]
            os.environ.setdefault(chave, valor)
    return env_file, True

ENV_FILE, ENV_CARREGADO = carregar_env()

API_BASE = os.getenv(
    "PORTAL_BI_API_URL",
    "https://portal-bi-granjabrasilia.onrender.com",
).rstrip("/")

AGENT_KEY = str(os.getenv("PORTAL_BI_AGENT_KEY") or "").strip()
AGENT_VERSION = "3.2 - tratamentos independentes por modulo"
MAX_TENTATIVAS_JOB = 3
ESPERA_REPETICAO_JOB = 10
POLL_SECONDS = 5
REQUEST_TIMEOUT = 60
HEARTBEAT_SECONDS = 60
AGENT_ID = str(os.getenv("PORTAL_BI_AGENT_ID") or socket.gethostname()).strip()[:255]

ROBOS = {
    "comercial_faturamento_cfop": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Comercial\comercial_faturamento_cfop.py"),
    "cadastro_de_vendedores": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Comercial\cadastro_de_vendedores.py"),
    "clientes_cadastrados": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Comercial\clientes_cadastrados.py"),
    "indice_zootecnico_mortalidade_peso_lotes_fechados": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Indice Zootecnico\indice_zootecnico_mortalidade_peso_lotes_fechados.py"),
    "indice_zootecnico_mortalidade_peso_lotes_abertos": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Indice Zootecnico\indice_zootecnico_mortalidade_peso_lotes_abertos.py"),
    "indice_zootecnico_base_dinamica": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Indice Zootecnico\indice_zootecnico_base_dinamica.py"),
    "logistica_cadastro_vendedores": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_cadastro_vendedores.py"),
    "logistica_contas_a_pagar": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_contas_a_pagar.py"),
    "logistica_controle_frete": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_controle_frete.py"),
    "logistica_controle_pallets": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_controle_pallets.py"),
    "logistica_devolucoes": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_devolucoes.py"),
    "logistica_faturamento_cfop": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_faturamento_cfop.py"),
    "logistica_frete": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_frete.py"),
    "logistica_ocorrencia_viagens_custo": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_ocorrencia_viagens_custo.py"),
    "logistica_relatorio_veiculos": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Logistica\logistica_relatorio_veiculos.py"),
    "pcp_desperdicio": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_desperdicio.py"),
    "pcp_devolucao": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_devolucao.py"),
    "pcp_diario_industria": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_diario_industria.py"),
    "pcp_diario_industria_avenova_turnos": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_diario_industria_avenova_turnos.py"),
    "pcp_estoque_online": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_estoque_online.py"),
    "pcp_estoque_por_transacao": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_estoque_por_transacao.py"),
    "pcp_movimento_geral_pesagem": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_movimento_geral_pesagem.py"),
    "pcp_plano_producao": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_plano_producao.py"),
    "pcp_relatorio_geral_condenacoes": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\PCP\pcp_relatorio_geral_condenacoes.py"),
    "suprimentos_contas_pagas": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_contas_pagas.py"),
    "suprimentos_notas_fiscais_item": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_notas_fiscais_item.py"),
    "suprimentos_ordens_compras_emitidas": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_ordens_compras_emitidas.py"),
    "suprimentos_relacao_oc_nf": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_relacao_oc_nf.py"),
    "suprimentos_relatorio_usuarios": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_relatorio_usuarios.py"),
    "suprimentos_solicitacoes_requisitante": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_solicitacoes_requisitante.py"),
    "suprimentos_titulos_agrupados": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Agrosys_Extractor\Suprimentos\suprimentos_titulos_agrupados.py"),
    "tratar_comercial": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Python\Comercial\Tratar_Comercial.py"),
    "tratar_zootecnico": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Python\Indice Zootecnico\Tratar_Zootecnico.py"),
    "tratar_logistica": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Python\Logistica\Tratar_Logistica.py"),
    "tratar_pcp": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Python\PCP\tratar_pcp.py"),
    "tratar_suprimentos": Path(r"\\192.168.1.139\Controladoria\BI_Granja\Python\Suprimentos\Tratar_Suprimentos.py"),
}

# Mantem a whitelist e resolve os caminhos na instalacao atual.
ROBOS = {
    codigo: Path(__file__).resolve().parents[2].joinpath(*caminho.parts[caminho.parts.index("BI_Granja") + 1:])
    for codigo, caminho in ROBOS.items()
}

def headers():
    return {
        "X-Agent-Key": AGENT_KEY,
        "X-Agent-Id": AGENT_ID,
        "Content-Type": "application/json",
    }

def claim_job():
    r = requests.post(
        f"{API_BASE}/api/agent/jobs/claim",
        headers=headers(),
        json={"agent_id": AGENT_ID},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("job")

def finish_job(job_id, status, erro=None):
    payload = {"status": status, "agent_id": AGENT_ID}
    if erro:
        payload["erro"] = erro[-20000:]
    r = requests.post(
        f"{API_BASE}/api/agent/jobs/{job_id}/finish",
        headers=headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def heartbeat_job(job_id):
    """Envia ao Render um sinal de vida do job em execução."""
    r = requests.post(
        f"{API_BASE}/api/agent/jobs/{job_id}/heartbeat",
        headers=headers(),
        json={"agent_id": AGENT_ID},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _loop_heartbeat(job_id, parar):
    """
    Mantém o heartbeat enquanto o processo filho estiver executando.
    Falha temporária de rede não encerra o robô; o Agent tenta novamente
    no próximo intervalo.
    """
    while not parar.wait(HEARTBEAT_SECONDS):
        try:
            heartbeat_job(job_id)
            print(
                f"[JOB #{job_id}] Heartbeat enviado ({AGENT_ID}).",
                flush=True,
            )
        except requests.RequestException as e:
            print(
                f"[JOB #{job_id}] AVISO: falha ao enviar heartbeat: {e}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[JOB #{job_id}] AVISO: heartbeat: {type(e).__name__}: {e}",
                flush=True,
            )


# Regras herdadas do atualizador local antigo, adaptadas aos códigos atuais
# cadastrados no Neon.
ROBOS_LOGISTICA_COM_PERIODO = {
    "logistica_frete",
    "logistica_controle_frete",
    "logistica_devolucoes",
    "logistica_ocorrencia_viagens_custo",
    "logistica_faturamento_cfop",
}

ROBOS_PCP_COM_MODO = {
    "pcp_devolucao",
    "pcp_diario_industria",
    "pcp_diario_industria_avenova_turnos",
    "pcp_movimento_geral_pesagem",
    "pcp_relatorio_geral_condenacoes",
}

ROBOS_PCP_DIAS_DIRETO = {
    "pcp_estoque_por_transacao",
}

ROBOS_COMERCIAL_COM_PERIODO = {
    "comercial_faturamento_cfop",
}

ROBOS_SUPRIMENTOS_COM_PERIODO = {
    "suprimentos_contas_pagas",
    "suprimentos_ordens_compras_emitidas",
    "suprimentos_solicitacoes_requisitante",
    "suprimentos_titulos_agrupados",
    "suprimentos_notas_fiscais_item",
}

ROBOS_SUPRIMENTOS_DATAS_DIRETAS = {
    "suprimentos_relacao_oc_nf",
}

ROBOS_ZOOTECNICO_COM_PERIODO = {
    "indice_zootecnico_base_dinamica",
    "indice_zootecnico_mortalidade_peso_lotes_abertos",
    "indice_zootecnico_mortalidade_peso_lotes_fechados",
}

ROBOS_ZOOTECNICO_SEM_PAUSA = {
    "indice_zootecnico_mortalidade_peso_lotes_abertos",
    "indice_zootecnico_mortalidade_peso_lotes_fechados",
}

ROBOS_TRATAMENTO = {
    "tratar_logistica",
    "tratar_pcp",
    "tratar_comercial",
    "tratar_suprimentos",
    "tratar_zootecnico",
}


def _data_br(valor):
    """Aceita YYYY-MM-DD ou DD/MM/YYYY e devolve DD/MM/YYYY."""
    if not valor:
        return None

    valor = str(valor).strip()

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor, formato).strftime("%d/%m/%Y")
        except ValueError:
            pass

    raise ValueError(
        f"Data inválida: {valor}. Use YYYY-MM-DD ou DD/MM/YYYY."
    )


def _periodo_dos_parametros(parametros):
    """Normaliza os parâmetros recebidos do Neon."""
    parametros = parametros if isinstance(parametros, dict) else {}

    modo = str(parametros.get("modo") or "auto").strip().lower()
    if modo in {"automatico", "automático", "auto_pasta"}:
        modo = "auto"

    if modo not in {"auto", "dias", "periodo"}:
        raise ValueError(f"Modo de período inválido: {modo}")

    info = {
        "modo": modo,
        "dias": None,
        "inicio": None,
        "fim": None,
    }

    if modo == "dias":
        try:
            dias = max(1, int(parametros.get("dias")))
        except (TypeError, ValueError):
            raise ValueError("No modo 'dias', informe um número válido em 'dias'.")

        fim = date.today()
        inicio = fim - timedelta(days=dias - 1)

        info.update({
            "dias": dias,
            "inicio": inicio.strftime("%d/%m/%Y"),
            "fim": fim.strftime("%d/%m/%Y"),
        })

    elif modo == "periodo":
        inicio = _data_br(parametros.get("inicio"))
        fim = _data_br(parametros.get("fim"))

        if not inicio or not fim:
            raise ValueError(
                "No modo 'periodo', informe 'inicio' e 'fim'."
            )

        data_inicio = datetime.strptime(inicio, "%d/%m/%Y").date()
        data_fim = datetime.strptime(fim, "%d/%m/%Y").date()

        if data_inicio > data_fim:
            raise ValueError("A data inicial não pode ser maior que a data final.")

        info.update({
            "inicio": inicio,
            "fim": fim,
        })

    return info


def montar_comando(codigo, script, parametros):
    """
    Monta a chamada do robô preservando a lógica do atualizador antigo.
    Robôs que não usam período continuam sendo executados sem argumentos.
    """
    info = _periodo_dos_parametros(parametros)
    modo = info["modo"]
    dias = info["dias"]
    inicio = info["inicio"]
    fim = info["fim"]

    cmd = [sys.executable, "-u", str(script)]

    tratamento_modo = str(
        (parametros or {}).get("tratamento_modo") or "incremental"
    ).strip().lower()

    if codigo in ROBOS_TRATAMENTO and tratamento_modo == "completo":
        cmd.append("--completo")

    if modo == "periodo":
        if (
            codigo in ROBOS_LOGISTICA_COM_PERIODO
            or codigo in ROBOS_PCP_COM_MODO
            or codigo in ROBOS_COMERCIAL_COM_PERIODO
            or codigo in ROBOS_SUPRIMENTOS_COM_PERIODO
            or codigo in ROBOS_ZOOTECNICO_COM_PERIODO
        ):
            cmd += [
                "--modo", "periodo",
                "--inicio", inicio,
                "--fim", fim,
            ]
        elif (
            codigo in ROBOS_SUPRIMENTOS_DATAS_DIRETAS
            or codigo in ROBOS_PCP_DIAS_DIRETO
        ):
            cmd += ["--inicio", inicio, "--fim", fim]

    elif modo == "dias":
        if (
            codigo in ROBOS_LOGISTICA_COM_PERIODO
            or codigo in ROBOS_COMERCIAL_COM_PERIODO
            or codigo in ROBOS_PCP_COM_MODO
            or codigo in ROBOS_ZOOTECNICO_COM_PERIODO
        ):
            cmd += ["--modo", "dias", "--dias", str(dias)]

        elif codigo in ROBOS_SUPRIMENTOS_COM_PERIODO:
            cmd += [
                "--modo", "periodo",
                "--inicio", inicio,
                "--fim", fim,
            ]

        elif codigo in ROBOS_SUPRIMENTOS_DATAS_DIRETAS:
            cmd += ["--inicio", inicio, "--fim", fim]

        elif codigo in ROBOS_PCP_DIAS_DIRETO:
            cmd += ["--dias", str(dias)]

    if codigo in ROBOS_ZOOTECNICO_SEM_PAUSA:
        cmd.append("--sem-pausa")

    if codigo == "tratar_zootecnico":
        cmd.append("--sem-pausa")

    return cmd, info


def montar_ambiente(info):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGROSYS_PERIODO"] = info["modo"]

    if info.get("inicio"):
        env["AGROSYS_DATA_INICIO"] = info["inicio"]
    if info.get("fim"):
        env["AGROSYS_DATA_FIM"] = info["fim"]

    return env


def resumir_falha(stdout, stderr, codigo):
    """Prioriza a causa, em vez do inicio do log com a reserva da conta."""
    linhas = (stdout or "").splitlines()
    relevantes = set()
    for i, linha in enumerate(linhas):
        if any(p in linha.lower() for p in ("erro:", "falha", "exception", "traceback", "timeout")):
            relevantes.update(range(max(0, i - 3), min(len(linhas), i + 4)))
    causa = "\n".join(linhas[i] for i in sorted(relevantes))
    detalhes = (stderr or "").strip()
    if causa:
        detalhes += ("\n" if detalhes else "") + causa
    if not detalhes:
        detalhes = (stdout or "").strip()[-4000:]
    return f"Robo terminou com codigo {codigo}.\n" + detalhes[-14000:]


def gravar_log_tentativa(job_id, tentativa, stdout, stderr):
    try:
        pasta = Path(__file__).resolve().parents[1] / "logs" / "jobs"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"job_{job_id}_tentativa_{tentativa}.log"
        destino.write_text((stdout or "") + "\n--- STDERR ---\n" + (stderr or ""), encoding="utf-8")
        print(f"[JOB #{job_id}] Log completo: {destino}", flush=True)
    except OSError as e:
        print(f"[JOB #{job_id}] Aviso: nao foi possivel gravar o log local: {e}", flush=True)


def executar_job(job):
    job_id = int(job["id"])
    codigo = str(job.get("robo_codigo") or "").strip()
    print(f"\n[JOB #{job_id}] Recebido: {codigo}", flush=True)
    script = ROBOS.get(codigo)
    if script is None or not script.is_file():
        finish_job(job_id, "erro", f"Robo nao configurado ou script ausente: {codigo}")
        return

    try:
        cmd, info_periodo = montar_comando(codigo, script, job.get("parametros") or {})
        env = montar_ambiente(info_periodo)
    except Exception as e:
        finish_job(job_id, "erro", f"Parametros invalidos: {type(e).__name__}: {e}")
        return

    parar = threading.Event()
    heartbeat = threading.Thread(target=_loop_heartbeat, args=(job_id, parar), daemon=True)
    heartbeat.start()
    try:
        erro = ""
        for tentativa in range(1, MAX_TENTATIVAS_JOB + 1):
            print(f"[JOB #{job_id}] Tentativa {tentativa}/{MAX_TENTATIVAS_JOB}: {codigo}", flush=True)
            stdout = stderr = ""
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(script.parent), env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                )
                stdout, stderr = proc.communicate()
                retorno = proc.returncode
            except OSError as e:
                retorno = 1
                stderr = f"Falha ao iniciar o processo: {type(e).__name__}: {e}"
            gravar_log_tentativa(job_id, tentativa, stdout, stderr)
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n", flush=True)
            if stderr:
                print(stderr, end="" if stderr.endswith("\n") else "\n", flush=True)
            if retorno == 0:
                # Falha no envio do resultado nao deve repetir uma extracao concluida.
                finish_job(job_id, "concluido")
                print(f"[JOB #{job_id}] CONCLUIDO na tentativa {tentativa}.", flush=True)
                return
            erro = resumir_falha(stdout, stderr, retorno)
            print(f"[JOB #{job_id}] {erro}", flush=True)
            if tentativa < MAX_TENTATIVAS_JOB:
                espera = ESPERA_REPETICAO_JOB * tentativa
                print(f"[JOB #{job_id}] Nova tentativa automatica em {espera}s.", flush=True)
                time.sleep(espera)
        finish_job(job_id, "erro", f"Falhou apos {MAX_TENTATIVAS_JOB} tentativas automaticas.\n{erro}")
    finally:
        parar.set()
        heartbeat.join(timeout=5)


def executar_fila_paralela(max_workers):
    """Executa jobs liberados pela API, com dependencias e exclusao por modulo."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

    capacidade = max_workers + 5  # Tres contas e um tratamento por modulo; API arbitra as reservas.
    with ThreadPoolExecutor(max_workers=capacidade) as executor:
        ativos = set()
        try:
            while True:
                concluidos = {f for f in ativos if f.done()}
                for futuro in concluidos:
                    try:
                        futuro.result()
                    except Exception as e:
                        print(f"[AGENT] Falha ao acompanhar job: {e}", flush=True)
                ativos -= concluidos
                if len(ativos) >= capacidade:
                    wait(ativos, timeout=POLL_SECONDS, return_when=FIRST_COMPLETED)
                    continue
                try:
                    job = claim_job()
                except requests.RequestException as e:
                    print(f"[CONEXAO] {e}. Nova tentativa em {POLL_SECONDS}s.", flush=True)
                    time.sleep(POLL_SECONDS)
                    continue
                if not job:
                    time.sleep(POLL_SECONDS)
                    continue
                ativos.add(executor.submit(executar_job, job))
        except KeyboardInterrupt:
            print("Encerrando apos finalizar os robos em andamento...", flush=True)


def main():
    if len(AGENT_KEY) < 32:
        raise SystemExit(
            "PORTAL_BI_AGENT_KEY ausente ou inválida. Configure a mesma chave usada no Render."
        )

    print("=" * 64)
    print("PORTAL BI AGENT — Granja Brasília")
    print(f"Versao: {AGENT_VERSION}")
    print(f"API: {API_BASE}")
    print(f"Python: {sys.executable}")
    print(f".env: {ENV_FILE} ({'carregado' if ENV_CARREGADO else 'não encontrado'})")
    print(f"Robôs autorizados: {len(ROBOS)}")
    print(f"Agent ID: {AGENT_ID}")
    print(f"Heartbeat: a cada {HEARTBEAT_SECONDS}s durante a execução")
    print("=" * 64)
    print("Aguardando jobs... Ctrl+C para encerrar.", flush=True)

    contas = contas_configuradas(carregar_config())
    if not contas:
        raise SystemExit("Nenhuma conta Agrosys completa no config.py.")
    print(f"Extracoes paralelas: {len(contas)} conta(s) completa(s).", flush=True)
    executar_fila_paralela(len(contas))

if __name__ == "__main__":
    main()
