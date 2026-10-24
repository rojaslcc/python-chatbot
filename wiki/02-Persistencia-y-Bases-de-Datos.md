# 💾 2. Persistencia y Bases de Datos SQLite

Esta página describe las dos bases de datos **SQLite**, los vectores `BLOB`, los trabajos de indexación reanudables y la publicación transaccional de documentos completos.

---

## 🗃️ ¿Por qué Dos Bases de Datos SQLite Separadas?

Para garantizar alta cohesión y bajo acoplamiento:
1. **`data/documents.db` (Documentos, Vectores y Trabajos):** Contiene metadatos, textos, vectores, trabajos incompletos y la agenda de envíos. No almacena el PDF original.
2. **`data/chat_history.db` (Historial de Conversaciones):** Contiene datos dinámicos generados por la interacción del usuario. Si un usuario decide borrar su historial o exportar solo sus preguntas, la base de datos de documentos permanece intacta sin fragmentación.

Configuración de persistencia:
- **`PRAGMA journal_mode = WAL;` (Write-Ahead Logging):** Permite lecturas concurrentes sin bloquear escrituras.
- **`PRAGMA foreign_keys = ON;`:** Se activa en las conexiones que crean o eliminan relaciones en `documents.db`, incluida la publicación del trabajo y su borrado en cascada.

---

## 🏗️ Creación Automática "al Vuelo" (`database.init_databases`)

Cuando la aplicación arranca en `pdf-chatbot.py`, se ejecuta:

```python
db_status = database.init_databases()
```

La función `init_databases()` realiza las siguientes acciones:

```python
os.makedirs(DATA_DIR, exist_ok=True)
docs_created = not os.path.exists(DOCUMENTS_DB_PATH)
chat_created = not os.path.exists(CHAT_HISTORY_DB_PATH)
```

1. Crea la carpeta local `data/` si aún no existe.
2. Crea `documents`, `document_chunks`, `indexing_jobs`, `indexing_chunks` y `embedding_schedule` si no existen, conservando los registros previos.
3. Crea los índices `idx_documents_hash` y `idx_chunks_doc_id` para acelerar las búsquedas por hash o ID.
4. Abre la conexión a `data/chat_history.db` y genera la tabla `chat_messages` junto con el índice `idx_chat_doc_id`.
5. Retorna un diccionario con el estado de creación: `{"documents_created": bool, "chat_created": bool}`.

---

## 📐 Esquema DDL SQL Detallado

### 1. Base de Datos `data/documents.db`

#### Tabla `documents`
Almacena la cabecera y metadatos globales de cada PDF procesado:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,               -- Hash SHA-256 truncado a 16 caracteres
    filename TEXT NOT NULL,            -- Nombre del archivo PDF (ej: reporte.pdf)
    file_hash TEXT UNIQUE NOT NULL,    -- Hash SHA-256 completo de 64 caracteres hex
    file_size INTEGER DEFAULT 0,       -- Tamaño del archivo en bytes
    total_pages INTEGER DEFAULT 0,     -- Número total de páginas
    total_chunks INTEGER DEFAULT 0,    -- Total de fragmentos de texto generados
    has_ocr INTEGER DEFAULT 0,         -- 1 si requirió OCR, 0 si fue solo texto digital
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Tabla `document_chunks`
Almacena los fragmentos de texto y su vector semántico:

```sql
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,      -- Orden posicional del chunk dentro del doc
    page_number INTEGER DEFAULT 1,     -- Número de página origen para citaciones
    content TEXT NOT NULL,             -- Texto del fragmento (hasta 1000 caracteres)
    embedding BLOB NOT NULL,           -- Vector de floats serializado en formato binario
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);
```

---

## Trabajos Pendientes y Agenda de Envíos

Estas tablas comparten `documents.db` con los documentos publicados:

```sql
CREATE TABLE IF NOT EXISTS indexing_jobs (
    id TEXT PRIMARY KEY,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexing_chunks (
    job_id TEXT NOT NULL REFERENCES indexing_jobs(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,
    PRIMARY KEY (job_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS embedding_schedule (
    scope TEXT PRIMARY KEY,
    next_request_at REAL NOT NULL
);
```

| Tabla | Contenido y propósito |
| :--- | :--- |
| `indexing_jobs` | ID SHA-256 calculado por `indexing.job_id_for()`. `metadata` guarda JSON con `filename`, `total_pages`, `has_ocr` y `model`. |
| `indexing_chunks` | Texto y página de cada fragmento. `embedding IS NULL` significa pendiente; un BLOB representa un vector confirmado. |
| `embedding_schedule` | Próximo turno de envío por ámbito (`scope`), un SHA-256 de clave y modelo; no se guarda la clave en claro. |

