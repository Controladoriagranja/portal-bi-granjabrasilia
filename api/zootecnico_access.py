"""Permissões da Integração, separadas do Comercial e da abertura do relatório.

Não importa app, não abre conexões ao importar e não mantém cache de permissões.
"""
import json
import re
import unicodedata
from flask import jsonify, request
from sqlalchemy import text
from zootecnico_catalog import peek as catalog_peek, get_or_start as catalog_get_or_start

RESOURCE = "zootecnico"
REPORT_ID = 13
SOURCES = (
    "vw_desempenho_acerto_portal", "acerto_lote_resultado_geral",
    "base_dinamica", "mortalidade_peso_abertos", "mortalidade_peso_fechados",
    "vw_historico_lotes_criacao_portal",
)
PRIMARY_SOURCES = SOURCES[0], SOURCES[2], SOURCES[3], SOURCES[5]


def name_key(value):
    return ' '.join(unicodedata.normalize('NFC',str(value or '')).split()).casefold()


def normalize_form_access(value):
    if not isinstance(value,dict) or value.get('mode') not in ('none','proprio','equipe','todos'):
        raise ValueError('Informe o acesso à Integração.')
    if value.get('technicianIds'):
        raise ValueError('Atualize o portal: o vínculo agora é pelo usuário, sem catálogo separado.')
    version=value.get('formVersion',2)
    if type(version) is not int or version not in (2,3):raise ValueError('Versão do formulário inválida.')
    identity=value.get('identityId') or None
    if identity is not None and (not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identity)):
        raise ValueError('Selecione uma identidade técnica válida.')
    if identity and (version!=3 or value['mode']!='proprio'):raise ValueError('A identidade individual só é usada no acesso próprio.')
    mode=value['mode'];ids=value.get('userIds',[]);resolutions=value.get('resolutions',{})
    if not isinstance(ids,list) or len(ids)>100 or any(type(uid) is not int or uid<1 for uid in ids) or len(set(ids))!=len(ids):
        raise ValueError('Selecione usuários válidos da equipe.')
    if mode=='equipe' and not ids:raise ValueError('Selecione os usuários da equipe.')
    if mode!='equipe' and ids:raise ValueError('Usuários da equipe só são usados no acesso Equipe.')
    if not isinstance(resolutions,dict) or len(resolutions)>100:raise ValueError('Correspondências inválidas.')
    if version==3 and resolutions:raise ValueError('Selecione a identidade consolidada, sem enviar aliases por fonte.')
    allowed={'self'} if mode=='proprio' else {str(uid) for uid in ids}
    for key,choice in resolutions.items():
        if key not in allowed or not isinstance(choice,dict):raise ValueError('Correspondência fora dos usuários selecionados.')
        selected=choice.get('selections',{});without=choice.get('withoutData',[])
        if not isinstance(selected,dict) or set(selected)-set(SOURCES):raise ValueError('Fonte de correspondência inválida.')
        if not isinstance(without,list) or any(source not in SOURCES for source in without):raise ValueError('Fonte sem dados inválida.')
        for values in selected.values():
            if not isinstance(values,list) or len(values)>50 or any(not isinstance(v,str) or not v or v!=v.strip() or len(v)>500 for v in values):
                raise ValueError('Selecione somente valores técnicos exatos.')
        if type(choice.get('confirmed',False)) is not bool:raise ValueError('Confirmação inválida.')
    if type(value.get('allowPending',False)) is not bool:raise ValueError('Opção de vínculo pendente inválida.')
    return {'formVersion':version,'mode':mode,'identityId':identity,'userIds':sorted(ids),'resolutions':resolutions,'allowPending':value.get('allowPending',False)}


def lock_form_access(conn):
    # Antes de alterar o usuário: ordem única inclusive nos cadastros concorrentes.
    conn.execute(text('SELECT pg_advisory_xact_lock(71811203)'))


def portal_users(conn):
    return [dict(row) for row in conn.execute(text('SELECT id,nome,email,ativo,role,perfil FROM public.usuarios ORDER BY nome,id')).mappings()]


