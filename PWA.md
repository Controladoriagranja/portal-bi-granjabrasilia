# PWA — Portal BI Granja Brasília

## Estrutura e implantação

O frontend de produção é `index.html` na raiz. O remoto do repositório é
`Controladoriagranja/portal-bi-granjabrasilia`; não há CNAME nem workflow de Pages
versionado. A URL padrão de projeto é:
https://controladoriagranja.github.io/portal-bi-granjabrasilia/
A configuração ativa do GitHub Pages deve ser conferida nas configurações do repositório.

`manifest.webmanifest` usa `id`, `start_url` e `scope` iguais a `./`, resolvidos
relativamente ao manifesto. Assim, funciona tanto no subcaminho do projeto quanto
na raiz de um domínio próprio. Os ícones e arquivos de instalação também usam
caminhos relativos. `auth/teste.html` é uma ferramenta de diagnóstico de autenticação,
não uma entrada do portal; não recebeu manifesto nem controle de instalação.

Os ícones PNG 192x192, 512x512 e apple-touch-icon 180x180 foram derivados da imagem
de marca de alta resolução já incorporada no login, preservando a proporção e
aplicando fundo branco. As cores são branco e azul institucional `#06243a`.

## Instalação

- Android/Chrome: o botão discreto aparece no login e no cabeçalho quando o navegador
  dispara `beforeinstallprompt`. O diálogo nativo só abre após clicar no botão.
  Após uma recusa, aguarda uma nova oferta do navegador; não insiste automaticamente.
- iOS/iPadOS: o botão abre instruções para Safari > Compartilhar > Adicionar à Tela
  de Início. Nenhuma instrução abre automaticamente.
- A opção fica oculta em standalone, quando `navigator.standalone` é verdadeiro,
  após `appinstalled` ou quando este navegador já registrou uma instalação.
- O indicador `portal-bi-pwa-installed` no localStorage contém apenas `1`. Não guarda
  login, credenciais ou dados empresariais. A desinstalação não emite um evento
  padronizado para a página: caso o usuário desinstale e queira ver novamente o botão,
  remova somente essa chave pelo DevTools. A instalação em outro navegador/dispositivo
  não pode ser detectada de modo confiável.
- O portal continua exigindo conexão. Não foi criado nem registrado service worker,
  nem implementado cache offline ou interceptação das chamadas de API.

Referências de comportamento:
https://web.dev/articles/install-criteria
https://support.apple.com/en-lamr/guide/iphone/iphea86e5236/ios

## Verificação rápida

Com Python, Selenium e Chrome disponíveis:

```powershell
py -B PortalBI/tests/test_pwa.py
py -B PortalBI/tests/test_portal_controls.py
```

O teste PWA serve o frontend em HTTP local, aceito pelo Chrome como origem segura,
verifica manifesto e imagens na raiz e no caminho de projeto, interpreta o manifesto
via Chrome, simula eventos de instalação/aceite/recusa e iOS/standalone, verifica
cliques mobile, console, registros de service worker e Cache Storage. APIs externas
recebem respostas fictícias. Não instala um aplicativo no sistema operacional.
A regressão de controles usa usuários fictícios e salvamento simulado.
A simulação de iOS em Chrome não substitui um teste em Safari real.

## Publicar no GitHub Pages

1. Faça commit e push de `index.html`, `manifest.webmanifest`, `assets/pwa/`, deste
   documento e do teste PWA para a branch usada na publicação. Não é necessário build.
2. No GitHub, abra Settings > Pages. Para publicação por branch, selecione
   Deploy from a branch, `main` e `/(root)` (ou mantenha a fonte existente que já publica
   a raiz). Se houver workflow externo, inclua manifesto e `assets/pwa/` no artefato.
3. Aguarde o deploy e abra a URL HTTPS indicada pelo GitHub Pages.
4. Confira `manifest.webmanifest`, `assets/pwa/icon-192.png`,
   `assets/pwa/icon-512.png` e `assets/pwa/apple-touch-icon.png` sob a mesma URL base.
5. Em Android/Chrome real, navegue/interaja com a página e aguarde a elegibilidade do
   navegador. Clique em Instalar aplicativo e abra pelo ícone. Confirme login, seleção
   de setor e abertura de relatórios. Em iPhone/iPad real, siga as instruções do botão,
   abra pelo ícone e confirme a ausência da opção de instalação em standalone.
6. Após um novo deploy, reabra o aplicativo conectado e confira a versão publicada.
   Nenhum service worker desta implementação retém uma versão antiga do frontend.

A implementação local não publica o site automaticamente e não modifica Flask,
Render, banco de dados, permissões ou regras de negócio.
