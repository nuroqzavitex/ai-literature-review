"""Download open papers and turn them into bounded embedding chunks."""

from __future__ import annotations

import asyncio
import hashlib
import re
import warnings
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from src.agents.litreview.domain.models import Paper

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_HTML_BYTES = 5 * 1024 * 1024
MIN_HTML_ARTICLE_TEXT_CHARS = 600
MAX_UPLOADED_DOCUMENT_TEXT_CHARS = 50_000
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
# Keep retrieved PDF passages focused enough for grounded answer composition.
CHUNK_SIZE = 1_400
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_PARAGRAPH = re.compile(r"\S.*?(?=\n\s*\n|\Z)", re.DOTALL)


def _is_table_layout(text: str) -> bool:
    """Detect malformed table text emitted by PDF-to-Markdown conversion."""
    upper = text.upper()
    return upper.startswith("TABLE") or text.count("|") >= 10 or "CONFUSIONMATRIX" in upper


def _section_type(heading: str) -> str:
    """Classify common academic headings without relying on one publisher's format."""
    value = heading.lower()
    if "abstract" in value:
        return "abstract"
    if any(term in value for term in ("reference", "bibliograph", "tài liệu tham khảo")):
        return "references"
    if any(term in value for term in ("method", "methodology", "materials", "phương pháp")):
        return "methods"
    if any(term in value for term in ("result", "finding", "kết quả")):
        return "results"
    if any(term in value for term in ("discussion", "conclusion", "thảo luận", "kết luận")):
        return "discussion"
    if any(term in value for term in ("limitation", "future work", "hạn chế")):
        return "limitations"
    return "body"


