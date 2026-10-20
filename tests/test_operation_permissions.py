"""Testes curtos, somente AST e banco em memoria simulado; nao importa app/.env."""
import ast
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
PERMISSION = "comercial.frete.editar"


def functions(path, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return tree


class Result:
    def __init__(self, value=None):
        self.value = value

    def mappings(self): return self
    def scalars(self): return self
    def scalar(self): return self.value
    def scalar_one(self): return self.value
    def first(self): return self.value
    def all(self): return self.value or []
    def __iter__(self): return iter(self.value or [])


class FakeEngine:
    def __init__(self):
        self.users = {41: {"usuario_id": 41, "nome": "Antes", "email": "offline@example.invalid",
                           "role": "sector", "perfil": "setor", "ativo": True,
                           "commercial_access": {"mode": "seller", "code": "7"}}}
        self.permissions = {41: {PERMISSION}}
        self.calls = []
        self.fail_grant = False
        self.rollback = False

    def begin(self): return self
    def connect(self): return self
    def __enter__(self):
        self.before = copy.deepcopy((self.users, self.permissions))
        return self

    def __exit__(self, typ, value, tb):
        if typ:
            self.users, self.permissions = self.before
            self.rollback = True
        return False

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        p = params or {}
        self.calls.append((sql, p))
        if "FROM public.usuario_operacoes" in sql and sql.startswith("DELETE"):
            self.permissions[p["uid"]] = self.permissions.get(p["uid"], set()) & set(p["permissions"])
        elif sql.startswith("INSERT INTO public.usuario_operacoes"):
            if self.fail_grant:
                raise RuntimeError("Falha simulada")
            self.permissions.setdefault(p["uid"], set()).add(p["permission"])
        elif sql.startswith("SELECT") and "u.id AS usuario_id" in sql:
            user = self.users.get(p["usuario_id"])
            if not user or not user["ativo"]:
                return Result()
            return Result({**user, "operation_permissions": sorted(self.permissions.get(p["usuario_id"], set()))})
        elif sql.startswith("SELECT id, email FROM public.usuarios"):
            return Result(self.users.get(p["id"]))
        elif sql.startswith("SELECT id FROM public.usuarios WHERE id"):
            uid = p.get("id", p.get("uid"))
            return Result(uid if uid in self.users else None)
        elif sql.startswith("INSERT INTO public.usuarios"):
            self.users[82] = dict(p, usuario_id=82)
            return Result(82)
        elif sql.startswith("UPDATE public.usuarios"):
            updates = dict(p)
            if updates.get("commercial_access") is None:
                updates.pop("commercial_access", None)  # SQL COALESCE preserves the saved scope.
            self.users[p["id"]].update(updates)
        return Result()


class Response(dict):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {}


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.ns = {"text": lambda sql: sql, "OPERATION_PERMISSIONS": frozenset({PERMISSION})}
        functions(ROOT / "api/operation_permissions.py", self.ns)
        functions(ROOT / "api/commercial_access.py", self.ns)
        self.ns["effective_commercial_access"] = self.ns["effective_data_access"]
        self.ns["normalize_commercial_access"] = self.ns["normalize_data_access"]
        import re
        self.ns["re"] = re
        self.tree = functions(ROOT / "api/app.py", self.ns)
        self.engine = FakeEngine()
        self.actor = {"usuario_id": 1, "role": "admin", "ativo": True}
        self.body = {"name": "Depois", "email": "offline@example.invalid", "role": "sector",
                     "status": "active", "sectors": [], "reportIds": []}
        self.ns.update(engine=self.engine, json=json, jsonify=Response, log=Mock(),
                       request=SimpleNamespace(method="PUT", get_json=lambda **kw: self.body),
                       _usuario_autenticado=lambda: self.actor,
                       carregar_portal_data_neon=lambda: {"users": list(self.engine.users.values())})

    def test_missing_empty_and_invalid_are_different(self):
        parse = self.ns["operation_permissions_from_payload"]
        self.assertIsNone(parse({}))
        self.assertEqual(parse({"operationPermissions": []}), [])
        self.assertEqual(parse({"operationPermissions": [PERMISSION]}), [PERMISSION])
        for invalid in (None, "comercial.frete.editar", {}, True, ["unknown"], [PERMISSION, PERMISSION]):
            with self.assertRaises(ValueError):
                parse({"operationPermissions": invalid})

    def test_multiple_permissions_need_no_schema_change(self):
        self.ns["OPERATION_PERMISSIONS"] = {PERMISSION, "comercial.outra.editar"}
        self.assertEqual(len(self.ns["normalize_operation_permissions"](
            [PERMISSION, "comercial.outra.editar"])), 2)

    def test_no_implicit_admin_or_director_writes(self):
        check = self.ns["has_operation_permission"]
        for role in ("admin", "director", "sector"):
            user = {"ativo": True, "role": role, "commercial_access": {"mode": "general"}}
            self.assertFalse(check(user, PERMISSION))
            user["operation_permissions"] = [PERMISSION]
            self.assertTrue(check(user, PERMISSION))
            user["ativo"] = False
            self.assertFalse(check(user, PERMISSION))

    def test_omission_never_touches_grants(self):
        self.ns["replace_operation_permissions"](self.engine, 41, None)
        self.assertEqual(self.engine.calls, [])

    def test_patch_preserves_then_revokes(self):
        self.assertEqual(self.ns["api_admin_usuario_patch"](41)["ok"], True)
        self.assertEqual(self.engine.permissions[41], {PERMISSION})
        self.body["operationPermissions"] = []
        self.assertTrue(self.ns["api_admin_usuario_patch"](41)["ok"])
        self.assertEqual(self.engine.permissions[41], set())

    def test_patch_grant_uses_permanent_id(self):
        self.engine.permissions[41] = set()
        self.body["operationPermissions"] = [PERMISSION]
        self.assertTrue(self.ns["api_admin_usuario_patch"](41)["ok"])
        self.assertEqual(self.engine.permissions[41], {PERMISSION})
        grants = [p for sql, p in self.engine.calls if sql.startswith("INSERT INTO public.usuario_operacoes")]
        self.assertEqual(grants, [{"uid": 41, "permission": PERMISSION}])

    def test_patch_rollback_keeps_user_and_permissions(self):
        self.engine.fail_grant = True
        self.body["operationPermissions"] = [PERMISSION]
        self.assertEqual(self.ns["api_admin_usuario_patch"](41)[1], 500)
        self.assertTrue(self.engine.rollback)
        self.assertEqual(self.engine.users[41]["nome"], "Antes")
        self.assertEqual(self.engine.permissions[41], {PERMISSION})

    def test_manual_requests_from_non_admin_denied(self):
        self.body["operationPermissions"] = [PERMISSION]
        for actor, expected in ((None, 401), ({"role": "sector"}, 403), ({"role": "director"}, 403)):
            self.actor = actor
            for route, args in (("api_admin_usuario_patch", (41,)),
                                ("api_admin_usuario_create", ()), ("api_portal_data", ())):
                self.assertEqual(self.ns[route](*args)[1], expected)
        self.assertEqual(self.engine.calls, [])

    def test_create_defaults_to_no_grants_even_for_admin(self):
        for role in ("admin", "director"):
            self.body.update(role=role, password="offline-only")
            self.assertEqual(self.ns["api_admin_usuario_create"]()[1], 201)
            self.assertEqual(self.engine.permissions.get(82, set()), set())

    def test_create_with_explicit_permission(self):
        self.body.update(password="offline-only", operationPermissions=[PERMISSION])
        self.assertEqual(self.ns["api_admin_usuario_create"]()[1], 201)
        self.assertEqual(self.engine.permissions[82], {PERMISSION})

    def snapshot(self, **overrides):
        return {"users": [{**self.body, "dbId": 41, "id": 900, **overrides}], "reports": [], "sectors": []}

    def test_bulk_old_payload_preserves_permission_and_data_access(self):
        self.ns["salvar_portal_data_neon"](self.snapshot())
        self.assertEqual(self.engine.permissions[41], {PERMISSION})
        update = next(p for sql, p in self.engine.calls if sql.startswith("UPDATE public.usuarios"))
        self.assertIsNone(update["commercial_access"])
        self.assertEqual(self.engine.users[41]["commercial_access"], {"mode": "seller", "code": "7"})
        sql = next(sql for sql, p in self.engine.calls if sql.startswith("UPDATE public.usuarios"))
        self.assertIn("commercial_access = COALESCE", sql)

    def test_bulk_explicit_empty_revokes(self):
        self.ns["salvar_portal_data_neon"](self.snapshot(operationPermissions=[]))
        self.assertEqual(self.engine.permissions[41], set())

    def test_bulk_failure_rolls_back_user_and_permission(self):
        self.engine.fail_grant = True
        with self.assertRaises(RuntimeError):
            self.ns["salvar_portal_data_neon"](self.snapshot(operationPermissions=[PERMISSION]))
        self.assertTrue(self.engine.rollback)
        self.assertEqual(self.engine.users[41]["nome"], "Antes")
        self.assertEqual(self.engine.permissions[41], {PERMISSION})

    def test_forged_token_claim_cannot_grant_and_revocation_is_fresh(self):
        self.ns.update(_auth_serializer=lambda: SimpleNamespace(loads=lambda *a, **kw: {
            "uid": 41, "operationPermissions": [PERMISSION]}), AUTH_TOKEN_MAX_AGE=100,
                       SignatureExpired=ValueError, BadSignature=TypeError)
        self.assertTrue(self.ns["has_operation_permission"](self.ns["_usuario_por_token"]("fake"), PERMISSION))
        self.engine.permissions[41] = set()
        self.assertFalse(self.ns["has_operation_permission"](self.ns["_usuario_por_token"]("fake"), PERMISSION))
        self.engine.users[41]["ativo"] = False
        self.assertIsNone(self.ns["_usuario_por_token"]("fake"))
        self.assertIn("u.ativo = TRUE", self.engine.calls[-1][0])
        self.assertEqual(self.engine.calls[-1][1], {"usuario_id": 41})

    def test_me_adds_permissions_preserves_contract_and_disables_cache(self):
        self.actor = {**self.engine.users[41], "operation_permissions": [PERMISSION]}
        response = self.ns["api_auth_me"]()
        self.assertEqual(response["user"]["operationPermissions"], [PERMISSION])
        self.assertEqual(response["user"]["id"], 41)
        self.assertEqual(response["user"]["dataAccess"], {"mode": "seller", "code": "7"})
        self.assertEqual(response["user"]["commercialAccess"], response["user"]["dataAccess"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
