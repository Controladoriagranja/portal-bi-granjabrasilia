"""CSV publico, somente leitura; importacao na sessao autenticada do solicitante."""
import csv
import hashlib
import io
import hmac
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.request import Request, urlopen

from sqlalchemy import text

SPREADSHEET_ID = "1mCLD88B_986zsZ16aDEFMK2RNhXKafMfuB99wWebe9k"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
try:
    CSV_TIMEZONE = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    # Windows pode nao ter a base IANA; nao instalar dependencias para esta leitura.
    CSV_TIMEZONE = timezone(timedelta(hours=-3))
CONTEXT_SALT = "portal-bi-forms-import-context-v1"
CONTEXT_MAX_AGE = 12 * 60 * 60
HEADERS = (
    "Carimbo de data/hora", "Nome", "E-mail", "Telefone", "Setor", "Tipo de Solicitação",
    "Em qual BI e tela será o ajuste", "Selecione o tipo de ajuste",
    "Descreva brevemente o ajuste necessário", "Adicione anexos do Ajuste",
    "Em qual BI e tela será a melhoria", "Descreva brevemente a melhoria",
    "Nome Completo do usuário", "E-mail", "Quais relatórios o usuário terá acesso?",
    "Adicione anexos da Melhoria",
)


def reader_config():
    # Sem chave Google ou Apps Script. A flag e apenas uma pausa opcional.
    if os.getenv("PORTAL_FORMS_IMPORT_ENABLED", "true").strip().lower() in {"false", "0", "off", "no"}:
        return None
    return CSV_URL


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Carimbo de data/hora inválido.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Carimbo de data/hora deve conter data e fuso em ISO 8601.") from error
    if result.tzinfo is None:
        raise ValueError("Carimbo de data/hora sem fuso.")
    return result.astimezone(timezone.utc)


def new_context(serializer, user, session_token, since):
    session_hash = hashlib.sha256(session_token.encode()).hexdigest()
    return serializer.dumps({"uid": int(user["usuario_id"]), "since": since.isoformat(),
                             "session": session_hash}, salt=CONTEXT_SALT)


def read_context(serializer, token, user, session_token):
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise ValueError("Contexto de solicitação inválido.")
    data = serializer.loads(token, salt=CONTEXT_SALT, max_age=CONTEXT_MAX_AGE)
    if int(data.get("uid", 0)) != int(user["usuario_id"]):
        raise ValueError("O contexto pertence a outra sessão de solicitante.")
    if not hmac.compare_digest(str(data.get("session", "")), hashlib.sha256(session_token.encode()).hexdigest()):
        raise ValueError("O contexto pertence a outro login.")
    since = utc_timestamp(data.get("since"))
    if since > datetime.now(timezone.utc):
        raise ValueError("Contexto com data futura.")
    return since


def csv_timestamp(value):
    try:
        return utc_timestamp(value)
    except ValueError:
        for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(value.strip(), pattern).replace(tzinfo=CSV_TIMEZONE).astimezone(timezone.utc)
            except ValueError:
                continue
    raise ValueError("Carimbo do CSV inválido. Esperado dia/mês/ano no fuso de Brasília.")


def fetch_rows(config, email, since):
    """GET publico, sem cookies, token do Portal, segredo ou transacao SQL aberta."""
    if config != CSV_URL:
        raise ValueError("Endereço da planilha não permitido.")
    req = Request(CSV_URL, headers={"Accept": "text/csv"}, method="GET")
    with urlopen(req, timeout=20) as response:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        content = response.read(1024 * 1024 + 1)
    if "text/html" in content_type:
        raise ValueError("O endereço não retornou CSV público da planilha.")
    if len(content) > 1024 * 1024:
        raise ValueError("CSV da planilha excede o limite de leitura de 1 MB.")
    parsed = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    headers = next(parsed, [])
    # Lista ordenada: DictReader perderia um dos dois campos E-mail.
    if [_canonical(h) for h in headers[:16]] != [_canonical(h) for h in HEADERS]:
        raise ValueError("As colunas do CSV não correspondem ao mapeamento configurado.")
    rows = []
    wanted = email.strip().lower()
    for values in parsed:
        if len(values) < 3 or values[2].strip().lower() != wanted:
            continue
        created = csv_timestamp(values[0])
        if created < since:
            continue
        if len(rows) >= 100:
            raise ValueError("Mais de 100 respostas do solicitante no período.")
        values = (values + [""] * 16)[:16]
        values[0] = created.isoformat()
        # Origem logica fixa: aba padrao do CSV; nenhuma celula e modificada.
        rows.append({"sheetId": "0", "values": values})
    return {"ok": True, "spreadsheetId": SPREADSHEET_ID, "headers": headers, "rows": rows}


def _canonical(value):
    return " ".join(unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower().split())


