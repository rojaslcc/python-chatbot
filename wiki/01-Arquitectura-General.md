# 🏗️ 1. Arquitectura General del Sistema

Esta página describe la arquitectura integral del proyecto, el flujo de datos de extremo a extremo, el ciclo de vida de la aplicación y la separación de responsabilidades entre los distintos módulos.

---

## 🧭 Diagrama de Flujo de Datos Global

```text
               ┌─────────────────────────────────────────────────────────────┐
               │                  Usuario (Navegador Web)                    │
               └──────────────┬───────────────────────────────▲──────────────┘
                              │ 1. Selección / Subida de PDF  │ 7. Respuesta
                              ▼                               │    formateada
               ┌───────────────────────────────┐              │
               │   Streamlit Web Server        │──────────────┘
               │   (pdf-chatbot.py)            │
               └───────────┬───────────────────┘
                           │ 2. ¿El archivo ya existe en SQLite?
                           ├────────────────────────────┐
             [NO: Nuevo PDF]                            │ [SÍ: Archivo Existente]
                           ▼                            ▼
               ┌───────────────────────┐   ┌───────────────────────────┐
               │ Extracción Híbrida    │   │ Carga instantánea de      │
               │ • pdfplumber (digital)│   │ vectores precalculados    │
               │ • RapidOCR (imágenes) │   │ (0 API calls, 0s OCR)     │
               └───────────┬───────────┘   └────────────┬──────────────┘
                           │ 3. Crear/recuperar trabajo │
                           │ Lotes + ritmo/reintentos  │
                           │ Guardar cada lote         │
                           ▼                            │
               ┌──────────────────────────────────────┐ │
               │ SQLite: data/documents.db            │ │
               │ • Tabla documents                    │ │
               │ • Tabla document_chunks (BLOBs float)│◄┘
               │ • indexing_jobs / indexing_chunks   │
               │ • embedding_schedule                │
               └───────────┬──────────────────────────┘
                           │ 4. Reconstrucción en memoria
                           ▼
               ┌──────────────────────────────────────┐
               │ FAISS Vector Store en Memoria        │
               └───────────┬──────────────────────────┘
                           │ 5. Usuario pregunta (st.chat_input)
                           ▼
               ┌──────────────────────────────────────┐
               │ LangChain Retrieval (MMR k=4)        │
               │ + Gemini Fallbacks LLM Chain         │
               └───────────┬──────────────────────────┘
                           │ 6. Guardar conversación
                           ▼
               ┌──────────────────────────────────────┐
               │ SQLite: data/chat_history.db         │
               │ • Tabla chat_messages (user / bot)   │
               └──────────────────────────────────────┘
```

---

## 🧩 Separación de Responsabilidades por Módulo

El sistema se estructura en tres módulos principales en Python:

### 1. `pdf-chatbot.py` (Capa de Presentación y Orquestación de IA)
Es el punto de entrada de la aplicación ejecutado mediante `streamlit run pdf-chatbot.py`.
- Inicializa las bases de datos y resuelve la clave de API.
- Extrae texto digital y OCR, conserva páginas y divide en fragmentos.
- Presenta los controles de indexación, los botones **Procesar documento** / **Reanudar indexación**, el progreso y los errores.
- Recupera trabajos pendientes y delega su ejecución a `indexing.index_job()`.
- Publica documentos completos, construye FAISS y ejecuta el chat RAG con MMR (`k=4`) y fallbacks de generación.

### 2. `database.py` (Capa de Persistencia y Almacén Vectorial)
Módulo encargado de interactuar directamente con SQLite mediante el conector nativo `sqlite3` de Python:
- `init_databases()` crea las tablas e índices de forma compatible con bases existentes.
- `create_indexing_job()` y `get_indexing_job()` guardan y recuperan la extracción completa.
- `save_indexing_batch()` confirma vectores por lote; `reserve_embedding_slot()` coordina el ritmo entre sesiones.
- `save_document()` publica metadatos y vectores, y elimina el trabajo temporal en la misma transacción.
- Reconstruye FAISS desde vectores guardados y gestiona documentos e historial.

### 3. `indexing.py` (Motor de Indexación Reanudable)

No depende de Streamlit. `IndexingSettings` define el ritmo y los límites;
`job_id_for()` identifica archivo y configuración; `index_job()` procesa solo
fragmentos pendientes. `embed_batch()` usa el cliente Gemini del modelo de
LangChain con tarea `RETRIEVAL_DOCUMENT`, timeout de 60 segundos y un solo intento
del SDK. `retry_details()` interpreta los errores estructurados de Google y
`IndexingPaused` comunica una pausa recuperable a la interfaz.

---

## Ciclo de Vida de un Documento Grande

```text
Archivo cargado
  ├─ Publicado por hash → cargar vectores → chat
  └─ No publicado → pulsar Procesar / Reanudar
       ├─ Sin trabajo previo → extracción/OCR → fragmentos → guardar trabajo
       └─ Con trabajo previo → recuperar texto y vectores guardados
            → reservar turno → enviar lote pendiente → validar → confirmar lote
                 ├─ error temporal → espera + reintento acotado
                 ├─ pausa → conservar trabajo → reanudar manualmente
                 └─ todos completos → publicación transaccional → FAISS → chat
```

Los puntos de recuperación comienzan al guardar la extracción completa y avanzan
por lote confirmado. No hay extracción incremental por página ni ejecución en
segundo plano: después de una interrupción se continúa al volver a subir el archivo
y pulsar el botón. El archivo, la opción de OCR, el modelo y la versión de
procesamiento determinan qué trabajo recuperar.

---

## ⚡ El Ciclo de Vida Reactivo de Streamlit

Streamlit reejecuta el script completo de arriba a abajo cada vez que el usuario interactúa (por ejemplo, al seleccionar un documento, pulsar un botón o enviar una pregunta por el chat):

1. **Persistencia entre Recargas (`st.session_state`):**
   - El índice vectorial en memoria `vector_store`, el ID del documento activo `active_doc_id` y el nombre `active_doc_name` se almacenan en `st.session_state` para evitar recargas redundantes.
2. **Independencia de la Base de Datos:**
   - Tras un reinicio, `database.get_all_documents()` devuelve solo documentos completos. Para un trabajo pendiente se vuelve a cargar el mismo PDF con la misma opción de OCR y se pulsa **Reanudar indexación**; los textos y lotes confirmados persisten aunque `st.session_state` se pierda.

---

## 🧭 Navegación entre Capítulos

| [🏠 Inicio (Home)](Home) | [Siguiente: 2. Persistencia y Bases de Datos SQLite ➡️](02-Persistencia-y-Bases-de-Datos) |
| :--- | :--- |