def personal_entity(conn,uid):
    rows=list(conn.execute(text("""
        SELECT DISTINCT e.identificador,e.nome FROM public.usuario_vinculos_dados v
        JOIN public.entidades_acesso_dados e ON e.tipo=v.tipo_entidade AND e.identificador=v.entidade_id AND e.ativo
        JOIN public.usuario_escopos_acesso s ON s.usuario_id=v.usuario_id AND s.recurso=v.recurso AND s.ativo
        WHERE v.usuario_id=:uid AND v.ativo AND v.tipo_entidade='tecnico'
          AND (v.recurso='zootecnico_identidade' OR (v.recurso='zootecnico' AND s.escopo='proprio'))
    """),{'uid':uid}).mappings())
    if len(rows)>1:raise ValueError('O usuário possui identidades técnicas conflitantes. Confira a correspondência no formulário.')
    return rows[0] if rows else None


def stored_aliases(conn,entity):
    result={source:[] for source in SOURCES}
    if entity:
        for row in conn.execute(text("""SELECT fonte,valor FROM public.entidade_aliases_dados
            WHERE recurso='zootecnico' AND tipo_entidade='tecnico' AND entidade_id=:id AND ativo ORDER BY fonte,valor"""),{'id':entity['identificador']}).mappings():
            if row['fonte'] in result:result[row['fonte']].append(row['valor'])
    return result


def catalog_from_neon(conn):
    """Somente identidades já confirmadas; nunca infere alias da lista de usuários."""
    rows=conn.execute(text("""SELECT e.identificador,e.nome,a.fonte,a.valor
        FROM public.entidades_acesso_dados e JOIN public.entidade_aliases_dados a
          ON a.tipo_entidade=e.tipo AND a.entidade_id=e.identificador
        WHERE e.tipo='tecnico' AND e.ativo AND a.ativo AND a.recurso='zootecnico'
        ORDER BY e.identificador,a.fonte,a.valor""")).mappings()
    sources={s:[] for s in SOURCES};groups={}
    for row in rows:
        if row['fonte'] not in sources:continue
        group=groups.setdefault(row['identificador'],{'identifier':row['identificador'],'name':row['nome'],'nameKey':name_key(row['nome']),'labels':{}})
        group['labels'].setdefault(row['fonte'],[]).append(row['valor']);sources[row['fonte']].append(row['valor'])
    if not groups:return None
    return {'ok':True,'sources':{s:sorted(set(v)) for s,v in sources.items()},'groups':list(groups.values()),'knownOnly':True}


def canonical_identities(conn):
    catalog=catalog_from_neon(conn)
    return sorted([{'id':g['identifier'],'name':g['name'],
                    'aliases':g['labels'],'aliasCount':sum(len(v) for v in g['labels'].values()),
                    'missingSources':[s for s in PRIMARY_SOURCES if not g['labels'].get(s)]}
                   for g in (catalog or {}).get('groups',[])],key=lambda g:name_key(g['name']))


def canonical_user_links(conn):
    rows=conn.execute(text("""SELECT DISTINCT v.usuario_id,e.identificador FROM public.usuario_vinculos_dados v
        JOIN public.usuario_escopos_acesso s ON s.usuario_id=v.usuario_id AND s.recurso=v.recurso AND s.ativo
        JOIN public.entidades_acesso_dados e ON e.tipo=v.tipo_entidade AND e.identificador=v.entidade_id AND e.ativo
        WHERE v.ativo AND v.tipo_entidade='tecnico' AND
          (v.recurso='zootecnico_identidade' OR (v.recurso='zootecnico' AND s.escopo='proprio'))""")).mappings()
    grouped={}
    for row in rows:grouped.setdefault(int(row['usuario_id']),set()).add(row['identificador'])
    return {uid:next(iter(ids)) for uid,ids in grouped.items() if len(ids)==1}