def prepare_rows(source, user, since, now=None):
    """Valida novamente fonte, ordem de colunas, janela e PRIMEIRO E-mail."""
    if source.get("spreadsheetId") != SPREADSHEET_ID:
        raise ValueError("Planilha de origem não permitida.")
    headers = source.get("headers")
    if not isinstance(headers, list) or [_canonical(h) for h in headers[:16]] != [_canonical(h) for h in HEADERS]:
        raise ValueError("As colunas da planilha não correspondem ao mapeamento configurado.")
    rows = source.get("rows")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Lote da planilha inválido ou acima de 100 respostas.")
    email = str(user["email"]).strip().lower()
    until = now or datetime.now(timezone.utc)
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("values"), list) or len(row["values"]) < 16:
            raise ValueError("Linha da planilha inválida.")
        values = row["values"]
        if any(not isinstance(v, str) or len(v) > 30000 for v in values[:16]):
            raise ValueError("Conteúdo da resposta inválido ou muito extenso.")
        # Coluna 3 identifica o solicitante. Coluna 14 e o usuario de um pedido de acesso.
        if values[2].strip().lower() != email:
            continue
        created = utc_timestamp(values[0])
        if created < since or created > until:
            continue
        sheet = str(row.get("sheetId", ""))
        if not re.fullmatch(r"[0-9]{1,15}", sheet):
            raise ValueError("Aba de origem inválida.")
        if not values[4].strip() or not values[5].strip():
            raise ValueError("Resposta sem setor ou tipo de solicitação.")
        key = hashlib.sha256(json.dumps([sheet, created.isoformat(), email], separators=(",", ":")).encode()).hexdigest()
        details = []
        for index in range(6, 16):
            value = values[index].strip()
            if value:
                label = "E-mail do usuário solicitado" if index == 13 else HEADERS[index]
                details.append(label + ": " + value)
        if not details:
            raise ValueError("Resposta sem descrição da solicitação.")
        subject = values[6].strip() or values[10].strip() or values[12].strip()
        title = values[5].strip() + (" — " + subject if subject else "")
        result.append({"key": key, "title": title[:250], "type": values[5].strip()[:100],
                       "sector": values[4].strip()[:150], "contact": values[3].strip()[:200],
                       "description": "\n\n".join(details), "created": created})
    return result


def persist_rows(conn, user, rows, number_for):
    """Somente inserts: nao sobrescreve status e nao ressuscita chamados excluidos."""
    # Lock antes dos recibos evita deadlock entre lotes sobrepostos em ordens distintas.
    conn.execute(text("SELECT pg_advisory_xact_lock(742013, 2)"))
    current = conn.execute(text("""
        SELECT id AS usuario_id, nome, email, ativo FROM public.usuarios
        WHERE id = :uid AND ativo = TRUE FOR SHARE
    """), {"uid": int(user["usuario_id"])}).mappings().first()
    if not current or str(current["email"]).lower() != str(user["email"]).lower():
        raise PermissionError("Sessão do solicitante alterada ou bloqueada.")
    imported = 0
    for row in rows:
        claimed = conn.execute(text("""
            INSERT INTO public.chamados_forms_importacoes (origem, resposta_key)
            VALUES (:source, :key) ON CONFLICT (origem, resposta_key) DO NOTHING
            RETURNING resposta_key
        """), {"source": SPREADSHEET_ID, "key": row["key"]}).scalar()
        if claimed is None:
            continue
        # IDs inteiros seguros tambem no Number do JavaScript; fora da faixa Date.now().
        for attempt in range(3):
            ticket_id = (1 << 51) + secrets.randbits(51)
            if conn.execute(text("SELECT id FROM public.chamados WHERE id = :id"), {"id": ticket_id}).scalar() is None:
                break
        else:
            raise RuntimeError("Não foi possível reservar identificador do chamado.")
        number = number_for(conn, ticket_id)
        conn.execute(text("""
            INSERT INTO public.chamados (
                id, numero, titulo, tipo, setor, descricao, tipo_demanda,
                solicitante_id, solicitante_nome, solicitante_contato, solicitante_email,
                status, prioridade, anexos, comentarios, checklist, tags, criado_em, atualizado_em
            ) VALUES (
                :id, :number, :title, :type, :sector, :description, 'chamado',
                :uid, :name, :contact, :email, 'awaiting_manager', 'Média',
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :created, NOW()
            )
        """), {**row, "id": ticket_id, "number": number, "uid": current["usuario_id"],
                 "name": current["nome"], "email": current["email"]})
        conn.execute(text("""
            INSERT INTO public.historico_chamados (chamado_id, usuario_id, usuario_nome, acao, detalhe, criado_em)
            VALUES (:id, :uid, :name, 'Importado do Google Forms',
                    'Importação na sessão autenticada do solicitante; aguardando aprovação.', NOW())
        """), {"id": ticket_id, "uid": current["usuario_id"], "name": current["nome"]})
        conn.execute(text("""
            UPDATE public.chamados_forms_importacoes SET chamado_id = :id
            WHERE origem = :source AND resposta_key = :key
        """), {"id": ticket_id, "source": SPREADSHEET_ID, "key": row["key"]})
        imported += 1
    return imported
