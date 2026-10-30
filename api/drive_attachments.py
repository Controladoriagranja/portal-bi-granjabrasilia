"""Envio direto ao Drive sem gravação no banco; helpers legados por compatibilidade."""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import HTTPException

from sqlalchemy import text
from forms_import import SPREADSHEET_ID, CSV_TIMEZONE

FOLDER_ID = "1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW"
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 5


class DriveUploadError(RuntimeError):
    """Motivo seguro para a tela/log: nunca incluir corpo ou URL de uma exceção."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def upload_status():
    url = os.getenv("PORTAL_DRIVE_UPLOAD_URL", "").strip()
    secret = os.getenv("PORTAL_DRIVE_UPLOAD_SECRET", "").strip()
    if not url:
        return "missing_url"
    if not secret:
        return "missing_secret"
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec", url):
        return "invalid_url"
    if len(secret) < 32:
        return "secret_too_short"
    return "ready"


def upload_config():
    if upload_status() != "ready":
        return None
    return os.environ["PORTAL_DRIVE_UPLOAD_URL"].strip(), os.environ["PORTAL_DRIVE_UPLOAD_SECRET"].strip()


def json_list(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


def merge_managed(existing, incoming):
    # O salvamento de uma cópia antiga do chamado não pode apagar o arquivo real.
    return ([a for a in json_list(incoming) if not isinstance(a, dict) or a.get("storage") != "portal-drive"] +
            [a for a in json_list(existing) if isinstance(a, dict) and a.get("storage") == "portal-drive"])


def own_targets(conn, user, since):
    """Somente identificadores dos pedidos do próprio usuário nesta sessão."""
    rows = conn.execute(text("""
        SELECT c.id, c.numero, c.titulo FROM public.chamados c
        JOIN public.chamados_forms_importacoes f ON f.chamado_id = c.id
        WHERE f.origem = :source AND c.solicitante_id = :uid
          AND LOWER(c.solicitante_email) = :email AND c.criado_em >= :since
        ORDER BY c.criado_em DESC, c.id DESC LIMIT 20
    """), {"source": SPREADSHEET_ID, "uid": int(user["usuario_id"]),
           "email": str(user["email"]).strip().lower(), "since": since}).mappings().all()
    return [{"id": str(r["id"]), "number": r["numero"], "title": r["titulo"]} for r in rows]


def authorized_ticket(conn, user, ticket_id, since):
    # Bloqueio/perfil continuam consultados no banco; nenhuma permissão em cache.
    current = conn.execute(text("""
        SELECT id AS usuario_id, nome, email FROM public.usuarios
        WHERE id = :uid AND ativo = TRUE FOR SHARE
    """), {"uid": int(user["usuario_id"])}).mappings().first()
    if not current or current["email"].lower() != str(user["email"]).lower():
        raise PermissionError("Sessão alterada ou bloqueada.")
    ticket = conn.execute(text("""
        SELECT c.id, c.numero, c.anexos FROM public.chamados c
        WHERE c.id = :id AND c.solicitante_id = :uid
          AND LOWER(c.solicitante_email) = :email AND c.criado_em >= :since
          AND EXISTS (SELECT 1 FROM public.chamados_forms_importacoes f
                      WHERE f.chamado_id = c.id AND f.origem = :source)
        FOR UPDATE OF c
    """), {"id": ticket_id, "uid": current["usuario_id"], "email": current["email"].lower(),
           "since": since, "source": SPREADSHEET_ID}).mappings().first()
    if not ticket:
        raise PermissionError("Solicitação indisponível para anexar nesta sessão.")
    return current, ticket


def read_file(storage):
    name = str(storage.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:180]
    if not name:
        raise ValueError("Selecione um arquivo com nome válido.")
    data = storage.stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("O arquivo deve ter conteúdo e no máximo 10 MB.")
    return {"original_name": name, "bytes_size": len(data),
            "mime_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "sha256": hashlib.sha256(data).hexdigest()}, data


def safe_name(value, limit):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")[:limit] or "Arquivo"


def direct_receipt(user, file, started, upload_key):
    """Nome estável para repetir o envio, sem recibo ou gravação no PostgreSQL."""
    if not re.fullmatch(r"[a-f0-9]{32}", upload_key):
        raise ValueError("Identificador do envio inválido.")
    key = hashlib.sha256(json.dumps([int(user["usuario_id"]), started.isoformat(),
        upload_key, file["sha256"], file["original_name"]], ensure_ascii=True).encode()).hexdigest()[:32]
    stamp = started.astimezone(CSV_TIMEZONE).strftime("%Y-%m-%d_%H-%M-%S")
    return {**file, "upload_key": key,
        "stored_name": f'{safe_name(str(user["nome"]), 60)}_{stamp}_{key}_{safe_name(file["original_name"], 120)}'}


def direct_attachment(receipt, file_id):
    return {"key": "drive:" + receipt["upload_key"], "name": receipt["original_name"],
        "size": receipt["bytes_size"], "storage": "portal-drive", "driveName": receipt["stored_name"],
        "url": "https://drive.google.com/file/d/" + file_id + "/view"}


def reserve(conn, user, ticket_id, since, upload_key, file):
    if not re.fullmatch(r"[a-f0-9]{32}", upload_key):
        raise ValueError("Identificador do envio inválido.")
    current, ticket = authorized_ticket(conn, user, ticket_id, since)
    old = conn.execute(text("""
        SELECT * FROM public.chamados_forms_anexos
        WHERE upload_key = :key OR (chamado_id = :id AND usuario_id = :uid
          AND sha256 = :sha256 AND original_name = :original_name)
        ORDER BY criado_em LIMIT 1 FOR UPDATE
    """), {**file, "key": upload_key, "id": ticket_id, "uid": current["usuario_id"]}).mappings().first()
    if old:
        if (old["chamado_id"] != ticket_id or old["usuario_id"] != current["usuario_id"] or
                any(old[k] != file[k] for k in ("sha256", "original_name", "bytes_size"))):
            raise ValueError("Este envio já pertence a outro arquivo ou solicitação.")
        if old["status"] == "done":
            return dict(old)
    pending = conn.execute(text("""
        SELECT COUNT(*) FROM public.chamados_forms_anexos
        WHERE chamado_id = :id AND status = 'pending'
          AND atualizado_em > NOW() - INTERVAL '2 minutes' AND upload_key != :key
    """), {"id": ticket_id, "key": old["upload_key"] if old else upload_key}).scalar_one()
    if len(json_list(ticket["anexos"])) + pending >= MAX_FILES:
        raise ValueError("Máximo de 5 anexos por solicitação. Aguarde os envios em andamento.")
    if old:
        conn.execute(text("UPDATE public.chamados_forms_anexos SET status = 'pending', atualizado_em = NOW() WHERE upload_key = :key"),
                     {"key": old["upload_key"]})
        return dict(old)
    stamp = datetime.now(timezone.utc).astimezone(CSV_TIMEZONE).strftime("%Y-%m-%d_%H-%M-%S")
    stored = f'{safe_name(current["nome"], 60)}_{stamp}_{upload_key}_{safe_name(file["original_name"], 120)}'
    row = {**file, "upload_key": upload_key, "chamado_id": ticket_id, "usuario_id": current["usuario_id"],
           "stored_name": stored, "status": "pending"}
    conn.execute(text("""
        INSERT INTO public.chamados_forms_anexos
          (upload_key, chamado_id, usuario_id, original_name, stored_name, bytes_size, mime_type, sha256)
        VALUES (:upload_key, :chamado_id, :usuario_id, :original_name, :stored_name, :bytes_size, :mime_type, :sha256)
    """), row)
    return row


def send_to_drive(config, receipt, data):
    # Nenhuma conexão SQL fica aberta durante o upload HTTP.
    url, secret = config
    payload = json.dumps({"folder": FOLDER_ID, "key": receipt["upload_key"],
        "name": receipt["stored_name"], "size": len(data), "mime": receipt["mime_type"],
        "sha256": receipt["sha256"], "data": base64.b64encode(data).decode("ascii")},
        ensure_ascii=True, separators=(",", ":"))
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), (stamp + "." + payload).encode(), hashlib.sha256).hexdigest()
    body = json.dumps({"timestamp": stamp, "payload": payload, "signature": signature}).encode()
    req = Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=35) as response:
            raw = response.read(16385)
    except HTTPError as error:
        error.close()
        if error.code in (401, 403):
            raise DriveUploadError("google_access_denied", "O Google negou acesso ao serviço. Confira a implantação do Apps Script: executar como Eu e acesso Qualquer pessoa.") from None
        if error.code in (404, 405):
            raise DriveUploadError("google_deployment_invalid", "A implantação do Apps Script não aceitou o envio. Confira a URL /exec e a implantação como Aplicativo da Web.") from None
        if error.code == 429:
            raise DriveUploadError("google_rate_limit", "O Google limitou os envios temporariamente. Aguarde e tente novamente com os mesmos arquivos.") from None
        raise DriveUploadError("google_http_error", "O serviço do Google retornou um erro. Tente novamente com os mesmos arquivos.") from None
    except TimeoutError:
        raise DriveUploadError("google_timeout", "O Google demorou para confirmar o envio. Tente novamente com os mesmos arquivos para recuperar a confirmação.") from None
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise DriveUploadError("google_timeout", "O Google demorou para confirmar o envio. Tente novamente com os mesmos arquivos.") from None
        raise DriveUploadError("google_connection_failed", "O servidor não conseguiu se conectar ao Google. Tente novamente em alguns instantes.") from None
    except (OSError, HTTPException):
        raise DriveUploadError("google_connection_failed", "A conexão com o Google foi interrompida. Tente novamente com os mesmos arquivos.") from None
    if len(raw) > 16384:
        raise DriveUploadError("google_invalid_response", "O Google retornou uma resposta inesperada. Confira se o Apps Script está publicado como Aplicativo da Web com acesso Qualquer pessoa.")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DriveUploadError("google_invalid_response", "O Google não retornou a confirmação de upload. Confira o acesso Qualquer pessoa e a versão implantada do Apps Script.") from None
    if not isinstance(result, dict):
        raise DriveUploadError("google_invalid_response", "O Google retornou uma confirmação inválida.")
    file_id = str(result.get("fileId") or "")
    if result.get("ok") is not True or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
        if result.get("retry") is True:
            raise DriveUploadError("google_busy", "O serviço está concluindo outro envio. Aguarde alguns segundos e tente novamente.")
        raise DriveUploadError("google_upload_rejected", "O Apps Script recusou o arquivo. Confira se o segredo é igual nos dois locais e se a conta do script pode editar a pasta.")
    return file_id


def finish(conn, user, ticket_id, since, receipt, file_id):
    _, ticket = authorized_ticket(conn, user, ticket_id, since)
    attachments = json_list(ticket["anexos"])
    key = "drive:" + receipt["upload_key"]
    existing = next((a for a in attachments if isinstance(a, dict) and a.get("key") == key), None)
    if existing:
        return existing
    if len(attachments) >= MAX_FILES:
        raise ValueError("A solicitação já tem 5 anexos. O arquivo enviado permanece na pasta do Drive.")
    attachment = {"key": key, "name": receipt["original_name"], "size": receipt["bytes_size"],
        "type": receipt["mime_type"], "storage": "portal-drive", "driveFileId": file_id,
        "driveName": receipt["stored_name"], "url": "https://drive.google.com/file/d/" + file_id + "/view",
        "uploadedAt": datetime.now(timezone.utc).isoformat()}
    attachments.append(attachment)
    conn.execute(text("""
        UPDATE public.chamados SET anexos = CAST(:anexos AS jsonb), atualizado_em = NOW() WHERE id = :id
    """), {"id": ticket_id, "anexos": json.dumps(attachments, ensure_ascii=False)})
    conn.execute(text("""
        UPDATE public.chamados_forms_anexos SET status = 'done', drive_file_id = :file_id,
          atualizado_em = NOW() WHERE upload_key = :key
    """), {"file_id": file_id, "key": receipt["upload_key"]})
    return attachment
