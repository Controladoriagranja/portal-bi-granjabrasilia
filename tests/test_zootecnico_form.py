"""Cadastro único e compatibilidade, offline. Sem SQL real, .env ou HTTP real."""
import asyncio
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_zootecnico_access import portal,api,request,Engine,install_sql_helpers
import test_operation_permissions as operations
from test_operation_permissions import FakeEngine,Result,ROOT
import zootecnico_catalog as cache

NAME='JOELMIR DIVINO DOS SANTOS'
SHORT='JDS - JOELMIR DI'


def catalog():
    rows=[dict(fonte=s,tecnico=NAME) for s in api.SOURCES]
    return api.build_technician_catalog(rows)


def form(mode='proprio',**kw):
    return portal.normalize_form_access(dict(mode=mode,**kw))


class MatchingTests(unittest.TestCase):
    def row(self,source,label,key=None,**kw):
        return dict(fonte=source,tecnico=label,chaves=key,**kw)

    def test_joelmir_requires_full_record_key_to_match_short_label(self):
        key=['12','3','9','2026-04-10']
        rows=[self.row(s,SHORT if s=='vw_desempenho_acerto_portal' else NAME,key) for s in portal.PRIMARY_SOURCES]
        result=api.build_technician_catalog(rows)
        resolved=portal.resolve_person(dict(id=0,key='self',nome=NAME),result,{})
        self.assertTrue(resolved['ready'])
        self.assertEqual(resolved['labels']['vw_desempenho_acerto_portal'],[SHORT])
        self.assertNotIn('chaves',json.dumps(result))
        self.assertNotIn('2026-04-10',json.dumps(result))

    def test_partial_name_or_initials_alone_never_match(self):
        rows=[self.row(s,NAME if s=='base_dinamica' else SHORT) for s in portal.PRIMARY_SOURCES]
        result=api.build_technician_catalog(rows)
        person=portal.resolve_person(dict(id=0,key='self',nome=NAME),result,{})
        self.assertFalse(person['ready']);self.assertIn('mortalidade_peso_abertos',person['unresolved'])
        self.assertEqual(person['labels']['mortalidade_peso_abertos'],[])

    def test_other_lot_date_or_producer_is_not_evidence(self):
        for key in (['99','3','9','2026-04-10'],['12','3','10','2026-04-10'],['12','3','9','2026-04-11']):
            result=api.build_technician_catalog([self.row('base_dinamica',NAME,['12','3','9','2026-04-10']),self.row('mortalidade_peso_abertos',SHORT,key)])
            self.assertNotIn('mortalidade_peso_abertos',result['groups'][0]['labels'])

    def test_conflicting_short_label_has_no_automatic_identity(self):
        rows=[self.row('mortalidade_peso_fechados',NAME,['12','3','9','2026-04-10']),
              self.row('mortalidade_peso_abertos',SHORT,['12','3','9','2026-04-10']),
              self.row('mortalidade_peso_fechados','OUTRO TECNICO COMPLETO',['99','3','9','2026-04-10']),
              self.row('mortalidade_peso_abertos',SHORT,['99','3','9','2026-04-10'])]
        result=api.build_technician_catalog(rows)
        self.assertTrue(all('mortalidade_peso_abertos' not in g['labels'] for g in result['groups']))
        self.assertTrue(result['pending'])

    def test_conflicting_snapshots_do_not_prove_identity(self):
        key=['12','3','9','2026-04-10']
        rows=[self.row('base_dinamica',NAME,key),self.row('base_dinamica','OUTRO TECNICO COMPLETO',key),self.row('mortalidade_peso_abertos',SHORT,key)]
        for group in api.build_technician_catalog(rows)['groups']:
            self.assertNotIn('mortalidade_peso_abertos',group['labels'])

    def test_duplicate_portal_name_requires_inline_confirmation(self):
        result=portal.resolve_person(dict(id=41,key='self',nome=NAME),catalog(),{},duplicate=True)
        self.assertFalse(result['ready'])

    def test_inline_choices_require_actual_values_and_confirmation(self):
        person=dict(id=41,key='self',nome='Nome diferente')
        choice=dict(selections={s:[NAME] for s in portal.PRIMARY_SOURCES},confirmed=False)
        self.assertFalse(portal.resolve_person(person,catalog(),{},choice)['ready'])
        choice['confirmed']=True
        self.assertTrue(portal.resolve_person(person,catalog(),{},choice)['ready'])
        choice['selections']['base_dinamica']=['INVENTADO']
        with self.assertRaises(ValueError):portal.resolve_person(person,catalog(),{},choice)

    def test_explicit_without_data_never_grants_source(self):
        choice=dict(withoutData=list(portal.SOURCES),confirmed=True)
        result=portal.resolve_person(dict(id=41,key='self',nome='Desconhecido'),catalog(),{},choice)
        self.assertTrue(result['ready']);self.assertFalse(any(result['labels'].values()))

    def test_existing_validated_identity_survives_missing_source_label(self):
        result=portal.resolve_person(dict(id=41,key='self',nome=NAME),catalog(),{'base_dinamica':[SHORT]})
        self.assertIn(SHORT,result['labels']['base_dinamica'])

    def test_empty_catalog_does_not_declare_technical_identity_validated(self):
        result=portal.resolve_person(dict(id=41,key='self',nome=NAME),api.build_technician_catalog([]),{})
        self.assertFalse(result['ready'])

    def test_invalid_team_or_old_catalog_payload_is_rejected(self):
        for kw in (dict(mode='equipe'),dict(mode='equipe',userIds=[True]),dict(mode='proprio',userIds=[1]),
                   dict(mode='proprio',technicianIds=['t1']),dict(mode='proprio',resolutions={'99':{}})):
            with self.subTest(kw=kw),self.assertRaises(ValueError):portal.normalize_form_access(kw)

    def test_team_overlap_is_already_pending_in_preview(self):
        users=[dict(id=41,nome=NAME,email='one@example.invalid',ativo=True),dict(id=42,nome='Outro Nome Completo',email='two@example.invalid',ativo=True)]
        access=form('equipe',userIds=[41,42],resolutions={'42':dict(selections={s:[NAME] for s in portal.PRIMARY_SOURCES},confirmed=True)})
        with patch.object(portal,'portal_users',return_value=users),patch.object(portal,'personal_entity',return_value=None),patch.object(portal,'stored_aliases',return_value={}),patch.object(portal,'identity_identifier',return_value='mock'):
            people=portal.resolve_form(Mock(),99,'Gerente','manager@example.invalid',access,catalog())
        self.assertTrue(all(not p['ready'] and 'dois usuários' in p['error'] for p in people))


