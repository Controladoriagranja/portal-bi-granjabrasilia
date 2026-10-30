"""Testes curtos com mocks: nenhum upload, banco, app.py importado ou .env lido."""
import ast
import base64
import hashlib
import hmac
import io
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, Request as FlaskRequest, request, jsonify
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wsgi import LimitedStream
from urllib.error import HTTPError, URLError
from itsdangerous import BadSignature, SignatureExpired

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
import drive_attachments as drive


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.user = {'usuario_id': 41, 'nome': 'Pessoa / Autenticada', 'email': 'test@example.invalid'}
        self.since = datetime.now(timezone.utc) - timedelta(minutes=3)
        self.key = 'a' * 32
        self.config = ('https://script.google.com/macros/s/test-only/exec', 'test-only-not-a-real-secret-0000000000')
        self.file, self.data = drive.read_file(FileStorage(io.BytesIO(b'file-fixture'), filename='teste.pdf'))
        self.ticket = {'id': 7, 'numero': 1007, 'anexos': []}
        self.conn = Mock()
        self.conn.execute.return_value.mappings.return_value.first.return_value = None
        self.conn.execute.return_value.scalar_one.return_value = 0

    def reserve(self):
        with patch.object(drive, 'authorized_ticket', return_value=(self.user, self.ticket)):
            return drive.reserve(self.conn, self.user, 7, self.since, self.key, self.file)

    def test_config_only_accepts_google_exec_server_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(drive.upload_config())
            os.environ.update(PORTAL_DRIVE_UPLOAD_URL=self.config[0], PORTAL_DRIVE_UPLOAD_SECRET=self.config[1])
            self.assertEqual(drive.upload_config(), self.config)
            os.environ['PORTAL_DRIVE_UPLOAD_URL'] = 'http://127.0.0.1/private'
            self.assertIsNone(drive.upload_config())

    def test_file_limit_and_path_sanitization(self):
        info, _ = drive.read_file(FileStorage(io.BytesIO(b'x'), filename=r'..\pasta\teste.pdf'))
        self.assertEqual(info['original_name'], 'teste.pdf')
        for data in (b'', b'x' * (drive.MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                drive.read_file(FileStorage(io.BytesIO(data), filename='arquivo.pdf'))

    def test_filename_identity_timestamp_and_receipt_only(self):
        row = self.reserve()
        self.assertRegex(row['stored_name'], r'^Pessoa_Autenticada_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_a{32}_teste.pdf$')
        self.assertEqual(row['bytes_size'], len(self.data))
        self.assertNotIn('file-fixture', repr(self.conn.execute.call_args_list))
        self.assertNotIn('data', row)

    def test_existing_same_file_reuses_original_key(self):
        row = self.reserve()
        row['drive_file_id'] = 'driveFile12345678'
        row['status'] = 'done'
        self.conn.reset_mock()
        self.conn.execute.return_value.mappings.return_value.first.return_value = row
        self.assertEqual(self.reserve()['upload_key'], self.key)
        self.assertEqual(self.conn.execute.call_count, 1)

    def test_same_key_cannot_change_owner_ticket_or_contents(self):
        row = self.reserve()
        for name, value in [('usuario_id', 42), ('chamado_id', 8), ('sha256', '0' * 64)]:
            self.conn.execute.return_value.mappings.return_value.first.return_value = {**row, name: value}
            with self.assertRaises(ValueError): self.reserve()

    def test_completed_and_pending_files_count_toward_limit(self):
        self.ticket['anexos'] = [{'name':'already'}] * 4
        self.conn.execute.return_value.scalar_one.return_value = 1
        with self.assertRaises(ValueError): self.reserve()

    def test_foreign_or_blocked_user_cannot_upload(self):
        with self.assertRaises(PermissionError):
            drive.authorized_ticket(self.conn, self.user, 7, self.since)
        self.conn.execute.return_value.mappings.return_value.first.side_effect = [self.user, None]
        with self.assertRaises(PermissionError):
            drive.authorized_ticket(self.conn, self.user, 7, self.since)
        sql = str(self.conn.execute.call_args_list[-1].args[0])
        self.assertIn('c.solicitante_id = :uid', sql)
        self.assertIn('c.criado_em >= :since', sql)
        self.assertIn('FOR UPDATE OF c', sql)

    def test_signed_post_is_fixed_folder_and_limited_response(self):
        row = self.reserve()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":true,"fileId":"driveFile12345678"}'
        with patch.object(drive, 'urlopen', return_value=response) as http:
            self.assertEqual(drive.send_to_drive(self.config, row, self.data), 'driveFile12345678')
        req = http.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.method, 'POST')
        self.assertEqual(http.call_args.kwargs['timeout'], 35)
        expected = hmac.new(self.config[1].encode(), (body['timestamp']+'.'+body['payload']).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(body['signature'], expected)
        self.assertNotIn(self.config[1], req.data.decode())
        payload = json.loads(body['payload'])
        self.assertEqual(payload['folder'], drive.FOLDER_ID)
        self.assertEqual(base64.b64decode(payload['data']), self.data)
        response.read.assert_called_once_with(16385)

    def test_google_failure_not_persisted_or_disclosed(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":false}'
        with patch.object(drive, 'urlopen', return_value=response), self.assertRaises(drive.DriveUploadError):
            drive.send_to_drive(self.config, self.reserve(), self.data)

    def test_finish_is_idempotent_and_preserves_previous_attachments(self):
        row = self.reserve()
        self.ticket['anexos'] = [{'name':'anterior'}]
        with patch.object(drive, 'authorized_ticket', return_value=(self.user, self.ticket)):
            attachment = drive.finish(self.conn, self.user, 7, self.since, row, 'driveFile12345678')
            self.assertEqual(len(self.ticket['anexos']), 2)
            self.assertEqual(attachment['url'], 'https://drive.google.com/file/d/driveFile12345678/view')
            self.conn.reset_mock()
            self.assertEqual(drive.finish(self.conn, self.user, 7, self.since, row, 'driveFile12345678'), attachment)
            self.conn.execute.assert_not_called()

    def test_stale_save_cannot_remove_or_forge_managed_attachment(self):
        actual = {'storage':'portal-drive', 'key':'real', 'url':'server-url'}
        fake = {'storage':'portal-drive', 'key':'fake'}
        legacy = {'name':'old-file'}
        self.assertEqual(drive.merge_managed([actual], [legacy, fake]), [legacy, actual])

    def routes(self, request_class=None):
        app = Flask('mock-upload-test')
        if request_class is not None: app.request_class=request_class
        mocked = Mock(wraps=drive)
        mocked.MAX_BYTES = drive.MAX_BYTES
        mocked.DriveUploadError = drive.DriveUploadError
        mocked.upload_config.return_value = self.config
        receipt = self.reserve()
        mocked.reserve.return_value = receipt
        mocked.send_to_drive.return_value = 'driveFile12345678'
        mocked.finish.return_value = {'storage':'portal-drive', 'url':'https://drive.google.com/file/d/driveFile12345678/view'}
        ns = {'forms_drive':mocked, 'request':request, 'jsonify':jsonify, 're':re, 'log':Mock(),
              '_usuario_autenticado':lambda:self.user, '_extrair_bearer_token':lambda:'mock-token',
              '_auth_serializer':Mock(), 'forms_read_context':Mock(return_value=self.since),
              '_resposta_nao_autorizado':lambda:(jsonify(ok=False),401), 'engine':Mock(),
              'BadSignature':BadSignature, 'SignatureExpired':SignatureExpired, 'RequestEntityTooLarge':RequestEntityTooLarge,
              'LimitedStream':LimitedStream}
        ns.update(forms_new_context=Mock(return_value='new-signed-context'), datetime=datetime, timezone=timezone)
        mocked.upload_status.return_value = 'ready'
        mocked.direct_receipt.side_effect = drive.direct_receipt
        mocked.direct_attachment.side_effect = drive.direct_attachment
        conn = Mock()
        ns['engine'].begin.return_value.__enter__ = Mock(return_value=conn)
        ns['engine'].begin.return_value.__exit__ = Mock(return_value=False)
        tree = ast.parse((ROOT/'api/app.py').read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {'_forms_import_response','_limit_forms_upload_request','api_forms_attachment',
                    'api_forms_attachment_status','api_forms_attachment_direct'}:
                node.decorator_list=[]
                exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated-upload','exec'),ns)
        app.add_url_rule('/upload',view_func=ns['api_forms_attachment'],methods=['POST'])
        app.add_url_rule('/status',view_func=ns['api_forms_attachment_status'],methods=['GET'])
        app.add_url_rule('/direct',view_func=ns['api_forms_attachment_direct'],methods=['POST'])
        return app.test_client(), ns, mocked

    def payload(self):
        return {'context':'signed-test','ticketId':'7','uploadId':self.key,
                'file':(io.BytesIO(self.data),'teste.pdf')}

    def test_endpoint_requires_authentication_and_signed_context(self):
        client, ns, remote = self.routes()
        ns['_usuario_autenticado'] = lambda:None
        self.assertEqual(client.post('/upload',data=self.payload()).status_code,401)
        remote.send_to_drive.assert_not_called()
        ns['_usuario_autenticado'] = lambda:self.user
        ns['forms_read_context'].side_effect = BadSignature('invalid')
        self.assertEqual(client.post('/upload',data=self.payload()).status_code,403)
        remote.send_to_drive.assert_not_called()

    def test_endpoint_rejects_identity_override_and_missing_configuration(self):
        client, ns, remote = self.routes()
        payload = self.payload(); payload['nome']='Outra pessoa'
        self.assertEqual(client.post('/upload',data=payload).status_code,400)
        remote.send_to_drive.assert_not_called()
        remote.upload_config.return_value = None
        self.assertEqual(client.post('/upload',data=self.payload()).status_code,503)

    def test_endpoint_commits_metadata_after_http_and_rechecks_access(self):
        client, ns, remote = self.routes()
        events=[]
        ns['engine'].begin.return_value.__enter__.side_effect=lambda:events.append('begin')
        ns['engine'].begin.return_value.__exit__.side_effect=lambda *args:events.append('commit')
        remote.send_to_drive.side_effect=lambda *args:events.append('http') or 'driveFile12345678'
        response=client.post('/upload',data=self.payload())
        self.assertEqual(response.status_code,200)
        self.assertEqual(events,['begin','commit','http','begin','commit'])
        remote.finish.assert_called_once()
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_endpoint_failure_never_records_success(self):
        client, ns, remote = self.routes()
        remote.send_to_drive.side_effect = TimeoutError('mock-timeout')
        self.assertEqual(client.post('/upload',data=self.payload()).status_code,503)
        remote.finish.assert_not_called()

    def test_status_has_no_database_or_remote_calls(self):
        client, ns, remote = self.routes()
        response=client.get('/status')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['uploadsEnabled'])
        self.assertEqual(response.json['context'],'new-signed-context')
        ns['engine'].begin.assert_not_called()
        remote.send_to_drive.assert_not_called()

    def test_direct_upload_requires_session_and_context_but_not_ticket(self):
        client, ns, remote = self.routes()
        payload=self.payload();payload.pop('ticketId')
        response=client.post('/direct',data=payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['attachment']['url'],'https://drive.google.com/file/d/driveFile12345678/view')
        remote.reserve.assert_not_called();remote.finish.assert_not_called()
        ns['engine'].begin.assert_not_called()
        ns['_usuario_autenticado']=lambda:None
        remote.send_to_drive.reset_mock()
        payload=self.payload();payload.pop('ticketId')
        self.assertEqual(client.post('/direct',data=payload).status_code,401)
        remote.send_to_drive.assert_not_called()

    def test_direct_invalid_context_and_identity_override_rejected(self):
        client, ns, remote = self.routes()
        ns['forms_read_context'].side_effect=BadSignature('invalid')
        payload=self.payload();payload.pop('ticketId')
        self.assertEqual(client.post('/direct',data=payload).status_code,403)
        payload=self.payload();payload.pop('ticketId');payload['nome']='Pessoa falsa'
        self.assertEqual(client.post('/direct',data=payload).status_code,400)
        remote.send_to_drive.assert_not_called()
        ns['engine'].begin.assert_not_called()

    def test_direct_name_is_stable_and_bound_to_identity_contents_and_server_stamp(self):
        first=drive.direct_receipt(self.user,self.file,self.since,self.key)
        second=drive.direct_receipt(self.user,self.file,self.since,self.key)
        self.assertEqual(first,second)
        self.assertIn(self.since.astimezone(drive.CSV_TIMEZONE).strftime('%Y-%m-%d_%H-%M-%S'),first['stored_name'])
        other=drive.direct_receipt({**self.user,'usuario_id':42},self.file,self.since,self.key)
        self.assertNotEqual(first['upload_key'],other['upload_key'])
        other=drive.direct_receipt(self.user,{**self.file,'sha256':'0'*64},self.since,self.key)
        self.assertNotEqual(first['upload_key'],other['upload_key'])

    def test_config_status_exposes_only_reason_never_values(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(drive.upload_status(),'missing_url')
            os.environ['PORTAL_DRIVE_UPLOAD_URL']=self.config[0]
            self.assertEqual(drive.upload_status(),'missing_secret')
            os.environ['PORTAL_DRIVE_UPLOAD_SECRET']='short'
            self.assertEqual(drive.upload_status(),'secret_too_short')
            os.environ['PORTAL_DRIVE_UPLOAD_SECRET']=self.config[1]
            self.assertEqual(drive.upload_status(),'ready')
            os.environ['PORTAL_DRIVE_UPLOAD_URL']='https://wrong.invalid'
            self.assertEqual(drive.upload_status(),'invalid_url')

    def test_direct_supports_readonly_limit_in_flask_before_31(self):
        class OlderFlaskRequest(FlaskRequest):
            @property
            def max_content_length(self): return None
        client, ns, remote=self.routes(OlderFlaskRequest)
        payload=self.payload();payload.pop('ticketId')
        response=client.post('/direct',data=payload)
        self.assertEqual(response.status_code,200)
        remote.send_to_drive.assert_called_once()

    def test_known_google_errors_are_distinct_and_sanitized(self):
        cases=[(HTTPError('https://private.invalid/token',403,'private-secret',None,None),'google_access_denied'),
               (HTTPError('https://private.invalid/token',404,'private-secret',None,None),'google_deployment_invalid'),
               (HTTPError('https://private.invalid/token',429,'private-secret',None,None),'google_rate_limit'),
               (HTTPError('https://private.invalid/token',500,'private-secret',None,None),'google_http_error'),
               (TimeoutError('private-secret'),'google_timeout'),
               (URLError('private-secret'),'google_connection_failed')]
        receipt=drive.direct_receipt(self.user,self.file,self.since,self.key)
        for error,code in cases:
            with self.subTest(code=code),patch.object(drive,'urlopen',side_effect=error):
                with self.assertRaises(drive.DriveUploadError) as caught:
                    drive.send_to_drive(self.config,receipt,self.data)
                self.assertEqual(caught.exception.code,code)
                self.assertNotIn('private-secret',str(caught.exception))
                self.assertNotIn('private.invalid',str(caught.exception))

    def test_google_html_busy_and_rejection_have_actionable_errors(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        cases=[(b'<html>private-secret</html>','google_invalid_response'),
               (b'{"ok":false,"retry":true}','google_busy'),(b'{"ok":false}','google_upload_rejected')]
        receipt=drive.direct_receipt(self.user,self.file,self.since,self.key)
        for raw,code in cases:
            response.read.return_value=raw
            with self.subTest(code=code),patch.object(drive,'urlopen',return_value=response):
                with self.assertRaises(drive.DriveUploadError) as caught: drive.send_to_drive(self.config,receipt,self.data)
                self.assertEqual(caught.exception.code,code)
                self.assertNotIn('private-secret',str(caught.exception))

    def test_two_photos_three_csv_are_accepted_sequentially_without_database(self):
        client,ns,remote=self.routes()
        for i,name in enumerate(['foto.png','foto.jpg','um.csv','dois.csv','tres.csv']):
            response=client.post('/direct',data={'context':'signed-test','uploadId':f'{i:032x}',
                                'file':(io.BytesIO(b'local-fixture'),name)})
            self.assertEqual(response.status_code,200)
        self.assertEqual(remote.send_to_drive.call_count,5)
        ns['engine'].begin.assert_not_called()

    def test_direct_rejects_oversize_body_with_413(self):
        client,ns,remote=self.routes()
        payload=self.payload();payload.pop('ticketId')
        response=client.post('/direct',data=payload,environ_overrides={'CONTENT_LENGTH':str(drive.MAX_BYTES+256*1024+1)})
        self.assertEqual(response.status_code,413)
        remote.send_to_drive.assert_not_called()

    def test_direct_returns_safe_google_reason(self):
        client,ns,remote=self.routes()
        remote.send_to_drive.side_effect=drive.DriveUploadError('google_access_denied','O Google negou acesso ao serviço.')
        payload=self.payload();payload.pop('ticketId')
        response=client.post('/direct',data=payload)
        self.assertEqual((response.status_code,response.json['errorCode']),(503,'google_access_denied'))
        ns['engine'].begin.assert_not_called()

    def test_stream_limit_handles_upload_without_content_length(self):
        streams=[]
        class RecordingRequest(FlaskRequest):
            def _get_file_stream(self,*args,**kwargs):
                stream=super()._get_file_stream(*args,**kwargs)
                streams.append(stream)
                return stream
        client,ns,remote=self.routes(RecordingRequest)
        payload=self.payload();payload.pop('ticketId')
        response=client.post('/direct',data=payload,environ_overrides={'CONTENT_LENGTH':None,'wsgi.input_terminated':True})
        self.assertEqual(response.status_code,200)
        remote.send_to_drive.reset_mock()
        remote.MAX_BYTES=16
        response=client.post('/direct',data={'context':'signed-test','uploadId':self.key,
                            'file':(io.BytesIO(b'x'*(256*1024+1024)),'grande.csv')},
                            environ_overrides={'CONTENT_LENGTH':None,'wsgi.input_terminated':True})
        self.assertEqual(response.status_code,413)
        remote.send_to_drive.assert_not_called()
        self.assertTrue(streams and all(s.closed for s in streams))


if __name__ == '__main__': unittest.main()
