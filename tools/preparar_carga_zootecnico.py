"""Cruza resultados fornecidos e gera carga local. NÃO conecta, importa app ou executa SQL."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'integrations/zootecnico/carga-local'


def key(value):return ' '.join(unicodedata.normalize('NFC',str(value or '')).split()).casefold()


def result(path):
    raw=Path(path).read_text(encoding='utf-8-sig').strip()
    start=min(i for i in (raw.find('{'),raw.find('[')) if i>=0)
    data=json.JSONDecoder().raw_decode(raw[start:])[0]
    if isinstance(data,list):data=json.loads(data[0]['resultado'])
    if isinstance(data,dict) and isinstance(data.get('resultado'),str):data=json.loads(data['resultado'])
    if data.get('somente_leitura')!='on':raise ValueError('Resultado não confirma transação de leitura.')
    return data


def api_module():
    spec=importlib.util.spec_from_file_location('carga_acl',ROOT/'integrations/zootecnico/api/zootecnico_acesso.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def roster(path,transcription=None):
    # Dados pessoais ficam somente na entrega local ignorada pelo Git.
    # Conferir a transcrição no Word, sem deduzir nome, e-mail ou login.
    data=json.loads(Path(transcription or OUTPUT/'lista_word.json').read_text(encoding='utf-8'))
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=data['source_sha256']:
        raise ValueError('O Word mudou; conferir a lista antes de gerar nova carga.')
    with ZipFile(path) as archive:
        root=ET.fromstring(archive.read('word/document.xml'))
    ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    text=key(' '.join(''.join(n.text or '' for n in p.iter(ns+'t')) for p in root.iter(ns+'p')))
    people=[]
    for person in data['pessoas']:
        name,login,email=(person[k] for k in ('nome','login_agrosys','email'))
        if not all(key(value) in text for value in (name,login,email)):
            raise ValueError('Transcrição não confere com o Word: '+name)
        people.append(dict(nome=name,login_agrosys=login,email=email))
    return people


def consolidate(internal,neon,people,api):
    if internal.get('banco')!='bi_granja' or internal.get('alcance')!='completo_sem_amostragem':
        raise ValueError('Levantamento interno incompleto ou de outro banco.')
    if neon.get('banco')!='portal-bi-granjabrasilia':raise ValueError('Banco Neon incorreto.')
    if {r['fonte'] for r in internal['fontes']}!=set(api.SOURCES):raise ValueError('Faltam fontes.')
    catalog=api.catalog_from_evidence(internal['valores'],internal['evidencias_candidatas'])
    counts={(r['fonte'],r['campo'],r['valor']):r['registros'] for r in internal['valores']}
    for group in catalog['groups']:
        group['registros_por_fonte']={source:sum(counts.get((source,'tecnico',v),0) for v in values) for source,values in group['labels'].items()}
        group['evidencias']=[p for p in internal['evidencias_candidatas']
            if p['fonte_a']!='base_dinamica' and p['fonte_b']!='base_dinamica'
            and p['valor_a'] in group['labels'].get(p['fonte_a'],[]) and p['valor_b'] in group['labels'].get(p['fonte_b'],[])]
        group['estado']='identidade_confirmada'
    for row in catalog['pending']:
        row['registros']=counts.get((row['fonte'],'tecnico',row['valor']),0)
    users=neon['usuarios'];cross=[];bindings=[]
    for person in people:
        accounts=[u for u in users if key(u['email'])==key(person['email'])]
        names=[u for u in users if key(u['nome'])==key(person['nome'])]
        groups=[g for g in catalog['groups'] if g['nameKey']==key(person['nome'])]
        problems=[]
        if not accounts:problems.append('cadastrar_pelo_portal')
        if len(accounts)>1:problems.append('email_duplicado')
        if len(groups)!=1:problems.append('confirmar_nome_exato_na_fonte_no_formulario')
        if accounts and any(key(u['nome'])!=key(person['nome']) for u in accounts):problems.append('nome_da_conta_diverge_do_word')
        if accounts and not all(u['ativo'] for u in accounts):problems.append('conta_inativa')
        if not accounts and names:problems.append('nome_encontrado_com_outro_email')
        if person['email'].endswith('@granjabrasilia.com'):problems.append('confirmar_dominio_email_com_sem_br')
        row={**person,'contas_por_email':accounts,'contas_por_nome':names,
             'identidades_exatas':[g['identifier'] for g in groups],'pendencias':problems}
        cross.append(row)
        if not problems and len(accounts)==len(groups)==1:
            bindings.append(dict(usuario_id=accounts[0]['id'],email=accounts[0]['email'],nome=accounts[0]['nome'],entidade_id=groups[0]['identifier']))
    # Catálogo novo: preservar IDs existentes para os mesmos aliases/nome, sem
    # transferir aliases de outra identidade, mesmo se estiverem inativos.
    entities={e['identificador']:e for e in neon['entidades'] if e['tipo']=='tecnico'}
    remap={};load=[];conflicts=[]
    for group in catalog['groups']:
        owners={a['entidade_id'] for a in neon['aliases'] if any(a['fonte']==s and a['valor'] in vals for s,vals in group['labels'].items())}
        owners|={e['identificador'] for e in entities.values() if key(e['nome'])==group['nameKey']}
        if len(owners)>1 or any(not entities.get(owner,{}).get('ativo') or key(entities[owner]['nome'])!=group['nameKey'] for owner in owners):
            group['estado']='conflito_neon';conflicts.append(group['identifier']);continue
        if owners:
            old=group['identifier'];group['identifier']=next(iter(owners));remap[old]=group['identifier']
            group['name']=entities[group['identifier']]['nome']
        load.append(group)
    for row in cross:row['identidades_exatas']=[remap.get(v,v) for v in row['identidades_exatas']]
    for binding in bindings:binding['entidade_id']=remap.get(binding['entidade_id'],binding['entidade_id'])
    bindings=[b for b in bindings if b['entidade_id'] in {g['identifier'] for g in load}]
    payload={'entidades':[{'id':g['identifier'],'nome':g['name']} for g in load],
             'aliases':[{'fonte':s,'valor':v,'entidade_id':g['identifier']} for g in load for s,values in g['labels'].items() for v in values],
             'vinculos':bindings}
    catalog.update(fontes=internal['fontes'],valores_originais=internal['valores'],
                   conflitos_lotes=internal['conflitos'],correspondencias_usuarios=cross,
                   conflitos_neon=conflicts,
                   divergencias_base=[p for p in internal['evidencias_candidatas'] if 'base_dinamica' in {p['fonte_a'],p['fonte_b']}])
    return catalog,payload


def batch_sql(payload):
    serialized=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(serialized.encode()).hexdigest()[:24]
    marker='carga_'+digest;tag='$payload_'+digest+'$'
    if any(token in serialized for token in (tag,'$batch$','$undo$')):raise ValueError('Delimitador SQL inesperado.')
    body="""-- Gerado somente a partir dos resultados fornecidos. Executar manualmente no Neon.