class RegistrationEngine(FakeEngine):
    def __init__(self):
        super().__init__();self.aliases={};self.fail_alias=False
        self.users[41].update(id=41,nome=NAME)
    def __enter__(self):
        super().__enter__();self.before_aliases=copy.deepcopy(self.aliases);return self
    def __exit__(self,typ,*args):
        if typ:self.aliases=self.before_aliases
        return super().__exit__(typ,*args)
    def execute(self,sql,params=None):
        sql=' '.join(str(sql).split());p=params or {}
        value=None;handled=True
        if 'to_regclass' in sql:value=True
        elif sql.startswith('SELECT e.identificador,e.nome,a.fonte,a.valor'):value=[]
        elif sql.startswith('SELECT id,nome,email,role,perfil'):value=self.users.get(p['uid'])
        elif sql.startswith('SELECT EXISTS(SELECT 1 FROM public.usuarios WHERE id=:uid)'):value=p['uid'] in self.users
        elif sql.startswith('SELECT id,nome,email,ativo,role,perfil'):value=list(self.users.values())
        elif sql.startswith('SELECT DISTINCT e.identificador'):value=[]
        elif sql.startswith('SELECT DISTINCT a.entidade_id'):value=[]
        elif sql.startswith('SELECT EXISTS(SELECT 1 FROM public.usuario_vinculos_dados'):value=False
        elif sql.startswith('INSERT INTO public.entidade_aliases_dados'):
            if not self.fail_alias:self.aliases[p['source'],p['value']]=p['id'];value=p['id']
        else:handled=False
        if handled:self.calls.append((sql,p));return Result(value)
        result=super().execute(sql,p)
        if sql.startswith('INSERT INTO public.usuarios'):self.users[82]['id']=82
        return result


