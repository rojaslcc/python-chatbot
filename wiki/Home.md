# 📚 Wiki del Proyecto: Asistente Virtual para Documentos PDF

Bienvenido a la documentación técnica y funcional exhaustiva del **Asistente Virtual para Documentos PDF** (RAG + OCR Multimodal + Memoria SQLite).

Esta Wiki sigue la estructura de **GitHub Wikis** y detalla el funcionamiento del sistema, sus principios arquitectónicos y los módulos y funciones que implementan cada funcionalidad.

---

## 🗺️ Mapa de Contenidos

| Página | Descripción | Módulos y Enfoque |
| :--- | :--- | :--- |
| [**1. Arquitectura General**](01-Arquitectura-General) | Flujo de datos, ciclo de vida reactivo e indexación reanudable. | `pdf-chatbot.py`, `indexing.py`, `database.py` |
| [**2. Persistencia y Bases de Datos SQLite**](02-Persistencia-y-Bases-de-Datos) | Vectores BLOB, trabajos pendientes, agenda de envíos y publicación transaccional. | `database.py`, `documents.db`, `chat_history.db` |
| [**3. Extracción y OCR Multimodal**](03-Extraccion-y-OCR-Multimodal) | Estrategia híbrida: texto digital nativo, OCR local en CPU con RapidOCR, recorte de diagramas y fallback a Gemini Vision. | `pdfplumber`, `rapidocr_onnxruntime`, `extract_text_from_image` |
| [**4. Procesamiento Vectorial y RAG**](04-Procesamiento-Vectorial-y-RAG) | Lotes con ritmo configurable, reintentos acotados, búsqueda MMR y alcance de los fallbacks. | `indexing.py`, `RecursiveCharacterTextSplitter`, `FAISS`, Gemini |
| [**5. Interfaz Streamlit y Flujo de Usuario**](05-Interfaz-Streamlit-y-Flujo-de-Usuario) | Procesar/reanudar PDFs, progreso, controles de cuota, resolución de pausas y chat. | `st.progress`, `st.sidebar`, `st.session_state` |

---

## 🚀 Resumen Rápido del Sistema

El proyecto aborda cuatro desafíos en los chatbots conversacionales de documentos:

1. **Comprensión Completa de PDFs Reales:** No solo extrae texto seleccionable; si una página es una imagen escaneada o contiene diagramas técnicos incrustados, aplica **OCR local gratuito** sin gastar cuota de API.
2. **Persistencia Vectorial Ultrarrápida y Portable:** Mediante dos bases de datos SQLite locales (`documents.db` y `chat_history.db`), almacena los vectores precalculados (`np.float32`), permitiendo cambiar o reabrir documentos en **milisegundos con 0 llamadas a la API de embeddings**.
3. **Conversación Persistente por Documento:** Cada archivo mantiene su propio hilo de preguntas y respuestas almacenado, evitando que las conversaciones se borren al recargar el navegador.
4. **Documentos Grandes sin Reiniciar la Indexación:** Guarda textos y lotes terminados, espacia las solicitudes de embeddings y permite reanudar tras una pausa. No elimina las cuotas de Google ni sustituye un flujo de resúmenes completos.

### Inicio rápido para documentos grandes

Sube el PDF y pulsa **Procesar documento**. Los controles de **Indexación de documentos grandes** parten de 60 contenidos/minuto, lotes de 10, 3 reintentos y 120 segundos máximos por espera. Ajústalos a la cuota de tu proyecto en AI Studio. Si se pausa, vuelve a subir el mismo archivo con la misma opción de OCR y pulsa **Reanudar indexación**. Consulta el [flujo de usuario](05-Interfaz-Streamlit-y-Flujo-de-Usuario) para los detalles.

### Entorno local y dependencias

El proyecto declara **Python 3.12.13** en
[`.python-version`](https://github.com/rojaslcc/python-chatbot/blob/main/.python-version).
En macOS/Linux, con `pyenv` instalado e inicializado y sin otro entorno activado,
ejecuta desde la raíz del repositorio:

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Confirma **Python 3.12.13** antes de crear el entorno. `.python-version` no instala
Python ni modifica un `.venv` existente: si este se creó con 3.14 u otra versión,
debes recrearlo e instalar las dependencias nuevamente. Las versiones 1.4.x de
`rapidocr-onnxruntime` requieren Python menor que 3.13.

[`requirements.txt`](https://github.com/rojaslcc/python-chatbot/blob/main/requirements.txt)
es la fuente de las restricciones: fija con `==` Streamlit, pdfplumber,
langchain-community, OpenAI, FAISS y tiktoken; permite con `>=` langchain,
langchain-openai, langchain-core, langchain-text-splitters, langchain-google-genai,
python-dotenv y rapidocr-onnxruntime. Los mínimos no son versiones instaladas
exactas y el archivo no es un lockfile. NumPy y google-genai llegan como dependencias
transitivas; no forman parte de la biblioteca estándar.

La [guía de instalación del README](https://github.com/rojaslcc/python-chatbot/blob/main/README.md#2-seleccionar-python-31213-y-crear-el-entorno-virtual)
incluye la configuración de pyenv en zsh, la sustitución segura de un entorno
anterior, Windows/WSL y la tabla completa de restricciones actuales.

---

## 💻 ¿Cómo Usar esta Wiki en GitHub?

Los archivos contenidos en la carpeta [`wiki/`](https://github.com/rojaslcc/python-chatbot/tree/main/wiki) son 100% compatibles con el repositorio de Wikis de GitHub:
- El workflow [`.github/workflows/sync-wiki.yml`](https://github.com/rojaslcc/python-chatbot/blob/main/.github/workflows/sync-wiki.yml) sincroniza `wiki/` con la Wiki publicada cuando estos archivos llegan a `main`; también admite ejecución manual.
- La Wiki debe estar habilitada e inicializada con una primera página en GitHub para que pueda clonarse. Editar los archivos locales no publica los cambios por sí solo.
