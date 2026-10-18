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
                           │ 3. Chunks + Embeddings     │
                           ▼                            │
               ┌──────────────────────────────────────┐ │
               │ SQLite: data/documents.db            │ │
               │ • Tabla documents                    │ │
               │ • Tabla document_chunks (BLOBs float)│◄┘
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

El sistema se estructura en dos módulos principales en Python:

### 1. `pdf-chatbot.py` (Capa de Presentación y Orquestación de IA)
Es el punto de entrada de la aplicación ejecutado mediante `streamlit run pdf-chatbot.py`.
- **Líneas 1-26:** Importaciones de bibliotecas y módulos de LangChain, Google Gemini, Streamlit y RapidOCR.
- **Líneas 27-35 (Sección 0):** Invoca `database.init_databases()` para verificar y crear las bases de datos "al vuelo".
- **Líneas 36-47 (Sección 1):** Carga y resuelve la clave de API de Gemini (`GOOGLE_API_KEY`).
- **Líneas 48-108 (Sección 2):** Motor de OCR local con caché en memoria (`@st.cache_resource`) y función de extracción resiliente con fallback multimodal.
- **Líneas 109-216 (Sección 3):** Construcción de la interfaz web en Streamlit, barra lateral de configuración, menú desplegable de selección de documentos previos y carga de nuevos archivos.
- **Líneas 217-386 (Sección 4):** Lógica de extracción híbrida (digital vs OCR), segmentación semántica en fragmentos (`chunks`), cálculo de embeddings con Gemini por lotes, guardado en SQLite y construcción del índice FAISS.
- **Líneas 387-581 (Sección 5):** Interfaz conversacional activa, gestión de historial persistente con `st.chat_message`, cadena RAG con recuperación MMR (`k=4`) y fallback automático de modelos LLM.

### 2. `database.py` (Capa de Persistencia y Almacén Vectorial)
Módulo encargado de interactuar directamente con SQLite mediante el conector nativo `sqlite3` de Python:
- **Líneas 1-26:** Definición de rutas absolutas hacia `data/documents.db` y `data/chat_history.db`.
- **Líneas 28-101 (`init_databases`):** Crea el directorio `data/` y ejecuta los esquemas DDL con índices y modo WAL.
- **Líneas 104-106 (`calculate_file_hash`):** Calcula el hash SHA-256 de los bytes del PDF para deduplicación.
- **Líneas 109-267:** Operaciones CRUD sobre `documents.db` (consulta de lista, inserción por lotes con vectores serializados a `BLOB`, reconstrucción de FAISS y purgado en cascada).
- **Líneas 270-305:** Operaciones sobre `chat_history.db` (guardado de mensajes, consulta cronológica y borrado de chat).

---

## ⚡ El Ciclo de Vida Reactivo de Streamlit

Streamlit reejecuta el script completo de arriba a abajo cada vez que el usuario interactúa (por ejemplo, al seleccionar un documento, pulsar un botón o enviar una pregunta por el chat):

1. **Persistencia entre Recargas (`st.session_state`):**
   - El índice vectorial en memoria `vector_store`, el ID del documento activo `active_doc_id` y el nombre `active_doc_name` se almacenan en `st.session_state` para evitar recargas redundantes.
2. **Independencia de la Base de Datos:**
   - Si el usuario recarga la pestaña del navegador o reinicia el servidor, el estado en memoria se reinicia, pero **los datos no se pierden**: la aplicación lee `database.get_all_documents()` y permite continuar exactamente donde se quedó en 1 clic.