-- Não cria contas, não troca senhas/perfis, não altera Comercial ou escopos zootecnico.
-- Insere identidades/aliases confirmados e vínculos de identidade pessoal apenas.
-- Um marcador guarda SOMENTE as linhas realmente inseridas para rollback seguro.
BEGIN;
SET LOCAL statement_timeout='15s';
SET LOCAL lock_timeout='2s';
SELECT pg_advisory_xact_lock(71811203);
DO $batch$
DECLARE
    dados jsonb := __PAYLOAD__::jsonb;
    item jsonb; linha jsonb; atual jsonb;
    diario jsonb := '{"entidades":[],"aliases":[],"escopos":[],"vinculos":[]}'::jsonb;
BEGIN
    IF EXISTS(SELECT 1 FROM public.entidades_acesso_dados WHERE tipo='carga_zootecnico' AND identificador='__MARKER__') THEN
        RAISE NOTICE 'Carga já aplicada; nenhuma permissão foi alterada.'; RETURN;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(dados->'entidades') LOOP
        linha:=NULL;
        INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
        VALUES ('tecnico',item->>'id',item->>'nome',TRUE) ON CONFLICT DO NOTHING
        RETURNING to_jsonb(entidades_acesso_dados) INTO linha;
        IF linha IS NOT NULL THEN
            diario:=jsonb_set(diario,'{entidades}',(diario->'entidades')||jsonb_build_array(linha));
        ELSE
            SELECT to_jsonb(e) INTO atual FROM public.entidades_acesso_dados e WHERE tipo='tecnico' AND identificador=item->>'id';
            IF atual->>'nome' IS DISTINCT FROM item->>'nome' OR atual->>'ativo' IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION 'Identidade existente diverge; carga cancelada: %',item->>'id';
            END IF;
        END IF;
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(dados->'aliases') LOOP
        linha:=NULL;
        INSERT INTO public.entidade_aliases_dados(recurso,fonte,valor,tipo_entidade,entidade_id,ativo)
        VALUES ('zootecnico',item->>'fonte',item->>'valor','tecnico',item->>'entidade_id',TRUE) ON CONFLICT DO NOTHING
        RETURNING to_jsonb(entidade_aliases_dados) INTO linha;
        IF linha IS NOT NULL THEN
            diario:=jsonb_set(diario,'{aliases}',(diario->'aliases')||jsonb_build_array(linha));
        ELSE
            SELECT to_jsonb(a) INTO atual FROM public.entidade_aliases_dados a
            WHERE recurso='zootecnico' AND fonte=item->>'fonte' AND valor=item->>'valor';
            IF atual->>'tipo_entidade' IS DISTINCT FROM 'tecnico' OR atual->>'entidade_id' IS DISTINCT FROM item->>'entidade_id' OR atual->>'ativo' IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION 'Alias já possui outra configuração; carga cancelada: %',item->>'valor';
            END IF;
        END IF;
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(dados->'vinculos') LOOP
        IF NOT EXISTS(SELECT 1 FROM public.usuarios u WHERE u.id=(item->>'usuario_id')::bigint
            AND u.ativo AND LOWER(BTRIM(u.email))=LOWER(BTRIM(item->>'email'))
            AND LOWER(regexp_replace(BTRIM(u.nome),'\\s+',' ','g'))=LOWER(regexp_replace(BTRIM(item->>'nome'),'\\s+',' ','g'))) THEN
            RAISE EXCEPTION 'Conta mudou ou está inativa; carga cancelada: %',item->>'usuario_id';
        END IF;
        IF EXISTS(SELECT 1 FROM public.usuario_vinculos_dados v JOIN public.usuario_escopos_acesso s
            ON s.usuario_id=v.usuario_id AND s.recurso=v.recurso
            WHERE v.tipo_entidade='tecnico' AND
            (v.recurso='zootecnico_identidade' OR (v.recurso='zootecnico' AND s.escopo='proprio')) AND
            ((v.usuario_id=(item->>'usuario_id')::bigint AND v.entidade_id<>item->>'entidade_id') OR
             (v.usuario_id<>(item->>'usuario_id')::bigint AND v.entidade_id=item->>'entidade_id'))) THEN
            RAISE EXCEPTION 'Identidade pessoal já possui outro vínculo; carga cancelada.';
        END IF;
        linha:=NULL;
        INSERT INTO public.usuario_escopos_acesso(usuario_id,recurso,escopo,ativo)
        VALUES ((item->>'usuario_id')::bigint,'zootecnico_identidade','proprio',TRUE) ON CONFLICT DO NOTHING
        RETURNING to_jsonb(usuario_escopos_acesso) INTO linha;
        IF linha IS NOT NULL THEN
            diario:=jsonb_set(diario,'{escopos}',(diario->'escopos')||jsonb_build_array(linha));
        ELSE
            SELECT to_jsonb(s) INTO atual FROM public.usuario_escopos_acesso s WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso='zootecnico_identidade';
            IF atual->>'escopo' IS DISTINCT FROM 'proprio' OR atual->>'ativo' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'Escopo pessoal existente diverge.'; END IF;
        END IF;
        linha:=NULL;
        INSERT INTO public.usuario_vinculos_dados(usuario_id,recurso,tipo_entidade,entidade_id,ativo)
        VALUES ((item->>'usuario_id')::bigint,'zootecnico_identidade','tecnico',item->>'entidade_id',TRUE) ON CONFLICT DO NOTHING
        RETURNING to_jsonb(usuario_vinculos_dados) INTO linha;
        IF linha IS NOT NULL THEN
            diario:=jsonb_set(diario,'{vinculos}',(diario->'vinculos')||jsonb_build_array(linha));
        ELSE
            SELECT to_jsonb(v) INTO atual FROM public.usuario_vinculos_dados v WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso='zootecnico_identidade' AND tipo_entidade='tecnico' AND entidade_id=item->>'entidade_id';
            IF atual->>'ativo' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'Vínculo pessoal existente está inativo.'; END IF;
        END IF;
    END LOOP;
    INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
    VALUES ('carga_zootecnico','__MARKER__',diario::text,FALSE);
