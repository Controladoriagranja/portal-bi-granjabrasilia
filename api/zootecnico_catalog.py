"""Catálogo técnico confiável, somente sob demanda administrativa.

Fetch em thread para não bloquear o único worker Flask enquanto a API privada
valida o Bearer na CENTRAL. Cache efêmero compartilhado entre processos; não guarda
tokens, permissões ou dados dos lotes. Sem I/O ao importar, sem timer periódico.
"""
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError,URLError
import uuid

URL='https://api-bi-granja.controladoriagb05.workers.dev/api/zootecnico/acesso/opcoes'
CACHE=Path(tempfile.gettempdir())/'portal-zootecnico-opcoes-v1'
TTL=300
SOURCES=frozenset({'vw_desempenho_acerto_portal','base_dinamica','mortalidade_peso_abertos',
    'vw_historico_lotes_criacao_portal','acerto_lote_resultado_geral','mortalidade_peso_fechados'})


def validate(data):
    if not isinstance(data,dict) or data.get('ok') is not True or set(data.get('sources',{}))!=SOURCES:
        raise ValueError('Catálogo zootécnico inválido.')
    for values in data['sources'].values():
        if not isinstance(values,list) or len(values)>5000 or any(not isinstance(x,str) or not x or x!=x.strip() or len(x)>500 for x in values):
            raise ValueError('Valores técnicos inválidos.')
    if not isinstance(data.get('groups'),list) or len(data['groups'])>10000:raise ValueError('Grupos técnicos inválidos.')
    for group in data['groups']:
        if not isinstance(group,dict) or not isinstance(group.get('nameKey'),str) or not isinstance(group.get('labels'),dict):raise ValueError('Grupo técnico inválido.')
        for source,values in group['labels'].items():
            if source not in SOURCES or not isinstance(values,list) or any(value not in data['sources'][source] for value in values):raise ValueError('Prova técnica inválida.')
    return data


def read(name):
    try:return json.loads((CACHE/name).read_text(encoding='utf-8'))
    except (OSError,ValueError):return None


def atomic(name,value):
    temporary=CACHE/(uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temporary.replace(CACHE/name)


def peek():
    snapshot=read('ready.json')
    if snapshot and time.time()-snapshot.get('time',0)<TTL:return validate(snapshot['data'])
    return None


def fetch_catalog(token):
    try:
        request=Request(URL,headers={'Authorization':token,'Accept':'application/json','Cache-Control':'no-store'})
        with build_opener(ProxyHandler({})).open(request,timeout=35) as result:
            raw=result.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('Catálogo excedeu o limite seguro.')
        data=validate(json.loads(raw))
        atomic('ready.json',{'time':time.time(),'data':data})
        (CACHE/'error.json').unlink(missing_ok=True)
    except Exception as error:
        # Nunca armazenar corpo HTTP, token, URL privada ou mensagem de exceção.
        messages={401:'Sessão ou autenticação da API recusada. Entre novamente no portal.',
                  403:'O catálogo exige administrador e a ponte X-Portal-Authorization no Worker.',
                  404:'O endpoint /api/zootecnico/acesso/opcoes ainda não está disponível na API publicada.',
                  502:'O Worker não conseguiu alcançar a API privada.',503:'O serviço de catálogo está temporariamente indisponível.'}
        status=error.code if isinstance(error,HTTPError) else None
        message=messages.get(status,'A API não retornou um catálogo válido. Confira a publicação do serviço atualizado.')
        if isinstance(error,(TimeoutError,URLError)) and not isinstance(error,HTTPError):message='A conexão com o catálogo não respondeu. O usuário pode ser salvo com vínculo pendente.'
        if isinstance(error,HTTPError):error.close()
        atomic('error.json',{'time':time.time(),'status':status,'message':message})
    finally:
        (CACHE/'pending.lock').unlink(missing_ok=True)


def get_or_start(token,retry=False):
    data=peek()
    if data and not retry:return data
    CACHE.mkdir(parents=True,exist_ok=True)
    error=read('error.json')
    if error and time.time()-error.get('time',0)<30 and not retry:raise ValueError(error['message'])
    lock=CACHE/'pending.lock'
    try:
        if lock.exists() and time.time()-lock.stat().st_mtime>90:lock.unlink(missing_ok=True)
        with lock.open('x',encoding='utf-8') as stream:stream.write(str(time.time()))
    except FileExistsError:return None
    Thread(target=fetch_catalog,args=(token,),daemon=True,name='zootecnico-opcoes').start()
    return None
