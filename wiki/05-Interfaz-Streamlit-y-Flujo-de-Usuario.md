# 🖥️ 5. Interfaz Streamlit y Flujo de Usuario

Esta página documenta la interfaz gráfica reactiva implementada con **Streamlit**, los controles de la barra lateral, la gestión del selector de documentos previos y la experiencia de chat conversacional.

---

## 🎨 Configuración de la Interfaz (`pdf-chatbot.py`)

```python
st.set_page_config(
    page_title="PDF Chatbot con Memoria SQLite",
    page_icon="📚",
    layout="wide"
)
```
- **`layout="wide"`:** Utiliza el 100% del ancho de la pantalla para dar espacio simultáneo a la barra lateral de documentos y al hilo conversacional.

---

## 🎛️ Barra Lateral y Selector de Documentos

La barra lateral organiza la configuración y la gestión de archivos:

### 1. Clave de API y Opciones de OCR
- Si no existe una clave en el archivo `.env`, se presenta un campo seguro de tipo contraseña (`type="password"`).
- Casilla interactiva `ocr_embedded_images` que permite activar o desactivar el OCR en gráficos incrustados.

### 2. Indexación de Documentos Grandes

El desplegable del mismo nombre permite configurar el motor de embeddings:

| Control visible | Inicial | Restricción / significado |
| :--- | :--- | :--- |
| Contenidos de embeddings por minuto | 60 | Entero positivo; presupuesto por fragmento, no una cuota garantizada. |
| Fragmentos por lote | 10 | Entre 1 y el menor de 100 o el presupuesto por minuto. |
| Reintentos por lote | 3 | Entre 0 y 10, adicionales al intento inicial. |
| Espera máxima por pausa (segundos) | 120 | Entero positivo; se aplica a cada espera, no al documento completo. |

Los cambios se usan al pulsar **Procesar documento** o **Reanudar indexación**.
Pueden ajustarse al reanudar sin descartar los lotes guardados. Consulta la cuota
de tu proyecto en AI Studio; los límites pueden incluir tokens y consumo compartido
que estos controles no contabilizan.

### 3. Menú Desplegable de Documentos Previos
En lugar de forzar al usuario a buscar y resubir un PDF cada vez que abre la aplicación:
- Se consultan todos los documentos guardados en `documents.db` mediante `database.get_all_documents()`.
- Se genera una lista con:
  - `➕ Subir nuevo PDF...` (para cargar archivos adicionales).
  - Cada documento previo formateado como: `📄 NombreArchivo.pdf [OCR] (X págs)`.
- El componente `st.selectbox` permite alternar entre documentos en un solo clic.

```python
chosen_doc_id = st.selectbox(
    "Seleccionar documento activo:",
    options=doc_options,
    index=doc_options.index(selected_option) if selected_option in doc_options else 0,
    format_func=format_doc_choice
)
```

Solo aparecen documentos publicados; los trabajos incompletos se recuperan al
volver a cargar el archivo, no desde este selector.

### 4. Ficha de Metadatos y Purgado
Cuando se selecciona un documento existente, se muestra un contenedor desplegable (`st.expander`) con:
- Nombre del archivo y fecha de carga.
- Total de páginas y fragmentos procesados.
- Tipo de procesamiento aplicado (Digital vs OCR).
- Botón **`🗑️ Eliminar este documento`**, que ejecuta `database.delete_document(chosen_doc_id)`, limpia el estado de sesión y recarga la interfaz.

---

## Procesar y Reanudar un PDF

1. Selecciona **➕ Subir nuevo PDF...** y carga el archivo.
2. Ajusta **OCR en imágenes incrustadas** y el presupuesto de indexación.
3. Si es nuevo, pulsa **Procesar documento**: se extrae el texto, se fragmenta y
   se guarda el trabajo antes de enviar embeddings.
4. Observa el contador `Embeddings: completados/total` y los mensajes de espera,
   reintento o lote guardado.
