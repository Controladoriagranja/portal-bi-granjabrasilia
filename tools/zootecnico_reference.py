"""Leitor offline do ZIP de referência: somente builders puros da Integração.

Não importa serviço/app, configurações de conexão, robôs ou ETL. Não abre banco.
O registro financeiro é excluído porque não pertence ao diagnóstico zootécnico.
"""
import ast
import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from contextlib import contextmanager
from urllib.parse import urlencode
from zipfile import ZipFile

DEFAULT_ARCHIVE = Path.home() / 'Downloads/api_zootecnico(3).zip'
ALLOWED = frozenset({'registry','gpd_config','freshness','sql_utils','analytics',
    'gpd_fases_dinamica','mortalidade_exclusoes','mortalidade_faixas',
    'mortalidade_lotes','principal_contexto','filtros_contexto'})


class Reference(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    prefix = '_zootecnico_reference_modules'

    def __init__(self, archive=DEFAULT_ARCHIVE):
        self.archive = Path(archive)

    def source(self, relative):
        with ZipFile(self.archive) as zipped:
            return zipped.read('api_zootecnico/'+relative).decode('utf-8-sig').replace('\r\r\n','\n')

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.prefix:
            return importlib.util.spec_from_loader(fullname,self,is_package=True)
        if fullname.startswith(self.prefix+'.') and fullname.split('.',1)[1] in ALLOWED:
            return importlib.util.spec_from_loader(fullname,self)

    def create_module(self,spec): return None

    def exec_module(self,module):
        if module.__name__ == self.prefix:
            module.__path__=[]
            return
        name=module.__name__.split('.',1)[1]
        tree=ast.parse(self.source('bi_generic/'+name+'.py'))
        if name=='registry':
            nodes=[]
            for node in tree.body:
                if isinstance(node,ast.ImportFrom) and node.module=='faturamento_nf.config':continue
                # Um único registro financeiro usa esta constante externa.
                if isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and n.id=='FATURAMENTO_NF_CONFIG' for n in ast.walk(node)):continue
                nodes.append(node)
            tree.body=nodes
        exec(compile(tree,str(self.archive)+'!/bi_generic/'+name+'.py','exec'),module.__dict__)

    def __enter__(self):
        sys.meta_path.insert(0,self)
        return self

    def __exit__(self,*args):
        sys.meta_path.remove(self)
        for key in list(sys.modules):
            if key==self.prefix or key.startswith(self.prefix+'.'):sys.modules.pop(key,None)

    def load(self,name):
        if name not in ALLOWED:raise ValueError('Módulo fora da lista de builders puros.')
        return importlib.import_module(self.prefix+'.'+name)

    def router_namespace(self):
        from fastapi import APIRouter, HTTPException, Request
        from datetime import date
        from psycopg import sql
        ns=dict(APIRouter=APIRouter,HTTPException=HTTPException,Request=Request,date=date,
                sql=sql,SimpleNamespace=SimpleNamespace,
                build_faturamento_nf_service=lambda _:None)
        tree=ast.parse(self.source('bi_generic/router.py'))
        for node in tree.body:
            if isinstance(node,ast.ImportFrom) and node.level==1 and node.module!='faturamento_nf.service':
                mod=self.load(node.module)
                for alias in node.names:ns[alias.asname or alias.name]=getattr(mod,alias.name)
            elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SPECIAL_FILTER_KEYS' for t in node.targets):
                exec(compile(ast.Module(body=[node],type_ignores=[]),'router constants','exec'),ns)
            elif isinstance(node,ast.FunctionDef):
                exec(compile(ast.Module(body=[node],type_ignores=[]),'router functions','exec'),ns)
        return ns


def expected_columns(reference):
    """Campos efetivamente projetados/usados pelos quatro builders e pela ACL."""
    registry=reference.load('registry').BI_REGISTRY
    result={}
    def add(source,column,kind='texto_ou_tipado',required=True):
        key=(source,column)
        if key not in result or kind=='numeric':result[key]=(kind,required)
    def metric(source,value,context='texto_ou_tipado'):
        if isinstance(value,dict):
            inherited='numeric' if value.get('numeric_kind')=='typed' else context
            for key,item in value.items():
                if key in {'column','weight','numerator','denominator','multiply'} and isinstance(item,str):
                    kind=('numeric' if value.get('weight_numeric_kind')=='typed' else 'texto_ou_tipado') if key=='weight' else inherited
                    add(source,item,kind)
                elif key=='product' and isinstance(item,list):
                    for column in item:add(source,column,inherited)
                elif isinstance(item,(dict,list)):metric(source,item,inherited)
        elif isinstance(value,list):
            for item in value:metric(source,item,context)
    for bi in ('zootecnico','gpd-fases','lotes-abertos','historico-abertos','historico-fechados'):
        config=registry[bi];source=config['table']
        for column in config.get('columns',{}).values():add(source,column)
        if not config.get('engine'):
            for spec in config['filters'].values():add(source,spec['column'])
        if bi=='zootecnico':metric(source,config['metrics'])
        for item in config.get('freshness',{}).get('sources',[]):add(item['table'],item['column'])
        add(source,'carregado_em')
    for source in {key[0] for key in result}:
        add(source,'tecnico')
        if source in {'vw_desempenho_acerto_portal','acerto_lote_resultado_geral'}:add(source,'chave_lote')
    view='vw_desempenho_acerto_portal'
    for c in ('codigo','gal','lote','dt_aloj','data_abate','mort','aloj','tecnico_exibicao'):add(view,c)
    add(view,'candidatos_tecnico',required=False)
    dynamic='base_dinamica'
    for c in ('id','periodo_fim','carregado_em','origem_arquivo','cod_prod','galpao','lote',
              'data_de_alojamento','data_de_abate','aves_alojadas','mortalidade','peso_medio','idade'):
        add(dynamic,c)
    for age in (7,14,21,28,35):add(dynamic,'peso_'+str(age)+'_dias')
    for week in range(1,6):
        for prefix in ('m','d'):add(dynamic,f'{prefix}_sem_{week}')
    # Alvos são configuração comum, fora das seis fontes de dados pessoais.
    return result


