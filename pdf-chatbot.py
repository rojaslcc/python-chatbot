import os
import io
import base64
import pdfplumber
import streamlit as st
import numpy as np
from dotenv import load_dotenv

# Módulos de LangChain para procesamiento, estructura de documentos y división de texto
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Integraciones oficiales de Google Gemini para generación de embeddings y modelos de chat (LLM)
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI

# Base de datos vectorial en memoria (FAISS) para búsqueda de similitud ultrarrápida
from langchain_community.vectorstores import FAISS

# Utilidades para construcción de cadenas RAG, formateo de salida y plantillas de prompts
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

# Módulo propio de persistencia SQLite para documentos, vectores e historial de chat
import database

# ==============================================================================
# 0. VERIFICACIÓN Y CREACIÓN AUTOMÁTICA DE BASES DE DATOS SQLITE AL VUELO
# ==============================================================================
# Garantiza que el sistema sea completamente autocontenido. Si el usuario clona
# el repositorio por primera vez o no existen las bases de datos, esta función
# crea la carpeta `data/` y los esquemas en `documents.db` y `chat_history.db`
# automáticamente al vuelo, sin requerir migraciones manuales ni comandos externos.
db_status = database.init_databases()

# ==============================================================================
# 1. GESTIÓN Y CARGA SEGURA DE LA CLAVE DE API DE GOOGLE GEMINI
# ==============================================================================
# Carga las variables de entorno definidas en el archivo .env local si existe
load_dotenv()

# Prioridad 1: Obtener la clave desde variables de entorno (.env o sistema operativo)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Prioridad 2: Si no existe en .env, intentar leer desde secrets.toml de Streamlit
if not GOOGLE_API_KEY:
    try:
        GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")
    except Exception:
        GOOGLE_API_KEY = ""

# ==============================================================================
# 2. MOTOR DE OCR LOCAL (RAPIDOCR)
# Permite transcribir documentos escaneados e imágenes directamente en la CPU,
# sin consumir peticiones de la API de Google (100% gratuito e ilimitado).
# ==============================================================================
@st.cache_resource
def get_ocr_engine():
    """
    Inicializa el motor RapidOCR una sola vez y lo mantiene en memoria caché
    usando st.cache_resource para optimizar el rendimiento y velocidad en ejecuciones recurrentes.
    """
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()

def extract_text_from_image(pil_img, api_key: str = "") -> str:
    """
    Extrae texto de una imagen (página escaneada o gráfico incrustado) de forma local.
    Si por algún motivo el motor local falla, cuenta con un respaldo secundario
    usando la API multimodal de Gemini (gemini-flash-lite-latest).
    """
    try:
        engine = get_ocr_engine()
        # Convertir imagen PIL a arreglo NumPy compatible con RapidOCR (RGB)
        img_np = np.array(pil_img.convert("RGB"))
        result, _ = engine(img_np)
        if result:
            # result contiene una lista de tuplas con formato: [coordenadas, texto, nivel_confianza]
            lines = [line[1] for line in result]
            return "\n".join(lines).strip()
    except Exception:
        # Mecanismo de respaldo secundario mediante API si el OCR local encuentra un error
        if api_key:
            try:
                from langchain_core.messages import HumanMessage
                
                # Redimensionar la imagen si es excesivamente grande para ahorrar ancho de banda y latencia
                max_dim = 1600
                if max(pil_img.size) > max_dim:
                    pil_img.thumbnail((max_dim, max_dim))
                    
                buffer = io.BytesIO()
                pil_img.convert("RGB").save(buffer, format="JPEG", quality=85)
                img_b64 = base64.b64encode(buffer.getvalue()).decode()
                
                vision_llm = ChatGoogleGenerativeAI(
                    model="gemini-flash-lite-latest",
                    temperature=0.0,
                    google_api_key=api_key
                )
                msg = HumanMessage(content=[
                    {
                        "type": "text", 
                        "text": "Transcribe accurately all text, numbers, and tables in this image. Only return the transcribed text."
                    },
                    {
                        "type": "image_url", 
                        "image_url": f"data:image/jpeg;base64,{img_b64}"
                    }
                ])
                res = vision_llm.invoke([msg])
                return StrOutputParser().invoke(res).strip()
            except Exception:
                pass
    return ""

# ==============================================================================
# 3. INTERFAZ GRÁFICA DE USUARIO Y BARRA LATERAL (STREAMLIT)
# ==============================================================================
st.set_page_config(
    page_title="PDF Chatbot con Memoria SQLite",
    page_icon="📚",
    layout="wide"
)

