"""Somente mocks/AST: sem app, .env, Google, HTTP real ou PostgreSQL."""
import ast
import copy
import csv
import io
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
import forms_import as forms


class Result:
    def __init__(self, value=None): self.value = value
    def mappings(self): return self
    def first(self): return self.value
    def scalar(self): return self.value
    def scalar_one(self): return self.value


class Memory:
    def __init__(self, user):
        self.user = user
        self.receipts = set()
        self.tickets = []
        self.calls = []
        self.fail = False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if 'FROM public.usuarios' in sql: return Result(self.user)
        if 'INSERT INTO public.chamados_forms_importacoes' in sql:
            key = params['key']
            if key in self.receipts: return Result()
            self.receipts.add(key)
            return Result(key)
        if 'INSERT INTO public.chamados (' in sql:
            if self.fail: raise RuntimeError('Falha simulada')
            self.tickets.append(copy.deepcopy(params))
        return Result()

    def __enter__(self):
        self.before = copy.deepcopy((self.receipts, self.tickets))
        return self

    def __exit__(self, typ, value, tb):
        if typ: self.receipts, self.tickets = self.before
        return False


class Response(dict):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {}


class FormsTests(unittest.TestCase):
    def setUp(self):
        self.user = {'usuario_id': 41, 'email': 'autor@example.invalid', 'nome': 'Autor', 'ativo': True}
        self.now = datetime.now(timezone.utc)
        self.since = self.now - timedelta(minutes=2)
        self.serializer = URLSafeTimedSerializer('test-only-secret-not-a-real-key-0000', salt='portal-auth')
        self.token = self.serializer.dumps({'uid': 41})
        self.values = [(self.now - timedelta(seconds=10)).isoformat(), 'Nome informado',
                       self.user['email'], '1234', 'TI', 'Ajuste', 'BI — tela', 'Calculo',
                       'Descricao', '', '', '', 'Pessoa solicitada', 'destinatario@example.invalid', 'Relatorio X', '']
        self.source = {'ok': True, 'spreadsheetId': forms.SPREADSHEET_ID,
                       'headers': list(forms.HEADERS), 'rows': [{'sheetId': '0', 'values': self.values}]}
        self.conn = Memory(self.user)

    def rows(self): return forms.prepare_rows(self.source, self.user, self.since, self.now)

    def routes(self):
        ns = {'jsonify': Response, 'log': Mock(), 'forms_reader_config': lambda: forms.CSV_URL,
              '_usuario_autenticado': lambda: self.user, '_resposta_nao_autorizado': lambda: (Response({'ok': False}), 401),
              '_extrair_bearer_token': lambda: self.token, '_auth_serializer': lambda: self.serializer,
              'AUTH_TOKEN_MAX_AGE': 43200, 'BadSignature': BadSignature, 'SignatureExpired': SignatureExpired,
              'forms_new_context': forms.new_context, 'forms_read_context': forms.read_context,
              'forms_fetch_rows': Mock(return_value=self.source), 'forms_prepare_rows': forms.prepare_rows,
              'forms_persist_rows': forms.persist_rows, 'engine': Mock(),
              '_numero_para_novo_chamado': lambda *args, **kwargs: 1054}
        tree = ast.parse((ROOT / 'api/app.py').read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                    '_forms_import_response', 'api_forms_import_session', 'api_forms_import'}:
                node.decorator_list = []
                exec(compile(ast.Module(body=[node], type_ignores=[]), 'isolated-api', 'exec'), ns)
        context = forms.new_context(self.serializer, self.user, self.token, self.since)
        ns['request'] = Mock()
        ns['request'].get_json.return_value = {'context': context}
        ns['engine'].begin.return_value = self.conn
        return ns

    def test_context_cannot_be_used_as_portal_token(self):
        token = forms.new_context(self.serializer, self.user, self.token, self.since)
        self.assertEqual(forms.read_context(self.serializer, token, self.user, self.token), self.since)
        with self.assertRaises(BadSignature): self.serializer.loads(token)

    def test_context_bound_to_user_and_original_login(self):
        token = forms.new_context(self.serializer, self.user, self.token, self.since)
        for user, session in (({**self.user, 'usuario_id': 99}, self.token), (self.user, 'another-login')):
            with self.assertRaises(ValueError): forms.read_context(self.serializer, token, user, session)
        with patch.object(forms, 'CONTEXT_MAX_AGE', -1):
            with self.assertRaises(SignatureExpired): forms.read_context(self.serializer, token, self.user, self.token)

    def test_first_email_is_requester_second_is_only_description(self):
        row = self.rows()[0]
        self.assertIn('E-mail do usuário solicitado: destinatario@example.invalid', row['description'])
        self.values[2], self.values[13] = 'another@example.invalid', self.user['email']
        self.assertEqual(self.rows(), [])

    def test_old_and_future_responses_are_not_imported(self):
        for timestamp in (self.since - timedelta(seconds=1), self.now + timedelta(seconds=1)):
            self.values[0] = timestamp.isoformat()
            self.assertEqual(self.rows(), [])

    def test_source_headers_and_timestamp_are_strict(self):
        self.source['spreadsheetId'] = 'other'
        with self.assertRaises(ValueError): self.rows()
        self.source['spreadsheetId'] = forms.SPREADSHEET_ID
        self.source['headers'][2] = 'wrong'
        with self.assertRaises(ValueError): self.rows()
        self.source['headers'] = list(forms.HEADERS)
        self.values[0] = '2026-10-30T12:00:00'
        with self.assertRaises(ValueError): self.rows()

    def test_receipt_survives_edits_and_deleted_ticket(self):
        rows = self.rows()
        self.assertEqual(forms.persist_rows(self.conn, self.user, rows, lambda *a: 1054), 1)
        self.conn.tickets[0]['status'] = 'done'
        self.assertEqual(forms.persist_rows(self.conn, self.user, rows, lambda *a: 9999), 0)
        self.assertEqual(self.conn.tickets[0]['status'], 'done')
        self.conn.tickets.clear()  # Recibo nao e excluido junto ao chamado.
        self.assertEqual(forms.persist_rows(self.conn, self.user, rows, lambda *a: 9999), 0)
        self.assertEqual(self.conn.tickets, [])

    def test_creation_identity_status_and_lock_order(self):
        forms.persist_rows(self.conn, self.user, self.rows(), lambda *a: 1054)
        self.assertIn('pg_advisory_xact_lock', self.conn.calls[0][0])
        saved = self.conn.tickets[0]
        self.assertEqual((saved['uid'], saved['email'], saved['name']), (41, self.user['email'], 'Autor'))
        self.assertLess(saved['id'], 2**53)
        insert = next(sql for sql, p in self.conn.calls if 'INSERT INTO public.chamados (' in sql)
        self.assertIn("'awaiting_manager', 'Média'", insert)
        self.assertNotIn('UPDATE public.chamados SET', '\n'.join(sql for sql, p in self.conn.calls))

    def test_block_during_google_read_rejects_before_insert(self):
        self.conn.user = None
        with self.assertRaises(PermissionError): forms.persist_rows(self.conn, self.user, self.rows(), lambda *a: 1)
        self.assertEqual(self.conn.receipts, set())

    def test_transaction_rolls_back_receipt_and_ticket(self):
        self.conn.fail = True
        with self.assertRaises(RuntimeError):
            with self.conn: forms.persist_rows(self.conn, self.user, self.rows(), lambda *a: 1)
        self.assertEqual(self.conn.receipts, set())

    def csv_response(self):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(forms.HEADERS)
        values = list(self.values)
        values[0] = (self.now - timedelta(seconds=10)).astimezone(forms.CSV_TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')
        writer.writerow(values)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {'Content-Type': 'text/csv; charset=utf-8'}
        response.read.return_value = stream.getvalue().encode('utf-8-sig')
        return response

    def test_public_csv_uses_only_get_without_credentials(self):
        response = self.csv_response()
        with patch.object(forms, 'urlopen', return_value=response) as fetch:
            result = forms.fetch_rows(forms.reader_config(), self.user['email'], self.since)
        request = fetch.call_args.args[0]
        self.assertEqual(request.method, 'GET')
        self.assertIsNone(request.data)
        self.assertFalse(request.has_header('Authorization'))
        self.assertFalse(request.has_header('Cookie'))
        self.assertEqual(request.full_url, forms.CSV_URL)
        self.assertEqual(result['headers'].count('E-mail'), 2)
        self.assertEqual(result['rows'][0]['values'][13], 'destinatario@example.invalid')
        self.assertEqual(len(forms.prepare_rows(result, self.user, self.since)), 1)

    def test_csv_brasilia_timestamp_is_utc(self):
        self.assertEqual(forms.csv_timestamp('29/10/2026 17:46:39').isoformat(), '2026-10-29T20:46:39+00:00')

    def test_non_public_or_oversize_source_is_rejected(self):
        response = self.csv_response()
        response.headers = {'Content-Type': 'text/html'}
        with patch.object(forms, 'urlopen', return_value=response):
            with self.assertRaises(ValueError): forms.fetch_rows(forms.CSV_URL, self.user['email'], self.since)
        response.headers = {'Content-Type': 'text/csv'}
        response.read.return_value = b'a' * (1024 * 1024 + 1)
        with patch.object(forms, 'urlopen', return_value=response):
            with self.assertRaises(ValueError): forms.fetch_rows(forms.CSV_URL, self.user['email'], self.since)

    def test_source_address_cannot_be_selected_by_client(self):
        with patch.object(forms, 'urlopen') as fetch:
            with self.assertRaises(ValueError): forms.fetch_rows('https://other.invalid', self.user['email'], self.since)
        fetch.assert_not_called()

    def test_import_requires_auth_even_with_context(self):
        api = self.routes()
        api['_usuario_autenticado'] = lambda: None
        self.assertEqual(api['api_forms_import']()[1], 401)
        api['forms_fetch_rows'].assert_not_called()
        api['engine'].begin.assert_not_called()

    def test_client_cannot_choose_email_or_rows(self):
        api = self.routes()
        api['request'].get_json.return_value['email'] = 'another@example.invalid'
        self.assertEqual(api['api_forms_import']()[1], 400)
        api['forms_fetch_rows'].assert_not_called()

    def test_empty_matching_rows_never_opens_write_transaction(self):
        api = self.routes()
        self.values[2] = 'another@example.invalid'
        response, status = api['api_forms_import']()
        self.assertEqual((status, response['imported']), (200, 0))
        api['engine'].begin.assert_not_called()

    def test_no_key_needed_and_optional_pause_still_works(self):
        with patch.dict(os.environ, {}, clear=True): self.assertEqual(forms.reader_config(), forms.CSV_URL)
        with patch.dict(os.environ, {'PORTAL_FORMS_IMPORT_ENABLED': 'false'}, clear=True):
            self.assertIsNone(forms.reader_config())
        api = self.routes()
        api['forms_reader_config'] = lambda: None
        response, code = api['api_forms_import_session']()
        self.assertEqual((code, response['enabled']), (200, False))

    def test_endpoint_uses_authenticated_email_and_commits(self):
        api = self.routes()
        response, status = api['api_forms_import']()
        self.assertEqual((status, response['imported']), (200, 1))
        self.assertEqual(api['forms_fetch_rows'].call_args.args[1], self.user['email'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


if __name__ == '__main__': unittest.main()
