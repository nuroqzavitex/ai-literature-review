import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.services.paper_ingestion import (
    CHUNK_SIZE,
    _chunk_records,
    _download_open_pmc_fulltext,
    _download_public_html,
    _resolve_open_pmc_article_url,
    extract_uploaded_document_text,
    ingest_papers,
)


def test_chunking_preserves_section_boundaries_and_provenance() -> None:
    methods = "Methods paragraph. " * 250
    text = f"# Paper title\n\n## Methods\n\n{methods}\n\n## References\n\n[1] A reference"

    chunks = _chunk_records(text)

    assert chunks
    assert all(chunk["section"] == "Methods" for chunk in chunks)
    assert all(chunk["section_type"] == "methods" for chunk in chunks)
    assert all(len(chunk["text"]) <= CHUNK_SIZE for chunk in chunks)
    assert all(len(chunk["content_hash"]) == 64 for chunk in chunks)
    assert all(chunk["start_char"] < chunk["end_char"] for chunk in chunks)


def test_uploaded_pdf_uses_pypdf_for_text_extraction(tmp_path: Path, monkeypatch) -> None:
    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [
                SimpleNamespace(extract_text=lambda: "Machine learning"),
                SimpleNamespace(extract_text=lambda: "improves triage fairness."),
            ]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))
    document = tmp_path / "triage.pdf"
    document.write_bytes(b"not read by the fake parser")

    assert extract_uploaded_document_text(document) == "Machine learning improves triage fairness."


def test_uploaded_pdf_without_text_returns_a_validation_error(tmp_path: Path, monkeypatch) -> None:
    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [SimpleNamespace(extract_text=lambda: "")]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))
    document = tmp_path / "scan.pdf"
    document.write_bytes(b"not read by the fake parser")

    with pytest.raises(ValueError, match="did not contain extractable text"):
        extract_uploaded_document_text(document)


def test_chunk_size_limits_retrieved_passages_to_1400_characters() -> None:
    assert CHUNK_SIZE == 1_400


def test_chunking_discards_malformed_pdf_tables() -> None:
    table = "TABLEI " + " | ".join(f"cell {index}" for index in range(12))
    text = f"# Paper title\n\n## Results\n\nUseful prose evidence.\n\n{table}"

    chunks = _chunk_records(text)

    assert len(chunks) == 1
    assert chunks[0]["text"] == "Useful prose evidence."


@pytest.mark.asyncio
async def test_public_html_fallback_extracts_article_body() -> None:
    article_text = "Clinical evidence. " * 60
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f"<html><nav>Navigation</nav><article>{article_text}</article></html>",
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        result = await _download_public_html(client, ["https://example.test/article"])

    assert result is not None
    text, url = result
    assert "Navigation" not in text
    assert "Clinical evidence." in text
    assert url == "https://example.test/article"


@pytest.mark.asyncio
async def test_pmc_resolver_returns_an_open_exact_doi_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.ebi.ac.uk"
        assert request.url.params["query"] == "DOI:10.1111/acem.15066"
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "doi": "10.1111/acem.15066",
                            "isOpenAccess": "Y",
                            "pmcid": "PMC11921089",
                        }
                    ]
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _resolve_open_pmc_article_url(client, "10.1111/acem.15066")

    assert result == "https://pmc.ncbi.nlm.nih.gov/articles/PMC11921089/"


@pytest.mark.asyncio
async def test_pmc_resolver_rejects_a_non_matching_doi() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"resultList": {"result": [{"doi": "10.9999/other", "isOpenAccess": "Y", "pmcid": "PMC1"}]}},
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        result = await _resolve_open_pmc_article_url(client, "10.1111/acem.15066")

    assert result is None


@pytest.mark.asyncio
async def test_pmc_fulltext_downloads_xml_without_tables_or_references() -> None:
    xml = (
        "<article><body><sec><title>Results</title>"
        + "<p>Useful evidence. </p>" * 80
        + "<table-wrap><p>Table content</p></table-wrap><ref-list><ref>Reference</ref></ref-list>"
        + "<p>More useful evidence.</p></sec></body></article>"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            text=xml,
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        result = await _download_open_pmc_fulltext(client, "https://pmc.ncbi.nlm.nih.gov/articles/PMC11921089/")

    assert result is not None
    text, url = result
    assert "Useful evidence." in text
    assert "Table content" not in text
    assert "Reference" not in text
    assert url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC11921089/"


@pytest.mark.asyncio
async def test_ingestion_uses_configured_writable_storage_for_abstract_fallback(tmp_path: Path) -> None:
    paper = {
        "paper_id": "arxiv:1234.5678",
        "title": "A paper",
        "authors": ["Ada Lovelace"],
        "year": 2026,
        "doi": None,
        "url": "",
        "abstract": "An abstract used when no open PDF is available.",
        "cited_by_count": 0,
        "is_open_access": False,
    }

    documents, warnings = await ingest_papers([paper], "job-123", root=tmp_path / "papers")

    markdown_path = tmp_path / "papers" / "job-123" / "arxiv_1234.5678.md"
    assert markdown_path.is_file()
    assert "An abstract used when no open PDF is available." in markdown_path.read_text(encoding="utf-8")
    assert documents[0]["markdown_path"] == str(markdown_path)
    assert documents[0]["chunks"] == [paper["abstract"]]
    assert documents[0]["chunk_metadata"][0]["section_type"] == "abstract"
    assert documents[0]["ingestion"] == {
        "content_availability": "abstract_only",
        "ingestion_status": "unavailable",
        "full_text_source": None,
        "full_text_url": None,
        "full_text_chunks": 0,
        "ingestion_warning": "PDF_UNAVAILABLE:arxiv:1234.5678",
    }
    assert warnings == ["PDF_UNAVAILABLE:arxiv:1234.5678"]
