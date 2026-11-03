"""Planejar/conferir/cadastrar via API oficial. Nenhuma chamada de rede ao importar.

Não lê .env, não conecta diretamente ao banco e nunca modifica conta existente.
Senhas individuais são geradas somente no apply e protegidas por DPAPI do Windows.
"""
import argparse
import copy
from contextlib import contextmanager
import ctypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import unicodedata
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'integrations/zootecnico/carga-local/cadastro-usuarios'
BASE='https://portal-bi-granjabrasilia.onrender.com'
PRIMARY=('vw_desempenho_acerto_portal','base_dinamica','mortalidade_peso_abertos','vw_historico_lotes_criacao_portal')
SCREENS=dict(zip(PRIMARY,('Desempenho','GPD','Lotes em Criação','Histórico')))


class BatchError(Exception):pass


class ApiError(BatchError):
    def __init__(self,status=None):
        self.status=status
        super().__init__('A API não confirmou a operação'+(f' (HTTP {status})' if status else '')+'. Não repetir o POST automaticamente.')


def normalized(value):return ' '.join(unicodedata.normalize('NFC',str(value or '')).split()).casefold()


def full_name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFD',normalized(value)) if not unicodedata.combining(c))


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def save_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def load_manifest(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('version')!=1 or not isinstance(data.get('users'),list) or not 1<=len(data['users'])<=100:
        raise BatchError('Manifesto inválido.')
    emails=set();names=set()
    for row in data['users']:
        if not isinstance(row.get('name'),str) or not row['name'].strip() or not isinstance(row.get('email'),str) or '@' not in row['email']:
            raise BatchError('Nome/e-mail inválido no manifesto.')
        email=normalized(row['email'])
        if email in emails:raise BatchError('E-mail repetido no manifesto.')
        emails.add(email)
        name=full_name_key(row['name'])
        if name in names:raise BatchError('Nome completo repetido no manifesto; conferir para não duplicar pessoas.')
        names.add(name)
        if row.get('identityId') and not row.get('identityConfirmed'):
            raise BatchError('Identidade sem confirmação explícita no manifesto.')
    return data


def alias_digest(identity):return digest(identity.get('aliases',{})) if identity else None


def plan_rows(manifest,users,identities):
    by_id={i['id']:i for i in identities};rows=[]
    for supplied in manifest['users']:
        email=normalized(supplied['email']);same=[u for u in users if normalized(u['email'])==email]
        identity=by_id.get(supplied.get('identityId'))
        reasons=[];action='new'
        if len(same)>1:action='hold';reasons.append('E-mail duplicado no cadastro atual; conferir manualmente.')
        elif same:action='existing';reasons.append('Conta existente: não alterar senha, perfil, permissões ou vínculo.')
        else:
            name_matches=[u for u in users if full_name_key(u.get('name'))==full_name_key(supplied['name'])]
            local=email.split('@',1)[0]
            variants=[u for u in users if normalized(u['email']).split('@',1)[0]==local and
                      normalized(u['email']).split('@',1)[-1] in {'granjabrasilia.com','granjabrasilia.com.br'} and
                      email.split('@',1)[-1] in {'granjabrasilia.com','granjabrasilia.com.br'}]
            if name_matches or variants:
                action='hold';reasons.append('Possível conta da mesma pessoa com outro e-mail; não duplicar nem corrigir automaticamente.')
        if not identity or not supplied.get('identityConfirmed'):
            reasons.append('Identidade não confirmada: novo usuário fica pendente, sem dados liberados.')
        if supplied.get('emailConfirmed') is not True:
            if action=='new':action='hold'
            reasons.append('E-mail aguarda confirmação.')
        missing=[s for s in PRIMARY if identity and not identity.get('aliases',{}).get(s)]
        if missing:reasons.append('Catálogo pessoal sem alias em: '+', '.join(SCREENS[s] for s in missing)+'. Em acesso próprio, essas fontes ficam bloqueadas; acesso geral existente não muda.')
        current=same[0] if len(same)==1 else None
        rows.append(dict(name=supplied['name'],email=supplied['email'],action=action,
            existingId=current.get('id') if current else None,existingRole=current.get('role') if current else None,
            identityId=identity['id'] if identity and supplied.get('identityConfirmed') else None,
            technician=identity['name'] if identity else None,aliasesDigest=alias_digest(identity),
            missingSources=missing,pendingIdentity=identity is None or not supplied.get('identityConfirmed'),notes=reasons))
    return rows


def context_from_portal(data):
    reports=data.get('reports',[])
    selected=[r for r in reports if r.get('dbId')==13]
    if len(selected)!=1:raise BatchError('Relatório com dbId 13 não encontrado de forma única. Nada será cadastrado.')
    report=selected[0];code=report.get('sector')
    if full_name_key(code)!='integracao' or code not in data.get('sectors',[]):
        raise BatchError('Setor do relatório 13 não corresponde à Integração ativa.')
    request_id=report['id']
    if len([r for r in reports if r['id']==request_id])!=1:
        raise BatchError('Chave pública/legada do relatório 13 é ambígua. Conferir antes de cadastrar.')
    return dict(sectorId=4,sectorCode=code,reportDbId=13,reportRequestId=request_id)


def make_plan(manifest,users,identities,source,context=None):
    plan=dict(version=1,manifestDigest=digest(manifest),source=source,context=context,
              rows=plan_rows(manifest,users,identities),forcePasswordChangeSupported=False)
    plan['approvalDigest']=digest(plan)
    return plan


def verify_plan(plan,approval):
    content={k:v for k,v in plan.items() if k!='approvalDigest'}
    if digest(content)!=plan.get('approvalDigest') or approval!=plan['approvalDigest']:
        raise BatchError('Aprovação não corresponde ao plano. Refazer a conferência antes de executar.')
    if plan['source']!='api_oficial':raise BatchError('Plano offline não autoriza cadastro. Execute --check primeiro.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Api:
    def __init__(self):self.token=None;self.opener=build_opener(ProxyHandler({}),NoRedirect())
    def request(self,method,path,body=None):
        if not path.startswith('/api/') or '?' in path:raise BatchError('Caminho de API inválido.')
        headers={'Accept':'application/json','Cache-Control':'no-store'}
        if self.token:headers['Authorization']='Bearer '+self.token
        raw=json.dumps(body).encode() if body is not None else None
        if raw is not None:headers['Content-Type']='application/json'
        try:
            with self.opener.open(Request(BASE+path,data=raw,headers=headers,method=method),timeout=45) as response:
                status=response.status;payload=response.read(4_000_001)
            if len(payload)>4_000_000:raise ApiError(status)
            result=json.loads(payload)
            if not isinstance(result,dict) or result.get('ok') is False:raise ApiError(status)
            return status,result
        except HTTPError as error:
            status=error.code;error.close();raise ApiError(status) from None
        except (URLError,TimeoutError,OSError,ValueError):raise ApiError() from None
    def login(self,email,password):
        _,result=self.request('POST','/api/auth/login',dict(email=email,password=password))
        if result.get('user',{}).get('isAdmin') is not True or not result.get('token'):
            raise BatchError('É necessário usar uma conta administradora ativa do portal.')
        self.token=result['token']
        return result.get('portalData')
    def bootstrap(self):return self.request('GET','/api/auth/bootstrap')[1]['portalData']
    def catalog(self):
        result=self.request('GET','/api/admin/usuarios/0/zootecnico-access')[1]
        if result.get('access',{}).get('formVersion')!=3 or not isinstance(result.get('identities'),list):
            raise BatchError('Publicar o backend do seletor canônico antes do lote. Nenhuma conta foi enviada.')
        return result
    def user_access(self,uid):return self.request('GET',f'/api/admin/usuarios/{uid}/zootecnico-access')[1]['access']
    def create(self,body):return self.request('POST','/api/admin/usuarios',body)


def current_plan(api,manifest,portal_data=None):
    data=portal_data or api.bootstrap();catalog=api.catalog()
    # O catálogo administrativo usa os IDs reais do banco, sem confundir legacy_id.
    bootstrap_users={u['dbId']:u for u in data['users']}
    users=[dict(id=u['id'],name=u['name'],email=u['email'],role=bootstrap_users.get(u['id'],{}).get('role'),
                active=u['active']) for u in catalog['users']]
    if set(bootstrap_users)!={u['id'] for u in users}:raise BatchError('Cadastros mudaram durante a leitura. Refazer a conferência.')
    plan=make_plan(manifest,users,catalog['identities'],'api_oficial',context_from_portal(data))
    for row in plan['rows']:
        if row['action']=='existing':
            row['existingAccess']=api.user_access(row['existingId'])
            current=row['existingAccess']
            if current.get('mode')=='todos':row['notes'].append('Visão geral atual preservada.')
            elif current.get('identityId')!=row['identityId'] or current.get('pending'):
                row['notes'].append('Vínculo atual difere do pretendido ou está pendente; conferir no formulário sem alterar automaticamente.')
    plan['approvalDigest']=digest({k:v for k,v in plan.items() if k!='approvalDigest'})
    return plan,data


def creation_body(row,context,password):
    return dict(name=row['name'],email=row['email'],password=password,role='sector',status='active',
        sectors=[context['sectorCode']],reportAccessMode='specific',reportIds=[context['reportRequestId']],
        ticketPanelAccess=False,operationPermissions=[],commercialAccess={'mode':'none'},
        zootecnicoAccess=dict(formVersion=3,mode='proprio',identityId=row['identityId'],userIds=[],allowPending=True))


def verify_created(api,row,user,context):
    if (user['role']!='sector' or user.get('status')!='active' or user.get('sectors')!=[context['sectorCode']]
        or user.get('reportAccessMode')!='specific' or user.get('reportIds')!=[context['reportRequestId']]
        or user.get('commercialAccess',{}).get('mode')!='none' or user.get('operationPermissions')):
        raise BatchError('Conta criada requer conferência de perfil/setor/relatório. Não corrigir por PATCH automático.')
    access=api.user_access(user['dbId'])
    if access.get('mode')!='proprio' or access.get('identityId')!=row['identityId'] or bool(access.get('pending'))!=bool(row['pendingIdentity']):
        raise BatchError('Vínculo criado requer conferência. Nenhuma alteração automática adicional será feita.')
    return access


def dpapi(data,decrypt=False):
    if os.name!='nt':raise BatchError('A proteção de credenciais deste lote usa o DPAPI do Windows.')
    class Blob(ctypes.Structure):_fields_=[('length',ctypes.c_uint32),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));output=Blob()
    crypto=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(Blob)]
    function.restype=ctypes.c_int
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise BatchError('DPAPI indisponível para este usuário do Windows. Nenhuma senha será gravada em texto puro.')
    try:return ctypes.string_at(output.data,output.length)
    finally:kernel.LocalFree(output.data)


