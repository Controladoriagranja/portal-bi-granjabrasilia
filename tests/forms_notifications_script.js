/* Apps Script real em VM; Gmail, planilha, propriedades e gatilhos simulados. */
function testFormsNotifications(source, vm, crypto) {
  let checks=0;
  const assert=(value,message)=>{if(!value)throw new Error(message);checks++};
  const spreadsheetId='1mCLD88B_986zsZ16aDEFMK2RNhXKafMfuB99wWebe9k';
  const headers=['Carimbo de data/hora','Nome','E-mail','Telefone','Setor','Tipo de Solicitação',
    'Em qual BI e tela será o ajuste','Selecione o tipo de ajuste','Descreva brevemente o ajuste necessário',
    'Adicione anexos do Ajuste','Em qual BI e tela será a melhoria','Descreva brevemente a melhoria',
    'Nome Completo do usuário','E-mail','Quais relatórios o usuário terá acesso?'];
  const mails=[],triggers=[],props=new Map();let account='controladoriagb05@gmail.com',quota=100,locked=false;
  let activeId=spreadsheetId,brokenHeaders=false;
  const sheet={getFormUrl:()=> 'https://docs.google.com/forms/test-only',getParent:()=>spreadsheet,
    getSheetId:()=>0,getRange:(row,column,rows,columns)=>{
      assert(row===1&&column===1&&rows===1&&columns===15,'Leu respostas antigas ou a coluna P');
      return {getDisplayValues:()=>[brokenHeaders?['coluna alterada']:headers]};
    }};
  const spreadsheet={getId:()=>activeId,getSheets:()=>[sheet]};
  const lock={waitLock:ms=>{assert(ms<=20000,'Espera sem limite');locked=true},releaseLock:()=>{locked=false}};
  const context=vm.createContext({
    console:{log:()=>{}},Session:{getEffectiveUser:()=>({getEmail:()=>account})},
    SpreadsheetApp:{getActiveSpreadsheet:()=>spreadsheet},
    ScriptApp:{EventType:{ON_FORM_SUBMIT:'submit'},getProjectTriggers:()=>triggers,
      newTrigger:handler=>({forSpreadsheet:value=>{
        assert(value===spreadsheet,'Gatilho em outra planilha');
        return {onFormSubmit:()=>({create:()=>{
          triggers.push({getHandlerFunction:()=>handler,getEventType:()=> 'submit',getTriggerSourceId:()=>spreadsheetId});
        }})};
      }})},
    MailApp:{getRemainingDailyQuota:()=>quota,sendEmail:mail=>{
      assert(locked,'Enviou sem proteger duplicacao');mails.push(mail);quota-=3;
    }},
    Utilities:{DigestAlgorithm:{SHA_256:'sha256'},computeDigest:(_,value)=>Array.from(crypto.createHash('sha256').update(value).digest())},
    PropertiesService:{getScriptProperties:()=>({getProperty:key=>props.get(key)||null,setProperty:(key,value)=>props.set(key,value)})},
    LockService:{getScriptLock:()=>lock}
  });
  new vm.Script(source).runInContext(context);
  const values=type=>['30/10/2026 15:30:00','Autor Teste','autor@example.invalid','1234','TI',type,
    'BI-AJUSTE','CALCULO-AJUSTE','DESCRICAO-AJUSTE','ANEXOS-AJUSTE',
    'BI-MELHORIA','DESCRICAO-MELHORIA','PESSOA-NOVA','novo@example.invalid','RELATORIOS-NOVOS','COLUNA-P-EXCLUIDA'];
  const event=(type,row)=>({triggerUid:'trigger-test',values:values(type),range:{getSheet:()=>sheet,getRow:()=>row,getNumRows:()=>1}});
  const fails=(fn,message)=>{let failed=false;try{fn()}catch(_){failed=true}assert(failed,message)};

  context.configurarAvisosForms();context.configurarAvisosForms();
  assert(triggers.length===1,'Configuracao duplicou gatilho');
  assert(mails.length===0,'Configuracao enviou historico/email');
  account='outra-conta@example.invalid';
  fails(()=>context.configurarAvisosForms(),'Aceitou remetente diferente');
  fails(()=>context.avisarNovaSolicitacaoForms(event('Ajuste',2)),'Enviou usando outra conta');
  assert(mails.length===0,'Remetente incorreto enviou mensagem');
  account='controladoriagb05@gmail.com';
  activeId='outra-planilha';fails(()=>context.configurarAvisosForms(),'Aceitou outra planilha');activeId=spreadsheetId;
  fails(()=>context.avisarNovaSolicitacaoForms(),'Execucao manual enviou mensagem');
  fails(()=>context.avisarNovaSolicitacaoForms({...event('Ajuste',2),triggerUid:undefined}),'Aceitou evento de edicao');

  const ajuste=event('Ajuste',2);context.avisarNovaSolicitacaoForms(ajuste);
  assert(mails.length===1,'Ajuste sem aviso');
  assert(mails[0].to==='asalvino@granjabrasilia.com.br,bantunes@granjabrasilia.com.br,vchaves@granjabrasilia.com.br','Destinatarios incorretos');
  assert(mails[0].body.includes('Autor: Autor Teste')&&mails[0].body.includes('autor@example.invalid'),'Autor nao veio de B/C');
  assert(mails[0].body.includes('BI-AJUSTE')&&mails[0].body.includes('CALCULO-AJUSTE')&&mails[0].body.includes('DESCRICAO-AJUSTE')&&mails[0].body.includes('ANEXOS-AJUSTE'),'Ajuste nao usou G-J');
  assert(!mails[0].body.includes('BI-MELHORIA')&&!mails[0].body.includes('novo@example.invalid'),'Ajuste vazou outra secao');
  context.avisarNovaSolicitacaoForms(ajuste);assert(mails.length===1,'Evento repetido duplicou e-mail');
  context.avisarNovaSolicitacaoForms(event('Melhoria',3));
  assert(mails[1].body.includes('BI-MELHORIA')&&mails[1].body.includes('DESCRICAO-MELHORIA'),'Melhoria nao usou K-L');
  assert(!mails[1].body.includes('BI-AJUSTE')&&!mails[1].body.includes('PESSOA-NOVA')&&!mails[1].body.includes('ANEXOS-AJUSTE'),'Melhoria usou outra secao');
  context.avisarNovaSolicitacaoForms(event('Novo usuário',4));
  assert(mails[2].body.includes('PESSOA-NOVA')&&mails[2].body.includes('novo@example.invalid')&&mails[2].body.includes('RELATORIOS-NOVOS'),'Novo usuario nao usou M-O');
  assert(mails[2].body.includes('E-mail do solicitante: autor@example.invalid')&&mails[2].body.includes('E-mail do novo usuário: novo@example.invalid'),'Confundiu os dois E-mails');
  assert(mails.every(mail=>!mail.body.includes('COLUNA-P-EXCLUIDA')&&!mail.htmlBody.includes('COLUNA-P-EXCLUIDA')),'Coluna P apareceu no email');
  assert(mails.every(mail=>!Object.hasOwn(mail,'replyTo')&&!Object.hasOwn(mail,'from')),'Usou identidade autodeclarada como remetente');

  const hostile=values('Melhoria');hostile[1]='<img src=x onerror=alert(1)>';hostile[11]='<script>alert(1)</script>';
  const safe=context.montarAvisoForms(hostile);
  assert(!safe.htmlBody.includes('<img')&&!safe.htmlBody.includes('<script>')&&safe.htmlBody.includes('&lt;img'),'HTML informado no Forms nao foi escapado');
  quota=2;fails(()=>context.avisarNovaSolicitacaoForms(event('Ajuste',5)),'Ignorou cota diaria');
  assert(mails.length===3&&!locked,'Cota baixa enviou ou reteve lock');quota=100;
  context.avisarNovaSolicitacaoForms(event('Ajuste',5));assert(mails.length===4,'Cota baixa marcou email como enviado');
  brokenHeaders=true;fails(()=>context.avisarNovaSolicitacaoForms(event('Melhoria',6)),'Cabecalhos diferentes foram aceitos');brokenHeaders=false;
  fails(()=>context.avisarNovaSolicitacaoForms(event('Outro tipo',6)),'Tipo desconhecido enviado');
  assert(mails.length===4,'Evento invalido enviou email');
  const historyKey=[...props.keys()][0];props.set(historyKey,JSON.stringify(Array.from({length:100},(_,i)=>String(i).padStart(64,'0'))));
  context.avisarNovaSolicitacaoForms(event('Melhoria',7));
  assert(JSON.parse(props.get(historyKey)).length===100&&props.get(historyKey).length<9000,'Historico excedeu propriedade Google');
  assert(!/\.setValues?\(|\.appendRow\(|\.insertRows?\(|UrlFetchApp|Jdbc|GmailApp/.test(source),'Alterou celulas, consultou servicos externos ou pediu acesso a caixa postal');
  return {checks,previewHtml:context.montarAvisoForms(values('Melhoria')).htmlBody};
}

if(typeof module!=='undefined') {
  module.exports={testFormsNotifications};
  if(require.main===module){
    const fs=require('fs'),path=require('path');
    const result=testFormsNotifications(fs.readFileSync(path.join(__dirname,'../integrations/forms_notifications/NotificacoesForms.gs'),'utf8'),require('vm'),require('crypto'));
    console.log({checks:result.checks});
  }
}
