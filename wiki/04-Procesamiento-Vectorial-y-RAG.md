# 🧠 4. Procesamiento Vectorial y RAG

Esta página describe la segmentación, la indexación reanudable con **Gemini**, el control de cuota y la cadena **RAG**. La indexación de documentos, la vectorización de preguntas y la generación de respuestas son operaciones distintas.

---

## ✂️ Segmentación en Fragmentos (`pdf-chatbot.py`)

Para que el modelo de lenguaje pueda consultar fragmentos relevantes en lugar del libro o documento completo, se utiliza `RecursiveCharacterTextSplitter`:

```python
text_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", ". ", " ", ""],
    chunk_size=1000,
    chunk_overlap=200
)
chunks = text_splitter.split_documents(page_documents)
```

### Parámetros Clave:
1. **`chunk_size=1000`:** Tamaño máximo configurado en caracteres, no tokens. No garantiza conservar tablas o ideas completas.
2. **`chunk_overlap=200`:** Solapamiento de 200 caracteres entre fragmentos adyacentes para evitar que frases o conceptos importantes se corten por la mitad en el límite del chunk.
3. **`split_documents(page_documents)`:** Preserva los metadatos de origen `{"page": page_num}` en cada chunk resultante, lo que permite citar la página exacta en la respuesta.

---

## 🧠 Indexación Reanudable (`indexing.py`)

El modelo de vectorización utilizado es `models/gemini-embedding-001`.

`index_job()` carga el trabajo guardado y selecciona solo fragmentos cuyo
`embedding` es nulo. Por cada lote reserva un turno, espera si corresponde, llama
a Gemini, valida los vectores y confirma el lote en SQLite. La interfaz recibe
progreso mediante un callback con fragmentos completados, total y mensaje.

```python
# Valores iniciales de IndexingSettings; editables desde la barra lateral
settings = indexing.IndexingSettings(
    contents_per_minute=60,
    batch_size=10,
    max_retries=3,
    max_wait_seconds=120,
)
```

Los lotes ya no son de 50 sin regulación. El tamaño permitido es entre 1 y el
menor de 100 o el presupuesto por minuto. Este presupuesto es **por contenido**:
10 fragmentos consumen 10 unidades, aunque viajen juntos. Es una estrategia
conservadora; agrupar textos no garantiza evitar un 429.

### Ritmo y alcance de la cuota

`database.reserve_embedding_slot()` coordina sesiones que usan la misma base,
clave y modelo. Reserva un intervalo de 60 segundos multiplicado por el número de
contenidos del lote y dividido por el presupuesto por minuto. Con los valores
iniciales, un lote de 10 reserva 10 segundos.

