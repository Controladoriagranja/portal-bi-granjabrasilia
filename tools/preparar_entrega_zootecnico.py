"""Atualiza o ZIP original, conservando sua estrutura e arquivos; sem publicação."""
from copy import copy
import difflib
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=Path.home()/'Downloads/api_zootecnico(3).zip'
DELIVERY=ROOT/'integrations/zootecnico/entrega'
API=ROOT/'integrations/zootecnico/api'
CONFIRMED_BASE_SHA256='3e8110d7b9855e9cb521b857f57ae6b195e26c73bfeba1f0a6ad4da91bbd9300'
API_FILES=('servico_zootecnico.py','portal_router.py','Dockerfile.zootecnico','zootecnico_acesso.py')
PACKAGE_NAME='api_zootecnico_atualizada.zip'


def original_docker_with_new_module(original):
    """Mesmo Dockerfile, mesmos bytes: somente um COPY necessário é inserido."""
    anchor=b'COPY API/api_zootecnico/servico_zootecnico.py .'
    if original.count(anchor)!=1:
        raise ValueError('COPY do serviço não corresponde ao Dockerfile confirmado.')
    end=original.index(anchor)+len(anchor)
    tail=original[end:]
    newline=next((nl for nl in (b'\r\r\n',b'\r\n',b'\n') if tail.startswith(nl)),None)
    if newline is None:raise ValueError('Fim de linha do Dockerfile não reconhecido.')
    return original[:end]+newline+b'COPY API/api_zootecnico/zootecnico_acesso.py .'+original[end:]


def integration_patch():
    parts=[]
    with ZipFile(ARCHIVE) as source:
        for name in ('servico_zootecnico.py','portal_router.py','Dockerfile.zootecnico'):
            old=source.read('api_zootecnico/'+name).decode('utf-8-sig').replace('\r\r\n','\n').replace('\r\n','\n')
            new=(API/name).read_text(encoding='utf-8')
            parts.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                 fromfile='a/API/api_zootecnico/'+name,tofile='b/API/api_zootecnico/'+name))
    return ''.join(parts)


def prepare():
    base_hash=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if base_hash!=CONFIRMED_BASE_SHA256:
        raise ValueError('O ZIP mudou desde a confirmação do usuário. Pacote não sobrescrito.')
    DELIVERY.mkdir(parents=True,exist_ok=True)
    patch=integration_patch()
    (DELIVERY/'integracao_api.patch').write_text(patch,encoding='utf-8')
    package=DELIVERY/PACKAGE_NAME
    with ZipFile(ARCHIVE) as source,ZipFile(package,'w',compression=ZIP_DEFLATED) as zipped:
        replacements={
            'api_zootecnico/servico_zootecnico.py':(API/'servico_zootecnico.py').read_bytes(),
            'api_zootecnico/portal_router.py':(API/'portal_router.py').read_bytes(),
            'api_zootecnico/Dockerfile.zootecnico':original_docker_with_new_module(source.read('api_zootecnico/Dockerfile.zootecnico')),
        }
        for entry in source.infolist():
            # Cópia opaca dos demais arquivos, inclusive configurações originais:
            # não interpretar, exibir, importar ou executar o conteúdo.
            content=replacements[entry.filename] if entry.filename in replacements else source.read(entry.filename)
            zipped.writestr(copy(entry),content)
        zipped.write(API/'zootecnico_acesso.py','api_zootecnico/zootecnico_acesso.py')
    # O link da entrega anterior também passa a fornecer a estrutura corrigida.
    (DELIVERY/'Acesso_Tecnico_Zootecnico_Anderson.zip').write_bytes(package.read_bytes())
    (DELIVERY/'referencia.json').write_text(json.dumps({
            'base':'api_zootecnico(3).zip',
            'base_sha256':base_hash,
            'versao_oficial_confirmada':True,
            'confirmacao':'usuario, 2026-11-03',
            'servidor_inspecionado':False,
            'metadados_obrigatorios_confirmados_pelo_usuario':True,
            'candidatos_tecnico_obrigatorio':False,
            'publicado':False,
            'formato':'mesma estrutura completa do ZIP original',
            'alterados':['api_zootecnico/'+name for name in API_FILES[:3]],
            'adicionado':'api_zootecnico/zootecnico_acesso.py',
        },indent=2)+'\n',encoding='utf-8')
    return package


if __name__=='__main__':print(prepare())
