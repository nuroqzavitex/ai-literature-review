from types import SimpleNamespace

import pytest

from src.services import vector_store
from src.services.vector_store import QdrantVectorStore


class _FakeModels:
    class Document:
        def __init__(self, text, model):
            self.text = text
            self.model = model

    class VectorParams:
        def __init__(self, size, distance):
            self.size = size
            self.distance = distance

    class Distance:
        COSINE = "cosine"

    class MatchValue:
        def __init__(self, value):
            self.value = value

    class FieldCondition:
        def __init__(self, key, match):
            self.key = key
            self.match = match

    class Filter:
        def __init__(self, must):
            self.must = must


class _FakeQdrantClient:
    def __init__(self):
        self.created = False
        self.recreated = None
        self.upload = None
        self.deleted = None
        self.query = None
        self.query_filter = None
        self.collection_info = SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=384)))
        )

    def collection_exists(self, _collection):
        return self.created

    def get_embedding_size(self, _model):
        return 384

    def create_collection(self, **_kwargs):
        self.created = True

    def recreate_collection(self, **kwargs):
        self.created = True
        self.recreated = kwargs

    def delete(self, **kwargs):
        self.deleted = kwargs

    def get_collection(self, _collection):
        return self.collection_info

    def upload_collection(self, **kwargs):
        self.upload = kwargs

    def query_points(self, **kwargs):
        self.query_filter = kwargs["query_filter"]
        self.query = kwargs["query"]
        payloads = list(reversed(self.upload["payload"])) if self.upload else []
        return SimpleNamespace(
            points=[
                SimpleNamespace(payload=payload, score=0.91 - (index * 0.19)) for index, payload in enumerate(payloads)
            ]
        )


@pytest.mark.asyncio
async def test_qdrant_store_indexes_and_ranks_only_current_job(monkeypatch):
    monkeypatch.setattr(vector_store, "models", _FakeModels)
    client = _FakeQdrantClient()
    store = QdrantVectorStore(client=client)
    papers = [
        {
            "paper_id": "W1",
            "title": "First",
            "authors": ["A"],
            "year": 2024,
            "doi": None,
            "url": "https://openalex.org/W1",
            "abstract": "First abstract about graph learning.",
            "cited_by_count": 1,
            "is_open_access": True,
            "source": "semantic_scholar",
        },
        {
            "paper_id": "W2",
            "title": "Second",
            "authors": ["B"],
            "year": 2025,
            "doi": None,
            "url": "https://openalex.org/W2",
            "abstract": "Second abstract about molecular discovery.",
            "cited_by_count": 2,
            "is_open_access": True,
            "source": "arxiv",
        },
    ]

    ranked = await store.index_and_rank(papers, "molecular graph learning", "job_1", 2)

    assert client.created is True
    assert [payload["job_id"] for payload in client.upload["payload"]] == ["job_1", "job_1"]
    assert client.upload["vectors"][0].text == "Title: First\n\nAbstract: First abstract about graph learning."
    assert client.upload["vectors"][1].text == "Title: Second\n\nAbstract: Second abstract about molecular discovery."
    assert client.query_filter.must[0].key == "job_id"
    assert client.query_filter.must[0].match.value == "job_1"
    assert [paper["paper_id"] for paper in ranked] == ["W2", "W1"]
    assert [paper["rank"] for paper in ranked] == [1, 2]
    assert [paper["cited_by_count"] for paper in ranked] == [2, 1]
    assert [paper["source"] for paper in ranked] == ["arxiv", "semantic_scholar"]


