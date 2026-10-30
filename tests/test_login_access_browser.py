"""Chrome local, rede bloqueada e Google Forms simulado; nao executa app/API/robos.

Usa somente Selenium/Chrome/driver ja instalados. Screenshots ficam no TEMP local.
"""
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
URL = "https://docs.google.com/forms/d/e/1FAIpQLSd34H86yRAsPvFXT0RIfg5jLMplPNejN4ZYD-tCAcUYMJfksw/viewform?embedded=true"


def main():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    controller = html.split("let loginAccessTransition = 0;", 1)[1].split("function showScreen(id)", 1)[0]
    controller = "let loginAccessTransition = 0;" + controller
    screen = re.search(r"(?m)^function showScreen\(id\) \{[\s\S]*?^\}", html).group()
    fixture = re.sub(r"<script\b[^>]*>[\s\S]*?</script>|<link\b[^>]*>", "", html, flags=re.I)
    output = Path(tempfile.mkdtemp(prefix="portal-acesso-"))
    page = output / "login-fixture.html"
    page.write_text(fixture, encoding="utf-8")
    drivers = list((Path.home() / ".cache/selenium/chromedriver/win64").glob("*/chromedriver.exe"))
    if not drivers:
        raise RuntimeError("Requer driver local existente; nao faz downloads.")
    driver_path = max(drivers, key=lambda p: tuple(int(x) for x in p.parent.name.split(".")))
    options = Options()
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    for flag in ("--headless=new", "--disable-background-networking", "--disable-extensions",
                 "--disable-sync", "--no-first-run", "--no-default-browser-check"):
        options.add_argument(flag)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    driver = webdriver.Chrome(service=Service(str(driver_path), log_output=subprocess.DEVNULL), options=options)
    checks = 0

    def js(code, *args):
        return driver.execute_script(code, *args)

    def wait(code):
        WebDriverWait(driver, 4).until(lambda _: js(code))

    def check(condition, message):
        nonlocal checks
        if not condition:
            raise AssertionError(message)
        checks += 1

    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*"]})
        driver.get(page.as_uri())
        js("const script=document.createElement('script');script.textContent=arguments[0];document.head.append(script)",
           "window.stopUpdateMonitor=()=>{};window.stopCentralTicketSync=()=>{};" + controller + screen)
        check(js("return !document.getElementById('accessRequestIframe').getAttribute('src')"), "Preload indevido")
        check(js("return document.getElementById('accessRequestIframe').dataset.src") == URL, "URL incorreta")
        mock = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>body{margin:0;padding:28px 20px;font:15px Arial;background:#f7f8fa;color:#334155}'
                'main{max-width:640px;margin:auto;background:white;border:1px solid #e2e8f0;border-radius:10px;'
                'padding:24px;box-sizing:border-box}p{line-height:1.7}.space{height:850px}</style>'
                '<main><h2>Solicitação de acesso</h2><p>Área do Google Forms<br>Simulação local para '
                'verificar o enquadramento.</p><div class="space"></div><p>Fim do formulário de teste.</p></main>')
        data = "data:text/html;charset=utf-8;base64," + base64.b64encode(mock.encode()).decode()
        js("document.getElementById('accessRequestIframe').dataset.src=arguments[0];"
           "document.getElementById('loginEmail').value='teste@example.invalid';"
           "document.getElementById('loginPass').value='offline-only';window.loginSubmits=0;"
           "document.getElementById('portalLoginForm').onsubmit=e=>{e.preventDefault();window.loginSubmits++}", data)
        for width, height, name in ((1440, 1000, "pc"), (768, 1024, "tablet"), (390, 844, "celular"),
                                    (320, 640, "celular-pequeno"), (844, 390, "paisagem")):
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width <= 768})
            button = driver.find_element(By.ID, "loginAccessRequestBtn")
            button.location_once_scrolled_into_view
            check(js("return document.documentElement.scrollWidth<=innerWidth+1"), name + ": overflow login")
            if name == "pc":
                ActionChains(driver).move_to_element(driver.find_element(By.ID, "loginEmail")).perform()
                before = js("return getComputedStyle(document.getElementById('loginAccessRequestBtn')).backgroundColor")
                ActionChains(driver).move_to_element(button).perform()
                WebDriverWait(driver, 2).until(lambda _: js(
                    "return getComputedStyle(document.getElementById('loginAccessRequestBtn')).backgroundColor") != before)
                driver.save_screenshot(str(output / "login-pc.png"))
                check(True, "Hover")
            button.click()
            wait("return !document.getElementById('accessRequestPanel').hidden && !document.getElementById('accessRequestBackBtn').disabled")
            wait("return document.getElementById('accessRequestLoading').hidden")
            check(js("return document.getElementById('accessRequestFrame').getAttribute('aria-busy')==='false'"), name + ": carregamento nao concluido")
            check(js("return document.getElementById('loginCard').hidden && document.getElementById('loginAccessRequestBtn').getAttribute('aria-expanded')==='true'"), name + ": substituicao")
            check(js("return document.documentElement.scrollWidth<=innerWidth+1"), name + ": overflow formulario")
            check(js("const b=document.getElementById('accessRequestBackBtn').getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight&&b.width>=44&&b.height>=44"), name + ": retorno fora da tela")
            check(js("return document.getElementById('accessRequestIframe').getBoundingClientRect().height>120"), name + ": iframe sem altura")
            if name in ("pc", "celular"):
                driver.save_screenshot(str(output / ("form-" + name + ".png")))
            driver.find_element(By.ID, "accessRequestBackBtn").click()
            wait("return !document.getElementById('loginCard').hidden && !document.getElementById('loginAccessRequestBtn').disabled")
            check(js("return document.getElementById('loginEmail').value==='teste@example.invalid'&&document.getElementById('loginPass').value==='offline-only'"), name + ": campos apagados")
            check(js("return document.activeElement.id==='loginAccessRequestBtn'"), name + ": foco")
        check(js("return window.loginSubmits===0"), "Envio involuntario do login")
        js('setLoginAccessRequest(true);setLoginAccessRequest(true);showScreen("portal");')
        wait("return document.getElementById('accessRequestPanel').hidden && !document.getElementById('loginCard').hidden")
        check(js("return !document.getElementById('screen-login').classList.contains('active')"), "Transicao reabriu login")
        js('showScreen("login")')
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-reduced-motion", "value": "reduce"}, {"name": "display-mode", "value": "standalone"}]})
        js("setLoginAccessRequest(true)")
        wait("return !document.getElementById('accessRequestPanel').hidden && !document.getElementById('accessRequestBackBtn').disabled")
        check(js("return document.getElementById('accessRequestPanel').getAnimations().length===0"), "Movimento reduzido ignorado")
        check(js("return document.getElementById('accessRequestIframe').src===arguments[0]", data), "Formulario recriado")
        errors = [e for e in driver.get_log("browser") if e["level"] == "SEVERE" and (
            "Uncaught" in e["message"] or "SyntaxError" in e["message"])]
        check(not errors, "Erro JavaScript: " + str(errors))
        print(json.dumps({"checks": checks, "result": "OK — Chrome local, formulario simulado, rede bloqueada",
                          "screenshots": str(output)}, ensure_ascii=False))
    except Exception:
        driver.save_screenshot(str(output / "failure.png"))
        print("Diagnostico local:", output, driver.get_log("browser"))
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