class CapturedQuery(Exception):
    def __init__(self,original,scoped,params):
        self.original,self.scoped,self.params=original,scoped,params


def route_query(reference,acl,bi,action,params=(),access=None):
    """Invoca o builder real até o primeiro SQL, sem executar a consulta."""
    from starlette.requests import Request
    helper=reference.load('sql_utils')
    old_package,old_helper=sys.modules.get('bi_generic'),sys.modules.get('bi_generic.sql_utils')
    package=ModuleType('bi_generic');package.__path__=[]
    sys.modules['bi_generic']=package;sys.modules['bi_generic.sql_utils']=helper
    class Capture:
        def execute(self,query,values=None):
            raw=query if isinstance(query,str) else query.as_string()
            scoped=acl.scope_query(raw,access,bound_params=values is not None)
            raise CapturedQuery(raw,scoped,values)
    @contextmanager
    def banco():yield Capture()
    try:
        ns=reference.router_namespace()
        router=ns['criar_router'](banco)
        endpoint=next(r.endpoint for r in router.routes if r.path=='/api/bi/{bi}/'+action)
        req=Request(dict(type='http',method='GET',path='/api/bi/'+bi+'/'+action,
                         query_string=urlencode(params,doseq=True).encode(),headers=[]))
        try:
            import inspect
            endpoint(**({'bi':bi,'request':req} if 'request' in inspect.signature(endpoint).parameters else {'bi':bi}))
        except CapturedQuery as captured:return captured
        raise AssertionError('Builder não atingiu consulta SQL: '+bi+'/'+action)
    finally:
        for key,value in [('bi_generic',old_package),('bi_generic.sql_utils',old_helper)]:
            if value is None:sys.modules.pop(key,None)
            else:sys.modules[key]=value


ROUTE_CASES=(
    ('zootecnico','filtros',(('ano','2026'),)),
    ('zootecnico','resumo',(('ano','2026'),)),
    ('zootecnico','detalhes',(('ano','2026'),('indicador','iep'))),
    ('zootecnico','detalhes',(('ano','2026'),('indicador','mortalidade'),('etapa','principal'))),
    ('zootecnico','detalhes',(('ano','2026'),('indicador','mortalidade'),('etapa','evolucao'),('agrupamento','mensal'))),
    ('zootecnico','detalhes',(('ano','2026'),('indicador','mortalidade'),('etapa','lotes'),('agrupamento','mensal'),('inicio_periodo','2026-09-01'))),
    ('gpd-fases','filtros',(('ano','2026'),)),
    ('gpd-fases','resumo',(('ano','2026'),('agrupamento','semana'))),
    ('lotes-abertos','filtros',()),('lotes-abertos','resumo',()),('lotes-abertos','detalhes',()),
    ('historico-abertos','filtros',(('ano','2026'),)),
    ('historico-abertos','resumo',(('ano','2026'),)),
    ('historico-abertos','detalhes',(('ano','2026'),)),
    ('historico-fechados','resumo',(('ano','2026'),)),
    ('zootecnico','atualizacao',()),('gpd-fases','atualizacao',()),
    ('lotes-abertos','atualizacao',()),('historico-abertos','atualizacao',()),
)


def secondary_lookup_query(reference,acl,access):
    """Builder auxiliar real com UMA linha de entrada fictícia; SQL não executado."""
    old={key:sys.modules.get(key) for key in ('bi_generic','bi_generic.sql_utils')}
    package=ModuleType('bi_generic');package.__path__=[]
    sys.modules.update({'bi_generic':package,'bi_generic.sql_utils':reference.load('sql_utils')})
    class Capture:
        calls=0
        def execute(self,query,values=None):
            self.calls+=1
            raw=query.as_string() if not isinstance(query,str) else query
            scoped=acl.scope_query(raw,access,bound_params=values is not None)
            if self.calls==1:
                return SimpleNamespace(fetchall=lambda:[dict(chave_lote='mock-lote',codigo='1',gal='A',lote='10',
                    dt_aloj='2026-08-01',data_abate='2026-09-01',mort=1,aloj=100)])
            raise CapturedQuery(raw,scoped,values)
    try:
        module=reference.load('mortalidade_faixas')
        module.fetch_period_rows(Capture(),reference.load('registry').BI_REGISTRY['zootecnico'],{},'2026-09-01','2026-09-30')
        raise AssertionError('Lookup auxiliar não atingiu a consulta esperada.')
    except CapturedQuery as captured:return captured
    finally:
        for key,value in old.items():
            if value is None:sys.modules.pop(key,None)
            else:sys.modules[key]=value
