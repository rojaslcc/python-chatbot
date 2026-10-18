# 📚 Wiki del Proyecto: Asistente Virtual para Documentos PDF

Bienvenido a la documentación técnica y funcional exhaustiva del **Asistente Virtual para Documentos PDF** (RAG + OCR Multimodal + Memoria SQLite).

Esta Wiki ha sido diseñada con la estructura estándar de **GitHub Wikis**, detallando el funcionamiento del sistema paso a paso, los principios arquitectónicos adoptados y las **líneas de código exactas** que implementan cada funcionalidad.

---

## 🗺️ Mapa de Contenidos

| Página | Descripción | Módulos y Enfoque |
| :--- | :--- | :--- |
| [**1. Arquitectura General**](01-Arquitectura-General.md) | Visión global del sistema, flujo de datos end-to-end, ciclo de vida reactivo y separación de responsabilidades. | `pdf-chatbot.py`, `database.py`, Streamlit, LangChain |
| [**2. Persistencia y Bases de Datos SQLite**](02-Persistencia-y-Bases-de-Datos.md) | Almacenamiento vectorial en SQLite, tablas, serialización BLOB, creación "al vuelo" y purgado completo de datos. | `database.py`, `documents.db`, `chat_history.db` |
| [**3. Extracción y OCR Multimodal**](03-Extraccion-y-OCR-Multimodal.md) | Estrategia híbrida: texto digital nativo, OCR local en CPU con RapidOCR, recorte de diagramas y fallback a Gemini Vision. | `pdfplumber`, `rapidocr_onnxruntime`, `extract_text_from_image` |
| [**4. Procesamiento Vectorial y RAG**](04-Procesamiento-Vectorial-y-RAG.md) | Segmentación en chunks, embeddings por lotes, búsqueda MMR en FAISS y cadena RAG con tolerancia a fallos. | `RecursiveCharacterTextSplitter`, `FAISS`, Gemini Fallbacks |
| [**5. Interfaz Streamlit y Flujo de Usuario**](05-Interfaz-Streamlit-y-Flujo-de-Usuario.md) | Experiencia de usuario, selector de documentos previos, deduplicación por hash SHA-256 e historial de chat. | `st.chat_message`, `st.chat_input`, `st.sidebar`, Estado |

---

## 🚀 Resumen Rápido del Sistema

El proyecto resuelve tres desafíos fundamentales en los chatbots conversacionales de documentos:

1. **Comprensión Completa de PDFs Reales:** No solo extrae texto seleccionable; si una página es una imagen escaneada o contiene diagramas técnicos incrustados, aplica **OCR local gratuito** sin gastar cuota de API.
2. **Persistencia Vectorial Ultrarrápida y Portable:** Mediante dos bases de datos SQLite locales (`documents.db` y `chat_history.db`), almacena los vectores precalculados (`np.float32`), permitiendo cambiar o reabrir documentos en **milisegundos con 0 llamadas a la API de embeddings**.
3. **Conversación Persistente por Documento:** Cada archivo mantiene su propio hilo de preguntas y respuestas almacenado, evitando que las conversaciones se borren al recargar el navegador.

---

## 💻 ¿Cómo Usar esta Wiki en GitHub?

Los archivos contenidos en la carpeta [`wiki/`](./) son 100% compatibles con el repositorio de Wikis de GitHub:
- Si deseas publicarla en la pestaña **Wiki** de tu repositorio de GitHub, puedes clonar tu wiki (`git clone https://github.com/rojaslcc/python-chatbot.wiki.git`), copiar estos archivos markdown dentro de ella y hacer `git push`.
- Además, todos los enlaces y referencias a código fuente son navegables directamente dentro de este repositorio.