END;
$batch$;
COMMIT;
-- Conferência da carga efetivamente inserida; os escopos zootecnico anteriores continuam iguais.
SELECT identificador, jsonb_array_length(nome::jsonb->'entidades') AS identidades_inseridas,
       jsonb_array_length(nome::jsonb->'aliases') AS aliases_inseridos,
       jsonb_array_length(nome::jsonb->'vinculos') AS vinculos_pessoais_inseridos
FROM public.entidades_acesso_dados WHERE tipo='carga_zootecnico' AND identificador='__MARKER__';
"""
    rollback="""-- Reverte apenas as linhas registradas por ESTA carga. Executar manualmente no Neon.
-- Se houver edição posterior, a comparação exata cancela TODO o rollback.
-- Novas referências também impedem a exclusão por FK; não usar CASCADE.
BEGIN;
SET LOCAL statement_timeout='15s';
SET LOCAL lock_timeout='2s';
SELECT pg_advisory_xact_lock(71811203);
DO $undo$
DECLARE diario jsonb; item jsonb; atual jsonb;
BEGIN
    SELECT nome::jsonb INTO diario FROM public.entidades_acesso_dados
    WHERE tipo='carga_zootecnico' AND identificador='__MARKER__' FOR UPDATE;
    IF diario IS NULL THEN RAISE NOTICE 'Carga ausente ou já revertida.'; RETURN; END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(diario->'vinculos') LOOP
        SELECT to_jsonb(v) INTO atual FROM public.usuario_vinculos_dados v
        WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso=item->>'recurso' AND tipo_entidade=item->>'tipo_entidade' AND entidade_id=item->>'entidade_id' FOR UPDATE;
        IF atual IS DISTINCT FROM item THEN RAISE EXCEPTION 'Vínculo alterado após a carga; rollback cancelado.'; END IF;
        DELETE FROM public.usuario_vinculos_dados WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso=item->>'recurso' AND tipo_entidade=item->>'tipo_entidade' AND entidade_id=item->>'entidade_id';
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(diario->'escopos') LOOP
        SELECT to_jsonb(s) INTO atual FROM public.usuario_escopos_acesso s WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso=item->>'recurso' FOR UPDATE;
        IF atual IS DISTINCT FROM item THEN RAISE EXCEPTION 'Escopo alterado após a carga; rollback cancelado.'; END IF;
        IF EXISTS(SELECT 1 FROM public.usuario_vinculos_dados WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso=item->>'recurso') THEN
            RAISE EXCEPTION 'Novos vínculos usam o escopo; rollback cancelado sem CASCADE.';
        END IF;
        DELETE FROM public.usuario_escopos_acesso WHERE usuario_id=(item->>'usuario_id')::bigint AND recurso=item->>'recurso';
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(diario->'aliases') LOOP
        SELECT to_jsonb(a) INTO atual FROM public.entidade_aliases_dados a WHERE recurso=item->>'recurso' AND fonte=item->>'fonte' AND valor=item->>'valor' FOR UPDATE;
        IF atual IS DISTINCT FROM item THEN RAISE EXCEPTION 'Alias alterado após a carga; rollback cancelado.'; END IF;
        DELETE FROM public.entidade_aliases_dados WHERE recurso=item->>'recurso' AND fonte=item->>'fonte' AND valor=item->>'valor';
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(diario->'entidades') LOOP
        SELECT to_jsonb(e) INTO atual FROM public.entidades_acesso_dados e WHERE tipo=item->>'tipo' AND identificador=item->>'identificador' FOR UPDATE;
        IF atual IS DISTINCT FROM item THEN RAISE EXCEPTION 'Identidade alterada após a carga; rollback cancelado.'; END IF;
        DELETE FROM public.entidades_acesso_dados WHERE tipo=item->>'tipo' AND identificador=item->>'identificador';
    END LOOP;
    DELETE FROM public.entidades_acesso_dados WHERE tipo='carga_zootecnico' AND identificador='__MARKER__';
