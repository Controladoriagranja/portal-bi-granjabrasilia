import re
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests


class AgrosysEngine:
    def __init__(self, base_url, usuario, senha, pasta_html):
        self.base_url = base_url.rstrip("/")
        self.usuario = usuario
        self.senha = senha
        self.pasta_html = Path(pasta_html)
        self.pasta_html.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()


    def aguardar_com_log(self, segundos, motivo="aguardando"):
        """Mostra progresso durante esperas longas para o Portal não parecer travado."""
        segundos = int(segundos or 0)
        if segundos <= 0:
            return

        passo = 5
        restante = segundos
        while restante > 0:
            bloco = min(passo, restante)
            print(f"{motivo}... próxima consulta em {restante}s", flush=True)
            time.sleep(bloco)
            restante -= bloco

    def login(self, tentativas=None, espera=20):
        """
        Faz login no Agrosys e insiste até liberar sessão.

        Antes o robô parava após 5 tentativas quando o Agrosys retornava
        "aguardando novo login". Agora ele continua tentando até conseguir.

        Compatibilidade:
        - Se algum script antigo chamar login(tentativas=5), o parâmetro é aceito,
          mas o comportamento padrão é não desistir.
        """
        ultimo_html = ""
        ciclo = 1

        while True:
            print("=" * 80, flush=True)
            print(f"LOGIN AGROSYS - ciclo {ciclo}", flush=True)
            print("=" * 80, flush=True)

            self.session.cookies.clear()

            try:
                r = self.session.post(
                    f"{self.base_url}/webpro/webpad/acesso",
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Origin": self.base_url,
                        "Referer": f"{self.base_url}/sistema/padrao/index.html",
                    },
                    data={
                        "vusuario": self.usuario,
                        "vsenha": self.senha,
                        "vtenant": "",
                        "vauxtenant": "",
                        "vSaveLogin": "SAT",
                    },
                    timeout=60,
                )

                ultimo_html = r.text
                print("Login status:", r.status_code, flush=True)

                if "vpad-sessao" in self.session.cookies.get_dict():
                    print("Login OK.", flush=True)
                    return True

                debug_path = self.pasta_html / "login_aguardando_debug.html"
                debug_path.write_text(ultimo_html, encoding="latin1")

                print("Login não liberado pelo Agrosys. Vou aguardar e tentar novamente.", flush=True)
                print(f"Debug salvo em: {debug_path}", flush=True)

            except requests.exceptions.Timeout:
                print("Timeout ao tentar login. Vou aguardar e tentar novamente.", flush=True)

            except requests.exceptions.RequestException as e:
                print(f"Falha de conexão no login: {e}. Vou aguardar e tentar novamente.", flush=True)

            self.aguardar_com_log(espera, "Aguardando novo login")
            ciclo += 1

    def configurar_unidade(self, unidade, menu, modulo="14400"):
        dominio = "sistema.granjabrasilia.com.br"

        self.session.cookies.set("vpad-modulo", str(modulo), domain=dominio, path="/")
        self.session.cookies.set("semp-empresa", "1", domain=dominio, path="/")
        self.session.cookies.set("suni-unidade", str(unidade), domain=dominio, path="/")
        self.session.cookies.set("vpad-codmenu", str(menu), domain=dominio, path="/")
        self.session.cookies.set("vpad-lista-0", "", domain=dominio, path="/")

    def abrir_tela(self, caminho, menu):
        url = f"{self.base_url}{caminho}?vmen-codigo={menu}"

        r = self.session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{self.base_url}/webpro/webpad/wpadmenu",
            },
            timeout=60,
        )

        print("Abrir tela status:", r.status_code, flush=True)

        return url, r.text

    def extrair_inputs(self, html):
        dados = {}

        for name, value in re.findall(
            r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
            html,
            re.IGNORECASE,
        ):
            dados[name] = value

        return dados

    def disparar_relatorio(self, url, dados):
        r = self.session.post(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Origin": self.base_url,
                "Referer": url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=dados,
            timeout=60,
        )

        print("Disparo status:", r.status_code, flush=True)

        return r.text

    def capturar_processo(self, html):
        """
        Captura o número do processo nos formatos usados pelo Agrosys.

        Cadastro de Clientes retorna, por exemplo:
        fpad_form("/webpro/webpad/wpd007m1?vpad-modo=INC&vmodal=1&vparam=0003771684", ...)
        """
        if not html:
            return None

        candidatos = [
            html,
            html.replace("&amp;", "&"),
            html.replace("\\/", "/"),
            html.replace("\\u0026", "&"),
            html.replace("%26", "&"),
            html.replace("%3D", "=").replace("%3d", "="),
        ]

        padroes = [
            r"vparam\s*=\s*0*(\d{1,10})",
            r"vparam%3[dD]0*(\d{1,10})",
            r'vbatnump[^>]*value\s*=\s*["\']?0*(\d+)',
            r'N[ºo]\s*Processo.*?value\s*=\s*["\']?0*(\d+)',
            r'wpd007m1\?[^"\']*vparam\s*=\s*0*(\d{1,10})',
        ]

        for conteudo in candidatos:
            for padrao in padroes:
                m = re.search(
                    padrao,
                    conteudo,
                    re.IGNORECASE | re.DOTALL,
                )
                if m:
                    processo = m.group(1).lstrip("0") or "0"
                    print(
                        f"Processo capturado no retorno do Agrosys: {processo}",
                        flush=True,
                    )
                    return processo

        return None

    def baixar_relatorio(
        self,
        processo,
        referer,
        tentativas=None,
        espera=20,
        max_404_consecutivos=3,
        tempo_minimo_antes_descartar_404=300,
    ):
        """
        Consulta o relatório até ele ficar pronto.

        REGRA SEGURA PARA 404:
        - 404 logo após o disparo pode ser NORMAL: o Agrosys ainda está processando.
        - Durante os primeiros 300s (5 min), NUNCA descarta o processo por 404.
        - Depois desse período de carência, exige 3 retornos 404 consecutivos
          antes de considerar o processo fantasma.
        - Se em algum momento houver resposta diferente de 404, zera a sequência.
        - Status 200 ainda incompleto continua aguardando o MESMO processo.
        - Timeout/falha de conexão também continua aguardando o MESMO processo.
        """
        url_relatorio = (
            f"{self.base_url}/sistema/reports/"
            f"{self.usuario}-{int(processo):010d}.php"
        )

        print("URL relatório:", url_relatorio, flush=True)

        tentativa = 1
        consecutivos_404 = 0
        inicio_espera_processo = time.time()

        while True:
            print(
                f"Tentativa {tentativa} até o relatório ficar pronto...",
                flush=True,
            )

            self.aguardar_com_log(
                espera,
                f"Aguardando o Agrosys gerar o relatório {processo}",
            )

            try:
                print(
                    f"Consultando relatório {processo} no Agrosys...",
                    flush=True,
                )

                rel = self.session.get(
                    url_relatorio,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": referer,
                    },
                    timeout=45,
                )

                texto = rel.text.upper()
                tempo_decorrido = time.time() - inicio_espera_processo

                print(
                    "Status:",
                    rel.status_code,
                    "| Tamanho HTML:",
                    len(rel.text),
                    "| Tempo aguardando:",
                    f"{int(tempo_decorrido)}s",
                    flush=True,
                )

                if rel.status_code == 200 and (
                    "<TABLE" in texto
                    or "RELATÓRIO" in texto
                    or "RELATORIO" in texto
                    or "FATURAMENTO" in texto
                    or "VENDEDOR" in texto
                    or "VEÍCULO" in texto
                    or "VEICULO" in texto
                    or "CFOP" in texto
                    or "FRETE" in texto
                    or "DEVOLU" in texto
                    or "OCORR" in texto
                    or "CONTAS" in texto
                ):
                    print("Relatório pronto.", flush=True)
                    return rel.text

                if rel.status_code != 404:
                    consecutivos_404 = 0

                if rel.status_code == 404:
                    # Nos primeiros 5 minutos o 404 é tratado como processamento normal.
                    if tempo_decorrido < tempo_minimo_antes_descartar_404:
                        restante_carencia = int(
                            tempo_minimo_antes_descartar_404 - tempo_decorrido
                        )

                        print(
                            f"Processo {processo} retornou 404, mas ainda está "
                            f"dentro do período de carência. "
                            f"Não será descartado. Carência restante: {restante_carencia}s.",
                            flush=True,
                        )

                        tentativa += 1
                        continue

                    consecutivos_404 += 1

                    print(
                        f"Processo {processo} retornou 404 após o período de carência "
                        f"({consecutivos_404}/{max_404_consecutivos}).",
                        flush=True,
                    )

                    debug_path = (
                        self.pasta_html
                        / f"relatorio_404_{processo}_tentativa_{tentativa}.html"
                    )

                    try:
                        debug_path.write_text(
                            rel.text,
                            encoding="latin1",
                        )
                        print(
                            "Debug atualizado em:",
                            debug_path,
                            flush=True,
                        )
                    except Exception:
                        pass

                    if consecutivos_404 >= max_404_consecutivos:
                        print("=" * 80, flush=True)
                        print(
                            f"PROCESSO {processo} CONSIDERADO INVÁLIDO.",
                            flush=True,
                        )
                        print(
                            "O processo permaneceu em 404 por mais de "
                            f"{tempo_minimo_antes_descartar_404}s e continuou "
                            f"retornando 404 por {max_404_consecutivos} consultas.",
                            flush=True,
                        )
                        print(
                            "Vou abandonar este processo e solicitar um NOVO DISPARO.",
                            flush=True,
                        )
                        print("=" * 80, flush=True)
                        return None

                    tentativa += 1
                    continue

                debug_path = (
                    self.pasta_html
                    / f"relatorio_ainda_nao_pronto_{processo}.html"
                )

                try:
                    debug_path.write_text(
                        rel.text,
                        encoding="latin1",
                    )
                    print(
                        "Debug atualizado em:",
                        debug_path,
                        flush=True,
                    )
                except Exception:
                    pass

                print(
                    "Relatório ainda não ficou pronto. "
                    "Vou continuar tentando no mesmo processo.",
                    flush=True,
                )

            except requests.exceptions.Timeout:
                print(
                    f"Timeout ao consultar relatório {processo}. "
                    "Vou continuar tentando no mesmo processo.",
                    flush=True,
                )

            except requests.exceptions.RequestException as e:
                print(
                    f"Falha de conexão ao consultar relatório {processo}: {e}. "
                    "Vou continuar tentando no mesmo processo.",
                    flush=True,
                )

            tentativa += 1

    def executar_relatorio(
        self,
        caminho,
        menu,
        unidade,
        filtros,
        nome_debug="relatorio",
        modulo="14400",
        tentativas=30,
        espera=20,
        tentativas_disparo=5,
        espera_disparo=15,
        max_404_consecutivos=3,
        tempo_minimo_antes_descartar_404=300,
    ):
        """
        Executa o relatório com recuperação automática de processo fantasma.

        Fluxo:
        1. Abre a tela e dispara.
        2. Captura o número do processo.
        3. Aguarda o relatório.
        4. Se o processo retornar 404 repetidamente, abandona esse número.
        5. Reabre a tela, refaz os inputs e dispara novamente.
        6. Continua até obter um relatório válido.

        'tentativas_disparo' continua aceito por compatibilidade, mas o engine
        permanece resiliente e pode continuar tentando até o Agrosys responder.
        """
        ciclo_disparo = 1

        while True:
            print("=" * 80, flush=True)
            print(
                f"CICLO DE DISPARO DO RELATÓRIO: {ciclo_disparo}",
                flush=True,
            )
            print("=" * 80, flush=True)

            # Reaplica contexto a cada novo ciclo.
            self.configurar_unidade(
                unidade=unidade,
                menu=menu,
                modulo=modulo,
            )

            url, html_tela = self.abrir_tela(
                caminho=caminho,
                menu=menu,
            )

            dados = self.extrair_inputs(html_tela)
            dados.update(filtros)

            processo = None
            html_disparo = ""
            tentativa_disparo = 1

            # -------------------------------------------------------------
            # ENCONTRAR UM NÚMERO DE PROCESSO
            # -------------------------------------------------------------
            while True:
                print(
                    f"Tentativa de disparo {tentativa_disparo} "
                    "até encontrar processo...",
                    flush=True,
                )

                try:
                    html_disparo = self.disparar_relatorio(
                        url=url,
                        dados=dados,
                    )

                    debug_path = (
                        self.pasta_html
                        / (
                            f"{nome_debug}_ciclo_{ciclo_disparo}_"
                            f"disparo_tentativa_{tentativa_disparo}.html"
                        )
                    )

                    try:
                        debug_path.write_text(
                            html_disparo,
                            encoding="latin1",
                        )
                    except Exception:
                        pass

                    processo = self.capturar_processo(
                        html_disparo
                    )

                    if processo:
                        print(
                            "Processo:",
                            processo,
                            flush=True,
                        )
                        break

                    texto = html_disparo.upper()

                    if (
                        "SOLICITAÇÃO EFETUADA COM SUCESSO" in texto
                        or "SOLICITACAO EFETUADA COM SUCESSO" in texto
                    ):
                        print(
                            "Solicitação parece ter sido efetuada, "
                            "mas não achei o processo.",
                            flush=True,
                        )

                    print(
                        "Não encontrei número do processo. "
                        "Vou aguardar e tentar disparar novamente.",
                        flush=True,
                    )

                except requests.exceptions.Timeout:
                    print(
                        "Timeout no disparo do relatório. "
                        "Vou aguardar e tentar novamente.",
                        flush=True,
                    )

                except requests.exceptions.RequestException as e:
                    print(
                        f"Falha de conexão no disparo: {e}. "
                        "Vou aguardar e tentar novamente.",
                        flush=True,
                    )

                self.aguardar_com_log(
                    espera_disparo,
                    "Aguardando novo disparo",
                )

                tentativa_disparo += 1

                # A cada conjunto de tentativas, renova login/contexto.
                if (
                    tentativas_disparo
                    and tentativa_disparo > tentativas_disparo
                ):
                    print(
                        "Muitas tentativas sem processo. "
                        "Renovando login e reabrindo a tela...",
                        flush=True,
                    )

                    try:
                        self.login()
                    except Exception:
                        pass

                    self.configurar_unidade(
                        unidade=unidade,
                        menu=menu,
                        modulo=modulo,
                    )

                    url, html_tela = self.abrir_tela(
                        caminho=caminho,
                        menu=menu,
                    )

                    dados = self.extrair_inputs(html_tela)
                    dados.update(filtros)
                    tentativa_disparo = 1

            # -------------------------------------------------------------
            # AGUARDAR O PROCESSO GERAR O RELATÓRIO
            # -------------------------------------------------------------
            html_relatorio = self.baixar_relatorio(
                processo=processo,
                referer=url,
                tentativas=tentativas,
                espera=espera,
                max_404_consecutivos=max_404_consecutivos,
                tempo_minimo_antes_descartar_404=tempo_minimo_antes_descartar_404,
            )

            # Processo válido.
            if html_relatorio is not None:
                rel_path = (
                    self.pasta_html
                    / f"{nome_debug}_{processo}.html"
                )

                rel_path.write_text(
                    html_relatorio,
                    encoding="latin1",
                )

                return html_relatorio, processo

            # -------------------------------------------------------------
            # PROCESSO INVÁLIDO: NOVO DISPARO
            # -------------------------------------------------------------
            print(
                f"O processo {processo} foi descartado. "
                "Preparando um novo disparo do relatório...",
                flush=True,
            )

            self.aguardar_com_log(
                espera_disparo,
                "Aguardando antes do novo disparo",
            )

            # Renova login a cada 3 processos fantasmas para evitar
            # reaproveitar uma sessão inconsistente.
            if ciclo_disparo % 3 == 0:
                print(
                    "Renovando login antes do próximo ciclo...",
                    flush=True,
                )
                try:
                    self.login()
                except Exception:
                    pass

            ciclo_disparo += 1

    @staticmethod
    def html_para_tabelas(html):
        return pd.read_html(
            StringIO(html),
            decimal=",",
            thousands=".",
        )