# Inicializar modelo de embeddings si hay API Key disponible
embeddings_model = None
if GOOGLE_API_KEY:
    embeddings_model = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GOOGLE_API_KEY
    )

# ------------------------------------------------------------------------------
# BARRA LATERAL: CONFIGURACIÓN Y GESTOR DE DOCUMENTOS PERSISTENTES
# ------------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Configuración")
    
    # Si la clave no está en el .env, se solicita al usuario mediante un campo seguro (tipo password)
    if not GOOGLE_API_KEY:
        GOOGLE_API_KEY = st.text_input(
            "Gemini API Key", 
            type="password", 
            placeholder="Ingresa tu Gemini API Key"
        )
        if GOOGLE_API_KEY:
            embeddings_model = GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-001",
                google_api_key=GOOGLE_API_KEY
            )
            
    # Casilla para activar o desactivar el análisis profundo de imágenes dentro de páginas con texto
    ocr_embedded_images = st.checkbox(
        "OCR en imágenes incrustadas", 
        value=True, 
        help="Si una página contiene texto e imágenes/gráficos adicionales, también analiza las imágenes con OCR."
    )
    
    st.divider()
    st.title("📁 Gestión de Documentos")
    
    # Recuperar lista de todos los documentos previamente procesados y persistidos en SQLite
    saved_docs = database.get_all_documents()
    docs_map = {doc["id"]: doc for doc in saved_docs}
    
    # Opción especial para subir un archivo nuevo
    UPLOAD_NEW_OPTION = "__upload_new__"
    doc_options = [UPLOAD_NEW_OPTION] + [doc["id"] for doc in saved_docs]
    
    def format_doc_choice(opt_id: str) -> str:
        """Formatea la etiqueta visible en el menú desplegable de selección de documentos."""
        if opt_id == UPLOAD_NEW_OPTION:
            return "➕ Subir nuevo PDF..."
        d = docs_map.get(opt_id)
        if d:
            ocr_badge = " [OCR]" if d["has_ocr"] else ""
            return f"📄 {d['filename']}{ocr_badge} ({d['total_pages']} págs)"
        return opt_id
    
    # Determinar qué opción debe estar seleccionada por defecto en el estado de sesión
    selected_option = st.session_state.get("selected_doc_option", UPLOAD_NEW_OPTION)
    if selected_option not in doc_options:
        selected_option = doc_options[1] if len(doc_options) > 1 else UPLOAD_NEW_OPTION
        st.session_state.selected_doc_option = selected_option
        
    chosen_doc_id = st.selectbox(
        "Seleccionar documento activo:",
        options=doc_options,
        index=doc_options.index(selected_option) if selected_option in doc_options else 0,
        format_func=format_doc_choice,
        help="Selecciona un PDF del historial para continuar consultándolo o sube uno nuevo."
    )
    st.session_state.selected_doc_option = chosen_doc_id

    # Caso 1: El usuario seleccionó subir un nuevo documento
    uploaded_file = None
    if chosen_doc_id == UPLOAD_NEW_OPTION:
        uploaded_file = st.file_uploader(
            "Cargar archivo PDF:", 
            type="pdf",
            help="Sube un archivo para procesarlo e indexarlo en la base vectorial SQLite."
        )

    # Caso 2: El usuario seleccionó un documento existente del historial
    elif chosen_doc_id in docs_map:
        doc_info = docs_map[chosen_doc_id]
        with st.expander("ℹ️ Metadatos del Documento", expanded=True):
            st.write(f"**Archivo:** `{doc_info['filename']}`")
            st.write(f"**Páginas:** {doc_info['total_pages']}")
            st.write(f"**Fragmentos:** {doc_info['total_chunks']}")
            st.write(f"**Procesamiento:** {'OCR Local + Digital' if doc_info['has_ocr'] else 'Texto Digital'}")
            st.write(f"**Fecha de carga:** {doc_info['created_at']}")
            
            # Botón para eliminar el documento y su historial de la base de datos
            if st.button("🗑️ Eliminar este documento", type="secondary", use_container_width=True):
                database.delete_document(chosen_doc_id)
                st.session_state.selected_doc_option = UPLOAD_NEW_OPTION
                if "vector_store" in st.session_state:
                    del st.session_state["vector_store"]
                if "active_doc_id" in st.session_state:
                    del st.session_state["active_doc_id"]
                st.success("Documento e historial eliminados correctamente.")
                st.rerun()