class CredentialBook:
    def __init__(self,path):
        self.path=Path(path);self.entries=json.loads(dpapi(self.path.read_bytes(),True)) if self.path.exists() else {}
    def save(self):
        encrypted=dpapi(json.dumps(self.entries).encode())
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_name(self.path.name+'.writing');temporary.write_bytes(encrypted);temporary.replace(self.path)
    def prepare(self,email):
        k=normalized(email);entry=self.entries.get(k)
        if entry and entry['status']!='prepared':
            raise BatchError('Há um cadastro/envio anterior para '+email+'. Conferir a conta; não recriar nem reenviar automaticamente.')
        if not entry:
            for attempt in range(4):
                candidate=secrets.token_urlsafe(24)
                if all(e['password']!=candidate for e in self.entries.values()):break
            else:raise BatchError('Não foi possível gerar uma credencial individual única.')
            self.entries[k]=dict(password=candidate,status='prepared');self.save()
        return self.entries[k]
    def mark(self,email,status,uid=None):
        self.entries[normalized(email)].update(status=status,uid=uid);self.save()


@contextmanager
def execution_lock(path):
    if os.name!='nt':raise BatchError('Executar o lote no Windows.')
    import msvcrt
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path,'a+b') as file:
        file.seek(0,2)
        if file.tell()==0:file.write(b'0');file.flush()
        file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise BatchError('Já existe uma execução local deste lote.') from None
        try:yield
        finally:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)