def _split_long_paragraph(text: str) -> list[str]:
    """Split only oversized paragraphs, preferring sentence boundaries."""
    chunks: list[str] = []
    remaining = text
    while len(remaining) > CHUNK_SIZE:
        boundary = max(
            remaining.rfind(". ", 0, CHUNK_SIZE),
            remaining.rfind("? ", 0, CHUNK_SIZE),
            remaining.rfind("! ", 0, CHUNK_SIZE),
            remaining.rfind(" ", 0, CHUNK_SIZE),
        )
        boundary = boundary if boundary > CHUNK_SIZE // 2 else CHUNK_SIZE
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _chunk_records(text: str) -> list[dict[str, Any]]:
    """Build deterministic paragraph chunks that never cross a Markdown section."""
    records: list[dict[str, Any]] = []
    headings = list(_HEADING.finditer(text))
    sections = headings or [None]
    for index, heading_match in enumerate(sections):
        heading = heading_match.group(1).strip() if heading_match else "Document"
        section_type = _section_type(heading)
        if section_type == "references":
            continue
        start = heading_match.end() if heading_match else 0
        end = headings[index + 1].start() if heading_match and index + 1 < len(headings) else len(text)
        body = text[start:end]
        units: list[tuple[str, int, int]] = []
        for paragraph in _PARAGRAPH.finditer(body):
            normalized = re.sub(r"\s+", " ", paragraph.group(0)).strip()
            if not normalized or _is_table_layout(normalized):
                continue
            paragraph_start = start + paragraph.start()
            for piece in _split_long_paragraph(normalized):
                units.append((piece, paragraph_start, paragraph_start + len(paragraph.group(0))))

        current: list[tuple[str, int, int]] = []
        for unit in units:
            candidate_length = sum(len(item[0]) for item in current) + len(unit[0]) + max(0, len(current) - 1)
            if current and candidate_length > CHUNK_SIZE:
                chunk = "\n\n".join(item[0] for item in current)
                records.append(
                    {
                        "text": chunk,
                        "section": heading,
                        "section_type": section_type,
                        "start_char": current[0][1],
                        "end_char": current[-1][2],
                        "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    }
                )
                # One paragraph of overlap preserves local context without crossing the section boundary.
                current = [current[-1]] if len(current[-1][0]) + len(unit[0]) + 2 <= CHUNK_SIZE else []
            current.append(unit)
        if current:
            chunk = "\n\n".join(item[0] for item in current)
            records.append(
                {
                    "text": chunk,
                    "section": heading,
                    "section_type": section_type,
                    "start_char": current[0][1],
                    "end_char": current[-1][2],
                    "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                }
            )
    return records


def _chunks(text: str) -> list[str]:
    """Compatibility helper for callers that only need the chunk text."""
    return [record["text"] for record in _chunk_records(text)]


def _abstract_chunk(abstract: str) -> dict[str, Any]:
    """Build the one fallback record that is safe to label as abstract-only."""
    text = re.sub(r"\s+", " ", abstract).strip()
    return {
        "text": text,
        "section": "Abstract",
        "section_type": "abstract",
        "start_char": 0,
        "end_char": len(text),
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _ingestion_metadata(
    *,
    content_availability: str,
    ingestion_status: str,
    full_text_source: str | None = None,
    full_text_url: str | None = None,
    full_text_chunks: int = 0,
    ingestion_warning: str | None = None,
) -> dict[str, Any]:
    """Return the durable, job-specific content outcome for one paper."""
    return {
        "content_availability": content_availability,
        "ingestion_status": ingestion_status,
        "full_text_source": full_text_source,
        "full_text_url": full_text_url,
        "full_text_chunks": full_text_chunks,
        "ingestion_warning": ingestion_warning,
    }


def _to_markdown(paper: Paper, body: str) -> str:
    """Add stable paper metadata around Markdown produced by MarkItDown."""
    authors = ", ".join(paper.get("authors", []))
    return (
        f"# {paper['title']}\n\n"
        f"- **Paper ID:** `{paper['paper_id']}`\n"
        f"- **Authors:** {authors}\n"
        f"- **Year:** {paper.get('year') or 'Unknown'}\n"
        f"- **Source:** {paper.get('source', 'academic API')}\n"
        f"- **URL:** {paper['url']}\n\n"
        "## Extracted paper text\n\n"
        f"{body}\n"
    )


def _safe_name(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", paper_id)[:120]


def _extract_public_html_article(html: str) -> str:
    """Extract readable article text from a public HTML page, excluding chrome."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("script, style, noscript, nav, header, footer, aside, form"):
        element.decompose()
    article = soup.select_one("article, main, [role='main']") or soup.body
    return article.get_text("\n\n", strip=True) if article else ""


async def _resolve_open_pmc_article_url(client: httpx.AsyncClient, doi: str | None) -> str | None:
    """Find the public PMC page for an exact, open-access DOI match."""
    normalized_doi = (doi or "").strip().lower()
    if not normalized_doi:
        return None
    try:
        response = await client.get(
            EUROPE_PMC_SEARCH_URL,
            params={
                "query": f"DOI:{normalized_doi}",
                "format": "json",
                "pageSize": 1,
                "resultType": "core",
            },
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    results = response.json().get("resultList", {}).get("result", [])
    if not results:
        return None
    result = results[0]
    if str(result.get("doi") or "").strip().lower() != normalized_doi:
        return None
    if str(result.get("isOpenAccess") or "").upper() != "Y":
        return None
    pmcid = str(result.get("pmcid") or "").strip()
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid.startswith("PMC") else None


async def _download_open_pmc_fulltext(client: httpx.AsyncClient, pmc_article_url: str | None) -> tuple[str, str] | None:
    """Download public PMC XML through Europe PMC's full-text API."""
    if not pmc_article_url:
        return None
    pmcid = pmc_article_url.rstrip("/").rsplit("/", maxsplit=1)[-1]
    if not pmcid.startswith("PMC"):
        return None
    try:
        response = await client.get(EUROPE_PMC_FULLTEXT_URL.format(pmcid=pmcid))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    if len(response.content) > MAX_HTML_BYTES or "xml" not in response.headers.get("content-type", "").lower():
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(response.content, "html.parser")
    body = soup.find("body")
    if not body:
        return None
    for element in body.find_all(["table-wrap", "ref-list", "fig", "supplementary-material"]):
        element.decompose()
    text = body.get_text("\n\n", strip=True)
    return (text, pmc_article_url) if len(text) >= MIN_HTML_ARTICLE_TEXT_CHARS else None


async def _download_public_html(client: httpx.AsyncClient, urls: list[str | None]) -> tuple[str, str] | None:
    """Return article text only from a publicly accessible HTML response."""
    for url in dict.fromkeys(url for url in urls if url):
        try:
            response = await client.get(url, headers={"Accept": "text/html,application/xhtml+xml"})
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        if len(response.content) > MAX_HTML_BYTES or "html" not in response.headers.get("content-type", "").lower():
            continue
        text = _extract_public_html_article(response.text)
        if len(text) >= MIN_HTML_ARTICLE_TEXT_CHARS:
            return text, str(response.url)
    return None


def _convert_pdf_to_markdown(path: Path, paper: Paper) -> str:
    """Convert a PDF with Microsoft's MarkItDown before RAG chunking."""
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MarkItDown is not installed. Rebuild the backend image after installing the markitdown[pdf] dependency."
        ) from exc

    result = MarkItDown().convert(str(path))
    body = str(result.text_content or "").strip()
    if not body:
        raise ValueError("MarkItDown returned no Markdown text")
    return _to_markdown(paper, body)


def extract_uploaded_document_text(path: Path) -> str:
    """Extract bounded plain text from a user-provided PDF or DOCX.

    Uploads are used only to formulate an academic search seed.  Keeping this
    helper separate from paper ingestion makes that boundary explicit: the
    uploaded document never becomes an evidence source or vector-store record.
    """

    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in reader.pages)).strip()
        except Exception as exc:
            raise ValueError("The PDF could not be read.") from exc
        if not text:
            raise ValueError("The PDF did not contain extractable text.")
        return text[:MAX_UPLOADED_DOCUMENT_TEXT_CHARS]

    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Document parsing is unavailable. Rebuild the backend image after installing "
            "the markitdown[pdf] dependency."
        ) from exc

    result = MarkItDown().convert(str(path))
    text = re.sub(r"\s+", " ", str(result.text_content or "")).strip()
    if not text:
        raise ValueError("The document did not contain extractable text")
    return text[:MAX_UPLOADED_DOCUMENT_TEXT_CHARS]