END;
$undo$;
COMMIT;
"""
    up=body.replace('__PAYLOAD__',tag+serialized+tag).replace('__MARKER__',marker)
    down=rollback.replace('__MARKER__',marker)
    validate_batch_sql(up);validate_batch_sql(down)
    return up,down


def validate_batch_sql(script):
    """Guarda lexical local: aspas/parênteses e fim dos blocos DO.

    Não substitui compilação PL/pgSQL no PostgreSQL. JSON dollar-quoted é dado,
    não SQL; inspecionar o corpo DO sem interpretar seu payload como comandos.
    """
    blocks=list(re.finditer(r'\bDO\s+(\$[A-Za-z_][A-Za-z0-9_]*\$)(.*?)\1\s*;',script,re.S))
    if len(blocks)!=1:raise ValueError('Esperado exatamente um bloco DO completo.')
    body=blocks[0].group(2)
    if not body.rstrip().endswith('END;'):raise ValueError('Bloco DO deve terminar com END; dentro das aspas dollar.')
    stack=[];index=0
    while index<len(body):
        char=body[index]
        if body.startswith('--',index):
            end=body.find('\n',index);index=len(body) if end<0 else end+1;continue
        if char in "'\"":
            quote=char;start=index;index+=1
            while index<len(body):
                if body[index]==quote:
                    if index+1<len(body) and body[index+1]==quote:index+=2;continue
                    index+=1;break
                index+=1
            else:raise ValueError('Aspa sem fechamento no bloco DO, linha '+str(body.count('\n',0,start)+1))
            continue
        if char=='$':
            match=re.match(r'\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$',body[index:])
            if match:
                delimiter=match[0];end=body.find(delimiter,index+len(delimiter))
                if end<0:raise ValueError('Literal dollar-quoted sem fechamento.')
                index=end+len(delimiter);continue
        if char=='(':stack.append(index)
        elif char==')':
            if not stack:raise ValueError('Parêntese excedente no bloco DO, linha '+str(body.count('\n',0,index)+1))
            stack.pop()
        elif char==';' and stack:raise ValueError('Parêntese ou aspa incorreta antes do ponto e vírgula no bloco DO.')
        index+=1
    if stack:raise ValueError('Parêntese sem fechamento no bloco DO.')


def prepare(internal_path,neon_path,word_path,output=OUTPUT):
    internal,neon=result(internal_path),result(neon_path)
    catalog,payload=consolidate(internal,neon,roster(word_path),api_module())
    output.mkdir(parents=True,exist_ok=True)
    for name,data in [('catalogo_tecnicos.json',catalog),('carga_confirmada.json',payload)]:
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    up,down=batch_sql(payload)
    (output/'03_carga_inicial_neon.sql').write_text(up,encoding='utf-8')
    (output/'04_rollback_carga_neon.sql').write_text(down,encoding='utf-8')
    lines=['# Conferência da carga zootécnica','',
        'Gerado dos resultados reais fornecidos pelo usuário. Nada executado em produção.','',
        f"Identidades confirmadas: {len(payload['entidades'])}. Aliases confirmados: {len(payload['aliases'])}. Valores pendentes: {len(catalog['pending'])}.",
        f"Contas no Neon: {len(neon['usuarios'])}. Pessoas no Word: {len(catalog['correspondencias_usuarios'])}. Vínculos pessoais preparados: {len(payload['vinculos'])}.",'',
        'Os vínculos preparados são somente de identidade. Não concedem nem retiram acesso ao relatório; Admin/Diretor e os acessos gerais existentes continuam iguais.',
        'Leandro da Costa Elias (id 35) já possui escopo todos; preservado. Nenhuma conta será criada pelo SQL.','',
        'A base dinâmica tem divergências de responsável na mesma chave histórica: seus nomes entram apenas por igualdade exata. Esses pares não provam que uma sigla representa outra pessoa. Não há regra de maioria nem correspondência por iniciais.',
        'As equivalências de siglas usam as fontes históricas por chave completa e exigem um único nome no componente. Conflitos ficam pendentes.','',
        '| Nome no Word | Login Agrosys | E-mail fornecido | Conta encontrada | Identidade exata | Pendências |',
        '|---|---|---|---|---|---|']
    for person in catalog['correspondencias_usuarios']:
        lines.append('| '+' | '.join([person['nome'],person['login_agrosys'],person['email'],','.join(str(u['id']) for u in person['contas_por_email']) or 'Não',','.join(person['identidades_exatas']) or 'Pendente',', '.join(person['pendencias']) or 'Confirmado'])+' |')
    lines+=['','## Preservação dos acessos existentes','',
        'O SQL não escreve no recurso zootecnico, em usuários, setores, relatórios ou permissões comerciais. O rollback compara as linhas inseridas com seu conteúdo completo e cancela se elas tiverem sido editadas depois.',
        'Depois da conferência, executar somente 03_carga_inicial_neon.sql. O arquivo 04 é exclusivamente para reversão, se necessária. Não executar ambos na implantação.','',
        '## Catálogo consolidado','', '| Identidade | Nome da fonte | Fontes com aliases | Registros primários por fonte |','|---|---|---|---|']
    for group in catalog['groups']:
        lines.append('| '+' | '.join([group['identifier'],group['name'],', '.join(group['labels']),'; '.join(s+': '+str(n) for s,n in group['registros_por_fonte'].items())])+' |')
    (output/'conferencia_carga.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'identidades':len(payload['entidades']),'aliases':len(payload['aliases']),'pendentes':len(catalog['pending']),'vinculos_pessoais':len(payload['vinculos']),'pasta':str(output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interno',type=Path,required=True);parser.add_argument('--neon',type=Path,required=True)
    parser.add_argument('--word',type=Path,default=Path.home()/'Downloads/Usuarios Portal Resultados(1).docx')
    args=parser.parse_args();print(json.dumps(prepare(args.interno,args.neon,args.word),ensure_ascii=False))