def apply_plan(api,manifest,approved,approval,book,on_progress=lambda records:None):
    verify_plan(approved,approval)
    if digest(manifest)!=approved['manifestDigest']:raise BatchError('A lista mudou depois da conferência.')
    fresh,data=current_plan(api,manifest)
    if fresh['context']!=approved['context']:raise BatchError('O relatório/setor mudou; refazer a conferência.')
    before={u['dbId']:copy.deepcopy(u) for u in data['users']};records=[]
    if len(fresh['rows'])!=len(approved['rows']):raise BatchError('A lista mudou; refazer a conferência.')
    for row,old in zip(fresh['rows'],approved['rows']):
        if row['email']!=old['email']:raise BatchError('Ordem da lista mudou; refazer a conferência.')
        if row['action']=='new' and old['action']=='new' and (row['identityId']!=old['identityId'] or row['aliasesDigest']!=old['aliasesDigest']):
            raise BatchError('A identidade/aliases mudaram depois da conferência. Refazer --check antes de qualquer cadastro.')
    for row,old in zip(fresh['rows'],approved['rows']):
        if row['email']!=old['email']:raise BatchError('Ordem da lista mudou; refazer a conferência.')
        if row['action']=='existing':
            entry=book.entries.get(normalized(row['email']))
            if entry and entry['status']=='created_unverified' and entry.get('uid')==row['existingId']:
                verify_created(api,old,before[row['existingId']],fresh['context']);book.mark(row['email'],'confirmed',row['existingId'])
            records.append(dict(email=row['email'],status='existing_untouched',id=row['existingId']))
            on_progress(records);continue
        if row['action']=='hold' or old['action']!='new':
            records.append(dict(email=row['email'],status='pending_manual',notes=row['notes']));on_progress(records);continue
        if row['identityId']!=old['identityId'] or row['aliasesDigest']!=old['aliasesDigest']:
            raise BatchError('A identidade/aliases mudaram depois da conferência. Refazer --check.')
        entry=book.prepare(row['email']);password=entry['password']
        book.mark(row['email'],'sending')
        try:
            status,response=api.create(creation_body(row,fresh['context'],password))
            if status!=201:raise ApiError(status)
        except BatchError:
            book.mark(row['email'],'uncertain')
            records.append(dict(email=row['email'],status='request_uncertain'));on_progress(records);raise
        try:
            data=response.get('data') or api.bootstrap()
            matches=[u for u in data['users'] if normalized(u['email'])==normalized(row['email'])]
            if len(matches)!=1 or not matches[0].get('dbId'):raise BatchError('Resposta incompleta.')
        except (BatchError,KeyError,TypeError):
            book.mark(row['email'],'uncertain')
            records.append(dict(email=row['email'],status='created_response_unverified'));on_progress(records)
            raise BatchError('API confirmou criação, mas não foi possível localizar/conferir a conta. Conferir manualmente, sem reenviar o cadastro.') from None
        user=matches[0];book.mark(row['email'],'created_unverified',user['dbId'])
        try:
            if context_from_portal(data)!=fresh['context']:raise BatchError('Relatório/setor mudou durante a criação; conferir antes de continuar.')
            verify_created(api,row,user,fresh['context'])
            # Conferir usuários anteriores sem ler hashes nem chamar por conta antiga.
            after={u['dbId']:u for u in data['users']}
            if any(after.get(uid)!=previous for uid,previous in before.items()):
                raise BatchError('Uma conta anterior mudou durante o lote. Interrompido para conferência, sem sobrescrever alterações.')
        except BatchError:
            records.append(dict(email=row['email'],status='created_requires_review',id=user['dbId']));on_progress(records);raise
        book.mark(row['email'],'confirmed',user['dbId'])
        before[user['dbId']]=copy.deepcopy(user)
        records.append(dict(email=row['email'],status='created_pending' if row['pendingIdentity'] else 'created_verified',id=user['dbId']))
        on_progress(records)
    return records


