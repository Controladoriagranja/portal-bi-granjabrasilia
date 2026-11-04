# Status Acerto fixo — 04/11/2026

Preparado localmente; não publicado por este trabalho.

Somente usuários cujo escopo efetivo é `proprio`: no Desempenho e nas consultas
relacionadas ao Detalhamento, o Status Acerto é obrigatoriamente **Não Manual**.
O navegador mostra a seleção bloqueada, inclusive após limpar os filtros. A API
substitui parâmetros de status enviados pelo cliente e restringe a fonte oficial
antes de agregar. Mantém os aliases técnicos e as verificações de conflito atuais.
Equipe, acesso geral, Admin/Diretor e demais telas conservam sua política vigente.
Não altera cadastro, permissões do Neon, fórmulas, tabelas ou views.

## Publicação manual

1. Anderson: atualizar somente `zootecnico_acesso.py`, ao lado do serviço atual,
   e reconstruir/reiniciar pelo procedimento existente. O patch incremental
   `backend.patch` é contra o módulo de autorização publicado anteriormente.
   Conferir/aplicar esse patch ao módulo existente preserva mudanças independentes.
   A pasta `referencia` é para revisão; não substituir a API inteira.
2. Cloudflare: publicar `worker/worker.js` mantendo os bindings e secrets atuais.
   Ele apenas expõe o cabeçalho de apresentação enviado pela API.
3. GitHub Pages do BI Zootécnico: publicar os arquivos da pasta `frontend`,
   incluindo as referências de versão nos HTMLs. O Desktop e o painel mobile
   usam o mesmo controlador, sem mudanças de layout.

Não precisa republicar o backend Render do Portal nem executar SQL no Neon/Anderson.
Somente commitar o frontend não publica os componentes do Anderson e do Worker.
Se houver alterações posteriores nos arquivos de produção, comparar os patches
antes de aplicar; não sobrescrever essas alterações.

## Conferência após publicar

- Conta com Somente seus dados: vê apenas seus lotes Não Manual; filtro bloqueado.
- Limpar filtros e abrir o Detalhamento: a regra continua aplicada.
- Alterar URL/requisição para Manual ou remover o status: não amplia o resultado.
- Equipe e acesso geral: filtro permanece editável, incluindo Todos/Manual.
- Repetir em telefone e PC com o mesmo usuário.

Validação local: testes do controlador e transporte JavaScript, middleware de
autorização e composição SQL, com serviços/bancos simulados. Não houve login real,
acesso ao banco de produção ou validação visual em navegador neste trabalho.