class TransactionTests(unittest.TestCase):
    def setUp(self):
        fixture=operations.OperationTests('test_patch_preserves_then_revokes');fixture.setUp()
        self.ns=fixture.ns;self.body=fixture.body;self.engine=RegistrationEngine()
        self.ns.update(engine=self.engine,normalize_zootecnico_access=portal.normalize_form_access,
                       replace_zootecnico_access=portal.replace_form_access,lock_zootecnico_access=portal.lock_form_access,
                       carregar_portal_data_neon=lambda:{'users':list(self.engine.users.values())})
        self.body.update(name=NAME,zootecnicoAccess=dict(mode='proprio'))
        self.cache=patch.object(portal,'catalog_peek',return_value=catalog());self.cache.start();self.addCleanup(self.cache.stop)

    def test_create_user_permissions_identity_and_aliases_same_transaction(self):
        self.engine.users[41]['nome']='Usuário anterior'
        self.body['password']='offline-only'
        result=self.ns['api_admin_usuario_create']()
        self.assertEqual(result[1],201)
        self.assertEqual(set(self.engine.aliases.values()),{'usuario_82'})
        calls=self.engine.calls
        self.assertLess(next(i for i,(q,p) in enumerate(calls) if 'pg_advisory_xact_lock' in q),next(i for i,(q,p) in enumerate(calls) if q.startswith('INSERT INTO public.usuarios')))
        self.assertTrue(any(p.get('resource')=='zootecnico_identidade' for q,p in calls))
        self.assertFalse(self.engine.rollback)

    def test_missing_or_unmatched_catalog_rolls_back_entire_create(self):
        self.body['password']='offline-only'
        for data in (None,api.build_technician_catalog([dict(fonte=s,tecnico='OUTRO NOME COMPLETO') for s in api.SOURCES])):
            with patch.object(portal,'catalog_peek',return_value=data):result=self.ns['api_admin_usuario_create']()
            self.assertEqual(result[1],400);self.assertNotIn(82,self.engine.users)
            self.assertEqual(self.engine.aliases,{});self.assertTrue(self.engine.rollback)

    def test_concurrent_alias_collision_rolls_back_user_and_commercial(self):
        self.engine.fail_alias=True
        self.body.update(name='Nome alterado',commercialAccess=dict(mode='general'),operationPermissions=[])
        self.body['zootecnicoAccess']['resolutions']={'self':dict(selections={s:[NAME] for s in portal.PRIMARY_SOURCES},confirmed=True)}
        result=self.ns['api_admin_usuario_patch'](41)
        self.assertEqual(result[1],400)
        self.assertEqual(self.engine.users[41]['nome'],NAME)
        self.assertEqual(self.engine.users[41]['commercial_access'],dict(mode='seller',code='7'))
        self.assertTrue(self.engine.rollback)

    def test_omitted_access_preserves_existing_even_if_catalog_unavailable(self):
        del self.body['zootecnicoAccess']
        with patch.object(portal,'catalog_peek',side_effect=AssertionError('não deve consultar')):
            self.assertTrue(self.ns['api_admin_usuario_patch'](41)['ok'])
        self.assertFalse(any('usuario_escopos_acesso' in q for q,p in self.engine.calls))

    def test_general_managers_do_not_depend_on_catalog(self):
        for role in ('admin','director'):
            self.body['role']=role
            with patch.object(portal,'catalog_peek',side_effect=AssertionError('não deve consultar')):
                self.assertTrue(self.ns['api_admin_usuario_patch'](41)['ok'])
            self.assertTrue(any(p.get('mode')=='todos' for q,p in self.engine.calls))

    def test_general_role_change_does_not_block_user_edit_before_migration(self):
        self.body['role']='director'
        with patch.object(portal,'schema_ready',return_value=False):
            self.assertTrue(self.ns['api_admin_usuario_patch'](41)['ok'])
        self.assertEqual(self.engine.users[41]['role'],'director')

    def test_team_uses_member_users_without_inheriting_member_general_access(self):
        self.body['name']='Gerente da equipe'
        self.body['zootecnicoAccess']=dict(mode='equipe',userIds=[42])
        self.engine.users[42]=dict(id=42,usuario_id=42,nome=NAME,email='membro@example.invalid',role='admin',perfil='admin',ativo=True)
        self.assertTrue(self.ns['api_admin_usuario_patch'](41)['ok'])
        links=[p for q,p in self.engine.calls if q.startswith('INSERT INTO public.usuario_vinculos_dados')]
        self.assertTrue(any(p.get('uid')==41 and p.get('kind')=='usuario_portal' and p['id']=='42' for p in links))
        self.assertFalse(any(q.startswith('UPDATE public.usuarios') and p.get('id')==42 for q,p in self.engine.calls))
        # Consulta de autorização continua verificando bloqueio/identidade no servidor.
        engine=Mock();engine.execute.side_effect=[Result(dict(escopo='equipe',ativo=True)),Result(['usuario_42'])]
        self.assertEqual(portal.read_access(engine,41)['technicianIds'],['usuario_42'])
        query=str(engine.execute.call_args_list[1].args[0])
        self.assertIn('member.ativo',query);self.assertIn("ps.recurso='zootecnico_identidade'",query)
        self.assertNotIn('member.role',query)

    def test_inactive_team_member_rolls_back(self):
        self.engine.users[42]=dict(id=42,nome=NAME,email='offline@example.invalid',ativo=False)
        self.body['zootecnicoAccess']=dict(mode='equipe',userIds=[42])
        self.assertEqual(self.ns['api_admin_usuario_patch'](41)[1],400)
        self.assertTrue(self.engine.rollback)


