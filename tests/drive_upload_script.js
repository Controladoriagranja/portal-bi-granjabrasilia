/* Google Apps Script real, somente serviços Google simulados em memória. */
function testDriveUploadScript(source, vm, crypto) {
  let checks=0, writes=0, reads=0;
  const assert=(value,message)=>{if(!value)throw new Error(message);checks++};
  const secret='test-only-not-a-real-secret-0000000000';
  const files=new Map();
  const context=vm.createContext({
    PropertiesService:{getScriptProperties:()=>({getProperty:()=>secret})},
    ContentService:{MimeType:{JSON:'json'},createTextOutput:value=>({setMimeType:()=>JSON.parse(value)})},
    Utilities:{
      computeHmacSha256Signature:(message,key)=>Array.from(crypto.createHmac('sha256',key).update(message).digest()),
      computeDigest:(_,bytes)=>Array.from(crypto.createHash('sha256').update(new Uint8Array(bytes)).digest()),
      DigestAlgorithm:{SHA_256:'sha256'},base64Decode:value=>Array.from(Buffer.from(value,'base64')),
      newBlob:(bytes,mime,name)=>({bytes,mime,name})
    },
    LockService:{getScriptLock:()=>({tryLock:()=>true,hasLock:()=>true,releaseLock:()=>{}})},
    DriveApp:{getFolderById:id=>{
      reads++;assert(id==='1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW','Pasta diferente');
      return {getFilesByName:name=>{
        const matches=files.has(name)?[files.get(name)]:[];
        return {hasNext:()=>matches.length>0,next:()=>matches.pop()};
      },createFile:blob=>{
        writes++;const file={getId:()=> 'mockDriveFile12345',getSize:()=>blob.bytes.length};
        files.set(blob.name,file);return file;
      }};
    }}
  });
  new vm.Script(source).runInContext(context);
  const data=Buffer.from('fixture');
  const file={folder:'1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW',key:'a'.repeat(32),name:'Pessoa_2026-10-30_12-00-00_'+ 'a'.repeat(32)+'_teste.pdf',
    size:data.length,mime:'application/pdf',sha256:crypto.createHash('sha256').update(data).digest('hex'),data:data.toString('base64')};
  const event=(changes={},age=0)=>{
    const timestamp=String(Math.floor(Date.now()/1000)-age),payload=JSON.stringify({...file,...changes});
    return {postData:{contents:JSON.stringify({timestamp,payload,signature:crypto.createHmac('sha256',secret).update(timestamp+'.'+payload).digest('hex')})}};
  };
  const bad=event();const body=JSON.parse(bad.postData.contents);body.signature='0'.repeat(64);bad.postData.contents=JSON.stringify(body);
  assert(context.doPost(bad).ok===false && reads===0,'Envio sem assinatura acessou Drive');
  assert(context.doPost(event({},600)).ok===false && reads===0,'Assinatura vencida acessou Drive');
  assert(context.doPost(event({folder:'outra'})).ok===false && reads===0,'Pasta escolhida pelo cliente');
  assert(context.doPost(event({sha256:'0'.repeat(64)})).ok===false && reads===0,'Conteudo adulterado');
  assert(context.doPost(event({size:10*1024*1024+1})).ok===false && reads===0,'Arquivo acima de 10MB');
  assert(context.doPost(event()).fileId==='mockDriveFile12345' && writes===1,'Arquivo nao gravado');
  assert(context.doPost(event()).fileId==='mockDriveFile12345' && writes===1,'Repeticao duplicou arquivo');
  assert(context.doGet().ok===false && writes===1,'GET gravou arquivo');
  assert(!source.includes('SpreadsheetApp') && !source.includes('setSharing'),'Alterou planilha ou compartilhamento');
  return checks;
}

if(typeof module!=='undefined') {
  module.exports={testDriveUploadScript};
  if(require.main===module) console.log({checks:testDriveUploadScript(
    require('fs').readFileSync(require('path').join(__dirname,'../integrations/drive_upload/Code.gs'),'utf8'),require('vm'),require('crypto'))});
}