# ==============================================================================
# 4. EXTRACCIÓN HÍBRIDA, PERSISTENCIA VECTORIAL EN SQLITE Y CARGA INSTANTÁNEA
# ==============================================================================

# ------------------------------------------------------------------------------
# CASO A: El usuario seleccionó subir un archivo nuevo y cargó un PDF
# ------------------------------------------------------------------------------
if chosen_doc_id == UPLOAD_NEW_OPTION and uploaded_file is not None:
    # Validar que exista una clave API antes de iniciar cualquier procesamiento
    if not GOOGLE_API_KEY:
        st.warning("⚠️ Por favor ingresa tu Gemini API Key en la barra lateral para continuar.")
        st.stop()
        
    file_bytes = uploaded_file.getvalue()
    # Calcular hash criptográfico SHA-256 para detección inteligente de duplicados
    file_hash = database.calculate_file_hash(file_bytes)
    
    # 1. Comprobar si este mismo archivo ya existía previamente en SQLite
    existing_doc = database.get_document_by_hash(file_hash)
    
    if existing_doc:
        # Si ya existe en SQLite: Carga instantánea sin costo de OCR ni API
        st.info(f"⚡ **¡Documento reconocido en SQLite!** `{existing_doc['filename']}` ya estaba procesado. Cargando vectores instantáneamente (0 llamadas a la API, 0s OCR)...")
        with st.spinner("Reconstruyendo índice vectorial desde SQLite..."):
            vs = database.load_vectorstore_from_db(existing_doc["id"], embeddings_model)
            st.session_state.vector_store = vs
            st.session_state.active_doc_id = existing_doc["id"]
            st.session_state.active_doc_name = existing_doc["filename"]
            st.session_state.selected_doc_option = existing_doc["id"]
            st.rerun()
    else:
        # 2. Documento nuevo: extraer texto, ejecutar OCR si es necesario y generar embeddings
        with st.status("Procesando y vectorizando documento nuevo...", expanded=True) as status_box:
            with pdfplumber.open(uploaded_file) as pdf:
                total_pages = len(pdf.pages)
                status_box.write(f"📄 Total de páginas detectadas: {total_pages}")
                
                page_documents = []
                any_ocr_used = False
                
                # Iterar por cada página del PDF para extraer información textual o visual
                for idx, page in enumerate(pdf.pages):
                    page_num = idx + 1
                    page_text = page.extract_text() or ""
                    extracted_text = ""
                    
                    # ----------------------------------------------------------
                    # SUB-CASO 1: Páginas escaneadas o de solo imagen (< 30 caracteres digitales)
                    # ----------------------------------------------------------
                    if len(page_text.strip()) < 30:
                        status_box.write(f"🔍 Pág. {page_num}: Sin texto digital. Aplicando OCR local (gratis, 0 API)...")
                        try:
                            # Renderizar la página completa a imagen con resolución optimizada (150 DPI)
                            page_img = page.to_image(resolution=150).original
                            ocr_text = extract_text_from_image(page_img, GOOGLE_API_KEY)
                            if ocr_text:
                                extracted_text += f"\n--- Página {page_num} (OCR) ---\n" + ocr_text + "\n"
                                any_ocr_used = True
                        except Exception as e:
                            status_box.write(f"⚠️ Error en captura de imagen pág. {page_num}: {e}")
                    else:
                        # ------------------------------------------------------
                        # SUB-CASO 2: Páginas con texto digital seleccionable normal
                        # ------------------------------------------------------
                        status_box.write(f"📝 Pág. {page_num}: Texto digital extraído.")
                        extracted_text += f"\n--- Página {page_num} ---\n" + page_text + "\n"
                        
                        # ------------------------------------------------------
                        # SUB-CASO 3: Páginas mixtas (texto digital con infografías/diagramas)
                        # ------------------------------------------------------
                        if ocr_embedded_images and len(page.images) > 0:
                            # Filtrar únicamente imágenes relevantes (> 120x120 px) para ignorar logos o íconos pequeños
                            significant_images = [
                                img for img in page.images 
                                if img.get("width", 0) > 120 and img.get("height", 0) > 120
                            ]
                            if significant_images:
                                status_box.write(f"🖼️ Pág. {page_num}: {len(significant_images)} gráficos detectados. Ejecutando OCR local...")
                                for img_idx, img_obj in enumerate(significant_images[:3]):
                                    try:
                                        # Recortar el área delimitada de la imagen dentro de la página
                                        bbox = (img_obj["x0"], img_obj["top"], img_obj["x1"], img_obj["bottom"])
                                        cropped_img = page.crop(bbox).to_image(resolution=150).original
                                        img_text = extract_text_from_image(cropped_img, GOOGLE_API_KEY)
                                        if img_text:
                                            extracted_text += f"\n[Contenido de imagen #{img_idx+1} en Pág. {page_num}]:\n{img_text}\n"
                                            any_ocr_used = True
                                    except Exception:
                                        pass
                                        
                    # Si se obtuvo texto de la página, estructurarlo como Document de LangChain con metadatos
                    if extracted_text.strip():
                        page_documents.append(Document(
                            page_content=extracted_text, 
                            metadata={"page": page_num}
                        ))

            # Validar que se haya obtenido algún texto legible o visual
            if not page_documents:
                st.error("⚠️ No se pudo extraer ningún texto legible ni visual de este archivo PDF.")
                st.stop()
                
            # ------------------------------------------------------------------
            # DIVISIÓN DEL TEXTO EN FRAGMENTOS SEMÁNTICOS (CHUNKS)
            # Permite que el buscador semántico encuentre secciones y páginas precisas
            # ------------------------------------------------------------------
            status_box.write("✂️ Dividiendo texto en fragmentos semánticos...")
            text_splitter = RecursiveCharacterTextSplitter(
                separators=["\n\n", "\n", ". ", " ", ""],
                chunk_size=1000,
                chunk_overlap=200
            )
            chunks = text_splitter.split_documents(page_documents)
            
            # ------------------------------------------------------------------
            # GENERACIÓN DE EMBEDDINGS CON GEMINI (POR LOTES)
            # ------------------------------------------------------------------
            status_box.write(f"🧠 Generando embeddings para {len(chunks)} fragmentos con Gemini...")
            chunk_texts = [c.page_content for c in chunks]
            
            # Procesar embeddings en lotes de 50 para evitar exceder límites de payload de la API
            all_embeddings = []
            batch_size = 50
            for b_idx in range(0, len(chunk_texts), batch_size):
                batch = chunk_texts[b_idx:b_idx + batch_size]
                batch_embs = embeddings_model.embed_documents(batch)
                all_embeddings.extend(batch_embs)
                
            # ------------------------------------------------------------------
            # PERSISTENCIA EN BASE DE DATOS VECTORIAL SQLITE (data/documents.db)
            # ------------------------------------------------------------------
            status_box.write("💾 Persistiendo documento y base vectorial en SQLite (`data/documents.db`)...")
            new_doc_id = file_hash[:16]
            chunks_data = []
            for c_idx, (chunk, emb) in enumerate(zip(chunks, all_embeddings)):
                chunks_data.append({
                    "chunk_index": c_idx,
                    "page_number": chunk.metadata.get("page", 1),
                    "content": chunk.page_content,
                    "embedding": emb
                })
                
            # Guardar metadatos y vectores binarios float32 en SQLite
            database.save_document(
                doc_id=new_doc_id,
                filename=uploaded_file.name,
                file_hash=file_hash,
                file_size=len(file_bytes),
                total_pages=total_pages,
                total_chunks=len(chunks),
                has_ocr=1 if any_ocr_used else 0,
                chunks=chunks_data
            )
            
            # ------------------------------------------------------------------
            # CONSTRUCCIÓN DEL ÍNDICE VECTORIAL EN MEMORIA (FAISS)
            # ------------------------------------------------------------------
            text_embeddings = list(zip(chunk_texts, all_embeddings))
            metadatas = [c.metadata for c in chunks]
            vector_store = FAISS.from_embeddings(text_embeddings, embeddings_model, metadatas=metadatas)
            
            # Guardar en st.session_state para reutilizarlo en preguntas inmediatas
            st.session_state.vector_store = vector_store
            st.session_state.active_doc_id = new_doc_id
            st.session_state.active_doc_name = uploaded_file.name
            st.session_state.selected_doc_option = new_doc_id
            
            status_box.update(label="✅ Documento procesado, persistido en SQLite y listo para consultas!", state="complete", expanded=False)
            st.rerun()

