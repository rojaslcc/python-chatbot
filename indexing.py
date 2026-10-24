"""Indexacion Gemini reanudable, sin dependencias de la interfaz Streamlit.

SQLite conserva la extraccion y los vectores confirmados; este modulo solicita
solo los pendientes y comunica el progreso mediante un callback. Una pausa no
publica un documento incompleto ni borra los lotes anteriores. La interfaz decide
cuando reanudar y cuando publicar el resultado mediante database.save_document().
"""

import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable

import numpy as np
from google.genai.errors import APIError
from google.genai import types
from langchain_google_genai import GoogleGenerativeAIEmbeddings

import database

EMBEDDING_MODEL = "models/gemini-embedding-001"


# ==============================================================================
# 1. CONFIGURACION Y RECUPERACION DE TRABAJOS
# Se separa la identidad del contenido de los limites operativos: ajustar el ritmo
# al reanudar no debe invalidar los vectores que ya fueron confirmados.
# ==============================================================================
@dataclass(frozen=True)
class IndexingSettings:
    """Presupuesto local de envio, independiente de las cuotas reales de Google.

    Cada fragmento cuenta como un contenido, incluso dentro de un lote.
    max_retries excluye el intento inicial y max_wait_seconds limita cada espera,
    no el tiempo total del documento. La configuracion es inmutable durante una
    ejecucion, pero puede cambiarse al reanudar sin invalidar los vectores.
    """

    contents_per_minute: int = 60
    batch_size: int = 10
    max_retries: int = 3
    max_wait_seconds: float = 120

    def __post_init__(self):
        # Un lote mayor al presupuesto enviaria de golpe mas contenidos que los
        # permitidos para un minuto, aunque despues se aplicara una espera.
        if self.contents_per_minute < 1:
            raise ValueError("El limite de contenidos por minuto debe ser positivo.")
        if not 1 <= self.batch_size <= min(100, self.contents_per_minute):
            raise ValueError("El lote debe estar entre 1 y min(100, contenidos/minuto).")
        if not 0 <= self.max_retries <= 10:
            raise ValueError("Los reintentos deben estar entre 0 y 10.")
        if not math.isfinite(self.max_wait_seconds) or self.max_wait_seconds <= 0:
            raise ValueError("La espera maxima debe ser positiva y finita.")


class IndexingPaused(RuntimeError):
    """El avance persiste y puede reanudarse sin repetir los lotes confirmados."""


def job_id_for(file_hash: str, ocr_images: bool) -> str:
    """Identifica el contenido y la configuracion que producen los vectores.

    El ritmo y los reintentos no forman parte del ID porque no alteran el texto
    ni el espacio vectorial. La opcion de OCR si cambia la extraccion; incluirla
    impide reutilizar accidentalmente un trabajo con contenido diferente.
    """
    # Cambiar la version si cambia la extraccion, segmentacion o dimension del vector.
    config = json.dumps([file_hash, ocr_images, EMBEDDING_MODEL, "chunks-1000-200-v1"])
    return hashlib.sha256(config.encode()).hexdigest()


# ==============================================================================
# 2. CLASIFICACION DE ERRORES Y ESPERAS DEL SERVICIO
# Una pausa conserva el trabajo; un reintento solo procede si el error pertenece
# a la lista transitoria y no identifica una cuota diaria agotada.
# ==============================================================================
def retry_details(error: Exception) -> tuple[bool, float, str]:
    """Devuelve (reintentable, espera minima en segundos, motivo visible).

    Inspecciona la causa APIError original aunque LangChain la envuelva. Los
    errores desconocidos no se consideran transitorios: se muestran al usuario
    en lugar de repetir solicitudes por problemas de credenciales o certificados.
    """
    cause = error
    while not isinstance(cause, APIError) and cause.__cause__ is not None:
        cause = cause.__cause__
    if not isinstance(cause, APIError):
        return False, 0, "Error no transitorio de embeddings."
    code = cause.code
    payload = cause.details or {}
    details = payload.get("error", {}).get("details", []) if isinstance(payload, dict) else []
    delay = 0.0
    # Retry-After puede ser una duracion o una fecha absoluta. Se combina con
    # RetryInfo tomando el mayor plazo, para respetar ambas indicaciones.
    response = getattr(cause, "response", None)
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                parsed = float(retry_after)
                if math.isfinite(parsed):
                    delay = max(delay, parsed)
            except ValueError:
                try:
                    delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    # Una cabecera invalida no impide consultar RetryInfo.
                    pass
    for detail in details:
        # Un 429 diario no se resuelve con una espera corta. Se detecta mediante
        # los identificadores estructurados, sin depender del idioma del mensaje.
        for violation in detail.get("violations", []):
            quota = str(violation.get("quotaId", "")).lower()
            metric = str(violation.get("quotaMetric", "")).lower()
            if "perday" in quota or "daily" in quota or "per_day" in metric:
                return False, 0, "Cuota diaria agotada; revisa el plan y los limites en AI Studio."
        raw_delay = detail.get("retryDelay")
        if isinstance(raw_delay, str) and raw_delay.endswith("s"):
            try:
                parsed = float(raw_delay[:-1])
            except ValueError:
                continue
            if math.isfinite(parsed):
                delay = max(delay, parsed)
    return code in (429, 500, 502, 503, 504), delay, f"Gemini devolvio HTTP {code}."