### Puntos de recuperación

1. `create_indexing_job()` guarda todos los fragmentos extraídos en una transacción.
2. `get_indexing_job()` recupera textos y vectores en orden; `index_job()` solicita solo los que tienen vector nulo.
3. `save_indexing_batch()` confirma un lote entero en una transacción, después de validar cantidad, valores finitos y dimensión consistente.
4. `save_document(..., indexing_job_id=...)` publica los metadatos y vectores completos, y elimina el trabajo temporal. El borrado de sus fragmentos pendientes se realiza en cascada dentro de esa misma transacción.

`get_all_documents()` consulta `documents`, no `indexing_jobs`: un PDF parcialmente
vectorizado no se ofrece al chat. Reiniciar la aplicación no elimina estos trabajos.
Una interrupción antes del primer guardado requiere repetir extracción/OCR; después,
solo el lote no confirmado podría repetirse. No se garantiza consumo de API
exactamente una vez si Google respondió pero el proceso terminó antes de guardar.

El ID combina hash del PDF, opción de OCR en imágenes, modelo y versión de
procesamiento (`chunks-1000-200-v1`). Cambiar el ritmo o el tamaño de lote no
cambia ese ID; cambiar OCR sí. Si se modifica extracción, segmentación o dimensión
en código, debe actualizarse la versión para no reutilizar trabajos incompatibles.

### Coordinación del ritmo

`reserve_embedding_slot()` usa `BEGIN IMMEDIATE` para reservar un turno de forma
serializada entre sesiones con la misma base, clave y modelo. Se reserva tiempo
proporcional a los contenidos del lote; si la espera supera el máximo permitido,
se pausa sin ampliar la cola. Esto no contabiliza el consumo de otros clientes,
otras claves del proyecto ni las consultas del chat.

---

## 🧬 ¿Cómo Funciona la Base Vectorial en SQLite?

El modelo `models/gemini-embedding-001` devuelve vectores numéricos. La aplicación no fija una dimensión de salida: conserva la recibida y comprueba su consistencia durante la indexación. Los vectores de preguntas y documentos deben usar un modelo y configuración compatibles.

### 1. Serialización e Inserción (`save_document` / `save_indexing_batch`)
Al guardar los chunks en `save_document()`, cada lista de Python `[float, float, ...]` se convierte en un arreglo NumPy de tipo `float32` y se transforma a bytes crudos mediante `.tobytes()`:

```python
emb_blob = np.array(chk["embedding"], dtype=np.float32).tobytes()
```

- Cada float32 ocupa 4 bytes; el tamaño del vector es su dimensión multiplicada por 4, sin contar texto ni sobrecarga de SQLite.
- Los vectores se insertan en bloque con `executemany`.

### 2. Deserialización y Carga (`load_vectorstore_from_db`)
Al cargar un documento previo con `load_vectorstore_from_db()`:

```python
for content, emb_blob, page_num in rows:
    vec = np.frombuffer(emb_blob, dtype=np.float32).tolist()
    text_embeddings.append((content, vec))
    metadatas.append({"page": page_num})

vectorstore = FAISS.from_embeddings(
    text_embeddings=text_embeddings,
    embedding=embeddings_model,
    metadatas=metadatas
)
```

**Resultado:** FAISS se reconstruye en RAM sin llamadas a Gemini. El tiempo y la memoria dependen del número y dimensión de los vectores; no se garantiza una duración fija.

---

## 🗑️ Operaciones de Purgado

### 1. `delete_document(doc_id)`
Elimina por completo todos los registros relacionados con un archivo en ambas bases de datos:

```python
with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM document_chunks WHERE document_id = ?;", (doc_id,))
    cursor.execute("DELETE FROM documents WHERE id = ?;", (doc_id,))
    conn.commit()

with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE document_id = ?;", (doc_id,))
    conn.commit()
```

El borrado usa transacciones separadas para documentos e historial; no es una única
transacción entre las dos bases. No borra el PDF original ni trabajos pendientes de
otras configuraciones. Actualmente no hay un botón para purgar trabajos pendientes.

### 2. `clear_chat_history(doc_id)`
Limpia únicamente los mensajes de conversación de ese documento en `chat_history.db`, manteniendo el documento y sus vectores intactos:

```python
cursor.execute("DELETE FROM chat_messages WHERE document_id = ?;", (document_id,))
```

---

## 🧭 Navegación entre Capítulos

| [⬅️ Anterior: 1. Arquitectura General](01-Arquitectura-General) | [🏠 Inicio (Home)](Home) | [Siguiente: 3. Extracción y OCR Multimodal ➡️](03-Extraccion-y-OCR-Multimodal) |
| :--- | :--- | :--- |