# ------------------------------------------------------------------------------
# CASO B: El usuario seleccionó un documento existente desde el selectbox
# ------------------------------------------------------------------------------
elif chosen_doc_id != UPLOAD_NEW_OPTION and chosen_doc_id in docs_map:
    # Si el almacén vectorial no está en memoria o no corresponde al documento seleccionado,
    # se reconstruye instantáneamente desde SQLite sin gastar cuota de API de embeddings
    if st.session_state.get("active_doc_id") != chosen_doc_id or "vector_store" not in st.session_state:
        if not GOOGLE_API_KEY:
            st.warning("⚠️ Ingresa tu Gemini API Key en la barra lateral para consultar este documento.")
            st.stop()
            
        with st.spinner(f"Cargando vectores de '{docs_map[chosen_doc_id]['filename']}' desde SQLite..."):
            vs = database.load_vectorstore_from_db(chosen_doc_id, embeddings_model)
            if vs:
                st.session_state.vector_store = vs
                st.session_state.active_doc_id = chosen_doc_id
                st.session_state.active_doc_name = docs_map[chosen_doc_id]["filename"]
            else:
                st.error("No se pudieron cargar los fragmentos vectoriales de este documento.")
                st.stop()

# ==============================================================================
# 5. ÁREA PRINCIPAL: CHAT CON PERSISTENCIA EN SQLITE (chat_history.db)
# ==============================================================================