def canonical_selection(conn,uid,value):
    identities={g['id']:g for g in canonical_identities(conn)}
    if value['mode']=='proprio':
        identifier=value.get('identityId')
        if identifier and identifier not in identities:raise ValueError('Identidade técnica inexistente, inativa ou sem aliases confirmados.')
        return [(uid,identities.get(identifier))]
    users={int(u['id']):u for u in portal_users(conn)}
    if any(member not in users or not users[member]['ativo'] for member in value['userIds']):
        raise ValueError('Selecione somente usuários ativos para a equipe.')
    links=canonical_user_links(conn)
    return [(member,identities.get(links.get(member))) for member in value['userIds']]


def bind_canonical_identity(conn,uid,identifier,actor):
    # Uma identidade canônica pode ser autorizada a contas diferentes (inclusive
    # conta de teste). O vínculo do usuário muda, a identidade e seus aliases não.
    write_scope(conn,uid,'zootecnico_identidade','proprio',actor)
    conn.execute(text("UPDATE public.usuario_vinculos_dados SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE usuario_id=:uid AND recurso='zootecnico_identidade'"),{'uid':uid,'actor':actor})
    write_link(conn,uid,'zootecnico_identidade','tecnico',identifier,actor)


def replace_canonical_access(conn,uid,value,actor):
    selected=canonical_selection(conn,uid,value)
    if any(identity is None for member,identity in selected):
        if value['allowPending']:return save_pending(conn,uid,value,actor)
        raise ValueError('Selecione uma identidade confirmada para o usuário e confira os vínculos da equipe.')
    for member,identity in selected:bind_canonical_identity(conn,member,identity['id'],actor)
    write_scope(conn,uid,RESOURCE,value['mode'],actor)
    conn.execute(text('UPDATE public.usuario_vinculos_dados SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE usuario_id=:uid AND recurso=:resource'),{'uid':uid,'resource':RESOURCE,'actor':actor})
    for member,identity in selected:
        if value['mode']=='proprio':write_link(conn,uid,RESOURCE,'tecnico',identity['id'],actor)
        else:
            conn.execute(text("""INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
                SELECT 'usuario_portal',id::text,nome,TRUE FROM public.usuarios WHERE id=:member
                ON CONFLICT(tipo,identificador) DO UPDATE SET nome=EXCLUDED.nome,ativo=TRUE,atualizado_em=NOW()"""),{'member':member})
            write_link(conn,uid,RESOURCE,'usuario_portal',str(member),actor)
    clear_pending(conn,uid,actor)
    return {'pending':False,'mode':value['mode']}


def resolve_person(person,catalog,stored,choice=None,duplicate=False):
    choice=choice or {};proposed={source:list(stored.get(source,[])) for source in SOURCES}
    groups=[g for g in catalog['groups'] if g['nameKey']==name_key(person['nome'])]
    if len(groups)==1 and not duplicate:
        for source,values in groups[0]['labels'].items():proposed[source]=sorted(set(proposed[source])|set(values))
    selected=choice.get('selections',{});without=set(choice.get('withoutData',[]));confirmed=choice.get('confirmed') is True
    unresolved=[]
    for source in SOURCES:
        if source in selected or source in without:
            values=selected.get(source,[])
            if any(v not in catalog['sources'][source] and v not in stored.get(source,[]) for v in values):
                raise ValueError('Valor técnico não existe na fonte validada. Atualize a correspondência.')
            if confirmed and (values or source in without):proposed[source]=sorted(set(values)) if source not in without else []
            else:unresolved.append(source)
        elif not proposed[source] and (catalog['sources'][source] or catalog.get('knownOnly')) and source in PRIMARY_SOURCES:
            unresolved.append(source)
    if not any(proposed[source] for source in PRIMARY_SOURCES) and not confirmed:
        unresolved.extend(PRIMARY_SOURCES)
    return {'key':person['key'],'userId':person['id'],'name':person['nome'],
            'labels':proposed,'unresolved':sorted(set(unresolved)),
            'ready':not unresolved,'previouslyValidated':any(stored.values()),'confirmed':confirmed}


