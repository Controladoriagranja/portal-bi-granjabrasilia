# Implantação do seletor de técnico da Integração

A carga de 35 identidades e 177 aliases já foi executada pelo usuário no Neon.
Não repetir a carga inicial, as migrações de estrutura/compatibilidade ou o rollback.
Nada foi executado em produção pelo Codex nesta correção.

## Correção do cadastro

O formulário anterior tentava reconstruir correspondências pelo nome da conta e
mostrava listas por fonte. Agora usa uma identidade canônica já validada no Neon.
O próprio helper `filterAccessLinks` do Comercial foi reaproveitado, mantendo os
parâmetros e comportamento padrão do Comercial. Zootécnico utiliza o mesmo campo
de pesquisa, dropdown simples, seleção automática de resultado único e indicação
do vínculo selecionado. A pesquisa usa os aliases confirmados como texto de busca;
o dropdown exibe somente o nome consolidado, uma vez por identidade.

- Somente seus dados: escolher o técnico uma única vez e salvar.
- Equipe: marcar os usuários do Portal que possuem uma identidade técnica vinculada.
- Todos os dados: manter a autorização geral existente ou concedê-la explicitamente.
- Admin/Diretor continuam gerais. Leandro da Costa Elias (35) e demais contas que
  já têm escopo `todos` continuam com seus acessos; abrir o cadastro não os modifica.

Uma conta chamada Conta de Teste pode selecionar Cristiano. A seleção é explícita:
não precisa ter o mesmo nome do técnico. Contas autorizadas diferentes podem usar
a mesma identidade canônica, sem duplicar o técnico ou seus aliases. Trocar a
seleção altera somente os vínculos dessa conta, nunca renomeia a identidade nem
reescreve seus aliases. O resumo de aliases é recolhível e somente leitura.

## Backend e segurança

O novo payload do formulário (`formVersion: 3`) envia `identityId` ou `userIds`.
O backend verifica se o administrador está autenticado e se a identidade existe,
está ativa e possui aliases confirmados no Neon. Não aceita aliases livres do
navegador nesse fluxo. A versão anterior permanece compatível para não interromper
clientes já publicados, mas não é usada pela nova interface.

Listar, salvar e reabrir não dependem da API especializada ou do Worker. Não há
polling do catálogo nesse formulário. A consulta aos dados do BI continua passando
pela mesma autenticação e pela autorização no servidor, com todos os filtros atuais.
Fonte sem alias validado continua bloqueada, mesmo quando outras fontes da mesma
identidade estão confirmadas. Faltando uma identidade para o usuário/membro da
equipe, pode-se salvar como pendente, sem acesso efetivo a registros.

Equipe utiliza as identidades pessoais dos usuários selecionados; não herda o
acesso geral de um membro Admin/Diretor. Trocas de identidade e bloqueios de membros
são considerados novamente nas requisições. O Comercial e as fórmulas não mudaram.

## SQL incremental

Nenhuma migração é necessária para o seletor ou para vincular usuários.
Cristiano, Joelmir e Mariana já possuem aliases nas seis fontes do catálogo carregado.

Foi preparado apenas o incremento opcional `carga-local/05_aliases_jjc.sql`, com
os dois valores `JJC - JANIO JOSE` em acerto/view, conforme a associação explícita
confirmada pelo usuário nesta solicitação. Usa a identidade existente de Janio,
recusa qualquer alias pertencente a outro técnico ou desativado e não sobrescreve
usuários, vínculos, perfis ou escopos. É transacional e idempotente; não foi executado.
Sem esse incremento, fontes sem o alias de Janio continuam bloqueadas para seu escopo.

A sigla CVB já é pesquisável pelo alias confirmado CVB - CRISTIANO. Não foram
criadas identidades a partir de códigos históricos de galpoes. Essa tabela não é
fonte das quatro consultas protegidas atuais: não foi incluída no filtro nem foi
ampliada a lista de fontes/colunas autorizadas sem necessidade. Os 35 técnicos e
177 aliases existentes foram reaproveitados, sem refazer a carga.

## Arquivos para republicar

- GitHub Pages do Portal: `index.html` e `assets/js/zootecnico-access.js`.
- Render do Portal: `api/zootecnico_access.py`, junto do backend atual.
- API do Anderson, Docker, Worker e frontend dos gráficos: sem alterações nesta etapa.

Publicar o backend do Portal antes dos dois arquivos de frontend. Não trocar
configurações, autenticação, Docker ou variáveis de ambiente.

## Testar depois de publicar

1. Admin → Usuários → criar/editar uma conta comum → perfil Setor → Integração.
2. Dados da Integração → Somente seus dados → pesquisar CVB ou Cristiano e salvar.
3. Reabrir: Cristiano precisa continuar selecionado. Testar também Conta de Teste
   com nome diferente; não é necessário criar uma identidade técnica nova.
4. Entrar nessa conta em outra janela: quatro telas devem consultar somente seus
   registros. Filtros alterados para outro técnico não podem ampliar o acesso.
5. Repetir com Joelmir/JDS e Mariana/MLC. Trocar a identidade e salvar, verificando
   que a autorização mudou sem modificar os aliases ou o nome do técnico.
6. Gerente Setor → Equipe → selecionar os usuários técnicos. Conferir somente a
   união deles; não incluir dados gerais de um membro Diretor/Admin.
7. Admin/Diretor e Leandro: visão geral preservada. Comercial deve continuar igual.

Validação local: 113 testes do Zootécnico/carga/pacote, 15 de regressão comercial
(128 no total) e 31 verificações Chrome com HTTP bloqueado. O Chrome usa o helper
real do Comercial e o catálogo local exportado; os testes de backend usam banco
simulado. Nada foi testado como se fosse login real, SQL real ou deploy em produção.

## Cadastro em lote de usuários

Por preferência do usuário, executar manualmente no SQL Editor do Neon o arquivo
`carga-local/cadastro-usuarios/06_cadastrar_usuarios_integracao.sql`. Ele utiliza
hashes bcrypt compatíveis com o backend e não altera contas existentes. Não exige
Python, terminal ou instalação. O lote permanece ignorado pelo Git. O procedimento
de execução, conferência e entrega de senhas individuais está em
[`tools/CADASTRO_TECNICOS.md`](../../tools/CADASTRO_TECNICOS.md).
Não executar o cadastro sem autorização. Não requer publicação de novos arquivos
do frontend, Worker ou API especializada.

## Nova modificação de 04/11/2026 — Status Acerto

O acesso próprio agora fixa Não Manual. Esta etapa exige atualização da API no
Anderson, do Worker e do frontend BI Zootécnico. Ver
[STATUS_ACERTO_PROPRIO.md](STATUS_ACERTO_PROPRIO.md). Não exige SQL nem atualização
do backend Render do Portal. A indicação anterior de componentes sem alterações
referia-se somente à etapa do seletor de identidade.
