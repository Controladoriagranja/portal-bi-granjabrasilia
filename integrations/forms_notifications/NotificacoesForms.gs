/** @OnlyCurrentDoc */
// Projeto vinculado à planilha. Separado do aplicativo de upload do Drive.
const AVISO_FORMS_PLANILHA = '1mCLD88B_986zsZ16aDEFMK2RNhXKafMfuB99wWebe9k';
const AVISO_FORMS_REMETENTE = 'controladoriagb05@gmail.com';
const AVISO_FORMS_DESTINATARIOS = [
  'asalvino@granjabrasilia.com.br',
  'bantunes@granjabrasilia.com.br',
  'vchaves@granjabrasilia.com.br'
];
const AVISO_FORMS_HISTORICO = 'avisos_forms_ultimos_100_v1';
// A–O. A coluna P foi excluída por solicitação do usuário.
const AVISO_FORMS_CABECALHOS = [
  'Carimbo de data/hora', 'Nome', 'E-mail', 'Telefone', 'Setor', 'Tipo de Solicitação',
  'Em qual BI e tela será o ajuste', 'Selecione o tipo de ajuste',
  'Descreva brevemente o ajuste necessário', 'Adicione anexos do Ajuste',
  'Em qual BI e tela será a melhoria', 'Descreva brevemente a melhoria',
  'Nome Completo do usuário', 'E-mail', 'Quais relatórios o usuário terá acesso?'
];
const AVISO_FORMS_SECOES = {
  ajuste: [[6,'BI / tela'],[7,'Tipo de ajuste'],[8,'Descrição'],[9,'Anexos informados']],
  melhoria: [[10,'BI / tela'],[11,'Descrição']],
  'novo usuario': [[12,'Nome do novo usuário'],[13,'E-mail do novo usuário'],[14,'Relatórios solicitados']]
};

function avisoFormsNormalizar(valor) {
  return String(valor || '').trim().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').toLowerCase();
}

function avisoFormsValidarConta() {
  if (String(Session.getEffectiveUser().getEmail()).trim().toLowerCase() !== AVISO_FORMS_REMETENTE) {
    throw new Error('Configure e autorize este projeto usando a conta ' + AVISO_FORMS_REMETENTE + '.');
  }
}

function avisoFormsValidarCabecalhos(aba) {
  const headers = aba.getRange(1,1,1,AVISO_FORMS_CABECALHOS.length).getDisplayValues()[0];
  if (!AVISO_FORMS_CABECALHOS.every((nome,i)=>avisoFormsNormalizar(headers[i])===avisoFormsNormalizar(nome))) {
    throw new Error('Os cabeçalhos A–O não correspondem ao mapeamento. Confira a aba de respostas antes de ativar os avisos.');
  }
}

// Executar UMA vez no editor para autorizar e instalar. Não envia e-mails nem lê respostas antigas.
function configurarAvisosForms() {
  avisoFormsValidarConta();
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  if (!planilha || planilha.getId()!==AVISO_FORMS_PLANILHA) {
    throw new Error('Abra a planilha de respostas e use Extensões → Apps Script.');
  }
  const respostas = planilha.getSheets().filter(aba=>!!aba.getFormUrl());
  if (respostas.length!==1) throw new Error('A planilha deve ter uma única aba vinculada ao Forms para esta configuração.');
  avisoFormsValidarCabecalhos(respostas[0]);
  const existentes = ScriptApp.getProjectTriggers().filter(t=>
    t.getHandlerFunction()==='avisarNovaSolicitacaoForms' &&
    t.getEventType()===ScriptApp.EventType.ON_FORM_SUBMIT &&
    t.getTriggerSourceId()===AVISO_FORMS_PLANILHA);
  if (!existentes.length) {
    ScriptApp.newTrigger('avisarNovaSolicitacaoForms').forSpreadsheet(planilha).onFormSubmit().create();
  }
  const saldo = MailApp.getRemainingDailyQuota();
  console.log('Avisos configurados. Saldo de destinatários hoje: ' + saldo + '. Nenhum e-mail foi enviado pela configuração.');
}

