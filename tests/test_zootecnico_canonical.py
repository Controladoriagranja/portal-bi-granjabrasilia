"""Cadastro canônico: banco simulado, catálogo real local quando disponível, sem rede."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_operation_permissions as operations
import test_zootecnico_access as existing

portal=existing.portal
ROOT=existing.ROOT


def seed_catalog():
    file=ROOT/'integrations/zootecnico/carga-local/carga_confirmada.json'
    if file.is_file():return json.loads(file.read_text(encoding='utf-8'))
    result={'entidades':[],'aliases':[]}
    for name,short in [('CRISTIANO VALADARES BARRETO','CVB - CRISTIANO'),('JOELMIR DIVINO DOS SANTOS','JDS - JOELMIR DI'),('MARIANA LEMAR CARDOSO','MLC - MARIANA LE')]:
        identifier='tec_'+hashlib.sha256(portal.name_key(name).encode()).hexdigest()[:24]
        result['entidades'].append(dict(id=identifier,nome=name))
        for source in portal.SOURCES:
            result['aliases'].append(dict(fonte=source,valor=short if source in portal.SOURCES[:2] else name,entidade_id=identifier))
    return result


class CanonicalEngine(operations.FakeEngine):
    def __init__(self):
        super().__init__();data=seed_catalog()
        self.catalog={e['id']:dict(name=e['nome'],active=True) for e in data['entidades']}
        self.aliases=copy.deepcopy(data['aliases']);self.scopes={};self.links={};self.members={}
        for uid,name,role in ((1,'Admin','admin'),(35,'Leandro da Costa Elias','sector'),(42,'Diretor','director'),(90,'Gerente','sector')):
            self.users[uid]=dict(id=uid,usuario_id=uid,nome=name,email=f'usuario{uid}@example.invalid',ativo=True,role=role,perfil=role)
        self.users[41]['id']=41
        self.scopes[35,'zootecnico']=dict(escopo='todos',ativo=True)
    def __enter__(self):
        super().__enter__();self.catalog_before=copy.deepcopy((self.catalog,self.aliases,self.scopes,self.links,self.members));return self
    def __exit__(self,typ,*args):
        if typ:self.catalog,self.aliases,self.scopes,self.links,self.members=self.catalog_before
        return super().__exit__(typ,*args)
    def personal_links(self):
        rows=[]
        for (uid,res,kind,identifier),active in self.links.items():
            scope=self.scopes.get((uid,res),{})
            if active and scope.get('ativo') and kind=='tecnico' and self.catalog.get(identifier,{}).get('active') and (res=='zootecnico_identidade' or res=='zootecnico' and scope.get('escopo')=='proprio'):
                rows.append(dict(usuario_id=uid,identificador=identifier))
        return rows
    def execute(self,query,params=None):
        query=' '.join(str(query).split());p=params or {};value=None;handled=True
        if 'to_regclass' in query:value=True
        elif query.startswith('SELECT id,nome,email,role,perfil'):value=self.users.get(p['uid'])
        elif query.startswith('SELECT role,perfil'):value=self.users.get(p['uid'])
        elif query.startswith('SELECT id,nome,email,ativo,role,perfil'):value=list(self.users.values())
        elif query.startswith('SELECT DISTINCT v.usuario_id,e.identificador'):value=self.personal_links()
        elif query.startswith('SELECT e.identificador,e.nome,a.fonte,a.valor'):
            value=[dict(identificador=a['entidade_id'],nome=self.catalog[a['entidade_id']]['name'],fonte=a['fonte'],valor=a['valor']) for a in self.aliases if self.catalog.get(a['entidade_id'],{}).get('active')]
        elif query.startswith('SELECT escopo AS requested_mode'):
            scope=self.scopes.get((p['uid'],'zootecnico_pendente'))
            value=dict(requested_mode=scope['escopo']) if scope and scope['ativo'] else None
        elif query.startswith('SELECT escopo, ativo'):value=self.scopes.get((p['uid'],p['resource']))
        elif query.startswith('INSERT INTO public.usuario_escopos_acesso'):
            self.scopes[p['uid'],p['resource']]=dict(escopo=p['mode'],ativo=True)
        elif query.startswith('UPDATE public.usuario_escopos_acesso'):
            scope=self.scopes.get((p['uid'],'zootecnico_pendente'))
            if scope:scope['ativo']=False
        elif query.startswith('UPDATE public.usuario_vinculos_dados'):
            res=p.get('resource') or ('zootecnico_identidade' if "recurso='zootecnico_identidade'" in query else 'zootecnico_pendente')
            for k in self.links:
                if k[:2]==(p['uid'],res):self.links[k]=False
        elif query.startswith('INSERT INTO public.usuario_vinculos_dados'):
            if p['kind']=='tecnico' and p['id'] not in self.catalog:raise AssertionError('FK canônica ausente')
            self.links[p['uid'],p['resource'],p['kind'],p['id']]=True
        elif query.startswith('INSERT INTO public.entidades_acesso_dados'):
            if "'usuario_portal'" not in query:raise AssertionError('Cadastro normal não deve criar técnicos')
            member=p.get('member')
            if member:self.members[str(member)]=self.users[member]['nome']
            else:self.members[p['id']]=p['name']
        elif query.startswith('SELECT DISTINCT member.id'):
            value=sorted({int(identifier) for (uid,res,kind,identifier),active in self.links.items() if uid==p['uid'] and res=='zootecnico' and kind=='usuario_portal' and active})
        elif query.startswith('SELECT entidade_id::bigint'):
            value=sorted({int(identifier) for (uid,res,kind,identifier),active in self.links.items() if uid==p['uid'] and res=='zootecnico_pendente' and active})
        elif query.startswith('SELECT v.entidade_id'):
            ids=set()
            for (uid,res,kind,identifier),active in self.links.items():
                if uid!=p['uid'] or res!=p['resource'] or not active:continue
                if kind=='tecnico' and self.catalog.get(identifier,{}).get('active'):ids.add(identifier)
                if kind=='usuario_portal' and self.users.get(int(identifier),{}).get('ativo'):
                    ids.update(row['identificador'] for row in self.personal_links() if row['usuario_id']==int(identifier))
            value=sorted(ids)
        elif query.startswith('SELECT a.fonte'):
            value=[dict(fonte=a['fonte'],valor=a['valor'],entidade_id=a['entidade_id']) for a in self.aliases if a['entidade_id'] in p['ids']]
        elif 'SELECT EXISTS (' in query and 'JOIN public.relatorios' in query:value=True
        else:handled=False
        if handled:self.calls.append((query,p));return operations.Result(value)
        value=super().execute(query,p)
        if query.startswith('INSERT INTO public.usuarios'):self.users[82]['id']=82
        return value


class CanonicalFormTests(unittest.TestCase):
    def setUp(self):
        fixture=operations.OperationTests('test_patch_preserves_then_revokes');fixture.setUp()
        self.ns,self.body=fixture.ns,fixture.body;self.engine=CanonicalEngine()
        self.ns.update(engine=self.engine,normalize_zootecnico_access=portal.normalize_form_access,
            replace_zootecnico_access=portal.replace_form_access,lock_zootecnico_access=portal.lock_form_access,
            carregar_portal_data_neon=lambda:{'users':list(self.engine.users.values())})
        self.cv=self.identifier('CRISTIANO VALADARES BARRETO');self.jo=self.identifier('JOELMIR DIVINO DOS SANTOS');self.ma=self.identifier('MARIANA LEMAR CARDOSO')
        self.catalog_before=copy.deepcopy((self.engine.catalog,self.engine.aliases))
        self.app=Flask(__name__)
        self.actor=dict(usuario_id=1,role='admin',ativo=True)
        portal.register_routes(self.app,self.engine,lambda:self.actor,lambda u:u.get('role')=='admin')
    def identifier(self,name):return next(k for k,v in self.engine.catalog.items() if v['name']==name)
    def access(self,identity=None,mode='proprio',members=None):
        return dict(formVersion=3,mode=mode,identityId=identity,userIds=members or [],allowPending=True)
    def save(self,uid=41,identity=None,mode='proprio',members=None):
        self.body['zootecnicoAccess']=self.access(identity,mode,members)
        return self.ns['api_admin_usuario_patch'](uid)

    def test_select_cristiano_joelmir_mariana_once_and_reopen_saved_link(self):
        for identifier,short in ((self.cv,'CVB - CRISTIANO'),(self.jo,'JDS - JOELMIR DI'),(self.ma,'MLC - MARIANA LE')):
            self.assertTrue(self.save(identity=identifier)['ok'])
            response=self.app.test_client().get('/api/admin/usuarios/41/zootecnico-access')
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['access']['identityId'],identifier)
            selected=next(i for i in response.json['identities'] if i['id']==identifier)
            self.assertIn(short,selected['aliases']['vw_desempenho_acerto_portal'])
            self.assertEqual(portal.read_access(self.engine,41)['technicianIds'],[identifier])
        self.assertEqual(self.catalog_before,(self.engine.catalog,self.engine.aliases))

    def test_account_name_can_differ_and_canonical_identity_is_not_renamed(self):
        self.body.update(name='Conta de teste',password='offline-only',zootecnicoAccess=self.access(self.cv))
        response,status=self.ns['api_admin_usuario_create']()
        self.assertEqual(status,201);self.assertFalse(response['zootecnicoAccess']['pending'])
        self.assertEqual(self.engine.users[82]['nome'],'Conta de teste')
        self.assertEqual(self.engine.catalog[self.cv]['name'],'CRISTIANO VALADARES BARRETO')
        self.assertEqual(portal.read_access(self.engine,82)['technicianIds'],[self.cv])

    def test_two_authorized_accounts_can_share_one_canonical_identity(self):
        self.assertTrue(self.save(identity=self.cv)['ok'])
        self.body.update(name='Outra conta autorizada',password='offline-only',zootecnicoAccess=self.access(self.cv))
        self.assertEqual(self.ns['api_admin_usuario_create']()[1],201)
        self.assertEqual(portal.read_access(self.engine,41)['technicianIds'],portal.read_access(self.engine,82)['technicianIds'])
        self.assertEqual(self.catalog_before,(self.engine.catalog,self.engine.aliases))

    def test_save_and_list_do_not_require_specialized_api(self):
        with patch.object(portal,'catalog_peek',side_effect=AssertionError('não usar cache da API')),patch.object(portal,'catalog_get_or_start',side_effect=AssertionError('não chamar API')):
            self.assertTrue(self.save(identity=self.cv)['ok'])
            self.assertEqual(self.app.test_client().get('/api/admin/usuarios/41/zootecnico-access').status_code,200)
            response=self.app.test_client().post('/api/admin/zootecnico/preview',json=dict(uid=41,access=self.access(self.cv)))
            self.assertTrue(response.json['ready']);self.assertEqual(response.json['source'],'neon')

    def test_forged_inactive_or_unknown_identity_is_rejected_atomically(self):
        for identifier in ('fake_unknown',"x' OR TRUE",self.cv):
            if identifier==self.cv:self.engine.catalog[identifier]['active']=False
            response,status=self.save(identity=identifier)
            self.assertEqual(status,400);self.assertEqual(self.engine.users[41]['nome'],'Antes')
        self.assertEqual(self.engine.aliases,self.catalog_before[1])

    def test_browser_cannot_submit_arbitrary_aliases_in_canonical_flow(self):
        value=self.access(self.cv);value['resolutions']={'self':dict(selections={'base_dinamica':['OUTRO']},confirmed=True)}
        with self.assertRaises(ValueError):portal.normalize_form_access(value)

    def test_source_without_alias_is_denied_not_promoted_to_general(self):
        self.engine.aliases=[a for a in self.engine.aliases if not(a['entidade_id']==self.cv and a['fonte']=='base_dinamica')]
        self.assertTrue(self.save(identity=self.cv)['ok'])
        self.actor=dict(usuario_id=41,role='sector',ativo=True)
        response=self.app.test_client().get('/api/auth/zootecnico-access')
        self.assertEqual(response.json['mode'],'proprio')
        self.assertFalse(any(a['fonte']=='base_dinamica' for a in response.json['aliases']))
        access=existing.api.validate_access(response.json)
        self.assertIn('WHERE FALSE',existing.api.scope_query('SELECT * FROM zootecnico.base_dinamica',access))

    def test_team_has_only_member_identities_and_tracks_identity_change_and_block(self):
        self.assertTrue(self.save(identity=self.cv)['ok'])
        self.body.update(name='Outro técnico',password='offline-only',zootecnicoAccess=self.access(self.ma))
        self.assertEqual(self.ns['api_admin_usuario_create']()[1],201)
        self.assertTrue(self.save(uid=90,mode='equipe',members=[41,82])['ok'])
        self.assertEqual(set(portal.read_access(self.engine,90)['technicianIds']),{self.cv,self.ma})
        self.assertEqual(self.app.test_client().get('/api/admin/usuarios/90/zootecnico-access').json['access']['userIds'],[41,82])
        self.assertTrue(self.save(identity=self.jo)['ok'])
        self.assertEqual(set(portal.read_access(self.engine,90)['technicianIds']),{self.jo,self.ma})
        self.engine.users[82]['ativo']=False
        self.assertEqual(portal.read_access(self.engine,90)['technicianIds'],[self.jo])
        self.engine.users[41]['ativo']=False
        self.assertEqual(portal.read_access(self.engine,90)['mode'],'none')
        configured=self.app.test_client().get('/api/admin/usuarios/90/zootecnico-access').json['access']
        self.assertEqual(configured['mode'],'equipe');self.assertEqual(configured['userIds'],[41,82])

    def test_pending_member_does_not_grant_general_team_access(self):
        self.assertTrue(self.save(uid=90,mode='equipe',members=[42])['zootecnicoAccess']['pending'])
        self.assertEqual(portal.read_access(self.engine,90)['mode'],'none')

    def test_existing_general_leandro_admin_director_and_commercial_preserved(self):
        self.body['zootecnicoAccess']=self.access(self.cv)
        for uid,role in ((35,'sector'),(1,'admin'),(42,'director')):
            self.actor=dict(usuario_id=uid,role=role,ativo=True)
            response=self.app.test_client().get('/api/auth/zootecnico-access')
            self.assertEqual(response.json['mode'],'todos')
        self.body.pop('zootecnicoAccess')
        self.assertTrue(self.ns['api_admin_usuario_patch'](41)['ok'])
        self.assertEqual(self.engine.users[41]['commercial_access'],dict(mode='seller',code='7'))
        self.assertEqual(portal.read_access(self.engine,35)['mode'],'todos')

    def test_no_identity_selected_can_be_saved_only_as_pending(self):
        response=self.save()
        self.assertTrue(response['zootecnicoAccess']['pending'])
        self.assertEqual(portal.read_access(self.engine,41)['mode'],'none')

    def test_catalog_cannot_be_read_or_modified_by_common_user(self):
        self.actor=dict(usuario_id=41,role='sector',ativo=True)
        self.assertEqual(self.app.test_client().get('/api/admin/usuarios/41/zootecnico-access').status_code,403)
        self.assertEqual(self.app.test_client().post('/api/admin/zootecnico/preview',json=dict(access=self.access(self.cv))).status_code,403)

    def test_initial_catalog_is_reused_without_inserting_or_updating_aliases(self):
        count=len(self.engine.catalog);aliases=len(self.engine.aliases)
        self.assertTrue(self.save(identity=self.cv)['ok'])
        self.assertEqual(len(self.engine.catalog),count);self.assertEqual(len(self.engine.aliases),aliases)
        self.assertFalse(any('entidade_aliases_dados' in q and not q.startswith('SELECT') for q,p in self.engine.calls))

    def test_technician_authorization_has_only_selected_aliases_in_all_four_screens(self):
        existing.install_sql_helpers()
        self.assertTrue(self.save(identity=self.cv)['ok'])
        self.actor=dict(usuario_id=41,role='sector',ativo=True)
        response=self.app.test_client().get('/api/auth/zootecnico-access')
        access=existing.api.validate_access(response.json)
        self.assertEqual(response.json['technicianIds'],[self.cv])
        for source in portal.PRIMARY_SOURCES:
            query=existing.api.scope_query('SELECT * FROM zootecnico.'+source,access)
            self.assertIn('za_scope_',query)
            for alias in self.engine.aliases:
                if alias['fonte']==source:
                    if alias['entidade_id']==self.cv:self.assertIn(alias['valor'],query)
                    else:self.assertNotIn("WHEN '"+alias['valor']+"' THEN",query)


if __name__=='__main__':unittest.main()
