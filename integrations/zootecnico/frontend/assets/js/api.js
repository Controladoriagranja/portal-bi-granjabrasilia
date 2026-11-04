/**
 * Cliente HTTP do BI Zootécnico.
 *
 * O navegador não lê mais Parquet.
 * Todos os dados vêm da API publicada pelo Cloudflare Worker,
 * que valida a sessão do Portal BI e encaminha a consulta
 * pelo binding privado até a API interna.
 */

class ApiError extends Error {
  constructor(message, status = 0, code = "HTTP_ERROR") {
    super(message); this.name = "ApiError"; this.status = status; this.code = code;
  }
}
function getPortalToken() {
  try {
    return sessionStorage.getItem("granjabi_auth_token") || "";
  } catch (_) {
    return "";
  }
}

const ApiActivity = (() => {
  let pending = 0, notice;
  function update() {
    if (typeof document === "undefined" || !document.body) return;
    if (!notice) {
      notice = document.createElement("div");
      notice.id = "apiFilterProgress";
      notice.className = "api-filter-progress hidden";
      notice.setAttribute("role", "status");
      notice.setAttribute("aria-live", "polite");
      notice.textContent = "Aplicando filtros…";
      document.body.appendChild(notice);
    }
    notice.classList.toggle("hidden", pending === 0);
  }
  return { begin() {
    pending++; update();
    let finished = false;
    return () => { if (!finished) { finished = true; pending--; update(); } };
  }};
})();

async function apiGet(endpoint, params = {}, options = {}) {
  const finish = ApiActivity.begin();
  try { return await requestApi(endpoint, params, options); }
  finally { finish(); }
}

