"""Permissões da Integração, separadas do Comercial e da abertura do relatório.

Não importa app, não abre conexões ao importar e não mantém cache de permissões.
"""
import re
from flask import jsonify, request
from sqlalchemy import text

RESOURCE = "zootecnico"
REPORT_ID = 13
SOURCES = (
    "vw_desempenho_acerto_portal", "acerto_lote_resultado_geral",
    "base_dinamica", "mortalidade_peso_abertos", "mortalidade_peso_fechados",
    "vw_historico_lotes_criacao_portal",
)


def general_role(user):
    # Política explicitamente autorizada: mesmos perfis gerais atuais do portal.
    return (str(user.get("role") or "").lower() in {"admin", "director"}
            or str(user.get("perfil") or "").lower() in {"admin", "diretor", "director"})


def normalize_access(value):
    if (not isinstance(value, dict) or not isinstance(value.get("mode"), str)
            or value["mode"] not in {"none", "proprio", "equipe", "todos"}):
        raise ValueError("Informe um acesso válido à Integração.")
    mode, ids = value["mode"], value.get("technicianIds", [])
    if (not isinstance(ids, list) or len(ids) > 100
            or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", x) for x in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Lista de técnicos inválida.")
    if mode == "proprio" and len(ids) != 1:
        raise ValueError("Selecione exatamente um técnico para acesso próprio.")
    if mode == "equipe" and not ids:
        raise ValueError("Selecione os técnicos da equipe.")
    if mode in {"none", "todos"} and ids:
        raise ValueError("Este alcance não deve conter vínculos de técnicos.")
    return {"mode": mode, "technicianIds": sorted(ids)}


def schema_ready(conn):
    return bool(conn.execute(text("""
        SELECT to_regclass('public.usuario_escopos_acesso') IS NOT NULL
           AND to_regclass('public.usuario_vinculos_dados') IS NOT NULL
           AND to_regclass('public.entidades_acesso_dados') IS NOT NULL
           AND to_regclass('public.entidade_aliases_dados') IS NOT NULL
    """)).scalar())


def read_access(conn, uid):
    row = conn.execute(text("""
        SELECT escopo, ativo FROM public.usuario_escopos_acesso
        WHERE usuario_id=:uid AND recurso=:resource
    """), {"uid": uid, "resource": RESOURCE}).mappings().first()
    if not row or not row["ativo"]:
        return {"mode": "none", "technicianIds": []}
    ids = list(conn.execute(text("""
        SELECT v.entidade_id FROM public.usuario_vinculos_dados v
        JOIN public.entidades_acesso_dados e
          ON e.tipo=v.tipo_entidade AND e.identificador=v.entidade_id AND e.ativo
        WHERE v.usuario_id=:uid AND v.recurso=:resource AND v.ativo
          AND v.tipo_entidade='tecnico' ORDER BY v.entidade_id
    """), {"uid": uid, "resource": RESOURCE}).scalars())
    try:
        return normalize_access({"mode": row["escopo"], "technicianIds": ids})
    except ValueError:
        return {"mode": "none", "technicianIds": []}


def replace_access(conn, uid, value, actor):
    """Somente depois da autorização administrativa, na transação do usuário."""
    access = normalize_access(value)
    if not schema_ready(conn):
        raise ValueError("A migração de permissões da Integração ainda não foi aplicada.")
    conn.execute(text("SELECT id FROM public.usuarios WHERE id=:uid FOR UPDATE"), {"uid": uid})
    for identifier in access["technicianIds"]:
        if not conn.execute(text("""
            SELECT EXISTS(SELECT 1 FROM public.entidades_acesso_dados
              WHERE tipo='tecnico' AND identificador=:id AND ativo)
        """), {"id": identifier}).scalar():
            raise ValueError("Técnico inexistente ou inativo.")
    params = {"uid": uid, "resource": RESOURCE, "mode": access["mode"], "actor": actor}
    conn.execute(text("""
        INSERT INTO public.usuario_escopos_acesso
          (usuario_id,recurso,escopo,ativo,criado_por,atualizado_por)
        VALUES (:uid,:resource,:mode,TRUE,:actor,:actor)
        ON CONFLICT (usuario_id,recurso) DO UPDATE
        SET escopo=EXCLUDED.escopo, ativo=TRUE, atualizado_em=NOW(), atualizado_por=:actor
    """), params)
    conn.execute(text("""
        UPDATE public.usuario_vinculos_dados SET ativo=FALSE, atualizado_em=NOW(), atualizado_por=:actor
        WHERE usuario_id=:uid AND recurso=:resource
    """), params)
    for identifier in access["technicianIds"]:
        conn.execute(text("""
            INSERT INTO public.usuario_vinculos_dados
              (usuario_id,recurso,tipo_entidade,entidade_id,ativo,criado_por,atualizado_por)
            VALUES (:uid,:resource,'tecnico',:id,TRUE,:actor,:actor)
            ON CONFLICT (usuario_id,recurso,tipo_entidade,entidade_id) DO UPDATE
            SET ativo=TRUE, atualizado_em=NOW(), atualizado_por=:actor
        """), {**params, "id": identifier})


