"""Gestão delegada, sem acesso aos BIs. Auditoria transacional no PostgreSQL."""
import json
import re
from sqlalchemy import text

PERMISSION = 'usuarios.gerenciar'


def is_admin(user):
    return bool(user and (str(user.get('role') or '').strip().lower() == 'admin'
                         or str(user.get('perfil') or '').strip().lower() == 'admin'))


def can_manage(user):
    return bool(user and user.get('ativo') is True and
                (is_admin(user) or PERMISSION in (user.get('operation_permissions') or [])))


def management_only(user):
    return can_manage(user) and not is_admin(user)


def allowed_request(user, path, method):
    if not management_only(user):
        return True
    if path in {'/api/auth/me', '/api/auth/bootstrap', '/api/auth/change-password',
                '/api/auth/logout'}:
        return True
    if path == '/api/portal-data':
        return method == 'GET'
    if path == '/api/admin/usuarios':
        return method == 'POST'
    if re.fullmatch(r'/api/admin/usuarios/[0-9]+/status', path):
        return method == 'POST'
    if re.fullmatch(r'/api/admin/usuarios/[0-9]+', path):
        return method == 'DELETE'
    return False


def portal_data(data, user):
    if not management_only(user):
        return data
    # Apenas metadados necessários para cadastrar usuários, sem URLs dos BIs.
    return {**data, 'reports': [{**r, 'url': ''} for r in data.get('reports', [])]}


def actor_context(conn, actor):
    if actor:
        safe = {k: actor.get(v) for k, v in
                [('id', 'usuario_id'), ('nome', 'nome'), ('email', 'email')]}
        conn.execute(text("SELECT set_config('portal.audit_actor', :actor, true)"),
                     {'actor': json.dumps(safe)})


def require_ready(conn):
    ready = conn.execute(text("""SELECT
        to_regclass('public.auditoria_usuarios') IS NOT NULL
        AND EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='public.usuarios'::regclass
                    AND attname='excluido_em' AND NOT attisdropped)
        AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='public.usuarios'::regclass
                    AND tgname='usuarios_auditoria_trg' AND tgenabled IN ('O','A'))""")).scalar()
    if not ready:
        raise ValueError('Aplique a migração 20261104_gestao_usuarios.sql antes de usar a gestão delegada/exclusão.')


def validate_delegated_create(body):
    allowed = {'name','email','password','role','status','sectors','reportAccessMode',
               'reportIds','ticketPanelAccess','commercialAccess','dataAccess','operationPermissions'}
    if (set(body) - allowed or body.get('role', 'sector') != 'sector'
        or body.get('status', 'active') != 'active'
        or body.get('ticketPanelAccess', False) is not False
        or body.get('operationPermissions', []) != []
        or body.get('commercialAccess', {'mode':'none'}) != {'mode':'none'}
        or body.get('dataAccess', {'mode':'none'}) != {'mode':'none'}
        or body.get('reportAccessMode', 'sector') not in {'sector','specific'}):
        raise ValueError('Gestor pode criar somente contas Setor, sem privilégios administrativos, comerciais ou delegação de gestão.')


def confirm_admin_block(target, active, body):
    if is_admin(target) and target.get('ativo') and not active and body.get('confirmAdminBlock') is not True:
        raise ValueError('Confirme o bloqueio de Admin. Sem outra conta ativa autorizada a desbloquear, a recuperação precisará ser feita no Neon.')


