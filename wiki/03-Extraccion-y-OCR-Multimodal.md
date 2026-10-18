# 🔍 3. Extracción y OCR Multimodal

Esta página documenta la estrategia híbrida de extracción de contenidos diseñada para procesar cualquier archivo PDF, combinando texto digital nativo, OCR local en CPU con **RapidOCR** y un mecanismo de respaldo secundario con visión artificial de Gemini.

---

## 📑 Clasificación de Páginas y Enfoque Híbrido

Los documentos PDF del mundo real presentan tres casuísticas distintas que el sistema detecta y procesa de forma adaptativa:

```text
                                  Página de PDF
                                        │
                       ¿Tiene texto digital seleccionable?
                                        │
                     ┌──────────────────┴──────────────────┐
                     │ < 30 caracteres                     │ >= 30 caracteres
                     ▼                                     ▼
         [Página Escaneada / Imagen]             [Página con Texto Digital]
                     │                                     │
         Renderizar a 150 DPI                              │
                     │                                     │
         RapidOCR en CPU local                   ¿Tiene imágenes incrustadas?
                     │                                     │
                     │                          ┌──────────┴──────────┐
                     │                          │ NO                  │ SÍ (> 120x120 px)
                     │                          ▼                     ▼
                     │                 Texto directo      Recortar gráfico (bbox)
                     │                                                │
                     │                                            RapidOCR
                     ▼                                                ▼
     --- Página X (OCR) ---                           [Contenido de imagen #N...]
```

---

## 🛠️ Motor de OCR Local en Memoria (`pdf-chatbot.py`: Líneas 53-60)

Para evitar recargar la red neuronal ONNX en cada página o petición de usuario, se utiliza el decorador `@st.cache_resource` de Streamlit:

```python
# pdf-chatbot.py: Líneas 53-60
@st.cache_resource
def get_ocr_engine():
    """
    Inicializa el motor RapidOCR una sola vez y lo mantiene en memoria caché
    usando st.cache_resource para optimizar el rendimiento y velocidad en ejecuciones recurrentes.
    """
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()
```

- **Ventaja:** `RapidOCR` se instancia una sola vez cuando la aplicación inicia. Las páginas subsecuentes se procesan inmediatamente a velocidad de CPU.

---

## 📷 Función Resiliente de OCR (`pdf-chatbot.py`: Líneas 62-108)

La función `extract_text_from_image(pil_img, api_key)` implementa una doble capa de extracción:

### Nivel 1: Procesamiento Local con RapidOCR (`pdf-chatbot.py`: Líneas 69-75)
```python
# pdf-chatbot.py: Líneas 69-75
engine = get_ocr_engine()
img_np = np.array(pil_img.convert("RGB"))
result, _ = engine(img_np)
if result:
    # result contiene: [[coordenadas], "texto_reconocido", confianza]
    lines = [line[1] for line in result]
    return "\n".join(lines).strip()
```
- Convierte la imagen PIL a un arreglo tridimensional NumPy (RGB).
- Extrae todas las líneas detectadas por el modelo ONNX y las une con saltos de línea.
- **Costo:** 0 peticiones de API, 100% privado y local.

### Nivel 2: Fallback Secundario con Gemini Vision (`pdf-chatbot.py`: Líneas 77-106)
Si ocurre una excepción inesperada en el motor local y el usuario dispone de clave de API:
1. Se redimensiona la imagen a un máximo de 1600 px para ahorrar ancho de banda.
2. Se codifica en Base64 JPEG.
3. Se invoca a `ChatGoogleGenerativeAI(model="gemini-flash-lite-latest")` con una instrucción especializada para transcribir tablas, textos y números visuales:

```python
# pdf-chatbot.py: Líneas 93-103
msg = HumanMessage(content=[
    {"type": "text", "text": "Transcribe accurately all text, numbers, and tables in this image. Only return the transcribed text."},
    {"type": "image_url", "image_url": f"data:image/jpeg;base64,{img_b64}"}
])
res = vision_llm.invoke([msg])
```

---

## 🔬 Flujo de Inspección Página a Página (`pdf-chatbot.py`: Líneas 241-314)

Al subir un nuevo PDF, se abre con `pdfplumber.open(uploaded_file)` y se recorren sus páginas:

### 1. Detección de Páginas Escaneadas (`pdf-chatbot.py`: Líneas 255-268)
Si `len(page_text.strip()) < 30`, la página carece de texto vectorial:
- Se renderiza la página completa a imagen con resolución optimizada:
  ```python
  page_img = page.to_image(resolution=150).original
  ocr_text = extract_text_from_image(page_img, GOOGLE_API_KEY)
  ```
- Se añade un encabezado semántico: `\n--- Página {page_num} (OCR) ---\n` para que el LLM sepa que proviene de un escaneo.

### 2. Páginas con Texto Digital Seleccionable (`pdf-chatbot.py`: Líneas 269-273)
Si la página contiene texto seleccionable:
- Se extrae directamente con `page.extract_text()`.
- Se añade el prefijo: `\n--- Página {page_num} ---\n`.

### 3. Detección y Recorte de Diagramas e Infografías (`pdf-chatbot.py`: Líneas 274-307)
Si la opción `ocr_embedded_images` está activada en la barra lateral y `len(page.images) > 0`:
- **Filtro de Relevancia:** Se descartan imágenes menores a $120 \times 120\text{ px}$ (evita procesar íconos, viñetas decorativas o pequeños logos).
- **Recorte por Coordenadas Bounding Box:**
  ```python
  bbox = (img_obj["x0"], img_obj["top"], img_obj["x1"], img_obj["bottom"])
  cropped_img = page.crop(bbox).to_image(resolution=150).original
  img_text = extract_text_from_image(cropped_img, GOOGLE_API_KEY)
  ```
- Se etiqueta el contenido: `\n[Contenido de imagen #N en Pág. X]:\n...`.

### 4. Empaquetado con Metadatos (`pdf-chatbot.py`: Líneas 308-314)
Cada página resultante se convierte en un objeto `Document` de LangChain:
```python
page_documents.append(Document(
    page_content=extracted_text, 
    metadata={"page": page_num}
))
```
Esto preserva el número de página de forma inmutable durante la posterior fase de división en fragmentos.