# ------------------------------------------------------------------------------
# ESTADO VACÍO: Cuando no hay ningún documento activo seleccionado
# ------------------------------------------------------------------------------
if not st.session_state.get("active_doc_id") or "vector_store" not in st.session_state:
    st.header("📚 Asistente Virtual para Documentos PDF con Memoria SQLite")
    st.markdown("""
    Bienvenido al asistente inteligente para documentos PDF. 
    
    ### 🚀 ¿Cómo empezar?
    1. **Sube un nuevo archivo PDF** usando la barra lateral izquierda, o
    2. **Selecciona un documento procesado previamente** desde el menú desplegable del historial.
    
    ---
    ### 💾 Persistencia Local con SQLite
    - **Base Vectorial Local (`data/documents.db`):** Los textos, páginas y embeddings se guardan automáticamente. Si vuelves a abrir la aplicación o seleccionas un documento previo, se cargará al instante con **0 llamadas a la API y 0 segundos de OCR**.
    - **Historial de Conversación (`data/chat_history.db`):** Cada documento mantiene su propio historial de preguntas y respuestas guardado de forma permanente.
    """)
    
    # Mostrar tarjetas de acceso rápido a documentos guardados si existen
    if saved_docs:
        st.subheader("📋 Documentos Guardados en el Historial:")
        cols = st.columns(min(len(saved_docs), 3))
        for i, doc in enumerate(saved_docs[:6]):
            with cols[i % len(cols)]:
                with st.container(border=True):
                    st.write(f"📄 **{doc['filename']}**")
                    st.caption(f"📑 {doc['total_pages']} páginas | 🧩 {doc['total_chunks']} chunks")
                    st.caption(f"📅 {doc['created_at'][:10]}")
    st.stop()

# ------------------------------------------------------------------------------
# ESTADO ACTIVO: Conversación sobre el documento seleccionado
# ------------------------------------------------------------------------------
active_doc_id = st.session_state.active_doc_id
active_doc_name = st.session_state.active_doc_name
vector_store = st.session_state.vector_store

# Cabecera con nombre del documento, botón para limpiar chat y botón para eliminar documento
header_col1, header_col2, header_col3 = st.columns([4, 1.2, 1.2])
with header_col1:
    st.subheader(f"💬 Conversando con: `{active_doc_name}`")
with header_col2:
    if st.button("🧹 Limpiar Chat", help="Borra el historial de conversación de este documento"):
        database.clear_chat_history(active_doc_id)
        st.toast("Historial de chat borrado con éxito.")
        st.rerun()
with header_col3:
    if st.button("🗑️ Eliminar Doc", help="Elimina este PDF, sus vectores y su historial de las bases de datos"):
        database.delete_document(active_doc_id)
        st.session_state.selected_doc_option = UPLOAD_NEW_OPTION
        if "vector_store" in st.session_state:
            del st.session_state["vector_store"]
        if "active_doc_id" in st.session_state:
            del st.session_state["active_doc_id"]
        st.toast("Documento, vectores e historial eliminados correctamente.")
        st.rerun()

# Recuperar historial de conversación desde SQLite (data/chat_history.db)
chat_history = database.get_chat_history(active_doc_id)

# Mostrar cronológicamente los mensajes previos guardados
for msg in chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada de nueva pregunta usando el componente nativo st.chat_input
user_question = st.chat_input("Escribe tu pregunta sobre el documento...")