def report_allowed(conn, user):
    if general_role(user):
        return True
    return bool(conn.execute(text("""
        SELECT EXISTS (
          SELECT 1 FROM public.usuarios u
          JOIN public.relatorios r ON r.id=:report
          JOIN public.setores s ON s.id=r.setor_id AND s.ativo
          WHERE u.id=:uid AND u.ativo AND (
            (u.report_access_mode='specific' AND EXISTS (
              SELECT 1 FROM public.usuario_relatorios x WHERE x.usuario_id=u.id AND x.relatorio_id=r.id))
            OR (COALESCE(u.report_access_mode,'sector')<>'specific' AND EXISTS (
              SELECT 1 FROM public.usuario_setores x WHERE x.usuario_id=u.id AND x.setor_id=r.setor_id))))
    """), {"uid": user["usuario_id"], "report": REPORT_ID}).scalar())


def response(body, status=200):
    result = jsonify(body)
    result.status_code = status
    result.headers["Cache-Control"] = "no-store, private"
    result.headers["Vary"] = "Authorization"
    return result


def register_routes(app, engine, authenticate, is_admin):
    @app.get("/api/auth/zootecnico-access")
    def zootecnico_authorization():
        user = authenticate()
        if not user:
            return response({"ok": False, "erro": "Sessão inválida ou expirada."}, 401)
        try:
            with engine.connect() as conn:
                if not report_allowed(conn, user):
                    return response({"ok": False, "erro": "Relatório não autorizado."}, 403)
                if not schema_ready(conn):
                    return response({"ok": False, "erro": "Permissões da Integração indisponíveis."}, 503)
                access = ({"mode": "todos", "technicianIds": []} if general_role(user)
                          else read_access(conn, user["usuario_id"]))
                aliases = []
                if access["technicianIds"]:
                    aliases = [dict(row) for row in conn.execute(text("""
                        SELECT a.fonte, a.valor, a.entidade_id
                        FROM public.entidade_aliases_dados a
                        JOIN public.entidades_acesso_dados e
                          ON e.tipo=a.tipo_entidade AND e.identificador=a.entidade_id AND e.ativo
                        WHERE a.recurso=:resource AND a.ativo AND a.tipo_entidade='tecnico'
                          AND a.entidade_id=ANY(CAST(:ids AS text[]))
                        ORDER BY a.fonte,a.valor
                    """), {"resource": RESOURCE, "ids": access["technicianIds"]}).mappings()]
            return response({"ok": True, "allowed": True, "resource": RESOURCE,
                             "reportId": REPORT_ID, "userId": user["usuario_id"],
                             **access, "aliases": aliases})
        except Exception:
            # Sem exceções SQL, URLs ou credenciais no corpo da resposta.
            return response({"ok": False, "erro": "Não foi possível validar as permissões da Integração."}, 503)

    @app.get("/api/admin/usuarios/<int:uid>/zootecnico-access")
    def zootecnico_user_access(uid):
        user = authenticate()
        if not user:
            return response({"ok": False}, 401)
        if not is_admin(user):
            return response({"ok": False}, 403)
        try:
            with engine.connect() as conn:
                if not schema_ready(conn):
                    return response({"ok": False, "erro": "Aplique a migração da Integração antes de configurar os técnicos."}, 503)
                target = conn.execute(text("SELECT role,perfil FROM public.usuarios WHERE id=:uid"), {"uid": uid}).mappings().first() if uid else {}
                if uid and not target:
                    return response({"ok": False}, 404)
                catalog = [dict(row) for row in conn.execute(text("""
                    SELECT identificador AS id,nome,ativo FROM public.entidades_acesso_dados
                    WHERE tipo='tecnico' ORDER BY nome,identificador
                """)).mappings()]
                access = read_access(conn, uid) if uid else {"mode": "none", "technicianIds": []}
                if general_role(target):
                    access = {"mode": "todos", "technicianIds": []}
            return response({"ok": True, "access": access, "technicians": catalog})
        except Exception:
            return response({"ok": False, "erro": "Não foi possível carregar o acesso da Integração."}, 503)
