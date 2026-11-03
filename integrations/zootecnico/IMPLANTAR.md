# Implantação — acesso por técnico

Código preparado localmente. Nada publicado, nenhum SQL executado pelo Codex.
Os campos obrigatórios foram confirmados pelo usuário no PostgreSQL real.
O usuário também confirmou `api_zootecnico(3).zip` como a versão vigente do Anderson.
`candidatos_tecnico` não existe na view e permanece opcional, via JSON/COALESCE.
Mesma sessão assinada e ponte Bearer/Basic já usadas pelo Comercial; sem novo login.
Perfil Admin/Diretor continua geral. Comercial, layout, fórmulas, views e ETL preservados.
Validação final local: 38 testes de autorização, 10 de builders/middleware,
15 de regressão, 3 do pacote/seed e 94 verificações do Worker em VM aprovados.
Nenhum teste executou SQL real ou publicou código.

## 1. Neon

Executar manualmente, nesta ordem:

1. `api/migrations/20261103_zootecnico_access.sql`, uma única vez. Cria só as
   tabelas de escopos/vínculos/entidades/aliases; não altera usuários nem senhas.
2. `api/migrations/20261103_zootecnico_tecnico_teste.sql`, depois de preencher o
   JSON inicial com nome, e-mail de uma conta comum ativa e aliases EXATOS.

**Cadastro do técnico de teste adiado por solicitação do usuário. Não executar o
segundo arquivo agora.** O JSON permanece vazio e protegido contra gravação.

Para a conta de teste, usar a tela existente de Usuários para criar a senha e
escolher perfil Setor. Preferir liberação específica do relatório Bi - Integração.
O segundo SQL vincula a conta existente e libera relatório 13 ou setor 4 conforme
o modo já escolhido, sem modificar esse modo nem permissões do Comercial.
Ele recusa Admin/Diretor, conta bloqueada, alias pertencente a outro técnico e
substituição de vínculo existente. A execução repetida com os mesmos dados é segura.

**Dados ainda necessários para preencher o SQL:** nome/e-mail do técnico de teste;
valores de `tecnico` em `vw_desempenho_acerto_portal`, `base_dinamica`,
`mortalidade_peso_abertos`, `vw_historico_lotes_criacao_portal` e nas auxiliares
`acerto_lote_resultado_geral`/`mortalidade_peso_fechados`. Na view do portal, incluir
também `tecnico_exibicao` se diferente. Nenhum valor foi deduzido de siglas.
Enquanto esses dados não forem confirmados, o SQL para antes de qualquer INSERT.
Não reenviar resultados de metadados nem executar novos diagnósticos para esta entrega.

## 2. Render e GitHub Pages

- **Render, backend do Portal:** publicar `api/app.py` e `api/zootecnico_access.py`
  junto da versão atual do backend. Não há nova variável de ambiente/dependência.
- **GitHub Pages, portal-bi-granjabrasilia:** `index.html` e
  `assets/js/zootecnico-access.js`.
- **GitHub Pages, bi-zootecnico:** `assets/js/api.js` já alterado naquele repositório.
  Preservar as demais alterações locais; não substituir gráficos ou HTMLs antigos.

## 3. Cloudflare

Código final: `integrations/zootecnico/worker/worker.js`.
Manter o Worker existente, binding `PRIVATE_API`, secrets `API_USER/API_PASSWORD`
e destino privado vigente. Não criar outro mecanismo de login ou serviço.
O Bearer fica em `X-Portal-Authorization` no proxy; Authorization privado fica Basic.
Não colocar credenciais em URLs nem no frontend.

## 4. Anderson

Enviar `integrations/zootecnico/entrega/api_zootecnico_atualizada.zip`.
Mantém a estrutura COMPLETA recebida, com pasta raiz `api_zootecnico/`, todos os
arquivos originais e apenas as três alterações/um módulo novo necessários.
O link anterior `Acesso_Tecnico_Zootecnico_Anderson.zip` contém o mesmo ZIP corrigido.
Os arquivos ajustados são:

- `servico_zootecnico.py`;
- `portal_router.py`;
- `Dockerfile.zootecnico`;
- novo `zootecnico_acesso.py`.

Os quatro arquivos incorporam a integração sobre a versão vigente confirmada.
O Dockerfile principal é idêntico ao original. O Dockerfile.zootecnico é o original
com somente um COPY adicional; não há outra imagem, porta, CMD ou projeto Docker.
Configurações e demais arquivos são conservados byte a byte; o ZIP completo fica
ignorado pelo Git para conservar essa entrega somente localmente.
Se houver alterações posteriores ao ZIP confirmado, aplicar o patch por trechos
nessa cópia mais recente; não substituir por arquivos inteiros nem forçar conflitos.
O teste local do patch preservou acréscimos posteriores fora dos trechos alterados.

## 5. Ordem e teste

1. Migração Neon; publicar backend Render e Portal.
2. Publicar Worker antes de ativar a API que exige o cabeçalho.
3. Anderson integrar/reconstruir o serviço atual; publicar api.js do BI.
4. Criar/usar a conta comum de teste e executar o SQL preenchido de vínculo.
5. Só depois iniciar os testes de acesso e liberar técnicos reais.

Entrar com a conta comum em janela separada: abrir as quatro telas, conferir
galpões, indicadores, filtros e detalhes; procurar um técnico diferente deve
retornar vazio ou recusa, nunca ampliar o conjunto. RxP exige geral.
Entrar com Admin ou Diretor: conferir a visão geral e os relatórios do Comercial.
Alterar/revogar o vínculo e repetir uma consulta para confirmar efeito imediato.
O teste final com registros reais é manual; testes locais não são evidência de produção.
