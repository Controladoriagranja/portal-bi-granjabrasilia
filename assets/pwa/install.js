/* Installation only: no service worker, network interception or offline cache. */
(() => {
  'use strict';
  const buttons = [...document.querySelectorAll('[data-pwa-install]')];
  const help = document.getElementById('pwaInstallHelp');
  const status = document.getElementById('pwaInstallStatus');
  const standalone = window.matchMedia('(display-mode: standalone)');
  const installedKey = 'portal-bi-pwa-installed';
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  let deferredPrompt = null;
  let installed = false;
  let busy = false;
  let lastButton = null;
  try { installed = localStorage.getItem(installedKey) === '1'; } catch (_) {}

  function isStandalone() { return standalone.matches || navigator.standalone === true; }
  function markInstalled() {
    installed = true;
    deferredPrompt = null;
    try { localStorage.setItem(installedKey, '1'); } catch (_) {}
    if (help?.open) help.close();
    refresh();
  }
  function refresh() {
    const available = !installed && !isStandalone() && (isIOS || deferredPrompt !== null);
    buttons.forEach(button => {
      button.hidden = !available;
      button.disabled = busy;
    });
  }
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    if (installed || isStandalone()) return;
    deferredPrompt = event;
    refresh();
  });
  window.addEventListener('appinstalled', markInstalled);
  standalone.addEventListener('change', () => {
    if (isStandalone()) markInstalled(); else refresh();
  });
  window.addEventListener('pageshow', refresh);

  buttons.forEach(button => button.addEventListener('click', async () => {
    if (busy || installed || isStandalone()) return;
    if (isIOS) {
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
