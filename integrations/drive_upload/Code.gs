// Aplicativo da Web executado como proprietário. Somente Drive, nunca planilhas.
const PORTAL_FOLDER_ID = '1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW';
const PORTAL_MAX_BYTES = 10 * 1024 * 1024;

function jsonResponse(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function hex(bytes) {
  return bytes.map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
}

function doPost(e) {
  let lock;
  try {
    if (!e || !e.postData || e.postData.contents.length > 15 * 1024 * 1024) throw new Error('body');
    const secret = PropertiesService.getScriptProperties().getProperty('PORTAL_DRIVE_UPLOAD_SECRET') || '';
    if (secret.length < 32) throw new Error('config');
    const body = JSON.parse(e.postData.contents);
    if (typeof body.payload !== 'string' || !/^\d{10}$/.test(body.timestamp) ||
        Math.abs(Date.now() / 1000 - Number(body.timestamp)) > 300 || !/^[a-f0-9]{64}$/.test(body.signature)) throw new Error('auth');
    const expected = hex(Utilities.computeHmacSha256Signature(body.timestamp + '.' + body.payload, secret));
    let mismatch = 0;
    for (let i = 0; i < 64; i++) mismatch |= expected.charCodeAt(i) ^ body.signature.charCodeAt(i);
    if (mismatch) throw new Error('signature');
    const file = JSON.parse(body.payload);
    if (file.folder !== PORTAL_FOLDER_ID || !/^[a-f0-9]{32}$/.test(file.key) ||
        typeof file.name !== 'string' || !/^[A-Za-z0-9_.-]{1,240}$/.test(file.name) ||
        !Number.isInteger(file.size) || file.size < 1 || file.size > PORTAL_MAX_BYTES ||
        !/^[a-f0-9]{64}$/.test(file.sha256) || typeof file.data !== 'string' ||
        file.data.length > Math.ceil(PORTAL_MAX_BYTES / 3) * 4 ||
        !/^[\w.+-]+\/[\w.+-]+$/.test(file.mime)) throw new Error('file');
    const bytes = Utilities.base64Decode(file.data);
    if (bytes.length !== file.size || hex(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, bytes)) !== file.sha256) throw new Error('digest');
    lock = LockService.getScriptLock();
    if (!lock.tryLock(1000)) return jsonResponse({ok:false, retry:true});
    const folder = DriveApp.getFolderById(PORTAL_FOLDER_ID);
    const matches = folder.getFilesByName(file.name);
    // Nome e hash estáveis permitem recuperar uma resposta HTTP perdida sem duplicar.
    while (matches.hasNext()) {
      const existing = matches.next();
      if (existing.getSize() === file.size) return jsonResponse({ok:true, fileId:existing.getId()});
    }
    const created = folder.createFile(Utilities.newBlob(bytes, file.mime, file.name));
    return jsonResponse({ok:true, fileId:created.getId()});
  } catch (_) {
    // Não devolver dados, nomes, conteúdo ou segredos em erros públicos.
    return jsonResponse({ok:false});
  } finally {
    if (lock && lock.hasLock()) lock.releaseLock();
  }
}

function doGet() {
  return jsonResponse({ok:false});
}
