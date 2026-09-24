"""Contas Agrosys e reservas exclusivas entre processos (inclusive via rede)."""
import atexit
import errno
import hashlib
import os
import runpy
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def carregar_config():
    # Caminho explicito: Logistica/config.py nao pode ocultar a configuracao central.
    return runpy.run_path(str(RAIZ / "config.py"))


def contas_configuradas(config, ambiente=None):
    ambiente = os.environ if ambiente is None else ambiente
    contas = []
    vistos = set()
    for numero in range(1, 5):
        sufixo = "" if numero == 1 else f"_{numero}"
        usuario = str(ambiente.get(f"AGROSYS_USUARIO{sufixo}",
                                  config.get(f"USUARIO_AGROSYS{sufixo}", ""))).strip()
        senha = str(ambiente.get(f"AGROSYS_SENHA{sufixo}",
                                config.get(f"SENHA_AGROSYS{sufixo}", "")))
        if not usuario or not senha or usuario.startswith("COLOQUE_") or senha.startswith("COLOQUE_"):
            continue
        if usuario.casefold() in vistos:
            continue
        vistos.add(usuario.casefold())
        contas.append((numero, usuario, senha))
    return contas[:3]


def chave_recurso(valor):
    return hashlib.sha256(str(valor).casefold().encode("utf-8")).hexdigest()[:24]


class ReservaArquivo:
    """O sistema operacional libera a reserva mesmo se o processo for encerrado."""
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.arquivo = None

    def tentar(self):
        if self.arquivo is not None:
            return True
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = self.caminho.open("a+b")
        try:
            arquivo.seek(0, 2)
            if arquivo.tell() == 0:
                arquivo.write(b"0")
                arquivo.flush()
            arquivo.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            arquivo.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        self.arquivo = arquivo
        return True

    def liberar(self):
        if self.arquivo is not None:
            self.arquivo.close()
            self.arquivo = None


class ReservaExecucao:
    def __init__(self, contas, base_url, identidade, pasta_locks=None):
        if not contas:
            raise RuntimeError("Nenhuma conta Agrosys completa no config.py.")
        self.contas = contas
        self.base_url = base_url.rstrip("/")
        self.pasta = Path(pasta_locks) if pasta_locks else RAIZ / ".locks"
        self.robo = ReservaArquivo(self.pasta / f"robo-{chave_recurso(identidade)}.lock")
        self.conta = None
        atexit.register(self.liberar)

    def adquirir(self, espera=2):
        try:
            avisou = False
            while not self.robo.tentar():
                if not avisou:
                    print("Aguardando outra execucao deste mesmo robo finalizar...", flush=True)
                    avisou = True
                time.sleep(espera)
            avisou = False
            while True:
                for numero, usuario, senha in self.contas:
                    chave = chave_recurso(self.base_url + "/" + usuario)
                    reserva = ReservaArquivo(self.pasta / f"conta-{chave}.lock")
                    if reserva.tentar():
                        self.conta = reserva
                        print(f"Conta Agrosys {numero} reservada para esta execucao.", flush=True)
                        return usuario, senha
                if not avisou:
                    print("Todas as contas Agrosys ocupadas. Aguardando uma conta livre...", flush=True)
                    avisou = True
                time.sleep(espera)
        except BaseException:
            self.liberar()
            raise

    def liberar(self):
        if self.conta is not None:
            self.conta.liberar()
            self.conta = None
        self.robo.liberar()