async def ingest_papers(
    papers: list[Paper], job_id: str, root: str | Path = "/tmp/litreview-papers"
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ingest OA PDFs, then public HTML full text, before falling back to abstracts."""
    directory = Path(root) / job_id
    directory.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": "LitReviewAgent/0.1"}
    ) as client:

        async def one(paper: Paper) -> dict[str, Any]:
            fallback = _to_markdown(paper, f"## Abstract\n\n{paper['abstract']}")
            pdf_url = paper.get("pdf_url")
            path = directory / f"{_safe_name(paper['paper_id'])}.pdf"

            async def html_or_abstract(pdf_error: Exception | None = None) -> dict[str, Any]:
                pmc_url = await _resolve_open_pmc_article_url(client, paper.get("doi"))
                pmc_result = await _download_open_pmc_fulltext(client, pmc_url)
                html_result = pmc_result or await _download_public_html(client, [pdf_url, paper.get("url")])
                if html_result:
                    article_text, article_url = html_result
                    markdown = _to_markdown(paper, f"## Extracted public article text\n\n{article_text}")
                    markdown_path = path.with_suffix(".md")
                    markdown_path.write_text(markdown, encoding="utf-8")
                    records = _chunk_records(markdown)
                    if records:
                        source = "pmc_xml" if pmc_result else "html"
                        warnings.append(f"HTML_FULLTEXT:{paper['paper_id']}")
                        return {
                            "paper": paper,
                            "chunks": [record["text"] for record in records],
                            "chunk_metadata": records,
                            "downloaded": True,
                            "full_text_source": source,
                            "article_url": article_url,
                            "ingestion": _ingestion_metadata(
                                content_availability="full_text",
                                ingestion_status="succeeded",
                                full_text_source=source,
                                full_text_url=article_url,
                                full_text_chunks=len(records),
                            ),
                            "markdown_path": str(markdown_path),
                        }

                markdown_path = path.with_suffix(".md")
                markdown_path.write_text(fallback, encoding="utf-8")
                records = [_abstract_chunk(paper["abstract"])]
                warning = (
                    f"PDF_FALLBACK:{paper['paper_id']}:{pdf_error}"
                    if pdf_error
                    else f"PDF_UNAVAILABLE:{paper['paper_id']}"
                )
                warnings.append(warning)
                return {
                    "paper": paper,
                    "chunks": [record["text"] for record in records],
                    "chunk_metadata": records,
                    "downloaded": False,
                    "ingestion": _ingestion_metadata(
                        content_availability="abstract_only",
                        ingestion_status="failed" if pdf_error else "unavailable",
                        ingestion_warning=warning,
                    ),
                    "markdown_path": str(markdown_path),
                }

            if not pdf_url:
                return await html_or_abstract()
            try:
                if not path.exists():
                    response = await client.get(pdf_url)
                    response.raise_for_status()
                    if (
                        len(response.content) > MAX_PDF_BYTES
                        or "pdf" not in response.headers.get("content-type", "").lower()
                    ):
                        raise ValueError("response is not a supported PDF")
                    path.write_bytes(response.content)
                markdown = await asyncio.to_thread(_convert_pdf_to_markdown, path, paper)
                markdown_path = path.with_suffix(".md")
                markdown_path.write_text(markdown, encoding="utf-8")
                records = _chunk_records(markdown)
                if not records:
                    raise ValueError("PDF text extraction returned no text")
                return {
                    "paper": paper,
                    "chunks": [record["text"] for record in records],
                    "chunk_metadata": records,
                    "downloaded": True,
                    "full_text_source": "pdf",
                    "pdf_path": str(path),
                    "ingestion": _ingestion_metadata(
                        content_availability="full_text",
                        ingestion_status="succeeded",
                        full_text_source="pdf",
                        full_text_url=str(pdf_url),
                        full_text_chunks=len(records),
                    ),
                    "markdown_path": str(markdown_path),
                }
            except Exception as exc:
                return await html_or_abstract(exc)

        documents = await asyncio.gather(*(one(paper) for paper in papers))
    return list(documents), warnings