def resolve_form(conn,uid,name,email,value,catalog):
    users=portal_users(conn);by_id={int(row['id']):row for row in users}
    if value['mode']=='proprio':people=[dict(id=uid,nome=name,email=email,key='self')]
    else:
        people=[]
        for member in value['userIds']:
            row=by_id.get(member)
            if not row or not row['ativo']:raise ValueError('Um usuário da equipe está inativo ou não existe.')
            people.append({**row,'key':str(member)})
    result=[]
    for person in people:
        entity=personal_entity(conn,person['id']) if person['id'] else None
        aliases=stored_aliases(conn,entity)
        duplicate=any(int(row['id'])!=person['id'] and row['ativo'] and name_key(row['nome'])==name_key(person['nome']) for row in users)
        choice=value['resolutions'].get(person['key']) or {}
        renamed=entity and name_key(entity['nome'])!=name_key(person['nome'])
        resolved=resolve_person(person,catalog,{s:[] for s in SOURCES} if renamed else aliases,choice,duplicate)
        if renamed and choice.get('confirmed') is not True:
            resolved['unresolved']=sorted(set(resolved['unresolved'])|set(PRIMARY_SOURCES));resolved['ready']=False
        resolved['entity']=entity
        if resolved['ready']:
            try:identity_identifier(conn,resolved)
            except ValueError as error:
                resolved['ready']=False;resolved['error']=str(error)
        result.append(resolved)
    owners={}
    for person in result:
        for source,values in person['labels'].items():
            for label in values:
                previous=owners.get((source,label))
                if previous and previous['userId']!=person['userId']:
                    for conflict in (previous,person):
                        conflict['ready']=False
                        conflict['error']='A mesma correspondência foi selecionada para dois usuários da equipe. Confira os valores no formulário.'
                        conflict['unresolved']=sorted(set(conflict['unresolved'])|{source})
                owners[source,label]=person
    return result


def write_scope(conn,uid,resource,mode,actor):
    conn.execute(text("""INSERT INTO public.usuario_escopos_acesso(usuario_id,recurso,escopo,ativo,criado_por,atualizado_por)
        VALUES (:uid,:resource,:mode,TRUE,:actor,:actor) ON CONFLICT (usuario_id,recurso) DO UPDATE
        SET escopo=EXCLUDED.escopo,ativo=TRUE,atualizado_em=NOW(),atualizado_por=:actor"""),
        {'uid':uid,'resource':resource,'mode':mode,'actor':actor})


def write_link(conn,uid,resource,kind,identifier,actor):
    conn.execute(text("""INSERT INTO public.usuario_vinculos_dados(usuario_id,recurso,tipo_entidade,entidade_id,ativo,criado_por,atualizado_por)
        VALUES (:uid,:resource,:kind,:id,TRUE,:actor,:actor)
        ON CONFLICT (usuario_id,recurso,tipo_entidade,entidade_id) DO UPDATE
        SET ativo=TRUE,atualizado_em=NOW(),atualizado_por=:actor"""),
        {'uid':uid,'resource':resource,'kind':kind,'id':identifier,'actor':actor})


