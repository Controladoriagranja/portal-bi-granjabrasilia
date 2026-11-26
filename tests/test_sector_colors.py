"""Rotas reais extraídas por AST, banco simulado. Sem app/.env/rede."""
import ast
import copy
from pathlib import Path
import re
from types import SimpleNamespace
import unicodedata
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Result:
    def __init__(self,value=None):self.value=value
    def mappings(self):return self
    def first(self):return self.value
    def scalar(self):return self.value

class Engine:
    def __init__(self):
        self.sectors={'integracao':dict(id=4,codigo='integracao',nome='Integração',label='Integração',cor='#34d399',ativo=True)}
        self.users=[{'usuario_id':1,'setor_id':4}];self.reports=[{'id':13,'setor_id':4}];self.calls=[]
    def begin(self):return self
    def __enter__(self):self.before=copy.deepcopy(self.sectors);return self
    def __exit__(self,t,v,tb):
        if t:self.sectors=self.before
        return False
    def execute(self,sql,p=None):
        sql=' '.join(str(sql).split());p=p or {};self.calls.append((sql,p))
        if sql.startswith('SELECT id,'):return Result(self.sectors.get(p['codigo']))
        if 'SELECT COUNT' in sql:return Result(1)
        if sql.startswith('INSERT INTO public.setores'):
            self.sectors[p['codigo']]=dict(id=8,codigo=p['codigo'],nome=p['nome'],label=p['nome'],cor=p['cor'],ativo=True)
        elif sql.startswith('UPDATE public.setores'):
            row=next(s for s in self.sectors.values() if s['id']==p['id'])
            row.update(nome=p['nome'],label=p['nome'])
            if p['cor'] is not None:row['cor']=p['cor']
        return Result()

class SectorColors(unittest.TestCase):
    def setUp(self):
        self.engine=Engine();self.body={};self.allowed=True
        self.ns=dict(re=re,unicodedata=unicodedata,text=lambda v:v,engine=self.engine,
                     jsonify=lambda value:value,log=lambda *args:None,
                     carregar_portal_data_neon=lambda:copy.deepcopy(self.engine.sectors),
                     _admin_atual_ou_resposta=lambda:({'email':'offline@example.invalid'},None) if self.allowed else (None,({'ok':False},403)),
                     request=SimpleNamespace(method='PATCH',get_json=lambda **kwargs:self.body))
        tree=ast.parse((ROOT/'api/app.py').read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node,ast.FunctionDef) and node.name in {'_normalizar_cor_setor','_normalizar_codigo_setor','api_admin_setor_create','api_admin_setor_item'}:
                node.decorator_list=[];exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.ns)

    def test_hex_normalized_without_restricting_palette(self):
        for value,expected in [('#a1B2c3','#A1B2C3'),('abc','#AABBCC'),('#fff','#FFFFFF'),('000000','#000000'),('#123456','#123456')]:
            self.assertEqual(self.ns['_normalizar_cor_setor'](value),expected)
        for value in ('red','rgb(1,2,3)','#12345678','#12',';color:red',123,{},True):
            with self.assertRaises(ValueError):self.ns['_normalizar_cor_setor'](value)

    def test_create_new_sector_saves_arbitrary_hex(self):
        self.body={'name':'Fábrica de Ração','color':'#d84fa2'}
        result,status=self.ns['api_admin_setor_create']()
        self.assertEqual(status,201);self.assertTrue(result['ok'])
        self.assertEqual(self.engine.sectors['fabrica_de_racao']['cor'],'#D84FA2')

    def test_edit_both_fields_preserves_id_code_and_relations(self):
        users=copy.deepcopy(self.engine.users);reports=copy.deepcopy(self.engine.reports)
        self.body={'name':'Integração — novo nome','color':'#1b2c3d'}
        self.assertTrue(self.ns['api_admin_setor_item']('integracao')['ok'])
        row=self.engine.sectors['integracao']
        self.assertEqual((row['id'],row['codigo']),(4,'integracao'))
        self.assertEqual((row['nome'],row['label'],row['cor']),('Integração — novo nome','Integração — novo nome','#1B2C3D'))
        self.assertEqual(self.engine.users,users);self.assertEqual(self.engine.reports,reports)

    def test_legacy_name_only_patch_preserves_existing_color(self):
        self.body={'name':'Outro nome'}
        self.assertTrue(self.ns['api_admin_setor_item']('integracao')['ok'])
        self.assertEqual(self.engine.sectors['integracao']['cor'],'#34d399')

    def test_invalid_color_does_not_change_sector(self):
        before=copy.deepcopy(self.engine.sectors);self.body={'name':'Mudança','color':'url(evil)'}
        self.assertEqual(self.ns['api_admin_setor_create']()[1],400)
        self.assertEqual(self.ns['api_admin_setor_item']('integracao')[1],400)
        self.assertEqual(self.engine.sectors,before)

    def test_non_admin_denied_for_create_and_edit(self):
        self.allowed=False;self.body={'name':'Nome','color':'#123456'}
        self.assertEqual(self.ns['api_admin_setor_create']()[1],403)
        self.assertEqual(self.ns['api_admin_setor_item']('integracao')[1],403)
        self.assertEqual(self.engine.calls,[])

if __name__=='__main__':unittest.main()