@pytest.mark.asyncio
async def test_qdrant_store_indexes_selected_papers_and_queries_them(monkeypatch):
    monkeypatch.setattr(vector_store, "models", _FakeModels)
    client = _FakeQdrantClient()
    store = QdrantVectorStore(client=client)
    paper = {
        "paper_id": "W10",
        "title": "Selected Paper",
        "authors": ["A"],
        "year": 2024,
        "doi": None,
        "url": "https://openalex.org/W10",
        "abstract": "Selected abstract about retrieval augmented generation.",
        "cited_by_count": 3,
        "is_open_access": True,
        "ingestion": {
            "content_availability": "full_text",
            "ingestion_status": "succeeded",
            "full_text_source": "pdf",
            "full_text_url": "https://example.test/paper.pdf",
            "full_text_chunks": 1,
            "ingestion_warning": None,
        },
    }

    indexed = await store.index_selected_papers([paper], "job_42")
    results = await store.query_selected_papers("retrieval augmented generation", "job_42", 1)

    assert indexed == 1
    assert client.deleted is not None
    assert client.deleted["points_selector"].must[0].key == "job_id"
    assert client.deleted["points_selector"].must[0].match.value == "job_42"
    assert (
        client.upload["vectors"][0].text
        == "Title: Selected Paper\n\nAbstract: Selected abstract about retrieval augmented generation."
    )
    assert client.query.text == "retrieval augmented generation"
    assert results[0]["paper_id"] == "W10"


def test_qdrant_store_allows_a_dedicated_collection(monkeypatch):
    monkeypatch.setattr(vector_store, "models", _FakeModels)

    store = QdrantVectorStore(client=_FakeQdrantClient(), collection="research-gap")

    assert store.collection == "research-gap"


@pytest.mark.asyncio
async def test_qdrant_store_returns_traceable_full_text_claim_evidence(monkeypatch):
    monkeypatch.setattr(vector_store, "models", _FakeModels)
    client = _FakeQdrantClient()
    store = QdrantVectorStore(client=client)
    paper = {
        "paper_id": "W10",
        "title": "Selected Paper",
        "authors": ["A"],
        "year": 2024,
        "doi": None,
        "url": "https://openalex.org/W10",
        "abstract": "Selected abstract.",
        "cited_by_count": 3,
        "is_open_access": True,
        "ingestion": {
            "content_availability": "full_text",
            "ingestion_status": "succeeded",
            "full_text_source": "pdf",
            "full_text_url": "https://example.test/paper.pdf",
            "full_text_chunks": 1,
            "ingestion_warning": None,
        },
    }

    await store.index_selected_papers(
        [paper],
        "job_42",
        documents=[
            {
                "paper": paper,
                "chunks": ["Methods show retrieval improves grounding."],
                "chunk_metadata": [
                    {
                        "section": "Methods",
                        "section_type": "methods",
                        "start_char": 120,
                        "end_char": 162,
                        "content_hash": "a" * 64,
                    }
                ],
                "downloaded": True,
            }
        ],
    )
    evidence = await store.retrieve_claim_evidence("retrieval improves grounding", "job_42", ["W10"])

    assert client.upload["payload"][0]["content_availability"] == "full_text"
    assert client.upload["payload"][0]["full_text_source"] == "pdf"
    assert client.upload["payload"][0]["full_text_chunks"] == 1

    assert evidence == [
        {
            "paper_id": "W10",
            "title": "Selected Paper",
            "source_url": "https://openalex.org/W10",
            "quote": "Methods show retrieval improves grounding.",
            "section": "Methods",
            "section_type": "methods",
            "source_level": "full_text",
            "document_id": "W10:chunk:0",
            "start_char": 120,
            "end_char": 162,
            "content_hash": "a" * 64,
            "retrieval_score": 0.91,
        }
    ]
    assert [condition.key for condition in client.query_filter.must] == ["job_id", "paper_id"]


def test_qdrant_store_recreates_collection_when_embedding_dimension_changes(monkeypatch):
    monkeypatch.setattr(vector_store, "models", _FakeModels)
    client = _FakeQdrantClient()
    client.created = True
    client.collection_info = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=384)))
    )
    store = QdrantVectorStore(client=client)
    store._legacy_document_mode = False

    store._ensure_collection()

    assert client.recreated is not None
    assert client.recreated["vectors_config"].size == 3072