def identity_identifier(conn,person):
    identifier=person['entity']['identificador'] if person['entity'] else 'usuario_'+str(person['userId'])
    # Reaproveitar catálogo legado ainda sem dono, sem reassociar outro usuário.
    pairs=[{'fonte':s,'valor':v} for s,values in person['labels'].items() for v in values]
    owners=list(conn.execute(text("""SELECT DISTINCT a.entidade_id,e.nome FROM public.entidade_aliases_dados a
        JOIN public.entidades_acesso_dados e ON e.tipo=a.tipo_entidade AND e.identificador=a.entidade_id
        JOIN jsonb_to_recordset(CAST(:pairs AS jsonb)) AS p(fonte text,valor text) ON p.fonte=a.fonte AND p.valor=a.valor
        WHERE a.recurso='zootecnico'"""),{'pairs':json.dumps(pairs)}).mappings())
    if owners and any(row['entidade_id']!=identifier for row in owners):
        if person['entity'] or len(owners)!=1 or (name_key(owners[0]['nome'])!=name_key(person['name']) and not person.get('confirmed')):
            raise ValueError('Uma correspondência selecionada já pertence a outra identidade técnica. O cadastro não foi salvo.')
        identifier=owners[0]['entidade_id']
    if conn.execute(text("""SELECT EXISTS(SELECT 1 FROM public.usuario_vinculos_dados v
        JOIN public.usuario_escopos_acesso s ON s.usuario_id=v.usuario_id AND s.recurso=v.recurso
        WHERE v.tipo_entidade='tecnico' AND v.entidade_id=:id AND v.usuario_id<>:uid
          AND (v.recurso='zootecnico_identidade' OR (v.recurso='zootecnico' AND s.escopo='proprio')))"""),
        {'id':identifier,'uid':person['userId']}).scalar():
        raise ValueError('O técnico já está vinculado a outro usuário. Use esse usuário na equipe; não foi criado vínculo duplicado.')
    return identifier


def save_identity(conn,person,actor):
    identifier=identity_identifier(conn,person)
    pairs=[{'fonte':s,'valor':v} for s,values in person['labels'].items() for v in values]
    conn.execute(text("""INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
        VALUES ('tecnico',:id,:name,TRUE) ON CONFLICT(tipo,identificador) DO UPDATE SET nome=EXCLUDED.nome,ativo=TRUE,atualizado_em=NOW()"""),
        {'id':identifier,'name':person['name']})
    write_scope(conn,person['userId'],'zootecnico_identidade','proprio',actor)
    conn.execute(text("UPDATE public.usuario_vinculos_dados SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE usuario_id=:uid AND recurso='zootecnico_identidade'"),{'uid':person['userId'],'actor':actor})
    write_link(conn,person['userId'],'zootecnico_identidade','tecnico',identifier,actor)
    conn.execute(text("UPDATE public.entidade_aliases_dados SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE recurso='zootecnico' AND entidade_id=:id AND tipo_entidade='tecnico'"),{'id':identifier,'actor':actor})
    for pair in pairs:
        saved=conn.execute(text("""INSERT INTO public.entidade_aliases_dados(recurso,fonte,valor,tipo_entidade,entidade_id,ativo,criado_por,atualizado_por)
            VALUES ('zootecnico',:source,:value,'tecnico',:id,TRUE,:actor,:actor)
            ON CONFLICT(recurso,fonte,valor) DO UPDATE SET ativo=TRUE,atualizado_em=NOW(),atualizado_por=:actor
            WHERE entidade_aliases_dados.entidade_id=:id RETURNING entidade_id"""),
            {'source':pair['fonte'],'value':pair['valor'],'id':identifier,'actor':actor}).scalar()
        if saved!=identifier:raise ValueError('A correspondência foi alterada por outro cadastro. Confira novamente; nada foi salvo.')
    return identifier


