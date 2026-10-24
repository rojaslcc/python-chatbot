# 📄 Asistente Virtual para Documentos PDF (RAG + OCR Multimodal + Memoria SQLite)

[![GitHub Repository](https://img.shields.io/badge/GitHub-rojaslcc%2Fpython--chatbot-blue?logo=github)](https://github.com/rojaslcc/python-chatbot.git)

> 🔗 **Repositorio Oficial:** [https://github.com/rojaslcc/python-chatbot.git](https://github.com/rojaslcc/python-chatbot.git)

Un chatbot conversacional inteligente desarrollado en **Python** con **Streamlit**, **LangChain**, **Google Gemini**, **FAISS** y **SQLite**. El sistema utiliza una arquitectura **RAG** (*Retrieval-Augmented Generation*) capaz de responder preguntas analizando de forma inteligente documentos PDF de cualquier tipo con **persistencia completa de vectores, selección de historial y gestión de conversaciones**:

1. **PDFs de solo texto:** Extrae texto digital en milisegundos sin consumir cuota de API.
2. **PDFs de solo imagen (escaneos/fotos):** Aplica OCR local automático directamente en CPU sin costo.
3. **PDFs mixtos (texto + imágenes):** Extrae los párrafos digitales y recorta infografías, esquemas o diagramas para procesarlos con OCR.
4. **Persistencia Vectorial Local (SQLite):** Guarda los fragmentos y embeddings como vectores `BLOB` en `data/documents.db`, cargando documentos previos en milisegundos con **0 llamadas a la API de embeddings**.
5. **Historial de Conversación Persistente (SQLite):** Guarda el flujo de preguntas y respuestas de cada documento en `data/chat_history.db`.
6. **Purgado y Eliminación Completa:** Permite borrar tanto el historial de chat como el documento completo (metadatos, vectores y mensajes) en un solo clic.
7. **Indexación Reanudable de Documentos Grandes:** Guarda la extracción y cada lote de embeddings completado, controla el ritmo de envío y permite continuar tras una pausa sin empezar desde cero.

> [!TIP]
> 📖 **Wiki Técnica Detallada:** Para una explicación de cada fase, diagramas de arquitectura y referencias a los módulos y funciones, visita la [Wiki Oficial del Proyecto](https://github.com/rojaslcc/python-chatbot/wiki).

---

## 🚀 Características Principales

- **100% Gratuito:** El OCR se ejecuta localmente en tu máquina (sin gastar cuota de API).
- **Doble Base de Datos SQLite con Creación "al Vuelo":** Si no existen las bases de datos o la carpeta `data/`, la aplicación las crea y estructura automáticamente al arrancar.
- **Selector e Historial de Documentos:** Menú desplegable en la barra lateral para alternar rápidamente entre documentos procesados anteriormente o subir uno nuevo.
- **Detección Inteligente de Duplicados por Hash SHA-256:** Si vuelves a arrastrar un archivo ya procesado, el sistema lo reconoce y lo carga en 0 segundos sin repetir el OCR ni la vectorización.
- **Historial de Chat por Documento:** Cada PDF mantiene su propio hilo de preguntas y respuestas almacenado de forma permanente.
- **Eliminación Total y Limpieza de Historial:** Botones para limpiar la conversación actual o purgar definitivamente el PDF y sus vectores de ambas bases de datos.
- **Control de cuota de embeddings:** Indexación reanudable por lotes en SQLite, ritmo configurable y reintentos acotados ante errores temporales. Los fallbacks del chat son independientes y no resuelven la cuota de embeddings.
- **Búsqueda Vectorial con FAISS:** Reconstrucción instantánea de índices en memoria desde los vectores binarios persistidos en SQLite.
- **Interfaz Moderna en Español:** Implementada con componentes nativos de chat (`st.chat_message`, `st.chat_input`) y estado reactivo en tiempo real.

---

## Documentos grandes e indexación reanudable

### Configuración y primer procesamiento

Selecciona **➕ Subir nuevo PDF...**, carga el archivo y pulsa **Procesar documento**.
En el desplegable **Indexación de documentos grandes**, dentro de la barra lateral,
puedes ajustar:

| Control | Valor inicial | Alcance |
| :--- | :--- | :--- |
| Contenidos de embeddings por minuto | 60 | Presupuesto positivo que cuenta cada fragmento como una unidad. |
| Fragmentos por lote | 10 | Entre 1 y el menor de 100 o el presupuesto por minuto. |
| Reintentos por lote | 3 | Entre 0 y 10; no incluye el intento inicial. |
| Espera máxima por pausa (segundos) | 120 | Máximo de cada espera de cuota o reintento, no de la duración total del trabajo. |

Son valores conservadores, no cuotas garantizadas: consulta los límites reales de
tu proyecto en [AI Studio](https://aistudio.google.com/usage?timeRange=last-28-days&tab=rate-limit).
El presupuesto cuenta cada fragmento como una unidad, aunque se envíen juntos.
No controla tokens/minuto, cuota diaria ni consumo de otras aplicaciones o claves
del mismo proyecto; ante un 429 temporal se respeta la espera indicada por Google.
Con los valores iniciales, se reserva aproximadamente un turno de 10 segundos por
lote de 10 fragmentos. La duración real depende de la latencia y las pausas.
La barra de progreso muestra fragmentos **guardados**, junto con mensajes de
espera, reintento y confirmación de lote.

### Reanudar después de una pausa

Los textos extraídos y cada lote terminado se guardan en `indexing_jobs` e
`indexing_chunks`, dentro de `data/documents.db`. Si hay un error o cierras la
aplicación, vuelve a subir **el mismo archivo**, conserva la misma opción de OCR
y pulsa **Reanudar indexación**. Se recupera el texto sin repetir OCR y solo se
solicitan los vectores pendientes. Un lote interrumpido antes de guardarse podría
tener que repetirse. Los documentos incompletos no aparecen en el historial
consultable; al completarse se publican y se elimina el trabajo temporal en una
misma transacción. Los documentos ya procesados siguen siendo compatibles.
La recuperación empieza después de guardar la extracción y fragmentación completas;
si se interrumpe antes, esa fase debe repetirse. El lote en curso tampoco es un
punto de recuperación hasta que se guarda entero.

La identidad del trabajo combina el hash del archivo, la opción de OCR en imágenes,
el modelo y la versión de procesamiento. Puedes cambiar el ritmo, el tamaño de lote
o los reintentos al reanudar sin perder el avance. Cambiar la opción de OCR crea
otro trabajo pendiente; no reutiliza los fragmentos de la configuración anterior.
No hay un botón de eliminación de trabajos pendientes: los botones de borrado
gestionan documentos ya publicados, no estos trabajos.

### Errores, cuotas y alcance

El ritmo se comparte entre sesiones que usan la misma base de datos, clave y modelo,
sin guardar la clave en SQLite. Los reintentos se limitan a HTTP 429 y errores
temporales 500/502/503/504, con espera incremental y `RetryInfo`/`Retry-After` de
Google. Una cuota diaria identificada, un error no transitorio, el límite de
reintentos o una espera mayor al máximo pausan el proceso y muestran el error.
No se desactiva la verificación SSL ni se cambia de modelo de embeddings.
Cada llamada de indexación tiene un timeout de 60 segundos y no añade reintentos
internos del SDK.

| Situación | Qué ocurre / qué hacer |
| :--- | :--- |
| 429 temporal o HTTP 500/502/503/504 | Espera y reintenta hasta el máximo configurado; después pausa conservando el avance. |
| Cuota diaria identificada | Pausa sin reintentar; revisa el plan o espera al restablecimiento de la cuota. |
| Espera indicada mayor al máximo o cola demasiado larga | Pausa; reanuda más tarde o ajusta el máximo si corresponde. |
| Credenciales, permisos, SSL u otro error no clasificado como transitorio | Pausa y muestra el detalle técnico; corrige la causa antes de reanudar. |
| Respuesta incompleta o vectores inválidos | No confirma ese lote; conserva los lotes anteriores. |

El modelo de embeddings sigue siendo `models/gemini-embedding-001`. Los fallbacks
de `ChatGoogleGenerativeAI` solo intervienen al generar la respuesta, no al indexar
ni al vectorizar la pregunta. `max_tokens` limita la salida del chat, no la cuota
de embeddings ni el tamaño de los PDFs.

Esto mejora la **indexación**, no convierte la búsqueda de cuatro fragmentos en un
resumen exhaustivo del PDF. Los resúmenes globales requieren un flujo por secciones.

Detalles internos en la Wiki: [Persistencia](https://github.com/rojaslcc/python-chatbot/wiki/02-Persistencia-y-Bases-de-Datos),
[Embeddings y RAG](https://github.com/rojaslcc/python-chatbot/wiki/04-Procesamiento-Vectorial-y-RAG)
y [Flujo de usuario](https://github.com/rojaslcc/python-chatbot/wiki/05-Interfaz-Streamlit-y-Flujo-de-Usuario).

Para ejecutar las pruebas locales sin consumir API:

```bash
python -m unittest discover -s tests -v
```

---

## 🧠 ¿Cómo Funciona la Arquitectura?

```text
               ┌─────────────────────────────────────────────────────────┐
               │              Interfaz de Usuario (Streamlit)            │
               │   • Selector de documentos previos                      │
               │   • Uploader de nuevos PDFs                             │
               │   • Chat conversacional (st.chat_message)               │
               │   • Botones de limpieza y eliminación total             │
               └───────────┬─────────────────────────────────┬───────────┘
                           │                                 │
           [ Documento Nuevo o Selección ]          [ Pregunta del Usuario ]
                           │                                 │
                           ▼                                 ▼
              ¿Existe en SQLite (Hash SHA-256)?     Recuperador FAISS (MMR - k=4)
              ├── SÍ: Carga instantánea desde BD             │
              └── NO: Extracción / OCR + Chunks              ▼
                      Crear/recuperar trabajo        Prompt + Contexto Recuperado
                      Lotes Gemini + ritmo/reintentos
                      Guardar avance en SQLite
                           │                                 │
                           ▼                                 ▼
                Persistencia en SQLite              LLM Gemini con Fallbacks
                ┌──────────────────────┐                     │
                │ data/documents.db    │                     ▼
                ├──────────────────────┤            Respuesta al Usuario
                │ • documents          │                     │
                │ • document_chunks    │                     ▼
                │   (Embeddings BLOB)  │            Persistencia en SQLite
                └──────────────────────┘            ┌──────────────────────┐
                                                    │ data/chat_history.db │
                                                    ├──────────────────────┤
                                                    │ • chat_messages      │
                                                    └──────────────────────┘
```

---

## 🗄️ Esquema de Bases de Datos SQLite

El sistema gestiona dos bases de datos SQLite independientes optimizadas con **modo WAL** (*Write-Ahead Logging*) y claves foráneas en cascada:

### 1. `data/documents.db` (Metadatos y Almacén Vectorial)
Almacena el registro de los archivos PDF procesados y sus vectores de embedding serializados en formato binario (`np.float32.tobytes()`):

```sql
-- Metadatos del documento
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,               -- Hash SHA-256 truncado a 16 caracteres
    filename TEXT NOT NULL,            -- Nombre del archivo PDF
    file_hash TEXT UNIQUE NOT NULL,    -- Hash SHA-256 completo del archivo
    file_size INTEGER DEFAULT 0,       -- Tamaño en bytes
    total_pages INTEGER DEFAULT 0,     -- Cantidad de páginas del documento
    total_chunks INTEGER DEFAULT 0,    -- Total de fragmentos generados
    has_ocr INTEGER DEFAULT 0,         -- 1 si requirió OCR, 0 si fue solo texto digital
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fragmentos y vectores de embedding (Vector Store)
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER DEFAULT 1,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,           -- Vector serializado de alta compacidad y velocidad
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON document_chunks(document_id);

-- Trabajos pendientes: no aparecen en el historial consultable
CREATE TABLE IF NOT EXISTS indexing_jobs (
    id TEXT PRIMARY KEY,
    metadata TEXT NOT NULL            -- JSON: filename, total_pages, has_ocr, model
);

CREATE TABLE IF NOT EXISTS indexing_chunks (
    job_id TEXT NOT NULL REFERENCES indexing_jobs(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,                   -- NULL mientras el vector esté pendiente
    PRIMARY KEY (job_id, chunk_index)
);

-- Agenda compartida para espaciar los envíos
CREATE TABLE IF NOT EXISTS embedding_schedule (
    scope TEXT PRIMARY KEY,           -- SHA-256 de clave/modelo; no la clave en claro
    next_request_at REAL NOT NULL      -- Instante del próximo turno
);
```

Las tablas nuevas se crean automáticamente sin borrar datos existentes.
`save_indexing_batch()` confirma cada lote en una transacción; `save_document()`
publica todos los fragmentos y elimina el trabajo temporal en otra transacción.
El PDF original no se almacena en SQLite: se conservan sus metadatos, textos y vectores.

### 2. `data/chat_history.db` (Historial de Mensajes por Documento)
Preserva las conversaciones completas vinculadas a cada archivo para que no se pierdan al recargar la aplicación o cambiar de documento:

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    role TEXT NOT NULL,                -- 'user' o 'assistant'
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_doc_id ON chat_messages(document_id);
```

---

## 🗑️ Gestión y Eliminación de Datos

La aplicación cuenta con herramientas de control y purgado para ambas bases de datos:

| Acción | Dónde se encuentra | ¿Qué elimina exactamente? |
| :--- | :--- | :--- |
| **🧹 Limpiar Chat** | Cabecera del chat | Borra los mensajes de conversación del documento activo en `data/chat_history.db` (`chat_messages`), manteniendo intactos el PDF y sus vectores. |
| **🗑️ Eliminar Documento** | Barra lateral (expander de metadatos) o Cabecera del Chat | Borra los metadatos publicados (`documents`), fragmentos y vectores (`document_chunks`), historial de chat (`chat_messages`) y estado activo de sesión. No borra el archivo PDF original ni trabajos pendientes de otras configuraciones. |

---

## 📁 Estructura del Proyecto

```text
python-chatbot/
│
├── .env                         # Variables de entorno locales (API Key - protegido en .gitignore)
├── .env.example                 # Plantilla para configurar la API Key de Google
├── .gitignore                   # Archivos ignorados por Git (.env, .venv, data/, etc.)
├── .python-version              # Python 3.12.13 seleccionado para este proyecto
├── database.py                  # Módulo de persistencia SQLite y vector store local
├── indexing.py                  # Trabajos reanudables, ritmo y reintentos de embeddings
├── pdf-chatbot.py               # Aplicación principal del chatbot en Streamlit
├── README.md                    # Documentación detallada del proyecto
├── requirements.txt             # Dependencias y librerías de Python
│
├── data/                        # [Auto-creado al vuelo] Bases de datos SQLite locales
│   ├── documents.db             # Almacén de metadatos, fragmentos y embeddings BLOB
│   └── chat_history.db          # Historial persistente de preguntas y respuestas
│
├── pdfs-ejemplo/                # Documentos de prueba listos para usar
│   ├── ejemplo001-imagenes.pdf          # PDF escaneado (solo imágenes) para probar OCR local
│   └── ejemplo002-imagenes-texto.pdf    # PDF mixto (texto digital con infografías y gráficos)
│
└── wiki/                        # Documentación técnica detallada (formato GitHub Wiki)
    ├── Home.md                  # Portada e índice de la Wiki
    ├── _Sidebar.md              # Barra lateral de navegación de la Wiki
    ├── _Footer.md               # Pie de página de la Wiki
    ├── 01-Arquitectura-General.md
    ├── 02-Persistencia-y-Bases-de-Datos.md
    ├── 03-Extraccion-y-OCR-Multimodal.md
    ├── 04-Procesamiento-Vectorial-y-RAG.md
    └── 05-Interfaz-Streamlit-y-Flujo-de-Usuario.md
```

---

## 📦 Librerías y Dependencias (`requirements.txt`)

La versión de Python del proyecto es **3.12.13**, declarada en
[`.python-version`](./.python-version). El manifiesto
[`requirements.txt`](./requirements.txt) combina versiones exactas (`==`) y
mínimos permitidos (`>=`): estos últimos no describen una versión instalada fija.
Pip resuelve las versiones compatibles con el conjunto de dependencias; el archivo
no es un lockfile y dos instalaciones en fechas distintas pueden resolver versiones
diferentes.

| Librería | Restricción en `requirements.txt` | ¿Para qué se utiliza en este proyecto? |
| :--- | :--- | :--- |
| **`streamlit`** | `==1.52.2` | Framework web reactivo en Python. Proporciona la interfaz gráfica: selector de historial, subida de archivos, mensajes con `st.chat_message` y campo `st.chat_input`. |
| **`pdfplumber`** | `==0.11.8` | Motor de lectura de PDFs. Extrae texto digital nativo, inspecciona metadatos de las páginas, detecta imágenes incrustadas y renderiza páginas a imagen para el OCR. |
| **`langchain`** | `>=1.2.0` | Framework principal de orquestación de IA. Conecta los documentos, la base de datos vectorial, los prompts y los modelos de lenguaje mediante tuberías (*runnables*). |
| **`langchain-openai`** | `>=1.1.6` | Integración de OpenAI con LangChain, conservada en el manifiesto; el flujo actual usa Gemini. |
| **`openai`** | `==2.14.0` | SDK de OpenAI, conservado como dependencia; no es el proveedor del flujo Gemini actual. |
| **`tiktoken`** | `==0.12.0` | Tokenizador disponible para integraciones de LangChain/OpenAI; la división actual se mide en caracteres. |
| **`langchain-google-genai`** | `>=4.4.0` | Integración oficial de Google Gemini en LangChain. Proporciona `GoogleGenerativeAIEmbeddings` para vectorizar texto y `ChatGoogleGenerativeAI` para interactuar con los LLMs de Gemini. |
| **`faiss-cpu`** | `==1.13.2` | Base de datos vectorial en memoria (*Facebook AI Similarity Search*). Permite indexar fragmentos de texto y realizar búsquedas de similitud semántica en milisegundos en la CPU. |
| **`langchain-community`** | `==0.4.1` | Módulo de extensiones de LangChain. Contiene la integración de la clase `FAISS` para la reconstrucción de índices desde embeddings precalculados. |
| **`langchain-core`** | `>=1.2.5` | Componentes fundamentales de LangChain: mensajes (`HumanMessage`), formateadores de prompts (`ChatPromptTemplate`) y analizadores de salida (`StrOutputParser`). |
| **`langchain-text-splitters`** | `>=1.1.0` | Herramientas de segmentación de texto. Proporciona `RecursiveCharacterTextSplitter` para trocear documentos respetando páginas, párrafos y solapamiento (*overlap*). |
| **`rapidocr-onnxruntime`** | `>=1.4.0` | Motor de OCR local ultrarrápido basado en redes ONNX. Permite transcribir imágenes y páginas escaneadas directamente en la CPU **sin consumir cuotas ni peticiones de la API de Google**. |
| **`numpy`** | Transitiva, sin entrada directa | Paquete externo instalado por las dependencias; serializa y deserializa vectores float32. No pertenece a la biblioteca estándar. |
| **`google-genai`** | Transitiva, sin entrada directa | SDK instalado por `langchain-google-genai`; `indexing.py` usa sus tipos, errores y opciones HTTP. |
| **`sqlite3` / `hashlib`** | N/A (Estándar) | Módulos incluidos en la librería estándar de Python para la gestión de las bases de datos locales y el cálculo de hashes SHA-256 sin librerías externas pesadas. |
| **`python-dotenv`** | `>=1.0.0` | Carga automática de variables de entorno desde el archivo `.env`. Evita exponer claves secretas directamente en el código fuente. |

No vuelvas a fijar `langchain-core==1.2.5`: las versiones de
`langchain-google-genai` pueden exigir un mínimo superior y pip debe resolverlo.
`rapidocr-onnxruntime` 1.4.x declara Python menor que 3.13; un entorno 3.14 no
sirve para esas versiones. Usa la versión exacta del proyecto en lugar del Python
global más reciente.

---

## 🛠️ Instalación y Configuración Paso a Paso

### 1. Clonar o ingresar al repositorio
```bash
git clone https://github.com/rojaslcc/python-chatbot.git
cd python-chatbot
```

### 2. Seleccionar Python 3.12.13 y crear el entorno virtual

#### macOS / Linux con pyenv

`pyenv` mantiene versiones independientes por proyecto sin sustituir el Python
del sistema. En macOS, instálalo con Homebrew si aún no lo tienes:

```bash
brew install pyenv
```

En Linux sigue la [instalación oficial de pyenv](https://github.com/pyenv/pyenv#installation)
y prepara las [dependencias de compilación](https://github.com/pyenv/pyenv/wiki#suggested-build-environment).
Python se compila localmente; en macOS también se necesitan las herramientas de
desarrollo de Xcode (`xcode-select --install` si no están instaladas).

Para el shell **zsh** de macOS, agrega lo siguiente a `~/.zshrc` una sola vez,
sin duplicar una configuración existente:

```bash
export PYENV_ROOT="$HOME/.pyenv"
[[ -d "$PYENV_ROOT/bin" ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - zsh)"
```

Abre una nueva terminal. Para Bash u otro shell, utiliza las instrucciones de
[configuración del shell de pyenv](https://github.com/pyenv/pyenv#set-up-your-shell-environment).
Después, desde la raíz del proyecto y **sin otro entorno virtual activado**:

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
pyenv version
python --version
python -m venv .venv
source .venv/bin/activate
python -c "import sys; print(sys.version); print(sys.executable)"
```

`python --version` debe mostrar **Python 3.12.13** antes de crear `.venv`.
Después de activarlo, `sys.executable` debe apuntar a `.venv/bin/python` del
proyecto. `pyenv local` escribe `.python-version` (ya incluido en el repositorio);
al entrar en esta carpeta, un pyenv inicializado selecciona esa versión. No hace
falta ejecutar `pyenv global` ni cambiar la versión de otros proyectos.

`.python-version` **no instala Python, no activa `.venv` y no cambia el intérprete
de un entorno ya creado**. Fuera de pyenv, usa explícitamente la ruta al ejecutable
de Python 3.12.13 para crear el entorno.

#### Si `.venv` fue creado con otra versión

Detén Streamlit y ejecuta `deactivate` si tienes un entorno activado. Desde la
raíz del proyecto, conserva el entorno anterior como respaldo y crea uno nuevo
(elige otro nombre de respaldo si `.venv-anterior` ya existe):

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
python --version
mv .venv .venv-anterior
python -m venv .venv
source .venv/bin/activate
```

Reinstala los paquetes del paso 3. El respaldo no se debe usar como entorno
activo después de moverlo; consérvalo solo para consultar su contenido. No borres
`.env` ni `data/`: las credenciales y los documentos no necesitan recrearse.
Si antes añadiste certificados o variables a `.venv/bin/activate`, esa configuración
no se copia al nuevo entorno; vuelve a configurarla de forma explícita.

#### Windows (PowerShell)

El pyenv original es para sistemas Unix; en Windows usa WSL con el flujo anterior
o un gestor compatible con Windows capaz de instalar **3.12.13**. El archivo
`.python-version` por sí solo no configura el lanzador `py`.
Si ya dispones del ejecutable de esa versión, úsalo por su ruta exacta:

```powershell
# Sustituye esta ruta por la de tu instalación real de Python 3.12.13
& "C:\ruta\Python-3.12.13\python.exe" --version
& "C:\ruta\Python-3.12.13\python.exe" -m venv .venv
.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.version); print(sys.executable)"
```

### 3. Instalar las dependencias

Con `.venv` activado y Python 3.12.13 confirmado:

```bash
python -m pip install -r requirements.txt
python -m pip check
```

No copies paquetes desde el entorno anterior. Si usas un IDE, selecciona
`.venv/bin/python` (Windows: `.venv\Scripts\python.exe`) como intérprete.

#### 3.1. En caso de error de SSL
```bash
python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

### 4. Configurar la Clave de API de Google Gemini (Gratuita)

1. Obtén tu clave gratuita en [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Crea tu archivo de entorno a partir de la plantilla:
   ```bash
   cp .env.example .env
   ```
3. Edita el archivo `.env` y coloca tu clave:
   ```env
   GOOGLE_API_KEY="AIzaSyTuClaveDeApiAqui"
   ```

> [!NOTE]
> Si no deseas usar un archivo `.env`, puedes ingresar la clave de API directamente en el campo seguro de la barra lateral al abrir la aplicación.

---

## 🖥️ Ejecución de la Aplicación

Con el entorno virtual activado, inicia el servidor de Streamlit:

```bash
streamlit run pdf-chatbot.py
```

1. La aplicación verificará y creará automáticamente las bases de datos SQLite en `data/` al vuelo.
2. Abrirá automáticamente tu navegador en `http://localhost:8501`.
3. Sube un archivo PDF y pulsa **Procesar documento**, o elige un documento del menú desplegable del historial (puedes probar con los ejemplos en [`pdfs-ejemplo/`](./pdfs-ejemplo)). Si se reconoce una indexación pendiente, pulsa **Reanudar indexación**; si ya está completo, se carga sin volver a indexar.
4. Escribe tus preguntas en la caja de chat: las respuestas y preguntas se guardarán en el historial de SQLite automáticamente.
5. Puedes alternar libremente entre documentos, limpiar el chat o purgar documentos por completo con los botones integrados.

---

## 🔒 Buenas Prácticas de Seguridad

- **Protección de Datos Locales y Credenciales:** El archivo [`.gitignore`](./.gitignore) incluido protege automáticamente tus claves (`.env`, `.streamlit/secrets.toml`), los entornos virtuales (`.venv/`) y las bases de datos generadas (`data/`, `*.db`).
- **Restricción de clave API:** En la [Consola de Google Cloud](https://console.cloud.google.com/apis/credentials), puedes restringir tu clave únicamente a la **Generative Language API** para mayor seguridad.

---

## 🤝 Dinámica de Contribución y Colaboración

¡Las contribuciones de la comunidad son bienvenidas! Para mantener la calidad, seguridad y estabilidad de la rama principal, el repositorio se rige bajo una política estricta de **Ramas Feature y Pull Requests**.

> [!IMPORTANT]
> - La rama `main` se encuentra protegida contra pushes directos y force-pushes (`git push --force`).
> - **Todos los cambios y aportes deben canalizarse mediante ramas `feature/` y Pull Requests.**
> - **Exclusividad de Merge:** Por directiva de seguridad del repositorio, **únicamente el propietario (`@rojaslcc`) cuenta con privilegios para aprobar y realizar el merge de los PRs en `main`.**

### 📋 Flujo de Trabajo para Colaborar

1. **Crear un Fork del Repositorio:**
   Haz clic en el botón **Fork** en la parte superior derecha de [rojaslcc/python-chatbot](https://github.com/rojaslcc/python-chatbot) para crear una copia en tu cuenta personal de GitHub.

2. **Clonar tu Fork en tu entorno local:**
   ```bash
   git clone https://github.com/TU-USUARIO/python-chatbot.git
   cd python-chatbot
   ```

3. **Configurar el repositorio remoto original (*upstream*):**
   ```bash
   git remote add upstream https://github.com/rojaslcc/python-chatbot.git
   ```

4. **Crear una rama temática desde `main` actualizado:**
   ```bash
   git checkout main
   git pull upstream main
   git checkout -b feature/nombre-de-la-mejora
   ```
   *(Recomendado usar prefijos semánticos: `feature/`, `fix/`, `docs/`, `refactor/`)*.

5. **Desarrollar y probar tus cambios:**
   - Activa tu entorno virtual (`source .venv/bin/activate` o `.venv\Scripts\Activate.ps1`).
   - Sigue las normas de seguridad del proyecto: **bajo ninguna circunstancia confirmes claves secretas (`.env`) ni bases de datos locales (`data/`)**.
   - Prueba que la aplicación inicie sin errores con `streamlit run pdf-chatbot.py`.

6. **Registrar commits claros:**
   ```bash
   git add .
   git commit -m "feat: descripción breve y clara del cambio"
   ```

7. **Subir la rama a tu Fork:**
   ```bash
   git push -u origin feature/nombre-de-la-mejora
   ```

8. **Abrir el Pull Request hacia `main`:**
   - Abre un **Pull Request** desde tu rama hacia `main` en [https://github.com/rojaslcc/python-chatbot](https://github.com/rojaslcc/python-chatbot).
   - O utiliza la CLI de GitHub si la tienes instalada:
     ```bash
     gh pr create --title "feat: título descriptivo" --body "Explicación detallada de la contribución"
     ```
   - Describe con claridad el propósito del cambio y qué pruebas realizaste.

9. **Revisión, Resolución y Fusión:**
   - Resuelve cualquier conversación o sugerencia dejada en la revisión del PR.
   - Una vez validado, el propietario (**@rojaslcc**) realizará el merge a `main`.
   - La rama de la feature se eliminará automáticamente del remoto tras la integración para mantener un historial limpio.
