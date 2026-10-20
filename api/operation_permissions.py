"""Permissoes de escrita da CENTRAL, independentes de perfil e alcance de dados."""
from sqlalchemy import text


OPERATION_PERMISSIONS = frozenset({"comercial.frete.editar"})


def normalize_operation_permissions(value):
    """Ausencia deve ser tratada pelo chamador; null nao significa revogacao."""
    if not isinstance(value, list) or len(value) > len(OPERATION_PERMISSIONS):
        raise ValueError("operationPermissions deve ser uma lista de permissoes conhecidas.")
    if any(not isinstance(code, str) or code not in OPERATION_PERMISSIONS for code in value):
        raise ValueError("Permissao de operacao desconhecida.")
    if len(set(value)) != len(value):
        raise ValueError("Permissoes de operacoes duplicadas.")
    return sorted(value)


def operation_permissions_from_payload(payload):
    """None preserva o cadastro; [] revoga explicitamente todas as operacoes."""
    if "operationPermissions" not in payload:
        return None
    return normalize_operation_permissions(payload["operationPermissions"])


def replace_operation_permissions(conn, usuario_id, permissions):
    """Usar na MESMA transacao do cadastro, somente apos autorizacao de admin."""
    if permissions is None:
        return
    permissions = normalize_operation_permissions(permissions)
    # Serializa substituicoes simultaneas para o mesmo ID permanente.
    conn.execute(text("SELECT id FROM public.usuarios WHERE id = :uid FOR UPDATE"), {"uid": usuario_id})
    conn.execute(text("""
        DELETE FROM public.usuario_operacoes
        WHERE usuario_id = :uid
          AND NOT (permissao = ANY(CAST(:permissions AS text[])))
    """), {"uid": usuario_id, "permissions": permissions})
    for code in permissions:
        conn.execute(text("""
            INSERT INTO public.usuario_operacoes (usuario_id, permissao)
            VALUES (:uid, :permission)
            ON CONFLICT (usuario_id, permissao) DO NOTHING
        """), {"uid": usuario_id, "permission": code})


def effective_operation_permissions(usuario):
    """Nunca inferir escrita por role/perfil, setor ou acesso geral aos dados."""
    if not usuario or usuario.get("ativo") is not True:
        return []
    return sorted(set(code for code in (usuario.get("operation_permissions") or [])
                      if isinstance(code, str) and code in OPERATION_PERMISSIONS))


def has_operation_permission(usuario, permission):
    """Receber apenas usuario carregado pela autenticacao CENTRAL, nunca JSON do cliente."""
    return permission in effective_operation_permissions(usuario)
