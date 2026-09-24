"""Configuracao por processo, compartilhada por todos os robos ativos."""
import sys
import tempfile
from pathlib import Path
from Core.agrosys_contas import (
    RAIZ, ReservaExecucao, carregar_config, chave_recurso, contas_configuradas,
)

_config = carregar_config()
BASE_AGROSYS = _config["BASE_AGROSYS"]
_script = Path(sys.argv[0]).resolve()
try:
    _identidade = str(_script.relative_to(RAIZ))
except ValueError:
    _identidade = _script.name
_recurso = _identidade
if "_HISTORICO_" in _script.stem:
    _recurso = str(_script.parent.relative_to(RAIZ) / (_script.stem.split("_HISTORICO_")[0] + ".py"))
elif _script.name == "indice_zootecnico_movimento_mortalidade_peso_lotes_aberto.py":
    _recurso = str(Path("Indice Zootecnico") / "indice_zootecnico_mortalidade_peso_lotes_abertos.py")
elif _script.name == "suprimentos_notas_fiscais_item_atualizado (1).py":
    _recurso = str(Path("Suprimentos") / "suprimentos_notas_fiscais_item.py")
_reserva = ReservaExecucao(contas_configuradas(_config), BASE_AGROSYS, _recurso)
USUARIO_AGROSYS, SENHA_AGROSYS = _reserva.adquirir()
# Pastas estaveis por robo; a reserva impede duas execucoes do mesmo robo.
_chave = chave_recurso(_identidade)
PASTA_HTML = RAIZ / "html" / "execucoes" / _chave
# O Chrome grava localmente; o robo transfere o arquivo pronto para a rede.
PASTA_DOWNLOAD = Path(tempfile.gettempdir()) / "BI_Granja" / "downloads" / _chave
