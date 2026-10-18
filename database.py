"""
Módulo de Persistencia SQLite y Almacén Vectorial Local
======================================================
Este módulo gestiona dos bases de datos SQLite independientes:
1. `data/documents.db`: Metadatos de documentos, fragmentos de texto (chunks) y
   almacén vectorial de embeddings persistidos como BLOBs (np.float32).
2. `data/chat_history.db`: Historial persistente de conversaciones (preguntas y respuestas)
   vinculadas a cada documento PDF.

Incluye verificación y creación automática de las bases de datos "al vuelo" si no existen.
"""

import os
import sqlite3
import hashlib
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings

# Directorio y rutas de las bases de datos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOCUMENTS_DB_PATH = os.path.join(DATA_DIR, "documents.db")
CHAT_HISTORY_DB_PATH = os.path.join(DATA_DIR, "chat_history.db")


def init_databases() -> Dict[str, bool]:
    """
    Verifica si las bases de datos SQLite y el directorio `data/` existen.
    Si no existen, las crea automáticamente 'al vuelo' junto con sus tablas e índices.
    
    Retorna un diccionario indicando si cada base de datos fue creada recientemente o ya existía.
    """
    # 1. Asegurar la existencia del directorio data/
    os.makedirs(DATA_DIR, exist_ok=True)
    
    docs_created = not os.path.exists(DOCUMENTS_DB_PATH)
    chat_created = not os.path.exists(CHAT_HISTORY_DB_PATH)
    
    # 2. Inicializar BD de Documentos y Embeddings Vectoriales
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        cursor = conn.cursor()
        
        # Tabla de metadatos de documentos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_hash TEXT UNIQUE NOT NULL,
                file_size INTEGER DEFAULT 0,
                total_pages INTEGER DEFAULT 0,
                total_chunks INTEGER DEFAULT 0,
                has_ocr INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Tabla de fragmentos (chunks) y embeddings vectoriales
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page_number INTEGER DEFAULT 1,
                content TEXT NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
            );
        """)
        
        # Índices para optimizar búsquedas por hash y recuperación por documento
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON document_chunks(document_id);")
        conn.commit()

    # 3. Inicializar BD de Historial de Chat
    with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        cursor = conn.cursor()
        
        # Tabla de mensajes de conversación
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_doc_id ON chat_messages(document_id);")
        conn.commit()
        
    return {
        "documents_created": docs_created,
        "chat_created": chat_created
    }


def calculate_file_hash(file_bytes: bytes) -> str:
    """Calcula el hash SHA-256 de los bytes de un archivo para detección de duplicados."""
    return hashlib.sha256(file_bytes).hexdigest()


# ==============================================================================
# OPERACIONES DE DOCUMENTOS Y BASE VECTORIAL (documents.db)
# ==============================================================================

def get_all_documents() -> List[Dict[str, Any]]:
    """Obtiene todos los documentos registrados, ordenados del más reciente al más antiguo."""
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, filename, file_hash, file_size, total_pages, total_chunks, has_ocr, created_at
            FROM documents
            ORDER BY created_at DESC;
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_document_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    """Busca un documento existente por su hash SHA-256."""
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, filename, file_hash, file_size, total_pages, total_chunks, has_ocr, created_at
            FROM documents
            WHERE file_hash = ?;
        """, (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_document_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    """Busca un documento existente por su ID único."""
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, filename, file_hash, file_size, total_pages, total_chunks, has_ocr, created_at
            FROM documents
            WHERE id = ?;
        """, (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def save_document(
    doc_id: str,
    filename: str,
    file_hash: str,
    file_size: int,
    total_pages: int,
    total_chunks: int,
    has_ocr: int,
    chunks: List[Dict[str, Any]]
) -> None:
    """
    Guarda los metadatos del documento y todos sus fragmentos con sus vectores
    de embedding serializados como BLOBs binarios en SQLite.
    
    Cada elemento de `chunks` debe ser un diccionario con:
    - 'chunk_index': int
    - 'page_number': int
    - 'content': str
    - 'embedding': list de float (vector numérico)
    """
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        
        # Insertar metadatos del documento
        cursor.execute("""
            INSERT OR REPLACE INTO documents 
            (id, filename, file_hash, file_size, total_pages, total_chunks, has_ocr, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
        """, (doc_id, filename, file_hash, file_size, total_pages, total_chunks, has_ocr))
        
        # Preparar inserción por lotes de los chunks con embeddings serializados en np.float32
        chunks_records = []
        for chk in chunks:
            # Serialización a bytes float32 para máxima compacidad y velocidad
            emb_blob = np.array(chk["embedding"], dtype=np.float32).tobytes()
            chunks_records.append((
                doc_id,
                chk["chunk_index"],
                chk.get("page_number", 1),
                chk["content"],
                emb_blob
            ))
            
        cursor.executemany("""
            INSERT INTO document_chunks 
            (document_id, chunk_index, page_number, content, embedding)
            VALUES (?, ?, ?, ?, ?);
        """, chunks_records)
        
        conn.commit()


def load_vectorstore_from_db(doc_id: str, embeddings_model: Embeddings) -> Optional[FAISS]:
    """
    Reconstruye el índice vectorial FAISS en memoria a partir de los embeddings y
    fragmentos almacenados en SQLite.
    
    ¡Esta operación NO realiza llamadas a la API de embeddings de Gemini!,
    permitiendo cargar documentos previos en milisegundos y con costo 0.
    """
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT content, embedding, page_number
            FROM document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index ASC;
        """, (doc_id,))
        rows = cursor.fetchall()
        
        if not rows:
            return None
            
        text_embeddings = []
        metadatas = []
        for content, emb_blob, page_num in rows:
            # Deserializar el BLOB binario a lista de floats
            vec = np.frombuffer(emb_blob, dtype=np.float32).tolist()
            text_embeddings.append((content, vec))
            metadatas.append({"page": page_num})
            
        # Reconstruir el índice FAISS directamente desde los vectores precalculados
        vectorstore = FAISS.from_embeddings(
            text_embeddings=text_embeddings,
            embedding=embeddings_model,
            metadatas=metadatas
        )
        return vectorstore


def delete_document(doc_id: str) -> None:
    """
    Elimina por completo un documento de ambas bases de datos:
    1. Elimina todos los fragmentos y vectores de embedding en `data/documents.db` (tabla `document_chunks`).
    2. Elimina los metadatos del archivo en `data/documents.db` (tabla `documents`).
    3. Elimina todo el historial de conversación asociado en `data/chat_history.db` (tabla `chat_messages`).
    """
    # 1. Eliminar fragmentos vectoriales y metadatos en documents.db
    with sqlite3.connect(DOCUMENTS_DB_PATH, timeout=15) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        # Borrado explícito de fragmentos y vectores (además del ON DELETE CASCADE)
        cursor.execute("DELETE FROM document_chunks WHERE document_id = ?;", (doc_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?;", (doc_id,))
        conn.commit()
        
    # 2. Eliminar historial de conversación asociado en chat_history.db
    with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE document_id = ?;", (doc_id,))
        conn.commit()


# ==============================================================================
# OPERACIONES DE HISTORIAL DE CONVERSACIÓN (chat_history.db)
# ==============================================================================

def save_chat_message(document_id: str, role: str, content: str) -> None:
    """Guarda un mensaje (usuario o asistente) asociado a un documento específico."""
    with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_messages (document_id, role, content, timestamp)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP);
        """, (document_id, role, content))
        conn.commit()


def get_chat_history(document_id: str) -> List[Dict[str, Any]]:
    """Recupera el historial de conversación completo de un documento, ordenado cronológicamente."""
    with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, timestamp
            FROM chat_messages
            WHERE document_id = ?
            ORDER BY id ASC;
        """, (document_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def clear_chat_history(document_id: str) -> None:
    """Borra todos los mensajes de conversación de un documento específico."""
    with sqlite3.connect(CHAT_HISTORY_DB_PATH, timeout=15) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE document_id = ?;", (document_id,))
        conn.commit()