# ==============================================================================
# 3. ADAPTADOR GEMINI Y EJECUCION REANUDABLE
# La llamada remota no publica documentos: primero se valida el lote y se guarda
# su checkpoint; solo el llamador publica cuando todos los vectores estan listos.
# ==============================================================================
def embed_batch(model: GoogleGenerativeAIEmbeddings, texts: list[str]) -> list[list[float]]:
    """Envia un lote con el mismo modelo y dimensionalidad usados por LangChain.

    Se usa el cliente existente para conservar credenciales y configuracion TLS.
    La tarea RETRIEVAL_DOCUMENT mantiene la semantica de indexacion; las preguntas
    siguen usando la integracion de embeddings del recuperador. Esta funcion no
    guarda avances: el llamador valida y confirma el lote completo.
    """
    # Opciones por peticion: evita multiplicar los reintentos del SDK y de la aplicacion.
    result = model.client.models.embed_content(
        model=model.model,
        contents=[types.Content(parts=[types.Part(text=text)]) for text in texts],
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=model.output_dimensionality,
            http_options=types.HttpOptions(
                timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ),
    )
    if result.embeddings is None or any(e.values is None for e in result.embeddings):
        raise IndexingPaused("Gemini no devolvio los vectores solicitados.")
    return [list(e.values) for e in result.embeddings]


def index_job(
    job_id: str,
    embed: Callable[[list[str]], list[list[float]]],
    api_key: str,
    settings: IndexingSettings,
    report: Callable[[int, int, str], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> list[dict]:
    """Completa un trabajo persistido y devuelve sus fragmentos en orden.

    embed recibe textos y devuelve un vector por texto. report recibe el numero
    de fragmentos confirmados, el total y un mensaje; no necesita Streamlit.
    sleep y clock se pueden sustituir para comprobar esperas sin consumir API.

    IndexingPaused deja intactos los puntos de recuperacion y conserva la causa
    tecnica cuando existe. Si Google responde pero el proceso termina antes del
    commit, el lote puede repetirse: no se garantiza consumo exactamente una vez.
    """
    job = database.get_indexing_job(job_id)
    if job is None:
        raise ValueError("No existe el trabajo de indexacion.")
    # NULL en SQLite se recupera como None y es la marca de trabajo pendiente.
    # No se usa el estado en memoria de Streamlit como fuente de recuperacion.
    chunks = job["chunks"]
    pending = [c for c in chunks if c["embedding"] is None]
    completed = len(chunks) - len(pending)
    # El ambito permite compartir la agenda sin persistir la clave en claro.
    # No representa la cuota completa del proyecto ni el trafico de otros clientes.
    scope = hashlib.sha256(f"{api_key}:{EMBEDDING_MODEL}".encode()).hexdigest()
    report(completed, len(chunks), "Avance recuperado de SQLite.")
    for start in range(0, len(pending), settings.batch_size):
        batch = pending[start:start + settings.batch_size]
        for attempt in range(settings.max_retries + 1):
            # Tambien los reintentos reservan turno: una solicitud fallida puede
            # haber consumido cuota. La espera ocurre fuera de la transaccion SQL.
            wait = database.reserve_embedding_slot(
                scope, len(batch), settings.contents_per_minute, clock(),
                settings.max_wait_seconds,
            )
            if wait > settings.max_wait_seconds:
                raise IndexingPaused("Hay solicitudes en cola. Espera antes de reanudar.")
            if wait > 0:
                report(completed, len(chunks), f"Control de cuota: espera de {wait:.0f} s.")
                sleep(wait)
            try:
                vectors = embed([c["content"] for c in batch])
            except IndexingPaused:
                raise
            except Exception as error:
                transient, server_delay, reason = retry_details(error)
                if not transient or attempt == settings.max_retries:
                    raise IndexingPaused(
                        f"{reason} Indexacion pausada; los lotes completados estan guardados."
                    ) from error
                # La espera sugerida por Google nunca se acorta. La variacion
                # aleatoria evita que varios clientes reintenten al mismo tiempo.
                delay = max(server_delay, min(60, 2 ** attempt) + random.uniform(0, 1))
                if delay > settings.max_wait_seconds:
                    raise IndexingPaused(
                        f"Google solicita esperar {delay:.0f} s. Reanuda mas tarde."
                    ) from error
                report(
                    completed, len(chunks),
                    f"{reason} Reintento {attempt + 1}/{settings.max_retries} en {delay:.0f} s.",
                )
                sleep(delay)
                continue
            # Validar antes de modificar el lote evita checkpoints parciales o
            # vectores incompatibles con los ya persistidos para este documento.
            if len(vectors) != len(batch):
                raise IndexingPaused("Gemini devolvio un lote incompleto; no se guardo ese lote.")
            expected_dim = next(
                (len(c["embedding"]) for c in chunks if c["embedding"] is not None), None
            )
            for chunk, vector in zip(batch, vectors):
                if (not vector or not np.isfinite(vector).all()
                        or (expected_dim is not None and len(vector) != expected_dim)):
                    raise IndexingPaused("Gemini devolvio vectores invalidos o incompatibles.")
                expected_dim = len(vector)
            for chunk, vector in zip(batch, vectors):
                chunk["embedding"] = vector
            database.save_indexing_batch(job_id, batch)
            # El progreso visible avanza solo despues del commit, no al recibir
            # la respuesta: asi representa lo que sobrevivira a un reinicio.
            completed += len(batch)
            report(completed, len(chunks), "Lote guardado en SQLite.")
            break
    return chunks
