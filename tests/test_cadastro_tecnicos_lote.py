"""Lote: só API simulada e criptografia local com dados fictícios; nenhum acesso real."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import cadastrar_tecnicos_integracao as batch


def manifest():
    return dict(version=1,users=[dict(name='Técnico Um',email='um@example.invalid',identityId='t1',identityConfirmed=True,emailConfirmed=True),
                                 dict(name='Técnico Dois',email='dois@example.invalid',identityId='t2',identityConfirmed=True,emailConfirmed=True),
                                 dict(name='Diretor',email='DIRETOR@example.invalid',identityId='t1',identityConfirmed=True,emailConfirmed=True)])


class FakeApi:
    def __init__(self):
        self.identities=[dict(id='t1',name='TECNICO UM',aliases={s:['UM'] for s in batch.PRIMARY}),
                         dict(id='t2',name='TECNICO DOIS',aliases={s:['DOIS'] for s in batch.PRIMARY})]
        self.data=dict(users=[dict(id=42,dbId=42,name='Diretor',email='diretor@example.invalid',role='director',status='active',sectors=['integracao'],reportIds=[13],reportAccessMode='sector',commercialAccess={'mode':'general'},operationPermissions=[]),
                              dict(id=35,dbId=35,name='Leandro',email='leandro@example.invalid',role='sector',status='active',sectors=['integracao'],reportIds=[13],reportAccessMode='sector',commercialAccess={'mode':'seller','code':'7'},operationPermissions=['comercial.frete.editar'])],
                       reports=[dict(dbId=13,id=13,sector='integracao')],sectors=['integracao'])
        self.scopes={42:dict(mode='todos',pending=False,identityId=None),35:dict(mode='todos',pending=False,identityId=None)}
        self.calls=[];self.bodies=[];self.fail=False;self.commit_error=False;self.bad_role=False;self.change_existing=False;self.next=80;self.version=3
    def bootstrap(self):self.calls.append(('GET','/api/auth/bootstrap'));return copy.deepcopy(self.data)
    def catalog(self):
        self.calls.append(('GET','/api/admin/usuarios/0/zootecnico-access'))
        if self.version!=3:raise batch.BatchError('Backend antigo')
        return dict(access={'formVersion':3},identities=copy.deepcopy(self.identities),users=[dict(id=u['dbId'],name=u['name'],email=u['email'],active=u['status']=='active') for u in self.data['users']])
    def user_access(self,uid):self.calls.append(('GET',f'/api/admin/usuarios/{uid}/zootecnico-access'));return copy.deepcopy(self.scopes[uid])
    def create(self,body):
        self.calls.append(('POST','/api/admin/usuarios'));self.bodies.append(copy.deepcopy(body))
        if self.fail and not self.commit_error:raise batch.ApiError(503)
        self.next+=1
        user=dict(id=self.next,dbId=self.next,name=body['name'],email=body['email'].lower(),role='director' if self.bad_role else body['role'],
                  status=body['status'],sectors=body['sectors'],reportAccessMode=body['reportAccessMode'],reportIds=body['reportIds'],
                  commercialAccess=body['commercialAccess'],operationPermissions=body['operationPermissions'])
        self.data['users'].append(user)
        access=body['zootecnicoAccess'];self.scopes[self.next]=dict(mode=access['mode'],identityId=access['identityId'],pending=access['identityId'] is None)
        if self.change_existing:self.data['users'][0]['role']='sector'
        if self.commit_error:raise batch.ApiError(500)
        return 201,dict(ok=True,data=copy.deepcopy(self.data))


class FakeBook:
    def __init__(self):self.entries={};self.generated=0
    def prepare(self,email):
        if email in self.entries and self.entries[email]['status']!='prepared':raise batch.BatchError('Envio anterior')
        if email not in self.entries:
            self.generated+=1;self.entries[email]=dict(password='MOCK-ONLY-'+str(self.generated),status='prepared')
        return self.entries[email]
    def mark(self,email,status,uid=None):self.entries[email].update(status=status,uid=uid)


class BatchTests(unittest.TestCase):
    def setUp(self):self.api=FakeApi();self.manifest=manifest();self.book=FakeBook()
    def plan(self):return batch.current_plan(self.api,self.manifest)[0]
    def apply(self,plan=None,progress=lambda rows:None):
        plan=plan or self.plan();return batch.apply_plan(self.api,self.manifest,plan,plan['approvalDigest'],self.book,progress)

    def test_check_is_read_only_does_not_generate_passwords_or_change_existing(self):
        before=copy.deepcopy(self.api.data)
        with patch.object(batch.secrets,'token_urlsafe',side_effect=AssertionError('não gerar')):plan=self.plan()
        self.assertEqual(self.api.data,before);self.assertFalse(any(m!='GET' for m,p in self.api.calls))
        self.assertEqual([r['action'] for r in plan['rows']],['new','new','existing'])
        self.assertEqual(plan['rows'][2]['existingAccess']['mode'],'todos')

    def test_apply_only_creates_new_users_with_official_payload_then_verifies(self):
        old=copy.deepcopy(self.api.data['users']);scopes=copy.deepcopy(self.api.scopes)
        records=self.apply()
        self.assertEqual([r['status'] for r in records],['created_verified','created_verified','existing_untouched'])
        self.assertEqual(self.api.data['users'][:2],old);self.assertEqual(self.api.scopes[35],scopes[35]);self.assertEqual(self.api.scopes[42],scopes[42])
        for body in self.api.bodies:
            self.assertEqual(body['role'],'sector');self.assertEqual(body['sectors'],['integracao'])
            self.assertEqual(body['reportIds'],[13]);self.assertEqual(body['reportAccessMode'],'specific')
            self.assertEqual(body['zootecnicoAccess']['mode'],'proprio');self.assertEqual(body['zootecnicoAccess']['formVersion'],3)
            self.assertEqual(body['commercialAccess'],{'mode':'none'});self.assertEqual(body['operationPermissions'],[])
        self.assertEqual(len({b['password'] for b in self.api.bodies}),2)
        self.assertTrue(all(e['status']=='confirmed' for e in self.book.entries.values()))
        self.assertFalse(any(m in ('PATCH','PUT','DELETE') for m,p in self.api.calls))
        self.assertNotIn('password',json.dumps(records))

    def test_repeat_skips_users_without_resetting_password_or_profile(self):
        plan=self.plan();self.apply(plan);count=len(self.api.bodies);old=copy.deepcopy(self.api.data)
        records=self.apply(plan)
        self.assertEqual(len(self.api.bodies),count);self.assertEqual(self.api.data,old)
        self.assertTrue(all(r['status']=='existing_untouched' for r in records))

    def test_no_approval_or_offline_plan_never_creates(self):
        plan=self.plan()
        with self.assertRaises(batch.BatchError):batch.apply_plan(self.api,self.manifest,plan,'WRONG',self.book)
        offline=batch.make_plan(self.manifest,[],self.api.identities,'offline')
        with self.assertRaises(batch.BatchError):self.apply(offline)
        self.assertEqual(self.book.generated,0);self.assertEqual(self.api.bodies,[])

    def test_last_identity_changed_stops_before_first_post(self):
        plan=self.plan();self.api.identities[1]['aliases']['base_dinamica'].append('MUDOU')
        with self.assertRaises(batch.BatchError):self.apply(plan)
        self.assertEqual(self.api.bodies,[]);self.assertEqual(self.book.generated,0)

    def test_unknown_identity_creates_pending_without_records(self):
        self.manifest['users'][0]['identityId']='not-confirmed-in-live-catalog'
        records=self.apply()
        self.assertEqual(records[0]['status'],'created_pending')
        self.assertIsNone(self.api.bodies[0]['zootecnicoAccess']['identityId'])

    def test_email_variant_or_same_person_different_email_is_held(self):
        row=self.manifest['users'][0]
        self.api.data['users'].append(dict(dbId=70,id=70,name=row['name'],email='outra@example.invalid',role='sector',status='active'))
        plan=self.plan();self.assertEqual(plan['rows'][0]['action'],'hold')
        self.apply(plan);self.assertFalse(any(b['email']==row['email'] for b in self.api.bodies))
        self.manifest['users'][0].update(name='Outro Nome',email='mesmo@granjabrasilia.com.br')
        self.api.data['users'][-1]['email']='mesmo@granjabrasilia.com'
        self.assertEqual(self.plan()['rows'][0]['action'],'hold')

    def test_duplicate_current_email_is_not_treated_as_new(self):
        self.api.data['users'].append(dict(self.api.data['users'][0],id=70,dbId=70))
        self.assertEqual(self.plan()['rows'][2]['action'],'hold')

    def test_legacy_report_key_is_resolved_from_actual_report_id_13(self):
        self.api.data['reports'][0]['id']=99
        self.apply();self.assertTrue(all(b['reportIds']==[99] for b in self.api.bodies))
        self.assertTrue(all(u['reportIds']==[99] for u in self.api.data['users'][2:]))

    def test_ambiguous_report_or_wrong_sector_prevents_creation(self):
        self.api.data['reports'].append(dict(dbId=20,id=13,sector='outro'))
        with self.assertRaises(batch.BatchError):self.plan()
        self.api.data['reports'].pop();self.api.data['reports'][0]['sector']='comercial'
        with self.assertRaises(batch.BatchError):self.plan()
        self.assertEqual(self.api.bodies,[])

    def test_uncertain_post_is_not_retried_and_secret_is_not_marked_confirmed(self):
        plan=self.plan();self.api.fail=True;progress=[]
        with self.assertRaises(batch.ApiError):self.apply(plan,lambda rows:progress.extend(copy.deepcopy(rows)))
        self.assertEqual(len(self.api.bodies),1)
        self.assertEqual(self.book.entries['um@example.invalid']['status'],'uncertain')
        self.assertEqual(progress[-1]['status'],'request_uncertain')
        with self.assertRaises(batch.BatchError):self.apply(plan)
        self.assertEqual(len(self.api.bodies),1)

    def test_timeout_after_commit_is_skipped_later_without_changing_unknown_password(self):
        plan=self.plan();self.api.commit_error=True
        with self.assertRaises(batch.ApiError):self.apply(plan)
        self.api.commit_error=False;self.manifest['users']=self.manifest['users'][:1]
        fresh=self.plan();old=copy.deepcopy(self.api.data)
        self.apply(fresh)
        self.assertEqual(self.api.data,old)
        self.assertEqual(self.book.entries['um@example.invalid']['status'],'uncertain')

    def test_bad_verification_keeps_created_account_flagged_without_automatic_patch(self):
        self.api.bad_role=True;progress=[]
        with self.assertRaises(batch.BatchError):self.apply(progress=lambda rows:progress.extend(copy.deepcopy(rows)))
        self.assertEqual(progress[-1]['status'],'created_requires_review')
        self.assertEqual(self.book.entries['um@example.invalid']['status'],'created_unverified')
        self.assertFalse(any(m=='PATCH' for m,p in self.api.calls))

    def test_created_but_missing_response_is_reported_without_retry(self):
        progress=[]
        with patch.object(self.api,'create',return_value=(201,{'data':{'users':[]}})) as create:
            with self.assertRaises(batch.BatchError):self.apply(progress=lambda rows:progress.extend(copy.deepcopy(rows)))
        self.assertEqual(create.call_count,1)
        self.assertEqual(progress[-1]['status'],'created_response_unverified')
        self.assertEqual(self.book.entries['um@example.invalid']['status'],'uncertain')

    def test_existing_profile_change_during_run_is_detected_not_overwritten(self):
        self.api.change_existing=True
        with self.assertRaises(batch.BatchError):self.apply()
        self.assertEqual(self.api.data['users'][0]['role'],'sector')
        self.assertEqual(len(self.api.bodies),1)

    def test_password_transport_does_not_enable_redirects(self):
        self.assertIsNone(batch.NoRedirect().redirect_request(None,None,302,'',None,'https://not-used.invalid'))


class CredentialAndManifestTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','DPAPI do Windows')
    def test_credentials_are_encrypted_at_rest_and_recoverable_by_windows_owner(self):
        with tempfile.TemporaryDirectory(prefix='lote-credentials-test-') as tmp:
            path=Path(tmp)/'book.dpapi'
            with patch.object(batch.secrets,'token_urlsafe',return_value='ONLY-TEST-NOT-A-REAL-PASSWORD'):
                book=batch.CredentialBook(path);entry=book.prepare('fake@example.invalid')
            ciphertext=path.read_bytes()
            self.assertNotIn(b'ONLY-TEST-NOT-A-REAL-PASSWORD',ciphertext)
            self.assertNotIn(b'fake@example.invalid',ciphertext)
            restored=batch.CredentialBook(path)
            self.assertEqual(restored.entries,book.entries)
            book.mark('fake@example.invalid','sending')
            with self.assertRaises(batch.BatchError):book.prepare('fake@example.invalid')

    def test_manifest_validation_case_insensitive_email_and_full_name_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'manifest.json';data=manifest();data['users'][1]['email']='UM@example.invalid'
            batch.save_json(path,data)
            with self.assertRaises(batch.BatchError):batch.load_manifest(path)
            data=manifest();data['users'][1]['name']='TECNICO UM';batch.save_json(path,data)
            with self.assertRaises(batch.BatchError):batch.load_manifest(path)

    def test_prepared_real_manifest_has_15_confirmed_people_corrected_email_and_no_credentials(self):
        path=batch.OUTPUT/'usuarios.json'
        if not path.is_file():self.skipTest('Manifesto local não acompanha o repositório.')
        data=batch.load_manifest(path)
        self.assertEqual(len(data['users']),15)
        self.assertTrue(all(u['identityConfirmed'] and u['emailConfirmed'] for u in data['users']))
        joelmir=next(u for u in data['users'] if u['name'].startswith('Joelmir'))
        self.assertTrue(joelmir['email'].endswith('@granjabrasilia.com.br'))
        self.assertNotIn('password',path.read_text(encoding='utf-8'))
        self.assertNotIn('agrosys',path.read_text(encoding='utf-8').lower())


if __name__=='__main__':unittest.main()