def render(plan):
    labels={'new':'Novo','existing':'Existente — preservar','hold':'Pendente — não criar'}
    lines=['# Conferência do cadastro em lote da Integração','',
        'Fonte: '+plan['source']+'. A exportação offline não confirma o estado atual do Neon.',
        'Antes de qualquer cadastro, --check e --apply fazem a leitura atual pela API oficial.',
        'Conta existente não recebe PATCH, nova senha ou alteração de perfil/permissão.',
        'Não há troca obrigatória de senha no primeiro acesso implementada no portal atual.',
        'Nenhuma senha foi gerada nesta conferência. Após autorização, as senhas ficam protegidas por DPAPI, fora do banco em texto puro.','',
        '| Nome | E-mail informado | Situação | Técnico canônico | Pendência/observação |','|---|---|---|---|---|']
    for row in plan['rows']:
        status=labels[row['action']]+(f" ({row['existingId']}, {row['existingRole']})" if row['action']=='existing' else '')
        lines.append('| '+' | '.join([row['name'],row['email'],status,row['technician'] or 'Pendente','; '.join(row['notes']) or 'Identidade confirmada'])+' |')
    lines+=['','Aprovação do plano: `'+plan['approvalDigest']+'`.',
        'Planos offline não são aceitos no apply. Nenhuma ação deste relatório foi executada em produção.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=OUTPUT/'usuarios.json')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check',action='store_true');action.add_argument('--apply',action='store_true');action.add_argument('--show-password',metavar='EMAIL')
    parser.add_argument('--plan',type=Path,default=OUTPUT/'plano_online.json');parser.add_argument('--approve')
    args=parser.parse_args();manifest=load_manifest(args.manifest)
    book_path=args.manifest.parent/('credenciais_'+digest(manifest)[:16]+'.dpapi')
    if args.show_password:
        book=CredentialBook(book_path);entry=book.entries.get(normalized(args.show_password))
        if not entry or entry['status']!='confirmed':raise BatchError('Não há credencial de criação confirmada para esse e-mail.')
        ctypes.windll.user32.MessageBoxW(None,args.show_password+'\n\nSenha inicial: '+entry['password']+'\n\nSolicite a troca pelo menu Trocar Senha no primeiro uso.','Portal BI — credencial individual',0)
        return
    approved=None
    if args.apply:
        approved=json.loads(args.plan.read_text(encoding='utf-8-sig'));verify_plan(approved,args.approve)
    api=Api();email=input('E-mail do administrador do Portal: ').strip();password=getpass.getpass('Senha do administrador (oculta): ')
    initial=api.login(email,password);password=None
    try:
        if args.check:
            plan,_=current_plan(api,manifest,initial);save_json(args.plan,plan)
            args.plan.with_suffix('.md').write_text(render(plan),encoding='utf-8')
            print('Conferência pronta. Nenhuma conta foi criada. Plano: '+str(args.plan))
            print('Identificador para aprovação: '+plan['approvalDigest'])
        else:
            with execution_lock(args.manifest.parent/'cadastro.exec.lock'):
                book=CredentialBook(book_path)
                report=args.manifest.parent/'resultado_execucao.json'
                records=apply_plan(api,manifest,approved,args.approve,book,lambda data:save_json(report,data))
            print('Lote concluído. Conferência: '+str(report))
            print('Credenciais protegidas: '+str(book_path))
            print('Use --show-password EMAIL para visualizar uma credencial confirmada em janela local.')
    finally:api.token=None


if __name__=='__main__':
    try:main()
    except BatchError as error:
        print(str(error),file=sys.stderr);sys.exit(1)
    except (OSError,ValueError,KeyError):
        # Não imprimir corpo HTTP, tokens, senhas, payloads ou traceback de chamadas.
        print('Operação interrompida. Nenhuma conta existente foi sobrescrita. Consulte a conferência/resultado local e não repita envios sem confirmação.',file=sys.stderr)
        sys.exit(1)