if user_question:
    if not GOOGLE_API_KEY:
        st.warning("⚠️ Por favor ingresa tu Gemini API Key en la barra lateral.")
        st.stop()

    # 1. Mostrar y persistir de inmediato el mensaje del usuario en SQLite
    with st.chat_message("user"):
        st.markdown(user_question)
    database.save_chat_message(active_doc_id, "user", user_question)

    # 2. Configurar la cadena RAG (Retrieval-Augmented Generation) con LangChain
    
    # Función auxiliar para unir el contenido textual de los fragmentos recuperados
    def format_docs(docs):
        return "\n\n".join([doc.page_content for doc in docs])

    # Configurar el recuperador vectorial con búsqueda MMR (Maximal Marginal Relevance)
    # Selecciona los 4 fragmentos más relevantes y diversos del documento
    retriever = vector_store.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 4}
    )

    # --------------------------------------------------------------------------
    # CONFIGURACIÓN DEL MODELO LLM CON CADENA DE RESPALDO (FALLBACKS)
    # Utiliza modelos 'lite' con alto cupo gratuito (hasta 1,500 peticiones/día).
    # Si un modelo alcanza su límite momentáneo, conmuta automáticamente al siguiente.
    # --------------------------------------------------------------------------
    primary_llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0.3,
        max_tokens=1000,
        google_api_key=GOOGLE_API_KEY
    )
    fallback_llm1 = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        temperature=0.3,
        max_tokens=1000,
        google_api_key=GOOGLE_API_KEY
    )
    fallback_llm2 = ChatGoogleGenerativeAI(
        model="gemini-3.6-flash",
        temperature=0.3,
        max_tokens=1000,
        google_api_key=GOOGLE_API_KEY
    )
    llm = primary_llm.with_fallbacks([fallback_llm1, fallback_llm2])

    # --------------------------------------------------------------------------
    # PLANTILLA DE PROMPT DEL SISTEMA
    # Redactada en inglés como instrucción técnica precisa, diseñada para entender
    # texto digital, transcripciones OCR e imágenes, respondiendo en el idioma del usuario.
    # --------------------------------------------------------------------------
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an expert AI assistant specializing in answering questions about PDF documents.\n"
         "The provided context may contain:\n"
         "- Regular digital text extracted directly from the PDF.\n"
         "- OCR transcriptions from scanned/image pages (prefixed with '--- Página X (OCR) ---').\n"
         "- Visual element transcriptions from embedded charts, diagrams, or infographics (tagged like '[Contenido de imagen #N en Pág. X]').\n\n"
         "Strict Guidelines:\n"
         "1. Language Adaptation: ALWAYS respond in the EXACT same language as the user's question (e.g., if asked in Spanish, provide your full response in natural, professional Spanish).\n"
         "2. Multi-Modal Context Synthesis: Seamlessly connect and synthesize insights from both text sections and image/diagram transcriptions.\n"
         "3. Source Attribution: Whenever available in the context markers, cite the specific page number or image reference (e.g., 'Según la Página 1...', 'En el diagrama de la Página 4...').\n"
         "4. Factual Grounding: Answer strictly using ONLY the facts and data given in the context. Never invent facts or extrapolate beyond what is documented.\n"
         "5. Clear Structure: For multi-step procedures, technical explanations, or numbers, use bullet points, numbered lists, bold highlights, or markdown tables.\n"
         "6. Missing Information: If the context does not contain enough information to answer the question, state politely and clearly that the information is not present in the document.\n\n"
         "Context:\n{context}"),
        ("human", "{question}")
    ])

    # --------------------------------------------------------------------------
    # CONSTRUCCIÓN DE LA CADENA RAG (Retrieval-Augmented Generation)
    # Flujo: Pregunta -> Recuperador busca fragmentos -> Prompt con contexto -> LLM -> Salida formateada
    # --------------------------------------------------------------------------
    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    # 3. Generar y mostrar la respuesta del asistente con spinner interactivo
    with st.chat_message("assistant"):
        with st.spinner("Analizando documento y generando respuesta..."):
            response = chain.invoke(user_question)
            st.markdown(response)
            
    # 4. Guardar respuesta del asistente en SQLite (data/chat_history.db)
    database.save_chat_message(active_doc_id, "assistant", response)
    
    # 5. Rerun para sincronizar la vista y mantener el flujo continuo de conversación
    st.rerun()