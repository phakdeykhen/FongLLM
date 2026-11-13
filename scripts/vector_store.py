"""
Document search for FongAI, stored on disk with LanceDB (survives restarts, only new documents get embedded).

  out/vectors/            MINIMIND_VECTOR_DIR
    docs.lance            one row per document: name, chars, added, text (kept so it can be re-indexed later)
    chunks.lance          one row per passage: doc, chunk, text, vector (mxbai-embed-large, 1024 floats, normalized)
"""
import os
import threading
import time

import lancedb
import numpy as np
import pyarrow as pa

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VECTOR_DIR = os.environ.get("MINIMIND_VECTOR_DIR", os.path.join(ROOT, "out", "vectors"))
CHUNK, STEP = 500, 420   # 500-character passages that overlap by 80, so a sentence is never cut off from its context


def chunks_of(text):
    text = " ".join(text.split())
    return [text[i:i + CHUNK] for i in range(0, max(len(text), 1), STEP) if text[i:i + CHUNK].strip()]


def _q(s):
    return s.replace("'", "''")   # LanceDB filters are SQL strings


class VectorStore:
    """encode(list[str]) -> normalized vectors for passages; encode_query(str) -> one normalized vector."""

    def __init__(self, encode, encode_query, path=VECTOR_DIR):
        self.encode, self.encode_query, self.path = encode, encode_query, path
        self._db = None
        self._lock = threading.Lock()

    def _conn(self):
        if self._db is None:
            os.makedirs(self.path, exist_ok=True)
            self._db = lancedb.connect(self.path)
        return self._db

    def _table(self, name):
        db = self._conn()
        return db.open_table(name) if name in db.table_names() else None

    def add(self, name, text):
        """Add or replace one document. Only this document is embedded."""
        parts = chunks_of(text)
        vecs = np.asarray(self.encode(parts), dtype=np.float32) if parts else np.zeros((0, 1), np.float32)
        with self._lock:
            self._delete(name)
            db = self._conn()
            doc = [{"name": name, "chars": len(text), "added": time.time(), "text": text}]
            docs = self._table("docs")
            docs.add(doc) if docs is not None else db.create_table("docs", data=doc)
            if not parts:
                return
            rows = pa.table({
                "doc": [name] * len(parts), "chunk": list(range(len(parts))), "text": parts,
                "vector": pa.FixedSizeListArray.from_arrays(pa.array(vecs.ravel()), vecs.shape[1]),
            })
            table = self._table("chunks")
            table.add(rows) if table is not None else db.create_table("chunks", data=rows)

    def _delete(self, name):
        for t in ("docs", "chunks"):
            table = self._table(t)
            if table is not None:
                table.delete(f"{'name' if t == 'docs' else 'doc'} = '{_q(name)}'")

    def delete(self, name):
        with self._lock:
            self._delete(name)

    def documents(self):
        docs = self._table("docs")
        if docs is None:
            return []
        rows = docs.search().select(["name", "chars", "added"]).limit(100_000).to_list()
        return sorted(({"name": r["name"], "chars": r["chars"]} for r in rows), key=lambda d: d["name"].lower())

    def passages(self):
        table = self._table("chunks")
        return table.count_rows() if table is not None else 0

    def search(self, query, k=3):
        """Top k passages for a question: [{"text", "source", "score"}] (score = cosine similarity, 1 is best)."""
        table = self._table("chunks")
        if table is None or k <= 0 or table.count_rows() == 0:
            return []
        q = np.asarray(self.encode_query(query), dtype=np.float32)
        hits = table.search(q).metric("cosine").select(["doc", "text"]).limit(k).to_list()
        return [{"text": h["text"], "source": h["doc"], "score": round(1 - float(h["_distance"]), 3)} for h in hits]