class CatalogRouteTests(unittest.TestCase):
    def test_specialized_options_builds_six_read_only_sources_with_optional_counter(self):
        from contextlib import contextmanager
        install_sql_helpers();connection=Mock()
        connection.execute.return_value.fetchall.return_value=[]
        @contextmanager
        def banco():yield connection
        router=api.create_access_router(banco)
        marker=api.CURRENT.set(api.Access(1,'todos'))
        try:result=router.routes[0].endpoint()
        finally:api.CURRENT.reset(marker)
        self.assertEqual(set(result['sources']),api.SOURCES)
        query=connection.execute.call_args.args[0].as_string()
        self.assertEqual(query.count('LIMIT 50001'),6)
        self.assertIn("to_jsonb(s)->>'candidatos_tecnico'",query)
        self.assertNotIn('s.candidatos_tecnico',query)
        self.assertNotRegex(query,r'(?i)\b(INSERT|UPDATE|DELETE)\b')

    def test_admin_preview_pending_is_nonblocking_and_never_writes(self):
        from flask import Flask
        app=Flask(__name__);engine=Engine();user=dict(role='admin',usuario_id=1)
        portal.register_routes(app,engine,lambda:user,lambda u:u['role']=='admin')
        with patch.object(portal,'catalog_get_or_start',return_value=None) as fetch,patch.object(portal,'catalog_from_neon',return_value=None),patch.object(portal,'schema_ready',return_value=True):
            result=app.test_client().post('/api/admin/zootecnico/preview',json=dict(name=NAME,access=dict(mode='proprio')))
        self.assertEqual(result.status_code,202)
        self.assertTrue(result.json['pending'])
        user['role']='sector'
        with patch.object(portal,'catalog_get_or_start') as fetch:
            self.assertEqual(app.test_client().post('/api/admin/zootecnico/preview',json={}).status_code,403)
            fetch.assert_not_called()

    def test_specialized_catalog_uses_verified_commercial_admin_identity(self):
        commercial=ModuleType('comercial_acesso');commercial.identity=Mock(return_value=dict(id=41,isAdmin=True))
        async def next_(req):
            from starlette.responses import JSONResponse
            self.assertEqual(api.CURRENT.get().mode,'todos');return JSONResponse({'ok':True})
        with patch.dict(sys.modules,{'comercial_acesso':commercial}),patch.object(api,'resolve_access') as scope:
            result=asyncio.run(api.dispatch(request('/api/zootecnico/acesso/opcoes'),next_))
            self.assertEqual(result.status_code,200);scope.assert_not_called()
            commercial.identity.return_value['isAdmin']=False
            self.assertEqual(asyncio.run(api.dispatch(request('/api/zootecnico/acesso/opcoes'),Mock())).status_code,403)

    def test_catalog_fetch_keeps_token_out_of_disk_and_starts_only_on_demand(self):
        with tempfile.TemporaryDirectory(prefix='catalog-test-') as folder,patch.object(cache,'CACHE',Path(folder)),patch.object(cache,'Thread') as thread:
            self.assertIsNone(cache.get_or_start('Bearer MOCK-SECRET'))
            thread.assert_called_once()
            self.assertIsNone(cache.get_or_start('Bearer MOCK-SECRET'));thread.assert_called_once()
            with patch.object(cache,'build_opener') as opener:
                opener.return_value.open.return_value=io.BytesIO(json.dumps(catalog()).encode())
                cache.fetch_catalog('Bearer MOCK-SECRET')
            self.assertIsNotNone(cache.peek())
            for path in Path(folder).iterdir():self.assertNotIn('MOCK-SECRET',path.read_text(encoding='utf-8'))
            thread.reset_mock();self.assertIsNotNone(cache.get_or_start('Bearer OTHER'));thread.assert_not_called()

    def test_compatibility_migration_is_once_only_and_never_overwrites_scopes(self):
        sql=(ROOT/'api/migrations/20261103_zootecnico_preservar_existentes.sql').read_text(encoding='utf-8')
        self.assertIn('IF NOT FOUND THEN',sql);self.assertIn('ON CONFLICT (usuario_id,recurso) DO NOTHING',sql)
        self.assertIn('usuario_relatorios',sql);self.assertIn('usuario_setores',sql)
        self.assertNotRegex(sql,r'(?i)\bUPDATE\s+public\.')


if __name__=='__main__':unittest.main()
