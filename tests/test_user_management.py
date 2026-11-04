"""Gestão de usuários: Flask e banco simulados; não importa app/.env nem usa rede."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import user_management as management
import test_operation_permissions as existing


class Engine:
    def __init__(self):
        self.users = {
            1: dict(id=1, role='admin', perfil='admin', ativo=True, excluido_em=None, nome='Admin', email='admin@example.invalid'),
            2: dict(id=2, role='sector', perfil='usuario', ativo=True, excluido_em=None, nome='Operador', email='operador@example.invalid', operation_permissions=[management.PERMISSION]),
            3: dict(id=3, role='sector', perfil='usuario', ativo=True, excluido_em=None, nome='Comum', email='comum@example.invalid'),
        }
        self.audit=[]; self.actor={}; self.calls=[]; self.ready=True; self.fail_audit=False
        self.history=[dict(usuario_id=3, chamado_id=70)]

    def begin(self): return self
    def connect(self): return self
    def __enter__(self):
        self.snapshot=copy.deepcopy((self.users,self.audit));return self
    def __exit__(self, kind, value, trace):
        if kind: self.users,self.audit=self.snapshot
        self.actor={}
        return False
    def execute(self, sql, params=None):
        sql=' '.join(str(sql).split());p=params or {};self.calls.append((sql,p))
        if 'to_regclass' in sql: return existing.Result(self.ready)
        if 'set_config' in sql:
            self.actor=json.loads(p['actor']);return existing.Result()
        if sql.startswith('SELECT id,role'):
            return existing.Result(copy.deepcopy(self.users.get(p['uid'])))
        if sql.startswith('UPDATE public.usuarios'):
            user=self.users.get(p['uid'])
            if not user:return existing.Result()
            old=copy.deepcopy(user)
            if 'excluido_em=NOW()' in sql:user.update(ativo=False,excluido_em='2026-11-04T12:00:00Z');action='exclusao'
            elif 'excluido_em=NULL' in sql:
                if not user['excluido_em']:return existing.Result()
                user.update(ativo=False,excluido_em=None);action='restauracao'
            else:user['ativo']=p['active'];action='desbloqueio' if p['active'] else 'bloqueio'
            if user != old:
                if self.fail_audit:raise RuntimeError('Auditoria indisponível simulada')
                self.audit.append(dict(id=len(self.audit)+1,ocorrido_em=datetime.now(timezone.utc),acao=action,
                    autor_id=self.actor.get('id'),autor_nome=self.actor.get('nome'),autor_email=self.actor.get('email'),
                    usuario_id=user['id'],usuario_nome=user['nome'],usuario_email=user['email'],origem='portal'))
            return existing.Result()
        if 'FROM public.auditoria_usuarios' in sql:return existing.Result(list(reversed(self.audit))[:200])
        return existing.Result()


class UserManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine();self.actor_id=2
        self.app=Flask(__name__)
        def authenticate():
            user=self.engine.users.get(self.actor_id)
            if not user or not user['ativo'] or user['excluido_em']:return None
            return dict(user,usuario_id=user['id'])
        management.register_routes(self.app,self.engine,authenticate,
            lambda:dict(users=list(self.engine.users.values()),reports=[{'url':'private','title':'BI'}]))
        self.client=self.app.test_client()

    def test_regular_and_director_cannot_manage_admin_can_without_grant(self):
        self.actor_id=3
        self.assertEqual(self.client.post('/api/admin/usuarios/1/status',json={'status':'blocked','confirmAdminBlock':True}).status_code,403)
        self.engine.users[3]['role']='director'
        self.assertEqual(self.client.delete('/api/admin/usuarios/2').status_code,403)
        self.actor_id=1
        self.assertEqual(self.client.post('/api/admin/usuarios/3/status',json={'status':'blocked'}).status_code,200)

    def test_last_admin_can_be_blocked_with_explicit_confirmation_and_audit(self):
        response=self.client.post('/api/admin/usuarios/1/status',json={'status':'blocked','confirmAdminBlock':True})
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.engine.users[1]['ativo'])
        event=self.engine.audit[-1]
        self.assertEqual((event['autor_id'],event['usuario_id'],event['acao']),(2,1,'bloqueio'))
        self.assertEqual(response.json['data']['reports'][0]['url'],'')

    def test_admin_block_requires_confirmation_for_admin_and_delegate(self):
        for actor in (1,2):
            self.actor_id=actor
            self.assertEqual(self.client.post('/api/admin/usuarios/1/status',json={'status':'blocked'}).status_code,400)
        self.assertTrue(self.engine.users[1]['ativo']);self.assertEqual(self.engine.audit,[])

    def test_admin_can_block_itself_even_when_it_is_the_last_active_admin(self):
        self.actor_id=1
        response=self.client.post('/api/admin/usuarios/1/status',json={'status':'blocked','confirmAdminBlock':True})
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.engine.users[1]['ativo'])
        self.assertEqual(self.engine.audit[-1]['autor_id'],1)

    def test_delegate_can_unblock_admin_and_cannot_change_role_in_status(self):
        self.engine.users[1]['ativo']=False
        self.assertEqual(self.client.post('/api/admin/usuarios/1/status',json={'status':'active'}).status_code,200)
        self.assertEqual(self.engine.audit[-1]['acao'],'desbloqueio')
        self.assertEqual(self.client.post('/api/admin/usuarios/1/status',json={'status':'active','role':'sector'}).status_code,400)
        self.assertEqual(self.engine.users[1]['role'],'admin')

    def test_neither_admin_nor_delegate_can_delete_admin(self):
        for actor in (1,2):
            self.actor_id=actor
            self.assertEqual(self.client.delete('/api/admin/usuarios/1').status_code,403)
        self.assertEqual(self.engine.audit,[])

    def test_archive_preserves_history_is_idempotent_and_cannot_reactivate(self):
        history=copy.deepcopy(self.engine.history)
        self.assertEqual(self.client.delete('/api/admin/usuarios/3').status_code,200)
        self.assertEqual(self.engine.history,history)
        self.assertEqual(self.engine.audit[-1]['acao'],'exclusao')
        self.assertFalse(self.engine.users[3]['ativo'])
        self.assertEqual(self.client.delete('/api/admin/usuarios/3').status_code,200)
        self.assertEqual(len(self.engine.audit),1)
        self.assertEqual(self.client.post('/api/admin/usuarios/3/status',json={'status':'active'}).status_code,404)

    def test_self_deletion_is_denied(self):
        self.assertEqual(self.client.delete('/api/admin/usuarios/2').status_code,403)

    def test_only_admin_restores_archived_account_which_remains_blocked(self):
        self.client.delete('/api/admin/usuarios/3')
        self.assertEqual(self.client.post('/api/admin/usuarios/3/restaurar').status_code,403)
        self.actor_id=1
        self.assertEqual(self.client.post('/api/admin/usuarios/3/restaurar').status_code,200)
        self.assertIsNone(self.engine.users[3]['excluido_em']);self.assertFalse(self.engine.users[3]['ativo'])
        self.assertEqual(self.engine.audit[-1]['acao'],'restauracao')

    def test_audit_failure_rolls_back_block_and_archive(self):
        self.engine.fail_audit=True
        for path,method,body in (('/api/admin/usuarios/1/status','post',{'status':'blocked','confirmAdminBlock':True}),
                                 ('/api/admin/usuarios/3','delete',None)):
            before=copy.deepcopy(self.engine.users)
            response=getattr(self.client,method)(path,json=body)
            self.assertEqual(response.status_code,503)
            self.assertEqual(self.engine.users,before);self.assertEqual(self.engine.audit,[])

    def test_missing_migration_refuses_mutations(self):
        self.engine.ready=False
        self.assertEqual(self.client.delete('/api/admin/usuarios/3').status_code,400)
        self.assertEqual(self.client.post('/api/admin/usuarios/1/status',json={'status':'blocked','confirmAdminBlock':True}).status_code,400)
        self.assertTrue(self.engine.users[1]['ativo']);self.assertIsNone(self.engine.users[3]['excluido_em'])

    def test_only_admin_reads_audit_without_passwords(self):
        self.client.delete('/api/admin/usuarios/3')
        self.assertEqual(self.client.get('/api/admin/usuarios/auditoria').status_code,403)
        self.actor_id=1
        response=self.client.get('/api/admin/usuarios/auditoria')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['entries'][0]['autor_id'],2)
        self.assertNotIn('senha_hash',response.get_data(as_text=True))
        self.assertIn('LIMIT 200',self.engine.calls[-1][0])

    def test_revocation_and_block_take_effect_on_next_request(self):
        self.engine.users[2]['operation_permissions']=[]
        self.assertEqual(self.client.delete('/api/admin/usuarios/3').status_code,403)
        self.engine.users[2]['ativo']=False
        self.assertEqual(self.client.delete('/api/admin/usuarios/3').status_code,401)

    def test_delegate_whitelist_denies_business_admin_edit_and_grant_routes(self):
        delegate=dict(self.engine.users[2])
        for path,method in [('/api/chamados','GET'),('/api/auth/zootecnico-access','GET'),
                            ('/api/auth/report-access','GET'),('/api/admin/jobs','POST'),
                            ('/api/admin/usuarios/1','PATCH'),('/api/admin/usuarios/1/password','PATCH'),
                            ('/api/portal-data','PUT'),('/api/admin/setores','POST')]:
            self.assertFalse(management.allowed_request(delegate,path,method),(path,method))
        for path,method in [('/api/auth/me','GET'),('/api/auth/change-password','POST'),
                            ('/api/admin/usuarios','POST'),('/api/admin/usuarios/1/status','POST'),
                            ('/api/admin/usuarios/3','DELETE')]:
            self.assertTrue(management.allowed_request(delegate,path,method))
        self.assertTrue(management.allowed_request(self.engine.users[1],'/api/admin/setores','POST'))

    def test_delegate_create_cannot_escalate_or_reset_existing_accounts(self):
        management.validate_delegated_create({'name':'Comum','email':'u@example.invalid','password':'fake-only'})
        for payload in [{'role':'admin'},{'role':'director'}, {'operationPermissions':[management.PERMISSION]},
                        {'commercialAccess':{'mode':'general'}},{'zootecnicoAccess':{'mode':'todos'}},
                        {'ticketPanelAccess':True},{'user_id':1}]:
            with self.assertRaises(ValueError):management.validate_delegated_create(payload)


class OfficialCreateTests(existing.OperationTests):
    # Reutiliza o endpoint oficial extraído por AST, com a mesma transação simulada.
    def setUp(self):
        super().setUp()
        self.ns['OPERATION_PERMISSIONS']={existing.PERMISSION,management.PERMISSION}

    def test_delegate_create_uses_official_hash_no_privileges_and_audit_context(self):
        self.actor=dict(usuario_id=2,nome='Operador',email='operador@example.invalid',role='sector',ativo=True,
                        operation_permissions=[management.PERMISSION])
        self.body.update(password='fake-password-not-a-real-secret',role='sector')
        original=self.engine.execute
        def execute(sql,p=None):
            if 'to_regclass' in str(sql):return existing.Result(True)
            return original(sql,p)
        self.engine.execute=execute
        response=self.ns['api_admin_usuario_create']()
        self.assertEqual(response[1],201)
        creation=next(sql for sql,p in self.engine.calls if sql.startswith('INSERT INTO public.usuarios'))
        self.assertIn("crypt(:senha, gen_salt('bf', 12))",creation)
        self.assertEqual(self.engine.users[82]['role'],'sector')
        actor=next(json.loads(p['actor']) for sql,p in self.engine.calls if 'set_config' in sql)
        self.assertEqual(actor['id'],2)
        self.assertNotIn('fake-password',json.dumps(actor))
        self.assertEqual(self.engine.permissions.get(82,set()),set())

    def test_delegate_cannot_create_admin_through_official_endpoint(self):
        self.actor=dict(usuario_id=2,role='sector',ativo=True,operation_permissions=[management.PERMISSION])
        self.body.update(password='fake-only',role='admin')
        self.assertEqual(self.ns['api_admin_usuario_create']()[1],400)
        self.assertNotIn(82,self.engine.users)

    def test_delegated_director_cannot_inherit_general_access_in_external_apis(self):
        actor=dict(usuario_id=2,role='director',perfil='gestor',ativo=True,
                   commercial_access={'mode':'general'},operation_permissions=[management.PERMISSION,existing.PERMISSION])
        public=self.ns['_usuario_publico'](actor)
        self.assertEqual((public['role'],public['perfil']),('sector','usuario'))
        self.assertEqual(public['commercialAccess'],{'mode':'none'})
        self.assertEqual(public['operationPermissions'],[management.PERMISSION])
        self.assertFalse(public['isAdmin'])


if __name__=='__main__':unittest.main()
