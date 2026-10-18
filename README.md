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

> [!TIP]
> 📖 **Wiki Técnica Detallada:** Para una explicación exhaustiva de cada fase, diagrama de arquitectura y referencias a las líneas de código fuente exactas, visita la [Wiki Oficial del Proyecto](./wiki/Home.md).

---

## 🚀 Características Principales

- **100% Gratuito:** El OCR se ejecuta localmente en tu máquina (sin gastar cuota de API).
- **Doble Base de Datos SQLite con Creación "al Vuelo":** Si no existen las bases de datos o la carpeta `data/`, la aplicación las crea y estructura automáticamente al arrancar.
- **Selector e Historial de Documentos:** Menú desplegable en la barra lateral para alternar rápidamente entre documentos procesados anteriormente o subir uno nuevo.
- **Detección Inteligente de Duplicados por Hash SHA-256:** Si vuelves a arrastrar un archivo ya procesado, el sistema lo reconoce y lo carga en 0 segundos sin repetir el OCR ni la vectorización.
- **Historial de Chat por Documento:** Cada PDF mantiene su propio hilo de preguntas y respuestas almacenado de forma permanente.
- **Eliminación Total y Limpieza de Historial:** Botones para limpiar la conversación actual o purgar definitivamente el PDF y sus vectores de ambas bases de datos.
- **Prevención de Límites de Cuota (Error 429):** Utiliza modelos Gemini de alto cupo diario (`gemini-flash-lite-latest`) junto con una cadena de conmutación automática de respaldo (*fallbacks*).
- **Búsqueda Vectorial con FAISS:** Reconstrucción instantánea de índices en memoria desde los vectores binarios persistidos en SQLite.
- **Interfaz Moderna en Español:** Implementada con componentes nativos de chat (`st.chat_message`, `st.chat_input`) y estado reactivo en tiempo real.

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
                      Embeddings con Gemini         Prompt + Contexto Recuperado
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
```

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
| **🗑️ Eliminar Documento** | Barra lateral (expander de metadatos) o Cabecera del Chat | **Purgado total:** Borra el PDF y sus metadatos (`documents`), todos sus fragmentos y vectores (`document_chunks`), todo su historial de chat (`chat_messages`) y libera la memoria activa de sesión (`st.session_state`). |

---

## 📁 Estructura del Proyecto

```text
python-chatbot/
│
├── .env                         # Variables de entorno locales (API Key - protegido en .gitignore)
├── .env.example                 # Plantilla para configurar la API Key de Google
├── .gitignore                   # Archivos ignorados por Git (.env, .venv, data/, etc.)
├── database.py                  # Módulo de persistencia SQLite y vector store local
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

A continuación se detalla el propósito de cada librería utilizada en el proyecto:

| Librería | Versión | ¿Para qué se utiliza en este proyecto? |
| :--- | :--- | :--- |
| **`streamlit`** | `1.52.2` | Framework web reactivo en Python. Proporciona la interfaz gráfica: selector de historial, subida de archivos, mensajes con `st.chat_message` y campo `st.chat_input`. |
| **`pdfplumber`** | `0.11.8` | Motor de lectura de PDFs. Extrae texto digital nativo, inspecciona metadatos de las páginas, detecta imágenes incrustadas y renderiza páginas a imagen para el OCR. |
| **`langchain`** | `1.2.0` | Framework principal de orquestación de IA. Conecta los documentos, la base de datos vectorial, los prompts y los modelos de lenguaje mediante tuberías (*runnables*). |
| **`langchain-google-genai`** | `>=4.4.0` | Integración oficial de Google Gemini en LangChain. Proporciona `GoogleGenerativeAIEmbeddings` para vectorizar texto y `ChatGoogleGenerativeAI` para interactuar con los LLMs de Gemini. |
| **`faiss-cpu`** | `1.13.2` | Base de datos vectorial en memoria (*Facebook AI Similarity Search*). Permite indexar fragmentos de texto y realizar búsquedas de similitud semántica en milisegundos en la CPU. |
| **`langchain-community`** | `0.4.1` | Módulo de extensiones de LangChain. Contiene la integración de la clase `FAISS` para la reconstrucción de índices desde embeddings precalculados. |
| **`langchain-core`** | `1.2.5` | Componentes fundamentales de LangChain: mensajes (`HumanMessage`), formateadores de prompts (`ChatPromptTemplate`) y analizadores de salida (`StrOutputParser`). |
| **`langchain-text-splitters`** | `1.1.0` | Herramientas de segmentación de texto. Proporciona `RecursiveCharacterTextSplitter` para trocear documentos respetando páginas, párrafos y solapamiento (*overlap*). |
| **`rapidocr-onnxruntime`** | `>=1.4.0` | Motor de OCR local ultrarrápido basado en redes ONNX. Permite transcribir imágenes y páginas escaneadas directamente en la CPU **sin consumir cuotas ni peticiones de la API de Google**. |
| **`numpy`** | N/A (Estándar) | Serialización de vectores float32 a BLOBs binarios en SQLite y deserialización ultrarrápida. |
| **`sqlite3` / `hashlib`** | N/A (Estándar) | Módulos incluidos en la librería estándar de Python para la gestión de las bases de datos locales y el cálculo de hashes SHA-256 sin librerías externas pesadas. |
| **`python-dotenv`** | `>=1.0.0` | Carga automática de variables de entorno desde el archivo `.env`. Evita exponer claves secretas directamente en el código fuente. |

---

## 🛠️ Instalación y Configuración Paso a Paso

### 1. Clonar o ingresar al repositorio
```bash
git clone https://github.com/rojaslcc/python-chatbot.git
cd python-chatbot
```

### 2. Crear y activar el entorno virtual
En Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
En Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Instalar las dependencias
```bash
pip install -r requirements.txt
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
3. Sube un archivo PDF o elige un documento del menú desplegable del historial (puedes probar con los ejemplos en [`pdfs-ejemplo/`](./pdfs-ejemplo)).
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

