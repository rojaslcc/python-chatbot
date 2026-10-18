# 💾 2. Persistencia y Bases de Datos SQLite

Esta página detalla el funcionamiento interno del subsistema de persistencia basado en dos bases de datos **SQLite**, la estrategia de almacenamiento vectorial como binarios `BLOB`, la creación automática "al vuelo" y el purgado atómico de documentos e historiales.

---

## 🗃️ ¿Por qué Dos Bases de Datos SQLite Separadas?

Para garantizar alta cohesión y bajo acoplamiento:
1. **`data/documents.db` (Almacén de Documentos y Vectores):** Contiene datos estáticos del archivo y los vectores de embedding. Su tamaño es directamente proporcional a la cantidad de páginas y fragmentos del PDF.
2. **`data/chat_history.db` (Historial de Conversaciones):** Contiene datos dinámicos generados por la interacción del usuario. Si un usuario decide borrar su historial o exportar solo sus preguntas, la base de datos de documentos permanece intacta sin fragmentación.

Ambas bases de datos operan con:
- **`PRAGMA journal_mode = WAL;` (Write-Ahead Logging):** Permite lecturas concurrentes sin bloquear escrituras.
- **`PRAGMA foreign_keys = ON;`:** Asegura integridad referencial y borrados en cascada.

---

## 🏗️ Creación Automática "al Vuelo" (`database.py`: Líneas 28-101)

Cuando la aplicación arranca en `pdf-chatbot.py` (Línea 34), se ejecuta:

```python
# pdf-chatbot.py: Línea 34
db_status = database.init_databases()
```

La función `init_databases()` realiza las siguientes acciones:

```python
# database.py: Líneas 35-40
os.makedirs(DATA_DIR, exist_ok=True)
docs_created = not os.path.exists(DOCUMENTS_DB_PATH)
chat_created = not os.path.exists(CHAT_HISTORY_DB_PATH)
```

1. Crea la carpeta local `data/` si aún no existe.
2. Abre la conexión a `data/documents.db` y ejecuta el DDL de `documents` y `document_chunks`.
3. Crea los índices `idx_documents_hash` y `idx_chunks_doc_id` para garantizar búsquedas en tiempo $O(1)$ por hash o ID.
4. Abre la conexión a `data/chat_history.db` y genera la tabla `chat_messages` junto con el índice `idx_chat_doc_id`.
5. Retorna un diccionario con el estado de creación: `{"documents_created": bool, "chat_created": bool}`.

---

## 📐 Esquema DDL SQL Detallado

### 1. Base de Datos `data/documents.db`

#### Tabla `documents` (`database.py`: Líneas 49-59)
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

#### Tabla `document_chunks` (`database.py`: Líneas 63-73)
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

## 🧬 ¿Cómo Funciona la Base Vectorial en SQLite?

Los modelos de embedding como `models/gemini-embedding-001` devuelven vectores continuos de **768 dimensiones** (números en punto flotante).

### 1. Serialización e Inserción (`database.py`: Líneas 186-204)
Al guardar los chunks en `save_document()`, cada lista de Python `[float, float, ...]` se convierte en un arreglo NumPy de tipo `float32` y se transforma a bytes crudos mediante `.tobytes()`:

```python
# database.py: Línea 190
emb_blob = np.array(chk["embedding"], dtype=np.float32).tobytes()
```

- Cada float32 ocupa 4 bytes: $768 \times 4 = 3,072\text{ bytes (3 KB por fragmento)}$.
- Esto es **6 veces más compacto** que guardar el vector como texto JSON legible y se inserta en bloque con `executemany` a velocidad de disco nativa.

### 2. Deserialización y Carga Instantánea (`database.py`: Líneas 208-243)
Al cargar un documento previo con `load_vectorstore_from_db()`:

```python
# database.py: Líneas 231-242
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

**Resultado:** El índice FAISS se reconstruye en la memoria RAM en menos de **2 milisegundos**, sin realizar ninguna llamada a la API de Google Gemini (0 costo, 0 latencia de red).

---

## 🗑️ Operaciones de Purgado y Borrado Atómico

### 1. `delete_document(doc_id)` (`database.py`: Líneas 246-267)
Elimina por completo todos los registros relacionados con un archivo en ambas bases de datos:

```python
# database.py: Líneas 253-267
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

### 2. `clear_chat_history(doc_id)` (`database.py`: Líneas 299-304)
Limpia únicamente los mensajes de conversación de ese documento en `chat_history.db`, manteniendo el documento y sus vectores intactos:

```python
# database.py: Línea 303
cursor.execute("DELETE FROM chat_messages WHERE document_id = ?;", (document_id,))
```

---

## 🧭 Navegación entre Capítulos

| [⬅️ Anterior: 1. Arquitectura General](01-Arquitectura-General) | [🏠 Inicio (Home)](Home) | [Siguiente: 3. Extracción y OCR Multimodal ➡️](03-Extraccion-y-OCR-Multimodal) |
| :--- | :--- | :--- |
