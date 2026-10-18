# 🧠 4. Procesamiento Vectorial y RAG

Esta página describe la arquitectura de **Recuperación Aumentada por Generación (RAG)**, el algoritmo de segmentación semántica de texto, el cálculo de embeddings por lotes y la cadena tolerante a fallos de cuota con **Google Gemini**.

---

## ✂️ Segmentación Semántica en Fragmentos (`pdf-chatbot.py`: Líneas 315-327)

Para que el modelo de lenguaje pueda consultar fragmentos relevantes en lugar del libro o documento completo, se utiliza `RecursiveCharacterTextSplitter`:

```python
# pdf-chatbot.py: Líneas 319-326
text_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", ". ", " ", ""],
    chunk_size=1000,
    chunk_overlap=200
)
chunks = text_splitter.split_documents(page_documents)
```

### Parámetros Clave:
1. **`chunk_size=1000`:** Tamaño óptimo en caracteres (~200 a 250 palabras). Es lo suficientemente amplio para conservar una idea o tabla completa sin sobrecargar el contexto.
2. **`chunk_overlap=200`:** Solapamiento de 200 caracteres entre fragmentos adyacentes para evitar que frases o conceptos importantes se corten por la mitad en el límite del chunk.
3. **`split_documents(page_documents)`:** Preserva los metadatos de origen `{"page": page_num}` en cada chunk resultante, lo que permite citar la página exacta en la respuesta.

---

## 🧠 Generación de Embeddings por Lotes (`pdf-chatbot.py`: Líneas 328-341)

El modelo de vectorización utilizado es `models/gemini-embedding-001`.

Para evitar errores de cuota o límites de tamaño de paquete (*payload size limit*) cuando un PDF genera cientos de fragmentos, los embeddings se procesan en **lotes de 50 fragmentos**:

```python
# pdf-chatbot.py: Líneas 333-340
all_embeddings = []
batch_size = 50
for b_idx in range(0, len(chunk_texts), batch_size):
    batch = chunk_texts[b_idx:b_idx + batch_size]
    batch_embs = embeddings_model.embed_documents(batch)
    all_embeddings.extend(batch_embs)
```

---

## 🎯 Recuperación Semántica con MMR (`pdf-chatbot.py`: Líneas 497-501)

A diferencia de la búsqueda tradicional por similitud pura (que puede traer 4 párrafos casi idénticos de la misma página), el sistema utiliza **Maximal Marginal Relevance (MMR)**:

```python
# pdf-chatbot.py: Líneas 497-501
retriever = vector_store.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 4}
)
```

- **¿Cómo funciona MMR?** Busca el fragmento más similar a la pregunta del usuario y, a continuación, selecciona los siguientes fragmentos equilibrando la **relevancia con la diversidad**.
- **Resultado:** Si la respuesta se encuentra dispersa entre un texto y un diagrama en páginas distintas, el recuperador rescata ambos sin redundancia.

---

## 🛡️ Cadena de Fallbacks para Evitar Errores 429 (`pdf-chatbot.py`: Líneas 503-524)

Uno de los problemas más frecuentes en aplicaciones RAG con niveles gratuitos es el error `429: ResourceExhausted`. 

Para resolverlo, se diseñó una cadena de tres modelos ligeros con conmutación automática:

```python
# pdf-chatbot.py: Líneas 509-524
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
```

- Si `gemini-flash-lite-latest` alcanza su límite por minuto, conmuta de forma transparente e instantánea a `gemini-3.5-flash-lite`. Si este también se satura, conmuta a `gemini-3.6-flash`.
- El usuario nunca percibe una interrupción ni ve un mensaje de error en pantalla.

---

## 📝 Prompt de Sistema y Construcción de la Cadena LCEL (`pdf-chatbot.py`: Líneas 526-562)

La plantilla de prompt instruye al modelo con reglas estrictas de fidelidad:

1. **Adaptación de Idioma:** Responder exactamente en el mismo idioma en que preguntó el usuario.
2. **Síntesis Multimodal:** Combinar datos de texto y de imágenes etiquetadas como `[Contenido de imagen #N en Pág. X]`.
3. **Cita de Fuentes:** Mencionar siempre la página o diagrama de origen (ej: *"Según la Página 2..."*).
4. **Anclaje Factual Estricto:** Prohibido alucinar o inventar datos fuera del documento.
5. **Transparencia:** Si el dato no está en el PDF, indicarlo cortésmente.

### Tubería LCEL (LangChain Expression Language):
```python
# pdf-chatbot.py: Líneas 556-562
chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)
```

Al invocar `chain.invoke(user_question)`:
1. `retriever` busca los 4 fragmentos MMR en FAISS.
2. `format_docs` une los fragmentos con separadores de párrafo.
3. `prompt` ensambla el contexto con la pregunta.
4. `llm` (con fallbacks) genera la respuesta textual.
5. `StrOutputParser` limpia y extrae el texto puro para mostrarlo en Streamlit.
