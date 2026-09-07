"""Qdrant-backed semantic retrieval for papers selected in a review job.

Qdrant stores a rebuildable index of selected papers. It is deliberately not
used as the source of truth: review lifecycle data remains in JobRepository.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

try:
    from qdrant_client import QdrantClient, models
except ImportError:  # pragma: no cover - dependency is required in production.
    QdrantClient = None
    models = None

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:  # pragma: no cover - dependency is required in production.
    GoogleGenerativeAIEmbeddings = None

from src.agents.litreview.domain.models import Paper
from src.config import get_settings
from src.logging_utils import event, failure_code

logger = logging.getLogger(__name__)


class VectorStoreError(RuntimeError):
    """Raised when Qdrant cannot index or retrieve review papers."""


class QdrantVectorStore:
    """Index and semantically search papers in one configured vector space."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        backend: Literal["primary", "fallback"] = "primary",
        collection: str | None = None,
    ) -> None:
        settings = get_settings()
        self.backend = backend
        if backend == "fallback":
            self.collection = settings.qdrant_fallback_collection
            self.embedding_model = settings.qdrant_fallback_embedding_model
            self.embedding_provider = "fastembed"
            # FastEmbed obtains the authoritative vector size from its model.
            self.embedding_dimensions = 0
        else:
            self.collection = settings.qdrant_collection
            self.embedding_model = settings.qdrant_embedding_model
            self.embedding_provider = settings.qdrant_embedding_provider
            self.embedding_dimensions = settings.gemini_embedding_dimensions
        if collection:
            self.collection = collection
        self.timeout = settings.qdrant_timeout
        self._legacy_document_mode = client is not None
        self._gemini = None
        if client is not None:
            self.client = client
            return
        if QdrantClient is None or models is None:
            raise VectorStoreError("qdrant-client[fastembed] is not installed")
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=self.timeout,
        )

        if self.embedding_provider == "gemini":
            if GoogleGenerativeAIEmbeddings is None:
                raise VectorStoreError("langchain-google-genai is not installed")
            google_key = settings.google_api_key or settings.llm_api_key
            if not google_key:
                raise VectorStoreError("Gemini embedding requires GOOGLE_API_KEY or LLM_API_KEY")
            self._gemini = GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embedding_model,
                google_api_key=google_key,
            )

    async def index_and_rank(
        self,
        papers: list[Paper],
        query: str,
        job_id: str,
        limit: int,
    ) -> list[Paper]:
        """Upsert a job's abstracts then return only that job's semantic matches."""

        if not papers:
            return []
        try:
            return await asyncio.to_thread(self._index_and_rank_sync, papers, query, job_id, limit)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant semantic retrieval failed: {exc}") from exc

    async def index_selected_papers(
        self,
        papers: list[Paper],
        job_id: str,
        replace_existing: bool = True,
        documents: list[dict[str, Any]] | None = None,
    ) -> int:
        """Replace a job's chunk vectors with the current paper selection."""

        if not papers:
            return 0
        try:
            await asyncio.to_thread(self._index_papers_sync, papers, job_id, replace_existing, documents)
            return sum(len(item.get("chunks", [])) for item in (documents or [])) or len(papers)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant indexing failed: {exc}") from exc

    async def query_selected_papers(self, query: str, job_id: str, limit: int) -> list[Paper]:
        """Return selected papers ranked semantically against ``query``."""

        try:
            return await asyncio.to_thread(self._query_papers_sync, query, job_id, limit)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant semantic retrieval failed: {exc}") from exc

    async def retrieve_claim_evidence(
        self,
        claim_text: str,
        job_id: str,
        paper_ids: list[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Return traceable passages for grounding a single research claim.

        Retrieval is restricted to the job collection boundary.  ``paper_ids``
        is applied after querying so the method works with both Qdrant client
        versions without depending on version-specific ``MatchAny`` filters.
        """
        try:
            return await asyncio.to_thread(self._retrieve_claim_evidence_sync, claim_text, job_id, paper_ids, limit)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant claim-evidence retrieval failed: {exc}") from exc

    def _index_and_rank_sync(
        self,
        papers: list[Paper],
        query: str,
        job_id: str,
        limit: int,
    ) -> list[Paper]:
        self._index_papers_sync(papers, job_id, True)
        return self._query_papers_sync(query, job_id, limit)

    def _index_papers_sync(
        self, papers: list[Paper], job_id: str, replace_existing: bool, documents: list[dict[str, Any]] | None = None
    ) -> None:
        if models is None:
            raise VectorStoreError("qdrant-client[fastembed] is not installed")

        self._ensure_collection()
        if replace_existing and self.client.collection_exists(self.collection):
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="job_id",
                            match=models.MatchValue(value=job_id),
                        )
                    ]
                ),
                wait=True,
            )
        chunks = documents or [{"paper": paper, "chunks": [self._paper_text(paper)]} for paper in papers]
        rows = [
            (item["paper"], chunk_index, chunk, bool(item.get("downloaded")), metadata)
            for item in chunks
            for chunk_index, chunk in enumerate(item.get("chunks", []))
            for metadata in [
                (
                    (item.get("chunk_metadata") or [{}])[chunk_index]
                    if chunk_index < len(item.get("chunk_metadata") or [])
                    else {}
                )
            ]
            if chunk.strip()
        ]
        vectors = self._embed_documents([chunk for _, _, chunk, _, _ in rows])
        self.client.upload_collection(
            collection_name=self.collection,
            vectors=vectors,
            payload=[
                self._payload(paper, job_id, chunk_index, chunk, downloaded, metadata)
                for paper, chunk_index, chunk, downloaded, metadata in rows
            ],
            ids=[self._point_id(job_id, f"{paper['paper_id']}:{chunk_index}") for paper, chunk_index, _, _, _ in rows],
            wait=True,
        )

    def _query_papers_sync(self, query: str, job_id: str, limit: int) -> list[Paper]:
        if models is None:
            raise VectorStoreError("qdrant-client[fastembed] is not installed")
        if not self.client.collection_exists(self.collection):
            return []

        query_vector = self._embed_query(query)
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="job_id",
                        match=models.MatchValue(value=job_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            timeout=int(self.timeout),
        )
        ranked: list[Paper] = []
        seen: set[str] = set()
        for point in response.points:
            payload = point.payload or {}
            paper = self._paper_from_payload(payload)
            if paper is None or paper["paper_id"] in seen:
                continue
            seen.add(paper["paper_id"])
            ranked.append({**paper, "relevance_score": round(float(point.score), 4), "rank": len(ranked) + 1})
        return ranked

    def _retrieve_claim_evidence_sync(
        self,
        claim_text: str,
        job_id: str,
        paper_ids: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if models is None or not self.client.collection_exists(self.collection):
            return []
        filters = [models.FieldCondition(key="job_id", match=models.MatchValue(value=job_id))]
        if paper_ids and len(paper_ids) == 1:
            filters.append(models.FieldCondition(key="paper_id", match=models.MatchValue(value=paper_ids[0])))
        response = self.client.query_points(
            collection_name=self.collection,
            query=self._embed_query(claim_text),
            query_filter=models.Filter(must=filters),
            # Pull extra candidates before limiting, because a job can contain
            # chunks from papers outside the candidate's evidence set.
            limit=max(limit * 3, limit),
            with_payload=True,
            with_vectors=False,
            timeout=int(self.timeout),
        )
        allowed = set(paper_ids or [])
        results: list[dict[str, Any]] = []
        for point in response.points:
            payload = point.payload or {}
            paper_id = str(payload.get("paper_id", "")).strip()
            chunk = str(payload.get("chunk", "")).strip()
            if not paper_id or not chunk or (allowed and paper_id not in allowed):
                continue
            chunk_index = int(payload.get("chunk_index") or 0)
            results.append(
                {
                    "paper_id": paper_id,
                    "title": str(payload.get("title", "")).strip(),
                    "source_url": str(payload.get("url", "")).strip(),
                    "quote": chunk,
                    "section": str(
                        payload.get("section") or ("full_text" if payload.get("has_full_text") else "abstract")
                    ),
                    "section_type": str(
                        payload.get("section_type") or ("body" if payload.get("has_full_text") else "abstract")
                    ),
                    "source_level": "full_text" if payload.get("has_full_text") else "abstract",
                    "document_id": f"{paper_id}:chunk:{chunk_index}",
                    "start_char": int(payload.get("start_char") or 0),
                    "end_char": int(payload.get("end_char") or len(chunk)),
                    "content_hash": str(payload.get("content_hash") or ""),
                    "retrieval_score": round(float(point.score), 4),
                }
            )
            if len(results) >= limit:
                break
        return results

    async def delete_job_vectors(self, job_id: str) -> None:
        """Delete rebuildable Qdrant documents owned by a review job."""
        try:
            await asyncio.to_thread(self._delete_job_vectors_sync, job_id)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant cleanup failed: {exc}") from exc

    def _delete_job_vectors_sync(self, job_id: str) -> None:
        if models is None or not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.Filter(
                must=[models.FieldCondition(key="job_id", match=models.MatchValue(value=job_id))]
            ),
            wait=True,
        )

    def _ensure_collection(self) -> None:
        desired_size = self._embedding_size()
        vector_params = models.VectorParams(size=desired_size, distance=models.Distance.COSINE)
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vector_params,
            )
            return

        existing_size = self._collection_vector_size()
        if existing_size is None or existing_size == desired_size:
            return

        self.client.recreate_collection(
            collection_name=self.collection,
            vectors_config=vector_params,
        )

    def _embedding_size(self) -> int:
        if self._legacy_document_mode or self.embedding_provider == "fastembed":
            return self.client.get_embedding_size(self.embedding_model)
        return self.embedding_dimensions

    def _collection_vector_size(self) -> int | None:
        try:
            info = self.client.get_collection(self.collection)
        except Exception as exc:
            event(
                logger,
                "vector_store.collection_inspection_failed",
                level=logging.WARNING,
                collection=self.collection,
                failure_code=failure_code(exc),
                error_type=type(exc).__name__,
            )
            return None
        return self._extract_vector_size(info)

    @classmethod
    def _extract_vector_size(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, dict):
            if "size" in value:
                try:
                    return int(value["size"])
                except (TypeError, ValueError):
                    return None
            for key in ("vectors", "vectors_config", "vector_config", "params", "config"):
                if key in value:
                    size = cls._extract_vector_size(value[key])
                    if size is not None:
                        return size
            if len(value) == 1:
                return cls._extract_vector_size(next(iter(value.values())))
            return None
        for attr in ("size", "vectors", "vectors_config", "vector_config", "params", "config"):
            if hasattr(value, attr):
                size = cls._extract_vector_size(getattr(value, attr))
                if size is not None:
                    return size
        if hasattr(value, "__dict__"):
            return cls._extract_vector_size(vars(value))
        return None

    def _embed_documents(self, texts: list[str]) -> list[Any]:
        if self._legacy_document_mode or self.embedding_provider == "fastembed":
            return [models.Document(text=text, model=self.embedding_model) for text in texts]
        if self._gemini is None:
            raise VectorStoreError("Gemini embedding client is not configured")
        return self._gemini.embed_documents(texts)

    def _embed_query(self, text: str) -> Any:
        if self._legacy_document_mode or self.embedding_provider == "fastembed":
            return models.Document(text=text, model=self.embedding_model)
        if self._gemini is None:
            raise VectorStoreError("Gemini embedding client is not configured")
        return self._gemini.embed_query(text)

    @staticmethod
    def _point_id(job_id: str, paper_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"litreview:{job_id}:{paper_id}"))

    @staticmethod
    def _paper_text(paper: Paper) -> str:
        title = " ".join(paper["title"].split())
        abstract = " ".join(paper["abstract"].split())
        return f"Title: {title}\n\nAbstract: {abstract}".strip()

    @staticmethod
    def _payload(
        paper: Paper,
        job_id: str,
        chunk_index: int = 0,
        chunk: str | None = None,
        has_full_text: bool = False,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = chunk_metadata or {}
        ingestion = paper.get("ingestion") or {}
        return {
            "job_id": job_id,
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "abstract": paper["abstract"],
            "indexed_text": QdrantVectorStore._paper_text(paper),
            "year": paper["year"],
            "doi": paper["doi"],
            "url": paper["url"],
            "authors": paper["authors"],
            "cited_by_count": paper.get("cited_by_count", 0),
            "source": paper.get("source"),
            "is_open_access": paper["is_open_access"],
            "pdf_url": paper.get("pdf_url"),
            "content_availability": ingestion.get("content_availability"),
            "ingestion_status": ingestion.get("ingestion_status"),
            "full_text_source": ingestion.get("full_text_source"),
            "full_text_url": ingestion.get("full_text_url"),
            "full_text_chunks": ingestion.get("full_text_chunks", 0),
            "ingestion_warning": ingestion.get("ingestion_warning"),
            "chunk_index": chunk_index,
            "chunk": chunk or QdrantVectorStore._paper_text(paper),
            "has_full_text": has_full_text,
            "section": metadata.get("section"),
            "section_type": metadata.get("section_type"),
            "start_char": metadata.get("start_char", 0),
            "end_char": metadata.get("end_char", len(chunk or "")),
            "content_hash": metadata.get("content_hash"),
        }

    @staticmethod
    def _paper_from_payload(payload: dict[str, Any]) -> Paper | None:
        paper_id = str(payload.get("paper_id", "")).strip()
        title = str(payload.get("title", "")).strip()
        abstract = str(payload.get("abstract", "")).strip()
        url = str(payload.get("url", "")).strip()
        authors = payload.get("authors", [])
        if not paper_id or not title or not abstract or not url or not isinstance(authors, list):
            return None
        paper: Paper = {
            "paper_id": paper_id,
            "title": title,
            "authors": [str(author).strip() for author in authors if str(author).strip()],
            "year": payload.get("year"),
            "doi": payload.get("doi"),
            "url": url,
            "abstract": abstract,
            "cited_by_count": int(payload.get("cited_by_count") or 0),
            "is_open_access": bool(payload.get("is_open_access", True)),
            "source": payload.get("source")
            or (
                "semantic_scholar"
                if paper_id.startswith("s2:")
                else "arxiv"
                if paper_id.startswith("arxiv:")
                else "openalex"
            ),
            "pdf_url": payload.get("pdf_url"),
        }
        if payload.get("content_availability"):
            paper["ingestion"] = {
                "content_availability": payload["content_availability"],
                "ingestion_status": payload.get("ingestion_status") or "unavailable",
                "full_text_source": payload.get("full_text_source"),
                "full_text_url": payload.get("full_text_url"),
                "full_text_chunks": int(payload.get("full_text_chunks") or 0),
                "ingestion_warning": payload.get("ingestion_warning"),
            }
        return paper
