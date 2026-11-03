"""Resultados fornecidos + mocks. Sem banco, .env, HTTP real ou criação de contas reais."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_zootecnico_form as fixtures
sys.path.insert(0,str(fixtures.ROOT/'tools'))
import preparar_carga_zootecnico as batch

portal,api,cache=fixtures.portal,fixtures.api,fixtures.cache
INTERNAL=Path.home()/'.codex/attachments/695e059a-2aa4-4cb1-b315-d56c81625139/Pasted text.txt'
NEON=Path.home()/'.codex/attachments/ce547a11-5eea-4def-afa3-bebe8b6c025c/Pasted text.txt'
WORD=Path.home()/'Downloads/Usuarios Portal Resultados(1).docx'


class ProvidedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(p.is_file() for p in (INTERNAL,NEON,WORD)):raise unittest.SkipTest('Resultados fornecidos não estão disponíveis nesta máquina.')
        cls.internal=batch.result(INTERNAL);cls.neon=batch.result(NEON)
        cls.catalog,cls.payload=batch.consolidate(cls.internal,cls.neon,batch.roster(WORD),api)

    def test_real_counts_and_no_automatic_accounts(self):
        self.assertEqual(len(self.neon['usuarios']),65)
        self.assertEqual(len(self.catalog['groups']),35)
        self.assertEqual(len(self.catalog['pending']),15)
        self.assertEqual(len(self.payload['aliases']),177)
        self.assertEqual([b['usuario_id'] for b in self.payload['vinculos']],[42])
        self.assertNotIn('usuarios',self.payload)

    def test_joelmir_and_mariana_real_aliases_cover_four_screens_and_auxiliaries(self):
        for name,short in [('JOELMIR DIVINO DOS SANTOS','JDS - JOELMIR DI'),('MARIANA LEMAR CARDOSO','MLC - MARIANA LE')]:
            group=next(g for g in self.catalog['groups'] if g['name']==name)
            self.assertEqual(set(group['labels']),set(portal.SOURCES))
            self.assertIn(short,group['labels']['vw_desempenho_acerto_portal'])
            self.assertIn(name,group['labels']['base_dinamica'])
            for source in ('mortalidade_peso_abertos','mortalidade_peso_fechados','vw_historico_lotes_criacao_portal'):
                self.assertIn(name,group['labels'][source])
            self.assertTrue(group['evidencias'])
            self.assertTrue(all('base_dinamica' not in (p['fonte_a'],p['fonte_b']) for p in group['evidencias']))

    def test_existing_general_access_including_leandro_and_lucas_is_not_downgraded(self):
        general={s['usuario_id'] for s in self.neon['escopos'] if s['recurso']=='zootecnico' and s['escopo']=='todos' and s['ativo']}
        self.assertIn(35,general);self.assertIn(42,general)
        up,down=batch.batch_sql(self.payload)
        self.assertNotRegex(up,r'(?i)\b(?:UPDATE|DELETE FROM|INSERT INTO)\s+public\.usuarios\b')
        self.assertNotIn('commercial_access',up)
        self.assertNotIn("'zootecnico','proprio'",up)
        self.assertIn("'zootecnico_identidade','proprio'",up)
        self.assertNotIn('public.usuario_setores',up);self.assertNotIn('public.usuario_relatorios',up)

    def test_joelmir_email_not_silently_corrected_and_missing_accounts_stay_pending(self):
        joelmir=next(p for p in self.catalog['correspondencias_usuarios'] if p['nome'].startswith('Joelmir'))
        mariana=next(p for p in self.catalog['correspondencias_usuarios'] if p['nome'].startswith('Mariana'))
        self.assertEqual(joelmir['email'],'jdivino@granjabrasilia.com')
        self.assertIn('confirmar_dominio_email_com_sem_br',joelmir['pendencias'])
        self.assertEqual(mariana['contas_por_email'],[])
        self.assertIn('cadastrar_pelo_portal',mariana['pendencias'])

    def test_conflicting_aliases_not_loaded_by_majority_or_initials(self):
        pending={(p['fonte'],p['valor']) for p in self.catalog['pending']}
        loaded={(p['fonte'],p['valor']) for p in self.payload['aliases']}
        self.assertFalse(pending & loaded)
        self.assertIn(('vw_desempenho_acerto_portal','LAS - LUCAS AUGU'),pending)
        # O nome completo de Lucas continua confirmado; só a sigla é duvidosa.
        self.assertIn(('base_dinamica','LUCAS AUGUSTO DOS SANTOS'),loaded)

    def test_batch_idempotency_and_guarded_rollback_without_new_tables(self):
        up,down=batch.batch_sql(self.payload)
        self.assertEqual((up,down),batch.batch_sql(json.loads(json.dumps(self.payload))))
        self.assertIn('Carga já aplicada',up)
        self.assertIn('ON CONFLICT DO NOTHING',up)
        self.assertNotIn('CREATE TABLE',up)
        self.assertIn('RETURNING to_jsonb',up)
        self.assertIn('atual IS DISTINCT FROM item',down)
        self.assertIn('Novos vínculos usam o escopo',down)
        self.assertNotIn('DELETE FROM public.usuarios',down)

    def test_final_joelmir_mariana_manager_admin_and_leandro_with_real_aliases_mocked_sql(self):
        fixtures.install_sql_helpers()
        joelmir=next(g for g in self.catalog['groups'] if g['name']=='JOELMIR DIVINO DOS SANTOS')
        mariana=next(g for g in self.catalog['groups'] if g['name']=='MARIANA LEMAR CARDOSO')
        for selected,uid,mode in (([joelmir],9001,'proprio'),([mariana],9002,'proprio'),([joelmir,mariana],9003,'equipe')):
            aliases=[dict(fonte=s,valor=v,entidade_id=g['identifier']) for g in selected for s,values in g['labels'].items() for v in values]
            access=api.validate_access(dict(ok=True,allowed=True,resource='zootecnico',reportId=13,userId=uid,
                mode=mode,technicianIds=[g['identifier'] for g in selected],aliases=aliases))
            for source in portal.PRIMARY_SOURCES:
                generated=api.scope_query('SELECT * FROM zootecnico.'+source,access)
                self.assertIn('za_scope_',generated)
                for group in selected:self.assertIn(group['labels'][source][0],generated)
            if len(selected)==1:
                view=api.scope_query('SELECT * FROM zootecnico.vw_desempenho_acerto_portal',access)
                other=mariana if selected[0] is joelmir else joelmir
                self.assertNotIn(other['labels']['vw_desempenho_acerto_portal'][0],view)
        for uid in (1,35):
            original='SELECT * FROM zootecnico.base_dinamica'
            self.assertEqual(api.scope_query(original,api.Access(uid,'todos')),original)

    def test_runtime_catalog_and_batch_catalog_agree_for_joelmir_and_mariana(self):
        # Reconstruir apenas as provas agregadas, sem inventar chaves reais.
        rows=[dict(fonte=v['fonte'],tecnico=v['valor']) for v in self.internal['valores']]
        for index,proof in enumerate(self.internal['evidencias_candidatas']):
            if 'base_dinamica' in (proof['fonte_a'],proof['fonte_b']):continue
            if proof['origem']=='mesma_linha_tecnico_exibicao':
                rows.append(dict(fonte=proof['fonte_a'],tecnico=proof['valor_a'],exibicao=proof['valor_b']))
            else:
                for side in ('a','b'):
                    rows.append(dict(fonte=proof['fonte_'+side],tecnico=proof['valor_'+side],chaves=['prova',str(index)]))
        runtime=api.build_technician_catalog(rows)
        for name in ('JOELMIR DIVINO DOS SANTOS','MARIANA LEMAR CARDOSO'):
            expected=next(g for g in self.catalog['groups'] if g['name']==name)
            actual=next(g for g in runtime['groups'] if g['name']==name)
            self.assertEqual(expected['identifier'],actual['identifier']);self.assertEqual(expected['labels'],actual['labels'])


class PendingRegistrationTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.TransactionTests('test_create_user_permissions_identity_and_aliases_same_transaction');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.ns,self.body,self.engine=fixture.ns,fixture.body,fixture.engine
        self.body['zootecnicoAccess']['allowPending']=True

    def test_unavailable_api_saves_new_user_but_no_technical_aliases_or_records(self):
        self.body['password']='offline-only'
        with patch.object(portal,'catalog_peek',return_value=None),patch.object(portal,'catalog_from_neon',return_value=None):
            response,status=self.ns['api_admin_usuario_create']()
        self.assertEqual(status,201);self.assertTrue(response['zootecnicoAccess']['pending'])
        self.assertIn(82,self.engine.users);self.assertEqual(self.engine.aliases,{})
        scopes=[p for q,p in self.engine.calls if q.startswith('INSERT INTO public.usuario_escopos_acesso')]
        self.assertTrue(any(p['resource']=='zootecnico' and p['mode']=='none' for p in scopes))
        self.assertTrue(any(p['resource']=='zootecnico_pendente' and p['mode']=='proprio' for p in scopes))
        self.assertFalse(any(q.startswith('INSERT INTO public.entidade_aliases_dados') for q,p in self.engine.calls))

    def test_team_pending_keeps_users_selected_without_inheriting_member_general(self):
        self.body['name']='Gerente da equipe'
        self.body['zootecnicoAccess']=dict(mode='equipe',userIds=[42],allowPending=True)
        self.engine.users[42]=dict(id=42,nome='Membro da equipe',email='membro@example.invalid',ativo=True,role='admin',perfil='admin')
        with patch.object(portal,'catalog_peek',return_value=None),patch.object(portal,'catalog_from_neon',return_value=None):
            response=self.ns['api_admin_usuario_patch'](41)
        self.assertTrue(response['zootecnicoAccess']['pending'])
        links=[p for q,p in self.engine.calls if q.startswith('INSERT INTO public.usuario_vinculos_dados')]
        self.assertTrue(any(p.get('resource')=='zootecnico_pendente' and p.get('id')=='42' for p in links))
        self.assertFalse(any(p.get('resource')=='zootecnico' for p in links))

    def test_confirmed_neon_catalog_does_not_require_worker_during_save(self):
        self.engine.users[41]['nome']='Usuário anterior';self.body['password']='offline-only'
        with patch.object(portal,'catalog_peek',return_value=None),patch.object(portal,'catalog_from_neon',return_value=fixtures.catalog()),patch.object(portal,'catalog_get_or_start',side_effect=AssertionError('não chamar API')):
            response,status=self.ns['api_admin_usuario_create']()
        self.assertEqual(status,201);self.assertFalse(response['zootecnicoAccess']['pending'])
        self.assertTrue(self.engine.aliases)

    def test_invalid_team_is_still_rejected_atomically(self):
        self.body['zootecnicoAccess']=dict(mode='equipe',userIds=[999],allowPending=True)
        with patch.object(portal,'catalog_peek',return_value=None),patch.object(portal,'catalog_from_neon',return_value=None):
            self.assertEqual(self.ns['api_admin_usuario_patch'](41)[1],400)
        self.assertTrue(self.engine.rollback)

    def test_confirmed_catalog_preview_from_neon_skips_unavailable_api(self):
        app=Flask(__name__)
        portal.register_routes(app,self.engine,lambda:dict(usuario_id=1,role='admin'),lambda u:True)
        with patch.object(portal,'catalog_from_neon',return_value=fixtures.catalog()),patch.object(portal,'catalog_get_or_start',side_effect=AssertionError('não chamar API')):
            response=app.test_client().post('/api/admin/zootecnico/preview',json=dict(uid=41,name=fixtures.NAME,access=dict(mode='proprio')))
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['ready'])

    def test_catalog_unavailable_is_explained_and_can_be_saved_pending(self):
        app=Flask(__name__)
        portal.register_routes(app,self.engine,lambda:dict(usuario_id=1,role='admin'),lambda u:True)
        with patch.object(portal,'catalog_from_neon',return_value=None),patch.object(portal,'catalog_get_or_start',side_effect=ValueError('Endpoint ainda não publicado.')):
            response=app.test_client().post('/api/admin/zootecnico/preview',json=dict(uid=0,name=fixtures.NAME,access=dict(mode='proprio')))
        self.assertEqual(response.status_code,200);self.assertFalse(response.json['ready'])
        self.assertTrue(response.json['canSavePending']);self.assertIn('não publicado',response.json['warning'])

    def test_saved_pending_team_is_reopened_but_authorization_stays_none(self):
        class PendingEngine(fixtures.Engine):
            mode='none';ids=[]
            def execute(self,query,params=None):
                if 'AS requested_mode' in str(query):return fixtures.Result(dict(requested_mode='equipe'))
                if 'SELECT entidade_id::bigint' in str(query):return fixtures.Result([42])
                return super().execute(query,params)
        app=Flask(__name__);engine=PendingEngine()
        portal.register_routes(app,engine,lambda:dict(usuario_id=41,role='admin'),lambda u:True)
        response=app.test_client().get('/api/admin/usuarios/41/zootecnico-access')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['access']['pending'])
        self.assertEqual(response.json['access']['userIds'],[42])
        self.assertEqual(portal.read_access(engine,41)['mode'],'none')

    def test_http_diagnostics_do_not_persist_token_or_raw_error_response(self):
        with tempfile.TemporaryDirectory(prefix='zoo-http-test-') as folder,patch.object(cache,'CACHE',Path(folder)),patch.object(cache,'build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('https://not-used.invalid',404,'MOCK-SECRET',{},io.BytesIO(b'MOCK-SECRET'))
            cache.fetch_catalog('Bearer MOCK-SECRET')
            stored=(Path(folder)/'error.json').read_text(encoding='utf-8')
            self.assertNotIn('MOCK-SECRET',stored)
            self.assertIn('opcoes',stored)
            self.assertEqual(json.loads(stored)['status'],404)


class SqlSyntaxRegressionTests(unittest.TestCase):
    def setUp(self):
        self.up,self.down=batch.batch_sql(dict(entidades=[],aliases=[],vinculos=[]))

    def test_previous_unclosed_json_key_is_rejected_before_writing(self):
        broken=self.up.replace("BTRIM(item->>'nome')","BTRIM(item->>'nome)")
        self.assertNotEqual(broken,self.up)
        with self.assertRaises(ValueError):batch.validate_batch_sql(broken)

    def test_missing_parenthesis_is_rejected(self):
        broken=self.up.replace('jsonb_build_array(linha));','jsonb_build_array(linha);',1)
        with self.assertRaises(ValueError):batch.validate_batch_sql(broken)

    def test_up_and_rollback_use_explicit_block_terminators(self):
        self.assertIn('END;\n$batch$;',self.up)
        self.assertIn('END;\n$undo$;',self.down)
        batch.validate_batch_sql(self.up);batch.validate_batch_sql(self.down)

    def test_quotes_and_parentheses_in_json_are_data_not_sql(self):
        up,_=batch.batch_sql(dict(entidades=[dict(id='test',nome="O'Brien (teste")],aliases=[],vinculos=[]))
        batch.validate_batch_sql(up)

    def test_actual_user_validation_select_parses_with_available_local_parser(self):
        try:import duckdb
        except ImportError:self.skipTest('Parser local opcional indisponível; não instalar dependências.')
        import re
        select=re.search(r'IF NOT EXISTS\((SELECT 1 FROM public\.usuarios.*?)\) THEN',self.up,re.S)[1]
        # Só parser SQL local: não conecta nem executa a instrução, nem compila PL/pgSQL.
        self.assertEqual(len(duckdb.extract_statements(select)),1)
        broken=select.replace("BTRIM(item->>'nome')","BTRIM(item->>'nome)")
        with self.assertRaises(duckdb.ParserException):duckdb.extract_statements(broken)


if __name__=='__main__':unittest.main()