// Apenas transporte e combinação de respostas: fórmulas e totais permanecem no SQL.
const ApiProgressive = {
  async records(endpoint, params, options, onData) {
    const finish = ApiActivity.begin();
    try {
      const main = await apiGet(endpoint, {...params, etapa:'principal'}, options);
      main.carga_completa = main.etapa !== 'principal';
      onData(main);
      if (main.carga_completa) return main;
      if (options.signal?.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
      const groups = await apiGet(endpoint, {...params, etapa:'grupos'}, options);
      const result = {...groups, carga_completa:true};
      onData(result);
      return result;
    } finally { finish(); }
  },
  async summary(endpoint, params, options, onData) {
    const selected = params.mes ? [].concat(params.mes).map(Number) : Array.from({length:12}, (_, i) => i + 1);
    const months = [...new Set(selected)].sort((a,b) => a-b);
    let data;
    const finish = ApiActivity.begin();
    try {
      for (let offset = 0; offset < months.length; offset += 2) {
        if (options.signal?.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
        const response = await apiGet(endpoint, {...params, mes_carga:months.slice(offset, offset+2), incluir_totais:offset ? '0' : '1'}, options);
        // Compatibilidade com serviços que já retornam todos os meses.
        if (!response.meses_carregados) { onData(response); return response; }
        if (!data) data = response;
        else {
          data.anos = [...new Set([...data.anos, ...response.anos])].sort((a,b) => a-b);
          for (const [id, metric] of Object.entries(response.indicadores)) {
            const target = data.indicadores[id];
            for (const [year, values] of Object.entries(metric.por_ano)) {
              target.por_ano[year] ||= Array(12).fill(null);
              for (const month of response.meses_carregados) target.por_ano[year][month-1] = values[month-1];
            }
          }
          data.meses_carregados = [...new Set([...data.meses_carregados, ...response.meses_carregados])];
        }
        data.carga_completa = offset + 2 >= months.length;
        onData(data);
      }
      return data;
    } finally { finish(); }
  },
  async details(endpoint, params, options, onData) {
    const finish = ApiActivity.begin();
    try {
      const main = await apiGet(endpoint, {...params, etapa:'principal'}, options);
      main.carga_completa = main.etapa !== 'principal';
      onData(main);
      if (main.carga_completa) return main;
      const evolution = await apiGet(endpoint, {...params, etapa:'evolucao'}, options);
      main.evolucao = evolution.evolucao;
      main.carga_completa = true;
      onData(main);
      return main;
    } finally { finish(); }
  }
};

async function requestApi(endpoint, params = {}, options = {}) {
  if (!endpoint) {
    throw new Error("Endpoint da API não informado.");
  }

  const baseUrl = String(APP_CONFIG.API_URL || "").replace(/\/+$/, "");

  if (!baseUrl) {
    throw new Error("APP_CONFIG.API_URL não configurada.");
  }

  const token = getPortalToken();

  if (!token) {
    throw new ApiError("Sessão da CENTRAL não encontrada. Entre pela CENTRAL e abra o relatório novamente.", 401, "SESSION_MISSING");
  }

  const normalizedEndpoint = endpoint.startsWith("/")
    ? endpoint
    : `/${endpoint}`;

  const url = new URL(baseUrl + normalizedEndpoint);
  if (url.origin !== new URL(APP_CONFIG.API_URL).origin || !url.pathname.startsWith("/api/")) {
    throw new ApiError("Endereço de consulta inválido.", 0, "CONFIG_ERROR");
  }

  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }

    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== null && item !== undefined && item !== "") {
          url.searchParams.append(key, String(item));
        }
      });
      return;
    }

    url.searchParams.append(key, String(value));
  });

  let response;

  try {
    response = await fetch(url.toString(), {
      method: "GET",
      signal: options.signal,
      cache: "no-store",
      credentials: "omit",
      headers: {
        ...(options.headers || {}),
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }

    throw new ApiError(
      "Não foi possível conectar à API do BI. " +
        "Verifique a conexão com a internet e a disponibilidade do serviço."
    );
  }

  // Uma resposta iniciada na sessão anterior jamais pode alimentar a nova tela.
  if (getPortalToken() !== token) {
    throw new ApiError("A sessão foi alterada. Abra o relatório novamente pela CENTRAL.", 401, "SESSION_CHANGED");
  }

  if (!response.ok) {
    const messages = {
      400: "Consulta inválida. Confira o indicador e os filtros.",
      401: "Sessão inválida ou expirada. Entre novamente pela CENTRAL.",
      403: "Sem permissão para estes dados. Confira o acesso à Integração e o vínculo do técnico com o administrador.",
      404: "Consulta indisponível no serviço de dados.",
      422: "Filtros inválidos. Confira as datas e seleções.",
      500: "Não foi possível concluir a consulta. Tente novamente.",
      502: "Serviço de dados indisponível. Tente novamente.",
      503: "Serviço temporariamente indisponível. Tente novamente."
    };
    throw new ApiError(messages[response.status] || "Não foi possível concluir a consulta.", response.status);
  }
  let data;
  try { data = await response.json(); }
  catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError("O serviço retornou uma resposta inválida.", response.status, "INVALID_JSON");
  }
  if (getPortalToken() !== token) {
    throw new ApiError("A sessão foi alterada. Abra o relatório novamente pela CENTRAL.", 401, "SESSION_CHANGED");
  }
  // A API informa a trava da sessão; nunca deduzir acesso pelo nome ou pelo JWT.
  if (normalizedEndpoint === APP_CONFIG.endpoints.filtros && data && typeof data === 'object') {
    data.filtros_fixos = response.headers?.get('X-Zootecnico-Status-Acerto') === 'nao_manual'
      ? {status_acerto: ['Não Manual']} : {};
  }
  // Nova modificação de 26/10/2026: contrato exclusivo da evolução de mortalidade.
  // As demais respostas continuam com a validação oficial do Desempenho abaixo.
  const isMortalityEvolution = normalizedEndpoint === APP_CONFIG.endpoints.detalhes
    && url.searchParams.getAll('indicador').length === 1
    && url.searchParams.get('indicador') === 'mortalidade'
    && url.searchParams.getAll('etapa').length === 1
    && url.searchParams.get('etapa') === 'evolucao'
    && url.searchParams.getAll('agrupamento').length === 1
    && ['mensal', 'semanal'].includes(url.searchParams.get('agrupamento'))
    && url.searchParams.getAll('ano').length === 1;
  if (isMortalityEvolution) {
    const ids = ['1','2','3','4','5','35_abate'];
    const validNumber = value => value === null || (typeof value === 'number' && Number.isFinite(value));
    const validValues = item => item && item.faixas
      && ids.every(id => Object.hasOwn(item.faixas,id) && validNumber(item.faixas[id]))
      && validNumber(item.total);
    const compatible = data && data.rules_version === 'mortalidade-faixas-2026-10-26-v1'
      && data.unidade === '%'
      && data.ano === Number(url.searchParams.get('ano'))
      && data.agrupamento === url.searchParams.get('agrupamento')
      && data.fonte_total === 'mesma configuração, expressão mort/aloj e filtros do Desempenho'
      && data.fonte_faixas === 'zootecnico.base_dinamica; percentuais ponderados por aves_alojadas'
      && typeof data.valido === 'boolean'
      && Array.isArray(data.faixas) && data.faixas.length === ids.length
      && data.faixas.every((item,index) => item && item.id === ids[index])
      && Array.isArray(data.periodos) && data.periodos.every(validValues)
      && (data.consolidado === null || validValues(data.consolidado));
    if (!compatible) {
      throw new ApiError('A API retornou um contrato incompatível com as faixas de mortalidade. Confira a versão, as fontes, o ano e o agrupamento.',503,'MORTALITY_CONTRACT_PENDING');
    }
  } else if ([APP_CONFIG.endpoints.desempenho, APP_CONFIG.endpoints.detalhes].includes(endpoint)
      && (data.rules_version !== "acerto-iep-mensal-2026-10-16" || data.arquivo !== "zootecnico.vw_desempenho_acerto_portal")) {
    const receivedRules = String(data.rules_version || "não informadas").slice(0, 100);
    const receivedSource = String(data.arquivo || "não informada").slice(0, 120);
    throw new ApiError(
      "A API respondeu com regras " + receivedRules + " e fonte " + receivedSource + ". " +
      "Esta tela exige acerto-iep-mensal-2026-10-16 e zootecnico.vw_desempenho_acerto_portal. " +
      "Confira os arquivos instalados e reconstrua/recrie o serviço zootecnico no Anderson.",
      503, "SOURCE_PENDING"
    );
  }
  return data;
}
