# 🖥️ 5. Interfaz Streamlit y Flujo de Usuario

Esta página documenta la interfaz gráfica reactiva implementada con **Streamlit**, los controles de la barra lateral, la gestión del selector de documentos previos y la experiencia de chat conversacional.

---

## 🎨 Configuración de la Interfaz (`pdf-chatbot.py`: Líneas 111-116)

```python
# pdf-chatbot.py: Líneas 111-116
st.set_page_config(
    page_title="PDF Chatbot con Memoria SQLite",
    page_icon="📚",
    layout="wide"
)
```
- **`layout="wide"`:** Utiliza el 100% del ancho de la pantalla para dar espacio simultáneo a la barra lateral de documentos y al hilo conversacional.

---

## 🎛️ Barra Lateral y Selector de Documentos (`pdf-chatbot.py`: Líneas 127-214)

La barra lateral organiza la configuración y la gestión de archivos:

### 1. Clave de API y Opciones de OCR (`pdf-chatbot.py`: Líneas 131-149)
- Si no existe una clave en el archivo `.env`, se presenta un campo seguro de tipo contraseña (`type="password"`).
- Casilla interactiva `ocr_embedded_images` que permite activar o desactivar el OCR en gráficos incrustados.

### 2. Menú Desplegable de Documentos Previos (`pdf-chatbot.py`: Líneas 150-182)
En lugar de forzar al usuario a buscar y resubir un PDF cada vez que abre la aplicación:
- Se consultan todos los documentos guardados en `documents.db` mediante `database.get_all_documents()`.
- Se genera una lista con:
  - `➕ Subir nuevo PDF...` (para cargar archivos adicionales).
  - Cada documento previo formateado como: `📄 NombreArchivo.pdf [OCR] (X págs)`.
- El componente `st.selectbox` permite alternar entre documentos en un solo clic.

```python
# pdf-chatbot.py: Líneas 175-181
chosen_doc_id = st.selectbox(
    "Seleccionar documento activo:",
    options=doc_options,
    index=doc_options.index(selected_option) if selected_option in doc_options else 0,
    format_func=format_doc_choice
)
```

### 3. Ficha de Metadatos y Purgado (`pdf-chatbot.py`: Líneas 193-214)
Cuando se selecciona un documento existente, se muestra un contenedor desplegable (`st.expander`) con:
- Nombre y tamaño del archivo.
- Total de páginas y fragmentos procesados.
- Tipo de procesamiento aplicado (Digital vs OCR).
- Botón **`🗑️ Eliminar este documento`**, que ejecuta `database.delete_document(chosen_doc_id)`, limpia el estado de sesión y recarga la interfaz.

---

## ⚡ Detección Inteligente de Duplicados por Hash (`pdf-chatbot.py`: Líneas 223-240)

Si el usuario elige la opción de subir un nuevo PDF y arrastra un archivo que ya fue procesado con anterioridad:

```python
# pdf-chatbot.py: Líneas 223-238
file_bytes = uploaded_file.getvalue()
file_hash = database.calculate_file_hash(file_bytes)
existing_doc = database.get_document_by_hash(file_hash)

if existing_doc:
    st.info("⚡ ¡Documento reconocido en SQLite! Cargando vectores instantáneamente...")
    vs = database.load_vectorstore_from_db(existing_doc["id"], embeddings_model)
    st.session_state.vector_store = vs
    st.session_state.active_doc_id = existing_doc["id"]
    st.session_state.active_doc_name = existing_doc["filename"]
    st.rerun()
```
- **Resultado:** No se repite el OCR ni se gastan llamadas a la API de embeddings; el sistema reconoce el archivo por su contenido (hash SHA-256) y lo activa inmediatamente.

---

## 💬 Área Principal de Conversación (`pdf-chatbot.py`: Líneas 387-581)

El área principal adopta un diseño conversacional moderno basado en dos estados:

### Estado 1: Pantalla de Bienvenida (Sin Documento Activo) (`pdf-chatbot.py`: Líneas 390-424)
Si no hay ningún PDF seleccionado:
- Se muestra una guía visual de bienvenida.
- Se muestran tarjetas (`st.container(border=True)`) con los últimos PDFs almacenados para que el usuario pueda identificarlos rápidamente.

### Estado 2: Chat Activo con Memoria (`pdf-chatbot.py`: Líneas 425-581)
Cuando un PDF está activo:
1. **Barra de Acciones Superior:**
   - Muestra el nombre del documento activo (`active_doc_name`).
   - Botón **`🧹 Limpiar Chat`**: borra solo el historial de preguntas de ese documento.
   - Botón **`🗑️ Eliminar Doc`**: purga completamente el documento, sus vectores e historial.
2. **Renderizado del Historial Cronológico (`pdf-chatbot.py`: Líneas 470-475):**
   ```python
   chat_history = database.get_chat_history(active_doc_id)
   for msg in chat_history:
       with st.chat_message(msg["role"]):
           st.markdown(msg["content"])
   ```
3. **Caja de Entrada Pinned (`st.chat_input`) (`pdf-chatbot.py`: Líneas 477-581):**
   - El usuario escribe la pregunta y presiona Enter.
   - El mensaje se dibuja de inmediato en pantalla y se guarda en `chat_history.db`.
   - Se muestra un spinner reactivo: *"Analizando documento y generando respuesta..."*.
   - Se genera la respuesta con la cadena RAG y se guarda en `chat_history.db`.
   - Se invoca `st.rerun()` para que el nuevo mensaje forme parte del historial permanente.

---

## 🧭 Navegación entre Capítulos

| [⬅️ Anterior: 4. Procesamiento Vectorial y RAG](04-Procesamiento-Vectorial-y-RAG) | [🏠 Inicio (Home)](Home) |
| :--- | :--- |