No mide tokens/minuto, cuota diaria, tráfico de otras aplicaciones o claves del
mismo proyecto, ni los embeddings de preguntas. Los valores deben ajustarse a los
[límites de AI Studio](https://aistudio.google.com/usage?timeRange=last-28-days&tab=rate-limit).
La latencia y los reintentos afectan la duración real.

### Reintentos y pausas

`retry_details()` inspecciona `APIError` de Google, incluso si está envuelto como
causa de otra excepción. Solo clasifica como reintentables HTTP **429,
500, 502, 503 y 504**. Aplica espera exponencial con variación aleatoria y respeta
la mayor espera indicada por `RetryInfo.retryDelay` o `Retry-After` (segundos o fecha HTTP).

- Una cuota diaria identificada en los detalles estructurados pausa sin reintentar.
- Tres reintentos permiten como máximo cuatro llamadas por lote, contando la inicial.
- La espera máxima es **por pausa**, no un timeout total del documento. Una espera
  mayor al máximo, una cola demasiado larga o el agotamiento de intentos lanza
  `IndexingPaused`.
- Errores de SSL, autenticación u otros no clasificados como transitorios pausan y
  muestran su causa; no se resuelven cambiando de modelo.
- Un lote incompleto, con valores no finitos o dimensión incompatible no se confirma.

`embed_batch()` usa `model.client.models.embed_content()` con tarea
`RETRIEVAL_DOCUMENT`, timeout de **60 segundos** e `HttpRetryOptions(attempts=1)`
para evitar multiplicar los intentos del SDK y los de la aplicación. La
dimensionalidad sigue la configuración del modelo. No se cambia de proveedor,
no se mezclan modelos de embeddings y no se desactiva la verificación SSL.

La recuperación y publicación transaccional se detallan en
[Persistencia y Bases de Datos](02-Persistencia-y-Bases-de-Datos).

---

## 🎯 Recuperación Semántica con MMR (`pdf-chatbot.py`)

A diferencia de la búsqueda tradicional por similitud pura (que puede traer 4 párrafos casi idénticos de la misma página), el sistema utiliza **Maximal Marginal Relevance (MMR)**:

```python
retriever = vector_store.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 4}
)
```

- **¿Cómo funciona MMR?** Busca el fragmento más similar a la pregunta del usuario y, a continuación, selecciona los siguientes fragmentos equilibrando la **relevancia con la diversidad**.
- **Resultado:** Si la respuesta se encuentra dispersa entre un texto y un diagrama en páginas distintas, el recuperador rescata ambos sin redundancia.

La pregunta requiere un embedding compatible con los vectores del documento.
Esa llamada sigue usando la integración de LangChain y no pasa por el motor
reanudable de indexación. Reconstruir FAISS desde SQLite no consume API, pero
formular una pregunta sí puede consumir embeddings y generación.

**Límite funcional:** recuperar cuatro fragmentos no equivale a leer todas las
páginas para cada pregunta. Las preguntas puntuales son el caso de uso actual;
un resumen exhaustivo de un documento grande necesita un flujo por secciones
y síntesis jerárquica, que no forma parte de esta mejora.

---

## 🛡️ Fallbacks de Generación: Independientes de Embeddings

Uno de los problemas más frecuentes en aplicaciones RAG con niveles gratuitos es el error `429: ResourceExhausted`. 

La cadena de tres modelos permite intentar la generación con otro modelo si el
anterior falla. No evita todos los errores de cuota ni garantiza disponibilidad:
los modelos deben existir y estar habilitados para el proyecto.

```python
primary_llm = ChatGoogleGenerativeAI(
    model="gemini-flash-lite-latest",
    temperature=0.3,
    max_tokens=10000,
    google_api_key=GOOGLE_API_KEY
)
fallback_llm1 = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    temperature=0.3,
    max_tokens=10000,
    google_api_key=GOOGLE_API_KEY
)
fallback_llm2 = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    temperature=0.3,
    max_tokens=10000,
    google_api_key=GOOGLE_API_KEY
)
llm = primary_llm.with_fallbacks([fallback_llm1, fallback_llm2])
```

- Los fallbacks envuelven solo al LLM: no se activan si falla la vectorización
  del documento o de la pregunta, que ocurren antes.
- Si fallan todos los modelos, la generación también falla. No se garantiza una
  conmutación instantánea ni una respuesta sin errores.
- `max_tokens=10000` limita la salida, no aumenta la cuota de embeddings.

---

## 📝 Prompt de Sistema y Construcción de la Cadena LCEL

La plantilla de prompt instruye al modelo con reglas estrictas de fidelidad:

1. **Adaptación de Idioma:** Responder exactamente en el mismo idioma en que preguntó el usuario.
2. **Síntesis Multimodal:** Combinar datos de texto y de imágenes etiquetadas como `[Contenido de imagen #N en Pág. X]`.
3. **Cita de Fuentes:** Mencionar siempre la página o diagrama de origen (ej: *"Según la Página 2..."*).
4. **Anclaje Factual Estricto:** Prohibido alucinar o inventar datos fuera del documento.
5. **Transparencia:** Si el dato no está en el PDF, indicarlo cortésmente.

### Tubería LCEL (LangChain Expression Language):
```python
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

La plantilla solicita fidelidad y citas, pero no sustituye la comprobación de
las fuentes ni garantiza que todo el documento esté representado en el contexto.

---

## 🧭 Navegación entre Capítulos

| [⬅️ Anterior: 3. Extracción y OCR Multimodal](03-Extraccion-y-OCR-Multimodal) | [🏠 Inicio (Home)](Home) | [Siguiente: 5. Interfaz Streamlit y Flujo de Usuario ➡️](05-Interfaz-Streamlit-y-Flujo-de-Usuario) |
| :--- | :--- | :--- |
