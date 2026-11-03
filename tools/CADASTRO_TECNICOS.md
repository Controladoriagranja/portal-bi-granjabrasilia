# Cadastro em lote da Integração — SQL Editor do Neon

O procedimento principal agora é um único SQL; não exige Python, terminal ou
instalação de dependências.

## Arquivo pronto

`integrations/zootecnico/carga-local/cadastro-usuarios/06_cadastrar_usuarios_integracao.sql`

O arquivo contém os 15 nomes/e-mails confirmados e suas identidades canônicas.
Joelmir está com `jdivino@granjabrasilia.com.br`. As quatro diferenças de acentos
foram confirmadas pelo usuário. A pasta do lote já é ignorada pelo Git.

## Executar manualmente, somente quando autorizar a carga

1. Abra o arquivo SQL e copie todo o conteúdo.
2. No SQL Editor do Neon, selecione `portal-bi-granjabrasilia` e a branch correta
   usada pelo Portal. Não execute em uma branch de teste esperando alterar produção.
3. Execute o conteúdo inteiro, incluindo `BEGIN`, bloco `DO`, `COMMIT` e o `SELECT`
   final. Não execute somente trechos.
4. Confira que o `COMMIT` terminou sem erros. O último resultado mostra os 15
   usuários, situação, perfil, setor, relatório, escopo, vínculos e fontes sem alias.
5. Salve as senhas iniciais mostradas para as contas novas e entregue cada senha
   individualmente ao respectivo usuário. Não compartilhe a tabela completa.
6. Peça que alterem a senha pelo menu Trocar Senha no primeiro acesso. O Portal
   atual não suporta troca obrigatória nem expiração da senha inicial.

## O que o SQL faz

- Gera senhas individuais aleatórias dentro do Neon e grava somente hashes bcrypt
  permanentes, usando o mesmo `crypt(senha, gen_salt('bf', 12))` do backend.
- Confere o hash pela mesma função utilizada no login.
- Cria apenas contas inexistentes por e-mail, comparando sem distinguir maiúsculas.
- Para novos: `role='sector'`, `perfil='usuario'` (Setor no formulário), Integração
  4, relatório 13 específico, sem permissão comercial/administrativa e acesso próprio.
- Grava os dois pares de escopo/vínculo que o formulário canônico v3 utiliza:
  `zootecnico_identidade` e `zootecnico`, ambos `proprio`.
- Usa exclusivamente identidades/aliases existentes. Não altera o catálogo.
- Pula integralmente contas existentes; não corrige vínculos ou senhas delas.
  Lucas (42) precisa existir com o e-mail conhecido e permanece inalterado.
- Em possível duplicidade por nome completo/e-mail alternativo, ou identidade
  divergente, cancela todo o lote para conferência.
- Compara os registros dos usuários anteriores antes de confirmar a transação.

Apenas tabelas temporárias da conexão são utilizadas para a conferência e a
entrega das senhas. Nenhuma senha é escrita no arquivo SQL nem em tabela permanente
em texto puro. Elas aparecem no resultado final após o `COMMIT` e podem permanecer
visíveis na interface do Editor; guarde-as para entrega individual antes de fechar.

## Falhas e reexecução

Qualquer erro cancela a transação inteira, sem cadastros parciais confirmados.
Se o Editor indicar transação abortada, execute `ROLLBACK;`, confira a mensagem e
só então repita o arquivo inteiro. Não há captura que esconda erros nem `COMMIT`
parcial por usuário.

A reexecução pula todas as contas já existentes e não redefine ou revela novamente
as senhas. Se perder o resultado, use o fluxo administrativo de redefinição do
Portal; não apague contas para tentar recuperar as senhas deste lote.

Há bloqueios transacionais curtos contra alterações concorrentes. Login e leituras
continuam permitidos; outras escritas podem aguardar. `lock_timeout` de 2 segundos
cancela o lote quando há disputa de bloqueio, sem deixar alterações confirmadas.

Fontes sem alias validado continuam bloqueadas para usuários restritos. A coluna
final mostra ausências da identidade planejada; isso não retira o acesso geral de
um Diretor/Admin existente. Posteriormente, Equipe/Todos os dados são configuráveis
pelo formulário normal, como antes.

## Validação e publicação

Compatibilidade conferida no código de cadastro/login e nas estruturas de escopo
e vínculo do backend. Conferência estática: 15 entradas idênticas ao manifesto e
15 nomes/IDs idênticos ao catálogo fornecido, sem UPDATE/DELETE/ALTER em tabelas
permanentes. O SQL não foi executado em PostgreSQL real nem validado por parser
PostgreSQL local nesta entrega. As verificações internas rodarão na execução manual.

Não é necessário republicar frontend, Worker ou API para trocar o executor por SQL.
A publicação do backend canônico preparada anteriormente continua sendo um requisito
para o formulário de seleção de identidades. Não houve deploy ou carga automática.
O executor Python anterior foi preservado, mas não é necessário neste procedimento.
