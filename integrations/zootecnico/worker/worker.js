const PORTAL_ORIGIN =
  "https://controladoriagranja.github.io";

const PORTAL_AUTH_ME =
  "https://portal-bi-granjabrasilia.onrender.com/api/auth/me";

const INTERNAL_API =
  "http://192.168.1.193:8010";


function corsHeaders(origin) {
  const headers = new Headers();

  if (origin === PORTAL_ORIGIN) {
    headers.set(
      "Access-Control-Allow-Origin",
      PORTAL_ORIGIN
    );

    headers.set(
      "Access-Control-Allow-Headers",
      "Authorization, Content-Type, Accept"
    );

    headers.set(
      "Access-Control-Allow-Methods",
      "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    );

  }

  headers.set("Vary", "Origin, Authorization");
  headers.set("Cache-Control", "no-store");

  return headers;
}


function json(data, status, origin) {
  const headers = corsHeaders(origin);

  headers.set(
    "Content-Type",
    "application/json; charset=utf-8"
  );

  headers.set("Cache-Control", "no-store");

  return new Response(
    JSON.stringify(data),
    {
      status,
      headers
    }
  );
}


function basicAuth(user, password) {
  const bytes =
    new TextEncoder().encode(
      `${user}:${password}`
    );

  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary);
}


export default {
  async fetch(request, env) {

    const url = new URL(request.url);

    const origin =
      request.headers.get("Origin");


    // --------------------------------
    // CORS
    // --------------------------------

    if (request.method === "OPTIONS") {

      if (origin !== PORTAL_ORIGIN) {
        return new Response(null, {
          status: 403,
          headers: {"Cache-Control": "no-store", "Vary": "Origin"}
        });
      }

      return new Response(null, {
        status: 204,
        headers: corsHeaders(origin)
      });
    }


    // Navegadores de outros sites
    if (
      origin &&
      origin !== PORTAL_ORIGIN
    ) {
      return json(
        {
          detail: "Origem não autorizada"
        },
        403,
        origin
      );
    }


    // --------------------------------
    // SOMENTE /api/*
    // --------------------------------

    if (!url.pathname.startsWith("/api/")) {
      return json(
        {
          detail: "Not Found"
        },
        404,
        origin
      );
    }

    if ([...url.searchParams.keys()].some(key => /^(authorization|access_token|token|x-portal-authorization)$/i.test(key))) {
      return json({detail: "Credenciais não são aceitas na URL"}, 400, origin);
    }


    // --------------------------------
    // TOKEN DO PORTAL
    // --------------------------------

    const authorization =
      request.headers.get("Authorization") || "";


    if (
      !authorization.startsWith("Bearer ") || authorization.length > 4096 || !authorization.slice(7).trim()
    ) {
      return json(
        {
          detail: "Não autenticado"
        },
        401,
        origin
      );
    }


    // --------------------------------
    // VALIDA TOKEN NO RENDER
    // --------------------------------

    let authResponse;

    try {

      authResponse = await fetch(
        PORTAL_AUTH_ME,
        {
          method: "GET",

          cache: "no-store",
          redirect: "manual",
          headers: {
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "Authorization": authorization
          }
        }
      );

    } catch (error) {

      return json(
        {
          detail:
            "Não foi possível validar a sessão."
        },
        503,
        origin
      );
    }


    if (authResponse.status === 401 || authResponse.status === 403) {
      return json(
        {
          detail:
            "Sessão inválida ou expirada"
        },
        authResponse.status,
        origin
      );
    }


    if (!authResponse.ok) {
      return json(
        {
          detail:
            "Serviço de autenticação indisponível",
          status: authResponse.status
        },
        503,
        origin
      );
    }


    let authData;
    try {
      authData = await authResponse.json();
    } catch (_) {
      return json({ detail: "Resposta de autenticação inválida" }, 503, origin);
    }


    if (
      !authData?.ok ||
      !authData?.user?.email ||
      !Number.isSafeInteger(authData?.user?.id) ||
      authData.user.id < 1 ||
      authData.user.ativo !== true
    ) {
      return json(
        {
          detail: "Usuário não autorizado"
        },
        401,
        origin
      );
    }


    // --------------------------------
    // CREDENCIAL DA API INTERNA
    // --------------------------------

    if (
      !env.API_USER ||
      !env.API_PASSWORD
    ) {
      return json(
        {
          detail:
            "Credenciais internas não configuradas"
        },
        500,
        origin
      );
    }


    const headers =
      new Headers(request.headers);

    // Sobrescrever qualquer identidade enviada pelo cliente com o Bearer validado.
    // Basic autentica a infraestrutura; o Bearer autoriza o usuário na API.
    headers.set("X-Portal-Authorization", authorization);
    headers.set("Cache-Control", "no-store");


    headers.set(
      "Authorization",
      "Basic " +
      basicAuth(
        env.API_USER,
        env.API_PASSWORD
      )
    );


    // Não encaminha informações
    // desnecessárias do navegador.
    headers.delete("Origin");
    headers.delete("Referer");
    headers.delete("Cookie");


    // --------------------------------
    // URL DA API INTERNA
    // --------------------------------

    const targetUrl =
      new URL(
        url.pathname + url.search,
        INTERNAL_API
      );


    const proxyRequest =
      new Request(
        targetUrl.toString(),
        {
          method: request.method,
          cache: "no-store",
          headers: headers,

          body:
            request.method === "GET" ||
            request.method === "HEAD"
              ? undefined
              : request.body,

          redirect: "manual"
        }
      );


    // ========================================
    // IMPORTANTE:
    // VPC BINDING, NÃO fetch() NORMAL
    // ========================================

    let upstream;

    try {

      upstream =
        await env.PRIVATE_API.fetch(
          proxyRequest
        );

    } catch (error) {

      return json(
        {
          detail:
            "API interna indisponível"
        },
        502,
        origin
      );
    }

    if (upstream.status >= 300 && upstream.status < 400) {
      return json({ detail: "Redirecionamento inesperado da API interna" }, 502, origin);
    }
    if (upstream.status >= 500) {
      return json({ detail: "Serviço de dados temporariamente indisponível" }, upstream.status, origin);
    }


    // --------------------------------
    // RETORNO
    // --------------------------------

    const responseHeaders =
      new Headers(upstream.headers);


    responseHeaders.delete(
      "WWW-Authenticate"
    );
    responseHeaders.delete("Authorization");
    responseHeaders.delete("X-Portal-Authorization");
    responseHeaders.delete("Set-Cookie");
    responseHeaders.delete("Access-Control-Allow-Origin");
    responseHeaders.delete("Access-Control-Allow-Credentials");

    const vary = new Set((responseHeaders.get("Vary") || "").split(",").map(x => x.trim()).filter(Boolean));


    const cors =
      corsHeaders(origin);


    for (
      const [key, value]
      of cors.entries()
    ) {
      if (key.toLowerCase() === "vary") continue;
      responseHeaders.set(
        key,
        value
      );
    }
    for (const key of ["Origin", "Authorization", "X-Portal-Authorization"]) vary.add(key);
    responseHeaders.set("Vary", [...vary].join(", "));


    responseHeaders.set(
      "Cache-Control",
      "no-store"
    );


    return new Response(
      upstream.body,
      {
        status: upstream.status,
        headers: responseHeaders
      }
    );
  }
};
