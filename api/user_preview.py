"""Sessão temporária de visualização, emitida exclusivamente por Admin."""
from datetime import datetime,timezone,timedelta
from itsdangerous import BadSignature,SignatureExpired
from sqlalchemy import text

MAX_AGE=20*60

def is_admin(user):
    return bool(user and (str(user.get('role')or'').strip().lower()=='admin' or str(user.get('perfil')or'').strip().lower()=='admin'))

def validate_payload(serializer,token,payload,conn):
    if 'preview' not in payload:return None
    if payload.get('preview') is not True:return False
    try:
        serializer.loads(token,max_age=MAX_AGE)
        actor_id=int(payload['actor']);target_id=int(payload['uid'])
        if actor_id<1 or target_id<1:return False
    except (BadSignature,SignatureExpired,ValueError,TypeError,KeyError):return False
    actor=conn.execute(text("SELECT id,nome,role,perfil FROM public.usuarios WHERE id=:id AND ativo=TRUE AND (to_jsonb(usuarios)->>'excluido_em') IS NULL"),{'id':actor_id}).mappings().first()
    if not is_admin(actor):return False
    return {'actorId':actor_id,'actorName':actor['nome'],'readOnly':True}

def register_routes(app,engine,authenticate,serializer,log):
    from flask import jsonify,request
    @app.post('/api/admin/usuarios/<int:uid>/preview')
    def create_user_preview(uid):
        actor=authenticate()
        if not actor:return jsonify(ok=False,erro='Sessão inválida.'),401
        if not is_admin(actor) or actor.get('session_preview'):return jsonify(ok=False,erro='Somente Admin pode visualizar o portal de outro usuário.'),403
        with engine.connect()as conn:
            target=conn.execute(text("SELECT id,nome,ativo,(to_jsonb(usuarios)->>'excluido_em') AS excluido_em FROM public.usuarios WHERE id=:id"),{'id':uid}).mappings().first()
        if not target or target['excluido_em']:return jsonify(ok=False,erro='Usuário não encontrado ou excluído.'),404
        if target['ativo'] is not True:return jsonify(ok=False,erro='Este usuário está bloqueado e não pode acessar o portal.'),409
        token=serializer().dumps({'uid':uid,'actor':int(actor['usuario_id']),'preview':True})
        log(f"Visualização do portal iniciada: Admin {actor['usuario_id']} / usuário {uid}","INFO")
        response=jsonify(ok=True,token=token,user={'id':uid,'name':target['nome']},expiresAt=(datetime.now(timezone.utc)+timedelta(seconds=MAX_AGE)).isoformat())
        response.headers['Cache-Control']='no-store'
        return response