def replace_form_access(conn,uid,value,actor):
    value=normalize_form_access(value)
    target=conn.execute(text('SELECT id,nome,email,role,perfil FROM public.usuarios WHERE id=:uid'),{'uid':uid}).mappings().first()
    if not target:raise ValueError('Usuário não encontrado.')
    mode='todos' if general_role(target) else value['mode']
    if not schema_ready(conn):
        if general_role(target):return  # A autorização geral já é dada pelo perfil.
        raise ValueError('A estrutura de permissões da Integração ainda não está instalada.')
    if mode in {'none','todos'}:
        replace_access(conn,uid,{'mode':mode,'technicianIds':[]},actor)
        clear_pending(conn,uid,actor)
        return {'pending':False,'mode':mode}
    if value['formVersion']==3:
        return replace_canonical_access(conn,uid,value,actor)
    catalog=catalog_peek() or catalog_from_neon(conn)
    if catalog is None:
        if value['allowPending']:return save_pending(conn,uid,value,actor)
        raise ValueError('Valide a identificação dos técnicos no formulário antes de salvar. Nenhum cadastro foi concluído.')
    people=resolve_form(conn,uid,target['nome'],target['email'],value,catalog)
    if any(not person['ready'] for person in people):
        if value['allowPending']:return save_pending(conn,uid,value,actor)
        raise ValueError('Há correspondências pendentes. Resolva os campos da Integração antes de salvar.')
    identities={person['userId']:save_identity(conn,person,actor) for person in people}
    write_scope(conn,uid,RESOURCE,mode,actor)
    conn.execute(text('UPDATE public.usuario_vinculos_dados SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE usuario_id=:uid AND recurso=:resource'),{'uid':uid,'resource':RESOURCE,'actor':actor})
    if mode=='proprio':write_link(conn,uid,RESOURCE,'tecnico',identities[uid],actor)
    else:
        for person in people:
            conn.execute(text("""INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
                VALUES ('usuario_portal',:id,:name,TRUE) ON CONFLICT(tipo,identificador) DO UPDATE SET nome=EXCLUDED.nome,ativo=TRUE,atualizado_em=NOW()"""),{'id':str(person['userId']),'name':person['name']})
            write_link(conn,uid,RESOURCE,'usuario_portal',str(person['userId']),actor)
    clear_pending(conn,uid,actor)
    return {'pending':False,'mode':mode}


def clear_pending(conn,uid,actor):
    for table in ('usuario_vinculos_dados','usuario_escopos_acesso'):
        conn.execute(text('UPDATE public.'+table+" SET ativo=FALSE,atualizado_em=NOW(),atualizado_por=:actor WHERE usuario_id=:uid AND recurso='zootecnico_pendente'"),{'uid':uid,'actor':actor})


def save_pending(conn,uid,value,actor):
    users={int(u['id']):u for u in portal_users(conn)}
    if any(member not in users or not users[member]['ativo'] for member in value['userIds']):
        raise ValueError('Selecione somente usuários ativos para a equipe.')
    # A intenção fica separada da autorização efetiva. Nenhum alias é criado,
    # nenhuma identidade é reassociada, e a conta recebe zero registros.
    replace_access(conn,uid,{'mode':'none','technicianIds':[]},actor)
    clear_pending(conn,uid,actor)
    write_scope(conn,uid,'zootecnico_pendente',value['mode'],actor)
    for member in value['userIds']:
        conn.execute(text("""INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
            VALUES ('usuario_portal',:id,:name,TRUE) ON CONFLICT(tipo,identificador) DO NOTHING"""),
            {'id':str(member),'name':users[member]['nome']})
        write_link(conn,uid,'zootecnico_pendente','usuario_portal',str(member),actor)
    return {'pending':True,'mode':value['mode']}


def general_role(user):
    # Política explicitamente autorizada: mesmos perfis gerais atuais do portal.
    return (str(user.get("role") or "").strip().lower() in {"admin", "director"}
            or str(user.get("perfil") or "").strip().lower() in {"admin", "diretor", "director"})


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
    if row['escopo'] in {'none','todos'}:
        return {'mode':row['escopo'],'technicianIds':[]}
    ids = list(conn.execute(text("""
        SELECT v.entidade_id FROM public.usuario_vinculos_dados v
        JOIN public.entidades_acesso_dados e
          ON e.tipo=v.tipo_entidade AND e.identificador=v.entidade_id AND e.ativo
        WHERE v.usuario_id=:uid AND v.recurso=:resource AND v.ativo
          AND v.tipo_entidade='tecnico'
        UNION
        SELECT p.entidade_id FROM public.usuario_vinculos_dados team
        JOIN public.usuarios member ON member.id::text=team.entidade_id AND member.ativo
        JOIN public.usuario_escopos_acesso ps ON ps.usuario_id=member.id AND ps.recurso='zootecnico_identidade' AND ps.ativo
        JOIN public.usuario_vinculos_dados p ON p.usuario_id=member.id AND p.recurso=ps.recurso AND p.ativo AND p.tipo_entidade='tecnico'
        JOIN public.entidades_acesso_dados e ON e.tipo='tecnico' AND e.identificador=p.entidade_id AND e.ativo
        WHERE team.usuario_id=:uid AND team.recurso=:resource AND team.ativo AND team.tipo_entidade='usuario_portal'
        ORDER BY entidade_id
    """), {"uid": uid, "resource": RESOURCE}).scalars())
    try:
        return normalize_access({"mode": row["escopo"], "technicianIds": ids})
    except ValueError:
        return {"mode": "none", "technicianIds": []}


