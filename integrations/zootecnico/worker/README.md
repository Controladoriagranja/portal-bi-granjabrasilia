# Worker da Integração — correção local, NÃO PUBLICADA

## Origem e limite da auditoria

Endpoint configurado no frontend (`bi-zootecnico/assets/js/config.js`):
`https://api-bi-granja.controladoriagb05.workers.dev`.

Não foi localizado um projeto implantável atual do Worker nos repositórios
pesquisados em `Documents/GitHub`: sem `wrangler.toml`, `wrangler.jsonc`, identificador
do binding ou entrypoint atual. O teste antigo `bi-zootecnico/tests/worker-diagnostics.cjs`
depende de `outputs/worker-diagnostico/worker.js`, arquivo ausente; esse teste não
foi considerado aprovado nem substituído silenciosamente.

Foi localizada uma **cópia histórica fornecida em anexo**, referenciada por
`BI-PCP/tools/preparar_worker_diagnostico.py`:

```text
C:/Users/vchaves/.codex/attachments/00fda2bc-11f0-475a-a2b6-4f8eb757546b/Pasted text.txt
Data do arquivo: 08/10/2026
SHA256 bruto: 0FBCA77421F521197ED467BA93893F7B32F97C0B3E1C45ED47B8885CDA3A439C
```

O preparador NÃO foi executado. O anexo original não foi alterado. `worker.js`
é uma cópia dessa fonte com correções pontuais. O diff está em
`contra_fonte_historica.patch`. **Não certifica o código publicado atualmente.**
Não substituir o Worker atual por esta versão antiga sem comparar seu entrypoint
vigente; funcionalidades posteriores à fonte histórica podem existir.

## Contrato e auditoria

| Item | Fonte histórica | Candidato local |
|---|---|---|
| Identidade do navegador | `Authorization: Bearer` validado no Render `/api/auth/me` | Mantido; exige usuário ativo e ID válido |
| Autenticação privada | Substitui Authorization por Basic com `API_USER/API_PASSWORD` | Mantida somente no lado servidor |
| Identidade para a API | NÃO define `X-Portal-Authorization`; uma cópia enviada pelo cliente poderia permanecer | Define/sobrescreve com o mesmo Bearer validado, sem aceitar identidade forjada |
| Proxy | `env.PRIVATE_API.fetch(proxyRequest)` | Binding privado preservado; nenhum fetch público substitui a conexão privada |
| Origem CORS | Só `https://controladoriagranja.github.io` | Preservada; não autoriza X-Portal-Authorization no navegador |
| Métodos CORS | GET/POST/PUT/PATCH/DELETE/OPTIONS | Preservados para outros módulos |
| Cache | Resposta `no-store`, sem Cache API no código | Também no-store nos subrequests, Vary mesclado; configuração externa continua pendente |
| Erros de autenticação | 401 preservado; 403 convertido em 503; JSON inválido escapava | 401/403 preservados; 5xx/falha/JSON inválido retornam erro controlado sem chegar à API privada |
| Erros privados | Status/corpo retornados, WWW-Authenticate removido | 401/403 preservados; 5xx preservam status com corpo genérico; falha do binding retorna 502 |
| Redirecionamentos | Proxy manual, mas retorno podia apontar ao endereço privado | Autenticação/proxy manuais; redirecionamento privado é recusado com 502 |
| Retorno de credenciais | Remove só WWW-Authenticate | Também remove Authorization, X-Portal-Authorization e Set-Cookie do retorno |
| Corpo/URL de negócio | Mantém caminho/query/body/método | Preservados; parâmetros explícitos de token na URL são recusados |

Problema confirmado **na fonte histórica**: a nova API recebe Basic, mas fica sem
o Bearer necessário para `/api/auth/zootecnico-access`. O candidato corrige esse
contrato. Não há prova de que o Worker publicado ainda possua esse problema.

```text
Navegador -> Authorization: Bearer <sessão>
Worker -> Render /api/auth/me: Authorization: Bearer <mesma sessão>
Worker -> PRIVATE_API:
   Authorization: Basic <credencial privada>
   X-Portal-Authorization: Bearer <mesma sessão validada>
API -> Render /api/auth/zootecnico-access: Authorization: Bearer <mesma sessão>
```

Nenhum token em URL, segundo login, cache de permissões ou novo serviço. Cookies
do navegador não são necessários para a autenticação privada e não são encaminhados.
Nenhuma credencial real foi lida, embutida ou registrada.

## Configuração que precisa ser conferida no Cloudflare

- Binding existente `PRIVATE_API`, com método `fetch`, apontando para a API
  especializada/porta de `servico_zootecnico:app`. O ID e o tipo real do binding
  não estão disponíveis nesta cópia. Não inventar IDs nem criar infraestrutura nova.
- Secrets existentes `API_USER` e `API_PASSWORD`, sem copiar valores para Git,
  navegador, documentação ou conversa.
- Constantes de origem, autenticação e destino privado preservadas da fonte
  histórica. O destino privado também precisa ser comparado à configuração atual.
- `main`/entrypoint, `compatibility_date`, rotas/domínio e regras de cache atuais:
  não estão no workspace. Não foi criado um wrangler fictício.
- Confirmar que não há regra externa/Workers Cache servindo `/api/*` antes da
  execução da autorização, nem Cache API/KV de respostas pessoais em outra versão.
  `no-store` no código candidato não comprova a configuração publicada.

**Material que falta para fechar a validação:** exportação do código do Worker
`api-bi-granja` atualmente publicado (entrypoint indicado por `main` ou código do
editor Cloudflare), seu wrangler/configuração equivalente SEM valores de secrets,
e metadados do binding `PRIVATE_API`. O nome do repositório original não foi
identificado; não presumir que este diretório seja aquele repositório.

## Testes e documentação do runtime

`tests/zootecnico_worker.js`: 94 verificações em VM Node, fetch do Render e binding
privado totalmente simulados. Sem conexão ao Worker real, sem runtime Cloudflare,
sem validar a configuração dos secrets/binding existentes. Inclui POST de outro
módulo para verificar preservação de método/corpo.

Quando Node com Fetch API já estiver instalado:

```powershell
node tests/zootecnico_worker.js
```

Nesta etapa foi executado pela VM Node disponível nas ferramentas; não houve
instalação de Node/dependências nem publicação. O shim `duplex` existe somente no
teste para a diferença do runtime Node ao construir requests com corpo em stream.

As opções usadas foram conferidas na documentação oficial:
[Request](https://developers.cloudflare.com/workers/runtime-apis/request/) e
[Fetch](https://developers.cloudflare.com/workers/runtime-apis/fetch/).
Foi usado `redirect: manual`; Workers não implementa `redirect: error`. Para o
binding existente, consultar [Workers VPC Binding API](https://developers.cloudflare.com/workers-vpc/api/).
As regras externas precisam ser conferidas conforme
[Workers Cache](https://developers.cloudflare.com/workers/cache/).
