/* Worker real da cópia local em VM; Render/VPC inteiramente simulados. Sem rede. */
async function testZootecnicoWorker(source, vm, web) {
  let checks = 0;
  const check = (condition, message) => { if (!condition) throw new Error(message); checks++; };
  const origin = 'https://controladoriagranja.github.io';
  const bearer = 'Bearer mock-session-only';
  const basic = 'Basic ' + web.btoa('mock-user:mock-password');
  async function run(config = {}) {
    let centralCalls = 0, privateCalls = 0, centralOptions, privateRequest;
    const scope = {
      ...web, console: {error() {throw new Error('O Worker não deve registrar credenciais.');}},
      fetch: async (url, options) => {
        centralCalls++; centralOptions = options;
        check(url === 'https://portal-bi-granjabrasilia.onrender.com/api/auth/me', 'Destino de autenticação fixo');
        if (config.centralThrows) throw new Error('mock failure');
        return new web.Response(config.authBody ?? JSON.stringify(config.authData ?? {ok: true, user: {id: 41, ativo: true, email: 'mock@example.invalid'}}), {status: config.authStatus || 200});
      },
    };
    vm.createContext(scope);
    new vm.Script(source.replace('export default', 'globalThis.worker =')).runInContext(scope);
    const env = {API_USER: 'mock-user', API_PASSWORD: 'mock-password', PRIVATE_API: {fetch: async request => {
      privateCalls++; privateRequest = request;
      if (config.privateThrows) throw new Error('mock failure');
      const status = config.privateStatus || 200;
      return new web.Response(status === 204 ? null : (config.privateBody || '{"ok":true}'), {status, headers: {
        'WWW-Authenticate': 'Basic realm="private"', 'Authorization': basic,
        'X-Portal-Authorization': bearer, 'Set-Cookie': 'mock=private',
        'Vary': 'Accept-Encoding', 'Access-Control-Allow-Origin': '*', ...config.privateHeaders,
      }});
    }}, ...config.env};
    const request = new web.Request('https://api-bi-granja.controladoriagb05.workers.dev' + (config.path || '/api/bi/zootecnico/filtros'), {
      method: config.method || 'GET', headers: {Origin: origin, Authorization: bearer,
        'X-Portal-Authorization': 'Bearer spoofed-identity', Cookie: 'not-needed=mock',
        Referer: origin + '/bi-zootecnico/', ...config.headers}, body: config.body,
    });
    const response = await scope.worker.fetch(request, env);
    return {response, centralCalls, privateCalls, centralOptions, privateRequest};
  }
  for (const [config, status] of [
    [{method:'OPTIONS'},204], [{method:'OPTIONS',headers:{Origin:'https://other.invalid'}},403],
    [{headers:{Origin:'https://other.invalid'}},403], [{path:'/not-api'},404],
    [{headers:{Authorization:''}},401], [{headers:{Authorization:basic}},401],
    [{path:'/api/bi/zootecnico/filtros?access_token=mock-only'},400],
    [{headers:{Authorization:'Bearer '}},401], [{headers:{Authorization:'Bearer '+ 'x'.repeat(4097)}},401],
  ]) {
    const result = await run(config);
    check(result.response.status === status, 'Preflight/origem/rota/autenticação inicial');
    check(result.privateCalls === 0 && result.centralCalls === 0, 'Recusa antes de encaminhar');
  }
  for (const status of [401,403,500,503,302]) {
    const result = await run({authStatus:status});
    check(result.response.status === ([401,403].includes(status) ? status : 503), 'Status da autenticação');
    check(!result.privateCalls, 'Falha de autenticação não atinge a API privada');
    check(result.response.headers.get('Cache-Control') === 'no-store', 'Erros sem cache');
  }
  for (const config of [{centralThrows:true},{authBody:'not json'}]) {
    const result = await run(config);
    check(result.response.status === 503 && !result.privateCalls, 'Autenticação indisponível/JSON inválido');
  }
  for (const user of [{id:41,ativo:false,email:'mock@example.invalid'}, {id:'41',ativo:true,email:'mock@example.invalid'}, {ativo:true,email:'mock@example.invalid'}]) {
    const result = await run({authData:{ok:true,user}});
    check(result.response.status === 401 && !result.privateCalls, 'Identidade ativa e verificável obrigatória');
  }
  const result = await run({path:'/api/bi/zootecnico/filtros?tecnico=OUTRO&role=admin&usuario_id=99'});
  check(result.response.status === 200 && result.privateCalls === 1, 'Proxy autorizado');
  check(result.privateRequest.headers.get('X-Portal-Authorization') === bearer, 'Bearer validado sobrescreve cabeçalho forjado');
  check(result.privateRequest.headers.get('Authorization') === basic, 'Basic somente na conexão privada');
  check(result.centralOptions.headers.Authorization === bearer, 'Render recebe o Bearer original');
  check(result.centralOptions.cache === 'no-store' && result.centralOptions.redirect === 'manual', 'Autenticação sem cache/redirecionamento automático');
  check(result.privateRequest.cache === 'no-store' && result.privateRequest.redirect === 'manual', 'Proxy privado sem cache/redirecionamento automático');
  check(['Origin','Referer','Cookie'].every(key => !result.privateRequest.headers.has(key)), 'Metadados do navegador removidos');
  check(result.privateRequest.url.endsWith('?tecnico=OUTRO&role=admin&usuario_id=99'), 'Filtros preservados, sem usá-los como identidade');
  check(!result.privateRequest.url.includes('mock-session') && !result.privateRequest.url.includes('mock-password'), 'Sem credenciais em URL');
  check(result.response.headers.get('Access-Control-Allow-Origin') === origin, 'CORS permanece restrito');
  check(result.response.headers.get('Cache-Control') === 'no-store', 'Resposta pessoal sem cache');
  check(['Authorization','X-Portal-Authorization','WWW-Authenticate','Set-Cookie'].every(key => !result.response.headers.has(key)), 'Credenciais não voltam ao navegador');
  check(['Accept-Encoding','Origin','Authorization','X-Portal-Authorization'].every(key => result.response.headers.get('Vary').includes(key)), 'Vary preservado/mesclado');
  for (const status of [401,403]) {
    const blocked = await run({privateStatus:status,privateBody:'{"detail":"mock denied"}'});
    check(blocked.response.status === status && !blocked.response.headers.has('WWW-Authenticate'), '401/403 privados sem prompt Basic');
  }
  for (const status of [500,502,503,504]) {
    const failed = await run({privateStatus:status,privateBody:'mock-internal-diagnostic'});
    check(failed.response.status === status, '5xx privado preserva status');
    check(!(await failed.response.text()).includes('mock-internal-diagnostic'), '5xx não expõe diagnóstico interno');
    check(failed.response.headers.get('Cache-Control') === 'no-store', '5xx sem cache');
  }
  check((await run({privateThrows:true})).response.status === 502, 'Falha do binding');
  check((await run({env:{PRIVATE_API:undefined}})).response.status === 502, 'Binding ausente');
  check((await run({env:{API_PASSWORD:''}})).response.status === 500, 'Secret ausente');
  check((await run({privateStatus:302,privateHeaders:{Location:'http://private.invalid'}})).response.status === 502, 'Não encaminhar redirecionamento privado');
  check((await run({privateStatus:204})).response.status === 204, 'Resposta vazia preservada');
  const posted = await run({path:'/api/comercial-html/frete',method:'POST',headers:{'Content-Type':'application/json'},body:'{"mock":1}'});
  check(posted.privateRequest.method === 'POST' && await posted.privateRequest.text() === '{"mock":1}', 'Corpo/método de outros módulos preservados');
  return {checks, network:'mocked', cloudflareRuntime:false, workerReal:false};
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = testZootecnicoWorker;
  if (require.main === module) {
    const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
    const source = fs.readFileSync(path.join(__dirname,'../integrations/zootecnico/worker/worker.js'),'utf8');
    // Shim só do teste: Node exige duplex para streams; Workers não usa esta opção.
    class OfflineRequest extends Request {constructor(input,init={}) {super(input,{...init,...(init.body && typeof init.body==='object' ? {duplex:'half'} : {})});}}
    testZootecnicoWorker(source,vm,{URL,Headers,Request:OfflineRequest,Response,TextEncoder,btoa,Date})
      .then(result => console.log(JSON.stringify(result)))
      .catch(error => {console.error(error);process.exitCode=1;});
  }
}
