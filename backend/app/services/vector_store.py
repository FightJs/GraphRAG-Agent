"""Milvus vector store (Lite local file by default) — SPEC-VECTOR.

Collection schema: doc_chunks
  owner_id, doc_id, chunk_id, text, page_idx, media_refs (JSON), vector
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION = "doc_chunks"


class VectorStore:
    def __init__(self) -> None:
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        from pymilvus import MilvusClient
        uri = settings.MILVUS_URI
        if uri.startswith("./") or (uri.startswith("/") and not uri.startswith("//")):
            Path(uri).parent.mkdir(parents=True, exist_ok=True)
        self._client = MilvusClient(uri=uri)
        return self._client

    def ensure_collection(self, dim: int) -> None:
        from pymilvus import DataType
        client = self._connect()
        if client.has_collection(COLLECTION):
            return
        schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("owner_id", DataType.VARCHAR, max_length=64)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=64)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=64)
        schema.add_field("text", DataType.VARCHAR, max_length=4000)
        schema.add_field("page_idx", DataType.INT64)
        schema.add_field("media_refs", DataType.VARCHAR, max_length=2000)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        index_params = client.prepare_index_params()
        index_params.add_index("vector", index_type="FLAT", metric_type="COSINE")
        client.create_collection(collection_name=COLLECTION, schema=schema, index_params=index_params)
        logger.info("created milvus collection %s dim=%s", COLLECTION, dim)

    def upsert_chunks(
        self,
        *,
        owner_id: str,
        doc_id: str,
        chunks: list[dict],
        vectors: list[list[float]],
    ) -> int:
        if not chunks or not vectors or len(chunks) != len(vectors):
            raise ValueError("chunks/vectors length mismatch")
        dim = len(vectors[0])
        self.ensure_collection(dim)
        client = self._connect()
        rows = []
        for chunk, vec in zip(chunks, vectors):
            chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or uuid.uuid4())
            rows.append({
                "id": f"{doc_id}:{chunk_id}"[:64],
                "owner_id": owner_id,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "text": (chunk.get("text") or "")[:3900],
                "page_idx": int(chunk.get("page_idx") or 0),
                "media_refs": json.dumps(chunk.get("media_refs") or [], ensure_ascii=False)[:1900],
                "vector": vec,
            })
        client.delete(COLLECTION, filter=f'doc_id == "{doc_id}"')
        client.insert(COLLECTION, rows)
        return len(rows)

    def search(
        self,
        *,
        query_vector: list[float] | None = None,
        owner_id: str,
        doc_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        if not query_vector:
            return []
        client = self._connect()
        if not client.has_collection(COLLECTION):
            return []
        filters = [f'owner_id == "{owner_id}"']
        if doc_ids:
            ids = ", ".join(f'"{d}"' for d in doc_ids)
            filters.append(f"doc_id in [{ids}]")
        expr = " and ".join(filters)
        output_fields = ["doc_id", "chunk_id", "text", "page_idx", "media_refs"]
        res = client.search(
            COLLECTION,
            data=[query_vector],
            limit=top_k,
            output_fields=output_fields,
            filter=expr,
            search_params={"metric_type": "COSINE"},
        )
        results: list[dict] = []
        for hit in (res[0] if res else []):
            entity = hit.get("entity") or {}
            results.append({
                "chunk_id": entity.get("chunk_id"),
                "doc_id": entity.get("doc_id"),
                "text": entity.get("text") or "",
                "page_idx": entity.get("page_idx") or 0,
                "media_refs": json.loads(entity.get("media_refs") or "[]"),
                "score": hit.get("distance") or hit.get("score") or 0.0,
                "source": "vector",
            })
        return results

    def delete_doc(self, doc_id: str) -> None:
        client = self._connect()
        if client.has_collection(COLLECTION):
            client.delete(COLLECTION, filter=f'doc_id == "{doc_id}"')


vector_store = VectorStore()