function avisoFormsEscapar(valor) {
  return String(valor).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Layout provisório: dados iniciais + SOMENTE a seção escolhida em F.
function montarAvisoForms(valores) {
  const campo = i=>String(valores[i] || '').trim();
  const tipo = campo(5);
  const secao = AVISO_FORMS_SECOES[avisoFormsNormalizar(tipo)];
  if (!secao) throw new Error('Tipo de solicitação não reconhecido. Nenhum aviso enviado.');
  const campos = [
    ['Autor',campo(1)],['E-mail do solicitante',campo(2)],['Telefone',campo(3)],
    ['Setor',campo(4)],['Tipo',tipo],['Data/hora',campo(0)]
  ];
  secao.forEach(([i,nome])=>{if(campo(i)) campos.push([nome,campo(i)]);});
  const subject = ('[Portal BI] Nova solicitação — ' + tipo + ' — ' + campo(4)).replace(/[\r\n]+/g,' ').slice(0,180);
  const body = 'Nova solicitação de Dados & Power BI\n\n' + campos.map(([nome,valor])=>nome+': '+(valor||'Não informado')).join('\n\n');
  const htmlBody = '<div style="font:14px Arial,sans-serif;color:#08243b;max-width:640px">' +
    '<div style="border-bottom:3px solid #c0392b;padding:12px 0;font-size:19px;font-weight:bold">Nova solicitação de Dados &amp; Power BI</div>' +
    '<table style="width:100%;border-collapse:collapse;margin-top:12px">' + campos.map(([nome,valor])=>
      '<tr><th style="text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #e5e7eb">'+avisoFormsEscapar(nome)+'</th>' +
      '<td style="padding:9px;border-bottom:1px solid #e5e7eb;white-space:pre-wrap;overflow-wrap:anywhere">'+avisoFormsEscapar(valor||'Não informado')+'</td></tr>').join('') + '</table></div>';
  return {subject,body,htmlBody};
}

// Gatilho instalável: Da planilha → Ao enviar formulário. Não executar manualmente.
function avisarNovaSolicitacaoForms(e) {
  if (!e || !e.triggerUid || !e.range || !Array.isArray(e.values) || e.values.length<6) {
    throw new Error('Esta função recebe um envio real do Forms. Para instalar, execute configurarAvisosForms.');
  }
  avisoFormsValidarConta();
  const aba = e.range.getSheet();
  if (aba.getParent().getId()!==AVISO_FORMS_PLANILHA || !aba.getFormUrl() || e.range.getRow()<2 || e.range.getNumRows()!==1) {
    throw new Error('Origem do envio não permitida.');
  }
  avisoFormsValidarCabecalhos(aba);
  const mensagem = montarAvisoForms(e.values);
  const origem = JSON.stringify([AVISO_FORMS_PLANILHA,aba.getSheetId(),e.range.getRow(),String(e.values[0])]);
  const chave = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,origem)
    .map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const props = PropertiesService.getScriptProperties();
    const historico = JSON.parse(props.getProperty(AVISO_FORMS_HISTORICO)||'[]');
    if (!Array.isArray(historico)) throw new Error('Controle dos avisos inválido. Confira as propriedades do projeto.');
    if (historico.includes(chave)) return;
    if (MailApp.getRemainingDailyQuota()<AVISO_FORMS_DESTINATARIOS.length) {
      throw new Error('Saldo diário insuficiente para os três destinatários. Nenhum aviso enviado para esta resposta.');
    }
    MailApp.sendEmail({to:AVISO_FORMS_DESTINATARIOS.join(','),name:'Portal BI — Granja Brasília',...mensagem});
    props.setProperty(AVISO_FORMS_HISTORICO,JSON.stringify([...historico,chave].slice(-100)));
  } finally {
    lock.releaseLock();
  }
}