def read_configured_access(conn,uid):
    """Editor mostra a configuração salva; autorização efetiva usa read_access.

    Equipe com membros bloqueados não perde sua seleção ao reabrir o cadastro.
    Identidade inativa pode ser exibida como indisponível, mas nunca autorizada.
    """
    row=conn.execute(text('SELECT escopo, ativo FROM public.usuario_escopos_acesso WHERE usuario_id=:uid AND recurso=:resource'),{'uid':uid,'resource':RESOURCE}).mappings().first()
    if not row or not row['ativo'] or row['escopo'] not in {'none','proprio','equipe','todos'}:
        return {'mode':'none','technicianIds':[]}
    ids=list(conn.execute(text("SELECT v.entidade_id FROM public.usuario_vinculos_dados v WHERE v.usuario_id=:uid AND v.recurso=:resource AND v.ativo AND v.tipo_entidade='tecnico' ORDER BY v.entidade_id"),{'uid':uid,'resource':RESOURCE}).scalars()) if row['escopo']=='proprio' else []
    return {'mode':row['escopo'],'technicianIds':ids if len(ids)==1 else []}


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
    @app.post('/api/admin/zootecnico/preview')
    def zootecnico_preview():
        user=authenticate()
        if not user:return response({'ok':False},401)
        if not is_admin(user):return response({'ok':False},403)
        try:
            body=request.get_json(silent=True) or {}
            value=normalize_form_access(body.get('access'))
            uid=body.get('uid',0)
            if type(uid) is not int or uid<0:raise ValueError('Usuário inválido.')
            if value['mode'] in {'none','todos'}:return response({'ok':True,'ready':True,'persons':[]})
            if value['formVersion']==3:
                with engine.connect() as conn:
                    if not schema_ready(conn):raise ValueError('A estrutura de permissões da Integração ainda não está instalada.')
                    selected=canonical_selection(conn,uid,value)
                return response({'ok':True,'ready':all(identity is not None for member,identity in selected),
                                 'canSavePending':True,'source':'neon','persons':[
                                     {'userId':member,'identityId':identity['id'] if identity else None,
                                      'name':identity['name'] if identity else None,
                                      'missingSources':identity['missingSources'] if identity else list(PRIMARY_SOURCES)}
                                     for member,identity in selected]})
            name=str(body.get('name') or '').strip()
            if value['mode']=='proprio' and not name:raise ValueError('Informe o nome completo para identificar os dados.')
            with engine.connect() as conn:
                if not schema_ready(conn):raise ValueError('A estrutura de permissões da Integração ainda não está instalada.')
                if uid and not conn.execute(text('SELECT EXISTS(SELECT 1 FROM public.usuarios WHERE id=:uid)'),{'uid':uid}).scalar():raise ValueError('Usuário não encontrado.')
                local=catalog_from_neon(conn)
                people=resolve_form(conn,uid,name,str(body.get('email') or ''),value,local) if local else []
            ready=bool(people) and all(person['ready'] for person in people)
            warning=None
            if not ready:
                try:catalog=catalog_get_or_start(request.headers.get('Authorization',''),body.get('retry') is True)
                except ValueError as error:catalog=None;warning=str(error)
                if catalog:
                    with engine.connect() as conn:
                        people=resolve_form(conn,uid,name,str(body.get('email') or ''),value,catalog)
                    local=catalog;ready=all(person['ready'] for person in people)
                elif not warning:
                    return response({'ok':True,'pending':True,'canSavePending':True},202)
            public=[{key:value for key,value in person.items() if key!='entity'} for person in people]
            return response({'ok':True,'ready':ready,'canSavePending':True,'warning':warning,
                             'persons':public,'options':local['sources'] if local else {s:[] for s in SOURCES}})
        except ValueError as error:return response({'ok':False,'erro':str(error)},400)
        except Exception:return response({'ok':False,'erro':'Não foi possível conferir a correspondência. Nenhum cadastro foi concluído.'},503)

    @app.get("/api/auth/zootecnico-access")
    def zootecnico_authorization():
        user = authenticate()
        if not user:
            return response({"ok": False, "erro": "Sessão inválida ou expirada."}, 401)
        try:
            with engine.connect() as conn:
                if not report_allowed(conn, user):
                    return response({"ok": False, "erro": "Relatório não autorizado."}, 403)
                # Admin/Diretor já têm acesso geral pelo perfil, sem depender
                # das tabelas auxiliares novas nem da resolução de técnicos.
                if general_role(user):
                    return response({"ok":True,"allowed":True,"resource":RESOURCE,
                        "reportId":REPORT_ID,"userId":user['usuario_id'],
                        "mode":"todos","technicianIds":[],"aliases":[]})
                if not schema_ready(conn):
                    return response({"ok": False, "erro": "Permissões da Integração indisponíveis."}, 503)
                access = read_access(conn, user["usuario_id"])
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
                users=portal_users(conn)
                access = read_configured_access(conn, uid) if uid else {"mode": "none", "technicianIds": []}
                members=[]
                if uid and access['mode']=='equipe':
                    members=list(conn.execute(text("""SELECT DISTINCT member.id FROM public.usuario_vinculos_dados v
                        JOIN public.usuarios member ON (v.tipo_entidade='usuario_portal' AND v.entidade_id=member.id::text)
                        OR (v.tipo_entidade='tecnico' AND EXISTS (
                          SELECT 1 FROM public.usuario_vinculos_dados p JOIN public.usuario_escopos_acesso s
                            ON s.usuario_id=p.usuario_id AND s.recurso=p.recurso AND s.ativo
                          WHERE p.usuario_id=member.id AND p.ativo AND p.tipo_entidade='tecnico' AND p.entidade_id=v.entidade_id
                            AND (p.recurso='zootecnico_identidade' OR (p.recurso='zootecnico' AND s.escopo='proprio'))))
                        WHERE v.usuario_id=:uid AND v.recurso='zootecnico' AND v.ativo ORDER BY member.id"""),{'uid':uid}).scalars())
                pending=conn.execute(text("SELECT escopo AS requested_mode FROM public.usuario_escopos_acesso WHERE usuario_id=:uid AND recurso='zootecnico_pendente' AND ativo"),{'uid':uid}).mappings().first() if uid else None
                if pending and access['mode']=='none':
                    access['mode']=pending['requested_mode']
                    members=list(conn.execute(text("SELECT entidade_id::bigint FROM public.usuario_vinculos_dados WHERE usuario_id=:uid AND recurso='zootecnico_pendente' AND tipo_entidade='usuario_portal' AND ativo ORDER BY entidade_id"),{'uid':uid}).scalars())
                links=canonical_user_links(conn)
                access={'formVersion':3,'mode':access['mode'],'userIds':members,'pending':bool(pending),
                        'identityId':access.get('technicianIds',[None])[0] if access['mode']=='proprio' and access.get('technicianIds') else None}
                identities=canonical_identities(conn)
                if general_role(target):access={'formVersion':3,'mode':'todos','userIds':[],'identityId':None,'pending':False}
            return response({'ok':True,'access':access,'identities':identities,
                             'users':[{'id':int(row['id']),'name':row['nome'],'email':row['email'],
                                       'active':bool(row['ativo']),'identityId':links.get(int(row['id']))} for row in users]})
        except Exception:
            return response({"ok": False, "erro": "Não foi possível carregar o acesso da Integração."}, 503)
