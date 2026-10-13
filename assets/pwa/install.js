/* Installation only: no service worker, network interception or offline cache. */
(() => {
  'use strict';
  const buttons = [...document.querySelectorAll('[data-pwa-install]')];
  const help = document.getElementById('pwaInstallHelp');
  const status = document.getElementById('pwaInstallStatus');
  const standalone = window.matchMedia('(display-mode: standalone)');
  // Retire the legacy flag; installation availability belongs to the browser.
  try { localStorage.removeItem('portal-bi-pwa-installed'); } catch (_) {}
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  let deferredPrompt = null;
  const safariVersion = navigator.userAgent.match(/Version\/(\d+)/);
  const isMacSafari = !isIOS && /Macintosh/.test(navigator.userAgent) &&
    /Safari\//.test(navigator.userAgent) && !/Chrome|Chromium|Edg|OPR/.test(navigator.userAgent) &&
    Number(safariVersion?.[1]) >= 17;
  if (isMacSafari && help) {
    document.getElementById('pwaInstallHelpTitle').textContent = 'Instalar no Mac';
    document.getElementById('pwaInstallIOS').hidden = true;
    document.getElementById('pwaInstallMac').hidden = false;
  }
  let busy = false;
  let lastButton = null;


  function isStandalone() { return standalone.matches || navigator.standalone === true; }
  function markInstalled() {

    deferredPrompt = null;

    if (help?.open) help.close();
    refresh();
  }
  function refresh() {
    const available = !isStandalone() && (isIOS || isMacSafari || deferredPrompt !== null);
    buttons.forEach(button => {
      button.hidden = !available;
      button.disabled = busy;
    });
  }
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    if (isStandalone()) return;
    deferredPrompt = event;
    refresh();
  });
  window.addEventListener('appinstalled', markInstalled);
  standalone.addEventListener('change', () => {
    if (isStandalone()) markInstalled(); else refresh();
  });
  window.addEventListener('pageshow', refresh);

  buttons.forEach(button => button.addEventListener('click', async () => {
    if (busy || isStandalone()) return;
    if (isIOS || isMacSafari) {
      lastButton = button;
      if (help && !help.open) help.showModal();
      return;
    }
    const prompt = deferredPrompt;
    if (!prompt) return;
    deferredPrompt = null;
    busy = true;
    refresh();
    try {
      await prompt.prompt();
      const choice = await prompt.userChoice;
      if (choice.outcome === 'accepted') markInstalled();
    } catch (_) {
      if (status) status.textContent = 'Não foi possível abrir a instalação. Tente pelo menu do navegador.';
    } finally {
      busy = false;
      refresh();
    }
  }));
  document.querySelector('[data-pwa-close]')?.addEventListener('click', () => help?.close());
  help?.addEventListener('close', () => lastButton?.focus());
  if (isStandalone()) markInstalled(); else refresh();
})();