5. Al completar todos los vectores, se publica el documento y se activa el chat.

### Si se pausa o se reinicia la aplicación

Vuelve a subir **el mismo PDF**, conserva la misma opción de OCR y pulsa
**Reanudar indexación**. La pantalla muestra los fragmentos ya guardados; el texto
se recupera de SQLite sin repetir extracción ni OCR y solo se vectoriza lo pendiente.
Si la app se cerró antes de guardar la extracción completa, esa fase se repite.
Un lote enviado pero no confirmado también puede repetirse.

La pausa es recuperable, pero no se reanuda automáticamente en segundo plano.
El botón conserva el control del usuario para evitar reintentos al modificar
otros widgets. Cambiar la opción de OCR identifica otro trabajo, no continúa el
anterior. No hay un botón de borrado de trabajos pendientes.

### Qué significan los avisos

| Aviso / situación | Comportamiento y acción |
| :--- | :--- |
| Control de cuota: espera | El turno del lote aún no está disponible; espera sin reenviar manualmente. |
| HTTP 429 temporal o 500/502/503/504 | Se espera lo indicado por Google o la espera incremental, y se reintenta de forma acotada. |
| Cuota diaria identificada | Se pausa sin reintentos; consulta AI Studio y el plan antes de continuar. |
| Espera mayor al máximo o demasiada cola | Se pausa conservando el avance; reanuda más tarde o ajusta el máximo. |
| Reintentos agotados | Se conserva el avance; espera o corrige la causa y reanuda. |
| Error de credenciales, SSL u otro no transitorio | No se reintenta; consulta **Detalle técnico** cuando exista y corrige la causa. |
| Lote incompleto o vectores inválidos | Ese lote no se confirma; los anteriores siguen disponibles. |

El contador mide vectores guardados, no intentos realizados ni avance del OCR.
Los fallbacks del chat no solucionan una pausa de embeddings.

---

## ⚡ Detección Inteligente de Duplicados por Hash

Si el usuario elige la opción de subir un nuevo PDF y arrastra un archivo que ya fue procesado con anterioridad:

```python
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

## 💬 Área Principal de Conversación

El área principal adopta un diseño conversacional moderno basado en dos estados:

### Estado 1: Pantalla de Bienvenida (Sin Documento Activo)
Si no hay ningún PDF seleccionado:
- Se muestra una guía visual de bienvenida.
- Se muestran tarjetas (`st.container(border=True)`) con los últimos PDFs almacenados para que el usuario pueda identificarlos rápidamente.

### Estado 2: Chat Activo con Memoria
Cuando un PDF está activo:
1. **Barra de Acciones Superior:**
   - Muestra el nombre del documento activo (`active_doc_name`).
   - Botón **`🧹 Limpiar Chat`**: borra solo el historial de preguntas de ese documento.
   - Botón **`🗑️ Eliminar Doc`**: purga completamente el documento, sus vectores e historial.
2. **Renderizado del Historial Cronológico:**
   ```python
   chat_history = database.get_chat_history(active_doc_id)
   for msg in chat_history:
       with st.chat_message(msg["role"]):
           st.markdown(msg["content"])
   ```
3. **Caja de Entrada (`st.chat_input`):**
   - El usuario escribe la pregunta y presiona Enter.
   - El mensaje se dibuja de inmediato en pantalla y se guarda en `chat_history.db`.
   - Se muestra un spinner reactivo: *"Analizando documento y generando respuesta..."*.
   - Se genera la respuesta con la cadena RAG y se guarda en `chat_history.db`.
   - Se invoca `st.rerun()` para que el nuevo mensaje forme parte del historial permanente.

---

## 🧭 Navegación entre Capítulos

| [⬅️ Anterior: 4. Procesamiento Vectorial y RAG](04-Procesamiento-Vectorial-y-RAG) | [🏠 Inicio (Home)](Home) |
| :--- | :--- |