def register_routes(app, engine, authenticate, load_data):
    from flask import jsonify, request

    def authorize():
        actor = authenticate()
        if not actor:
            return None, (jsonify(ok=False, erro='Sessão inválida ou acesso não permitido.'), 401)
        if not can_manage(actor):
            return None, (jsonify(ok=False, erro='Sem permissão para gerenciar usuários.'), 403)
        return actor, None

    def response_data(actor):
        return portal_data(load_data(), actor)

    @app.post('/api/admin/usuarios/<int:uid>/status')
    def manage_user_status(uid):
        actor, error = authorize()
        if error: return error
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {'status','confirmAdminBlock'} or body.get('status') not in {'active','blocked'}:
            return jsonify(ok=False, erro='Informe somente active ou blocked.'), 400
        try:
            with engine.begin() as conn:
                require_ready(conn)
                actor_context(conn, actor)
                target = conn.execute(text('SELECT id,role,perfil,ativo,excluido_em FROM public.usuarios WHERE id=:uid FOR UPDATE'), {'uid':uid}).mappings().first()
                if not target or target['excluido_em']:
                    return jsonify(ok=False, erro='Usuário não encontrado ou excluído.'), 404
                confirm_admin_block(target, body['status']=='active', body)
                # Intencionalmente permite bloquear QUALQUER Admin, inclusive o último.
                conn.execute(text('UPDATE public.usuarios SET ativo=:active,atualizado_em=NOW() WHERE id=:uid'),
                             {'active':body['status']=='active','uid':uid})
            return jsonify(ok=True, data=response_data(actor))
        except ValueError as exc:
            return jsonify(ok=False, erro=str(exc)), 400
        except Exception:
            return jsonify(ok=False, erro='Não foi possível alterar o status. Nenhuma alteração foi confirmada sem auditoria.'), 503

    @app.delete('/api/admin/usuarios/<int:uid>')
    def manage_user_delete(uid):
        actor, error = authorize()
        if error: return error
        if uid == int(actor['usuario_id']):
            return jsonify(ok=False, erro='Você não pode excluir a própria conta.'), 403
        try:
            with engine.begin() as conn:
                require_ready(conn)
                actor_context(conn, actor)
                target = conn.execute(text('SELECT id,role,perfil,ativo,excluido_em FROM public.usuarios WHERE id=:uid FOR UPDATE'), {'uid':uid}).mappings().first()
                if not target: return jsonify(ok=False, erro='Usuário não encontrado.'), 404
                if is_admin(target):
                    return jsonify(ok=False, erro='A exclusão de Admin está desabilitada por enquanto. Você pode bloqueá-lo, mediante confirmação.'), 403
                if not target['excluido_em']:
                    # Exclusão lógica: preserva chamados, anexos, IDs e rastreabilidade.
                    conn.execute(text('UPDATE public.usuarios SET ativo=FALSE,excluido_em=NOW(),atualizado_em=NOW() WHERE id=:uid'), {'uid':uid})
            return jsonify(ok=True, data=response_data(actor), archived=True)
        except ValueError as exc:
            return jsonify(ok=False, erro=str(exc)), 400
        except Exception:
            return jsonify(ok=False, erro='Não foi possível excluir. A operação exige auditoria e foi cancelada.'), 503

    @app.post('/api/admin/usuarios/<int:uid>/restaurar')
    def manage_user_restore(uid):
        actor, error = authorize()
        if error: return error
        if not is_admin(actor): return jsonify(ok=False, erro='Somente Admin pode restaurar contas excluídas.'), 403
        try:
            with engine.begin() as conn:
                require_ready(conn)
                actor_context(conn, actor)
                conn.execute(text('UPDATE public.usuarios SET excluido_em=NULL,ativo=FALSE,atualizado_em=NOW() WHERE id=:uid AND excluido_em IS NOT NULL'), {'uid':uid})
            return jsonify(ok=True, data=response_data(actor))
        except ValueError as exc:
            return jsonify(ok=False, erro=str(exc)), 400
        except Exception:
            return jsonify(ok=False, erro='Não foi possível restaurar a conta.'), 503

    @app.get('/api/admin/usuarios/auditoria')
    def manage_user_audit():
        actor, error = authorize()
        if error: return error
        if not is_admin(actor): return jsonify(ok=False, erro='Somente Admin pode consultar a auditoria.'), 403
        try:
            with engine.connect() as conn:
                require_ready(conn)
                rows = conn.execute(text('''SELECT id,ocorrido_em,acao,autor_id,autor_nome,autor_email,
                    usuario_id,usuario_nome,usuario_email,origem FROM public.auditoria_usuarios
                    ORDER BY id DESC LIMIT 200''')).mappings().all()
            return jsonify(ok=True, entries=[{**dict(r), 'ocorrido_em':r['ocorrido_em'].isoformat()} for r in rows])
        except ValueError as exc:
            return jsonify(ok=False, erro=str(exc)), 400
        except Exception:
            return jsonify(ok=False, erro='Não foi possível carregar a auditoria.'), 503
