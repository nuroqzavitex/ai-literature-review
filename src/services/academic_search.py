from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.litreview.domain.models import Paper
from src.config import get_settings
from src.logging_utils import event, failure_code
from src.services.llm import get_llm


class OpenAlexError(Exception):
    """Lỗi chung từ OpenAlex adapter."""

    pass


class OpenAlexRateLimitError(OpenAlexError):
    """Lỗi HTTP 429 Too Many Requests."""

    pass


class OpenAlexServerError(OpenAlexError):
    """Lỗi HTTP 5xx Server Error."""

    pass


class OpenAlexClientError(OpenAlexError):
    """Lỗi HTTP 4xx Client Error (ngoại trừ 429)."""

    pass


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]+", re.IGNORECASE)
_RANKING_STOPWORDS = frozenset(
    {
        "academic",
        "analysis",
        "approach",
        "biology",
        "empirical",
        "evolution",
        "evolutionary",
        "explanation",
        "latest",
        "overview",
        "perspective",
        "research",
        "review",
        "scientific",
        "study",
        "survey",
        "systematic",
    }
)
_OPENALEX_WORK_ID_RE = re.compile(r"^W\d+$")
_OPENALEX_WILDCARD_RE = re.compile(r"[?*]")
_DOI_IN_TEXT_RE = re.compile(r"(?<!\w)(10\.\d{4,9}/[-._;()/:a-z0-9]+)", re.IGNORECASE)

logger = logging.getLogger(__name__)


async def _extract_search_keywords(topic: str) -> str:
    """Turn a user question into a compact English academic query."""
    if topic.isascii():
        return topic
    try:
        response = await get_llm().ainvoke(
            [
                SystemMessage(
                    content=(
                        "Rewrite the research question as an English academic search query. "
                        "Return only 6-12 keywords or short phrases, no explanation. Preserve "
                        "important models, methods, languages, datasets, and benchmarks."
                    )
                ),
                HumanMessage(content=topic),
            ]
        )
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        query = " ".join(str(content).replace("\n", " ").split()).strip(" `\"'")
        return query[:500] or topic
    except Exception as exc:
        # A search provider outage must not become an LLM outage.
        event(
            logger,
            "search.keyword_extraction_fallback",
            level=logging.WARNING,
            failure_code=failure_code(exc),
            error_type=type(exc).__name__,
        )
        return topic


class RankedPaper(Paper):
    relevance_score: float
    rank: int


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text) if len(token) > 2}


def _valid_publication_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", value.strip(), flags=re.I)


def extract_doi(value: str) -> str | None:
    """Return the DOI embedded in user text, normalized for exact matching."""
    match = _DOI_IN_TEXT_RE.search(value)
    return _clean_doi(match.group(1).rstrip(".,;")) if match else None


def _inverted_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned))


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse an HTTP Retry-After value as seconds, including HTTP-date values."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _sanitize_openalex_query(query: str) -> str:
    """Remove wildcard operators from natural-language questions.

    OpenAlex treats ``?`` and ``*`` as wildcard syntax and otherwise responds
    with HTTP 400 for normal questions.
    """
    return " ".join(_OPENALEX_WILDCARD_RE.sub(" ", query).split())


class AcademicSearchService:
    """Search and normalize papers from OpenAlex, Semantic Scholar, and arXiv."""

    # Semantic Scholar's introductory API-key allowance is one request per
    # second across all endpoints. Keep this process below that ceiling even
    # when several review jobs run concurrently.
    _semantic_scholar_rate_lock = asyncio.Lock()
    _semantic_scholar_last_request_at: float | None = None

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=settings.academic_request_timeout,
            follow_redirects=True,
            headers={"User-Agent": "LitReviewAgent/0.1 (academic MVP)"},
        )
        self.settings = settings

    async def close(self) -> None:
        if self._owned_client:
            await self.client.aclose()

    async def search(self, topic: str, max_results: int) -> tuple[list[Paper], list[str]]:
        doi = extract_doi(topic)
        if doi:
            return await self.lookup_doi(doi), []
        papers = await self._search_openalex_with_retry(topic, max_results)
        return self._deduplicate(papers)[:max_results], []

    async def lookup_doi(self, doi: str) -> list[Paper]:
        """Fetch one work by DOI, never falling back to semantic search.

        A DOI identifies a single work.  Returning near matches here would let
        an unrelated search result be presented as the requested citation.
        """
        normalized_doi = _clean_doi(doi)
        if not normalized_doi:
            return []
        papers = await self._search_openalex_with_retry(normalized_doi, 1, doi=normalized_doi)
        return [paper for paper in papers if str(paper.get("doi") or "").casefold() == normalized_doi.casefold()][:1]

    async def search_all_sources(self, topic: str, max_results: int) -> tuple[list[Paper], list[str]]:
        query = await _extract_search_keywords(topic)
        event(logger, "search.providers_started", query_length=len(query), requested_limit=max_results)
        results = await asyncio.gather(
            self._search_openalex_with_retry(query, max_results),
            self._search_semantic_scholar(query, max_results),
            self._search_arxiv(query, max_results),
            return_exceptions=True,
        )
        papers: list[Paper] = []
        warnings: list[str] = []
        for source, result in zip(("openalex", "semantic_scholar", "arxiv"), results, strict=True):
            if isinstance(result, Exception):
                event(
                    logger,
                    "search.provider_failed",
                    level=logging.WARNING,
                    source=source,
                    failure_code=failure_code(result),
                    error_type=type(result).__name__,
                )
                warnings.append(f"{source}: {result}")
            else:
                papers.extend(result)
        deduplicated = self._deduplicate(papers)[: max_results * 3]
        event(logger, "search.providers_completed", papers_found=len(deduplicated), warning_count=len(warnings))
        return deduplicated, warnings

    async def snowball(self, seed_papers: list[Paper], max_results: int = 10) -> tuple[list[Paper], list[str]]:
        """Expand a corpus by one Semantic Scholar citation/reference hop.

        Only Semantic Scholar seeds carry a stable graph identifier. Failures are
        non-fatal because snowballing improves recall but must not block a job.
        """

        headers = (
            {"x-api-key": self.settings.semantic_scholar_api_key.strip()}
            if self.settings.semantic_scholar_api_key.strip()
            else {}
        )
        expanded: list[Paper] = []
        warnings: list[str] = []
        fields = "paperId,title,abstract,authors,year,externalIds,citationCount,openAccessPdf,url"
        for seed in seed_papers[:5]:
            paper_id = str(seed.get("paper_id") or "")
            if not paper_id.startswith("s2:"):
                continue
            try:
                await self._wait_for_semantic_scholar_slot()
                response = await self.client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/{paper_id[3:]}",
                    params={"fields": f"citations.{fields},references.{fields}"},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                neighbours = [*(payload.get("citations") or []), *(payload.get("references") or [])]
                for relation in neighbours:
                    item = relation.get("citingPaper") or relation.get("citedPaper") or relation
                    abstract = " ".join((item.get("abstract") or "").split())
                    title = " ".join((item.get("title") or "").split())
                    authors = [author.get("name", "") for author in item.get("authors", []) if author.get("name")]
                    neighbour_id = str(item.get("paperId") or "")
                    if (
                        not neighbour_id
                        or not title
                        or not authors
                        or len(abstract) < self.settings.academic_min_abstract_length
                    ):
                        continue
                    ids = item.get("externalIds") or {}
                    expanded.append(
                        {
                            "paper_id": f"s2:{neighbour_id}",
                            "title": title,
                            "authors": authors,
                            "year": item.get("year"),
                            "doi": _clean_doi(ids.get("DOI")),
                            "url": item.get("url") or f"https://www.semanticscholar.org/paper/{neighbour_id}",
                            "abstract": abstract,
                            "cited_by_count": int(item.get("citationCount") or 0),
                            "is_open_access": bool(item.get("openAccessPdf")),
                            "source": "semantic_scholar",
                            "pdf_url": (item.get("openAccessPdf") or {}).get("url"),
                        }
                    )
                    if len(expanded) >= max_results:
                        return self._deduplicate(expanded)[:max_results], warnings
            except (httpx.HTTPError, ValueError) as exc:
                event(
                    logger,
                    "search.snowball_failed",
                    level=logging.WARNING,
                    source="semantic_scholar",
                    paper_id=paper_id,
                    failure_code=failure_code(exc),
                    error_type=type(exc).__name__,
                )
                warnings.append(f"snowball:{paper_id}: {exc}")
        return self._deduplicate(expanded)[:max_results], warnings

    async def _search_openalex_with_retry(self, topic: str, limit: int, *, doi: str | None = None) -> list[Paper]:
        max_retries = self.settings.academic_openalex_max_retries
        base_delay = self.settings.academic_retry_base_delay_seconds

        for attempt in range(max_retries + 1):
            try:
                return await self._search_openalex(topic, limit, doi=doi)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    if attempt == max_retries:
                        raise OpenAlexRateLimitError(f"OpenAlex rate limit exceeded after {max_retries} retries.")
                    delay = base_delay * (2**attempt)
                    event(
                        logger,
                        "search.provider_retry",
                        level=logging.WARNING,
                        source="openalex",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay_seconds=delay,
                        failure_code="PROVIDER_RATE_LIMITED",
                    )
                    await asyncio.sleep(delay)
                elif status >= 500:
                    if attempt == max_retries:
                        raise OpenAlexServerError(f"OpenAlex server error ({status}) after {max_retries} retries.")
                    delay = base_delay * (2**attempt)
                    event(
                        logger,
                        "search.provider_retry",
                        level=logging.WARNING,
                        source="openalex",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay_seconds=delay,
                        failure_code="UPSTREAM_UNAVAILABLE",
                    )
                    await asyncio.sleep(delay)
                else:
                    # 4xx client errors (excluding 429) should not be retried
                    raise OpenAlexClientError(f"OpenAlex client error: {status}. Do not retry.")
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt == max_retries:
                    raise OpenAlexServerError(f"OpenAlex network error after {max_retries} retries: {exc}")
                delay = base_delay * (2**attempt)
                event(
                    logger,
                    "search.provider_retry",
                    level=logging.WARNING,
                    source="openalex",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    failure_code=failure_code(exc),
                )
                await asyncio.sleep(delay)
            except ValueError as exc:
                raise OpenAlexError(f"OpenAlex JSON parse error: {exc}")

    async def _search_openalex(self, topic: str, limit: int, *, doi: str | None = None) -> list[Paper]:
        params: dict[str, str | int] = {"per_page": limit}
        if doi:
            params["filter"] = f"doi:{doi}"
        else:
            params["search"] = _sanitize_openalex_query(topic)
        openalex_email = self.settings.openalex_email.strip()
        if openalex_email and openalex_email.lower() != "your-email@example.com":
            params["mailto"] = openalex_email
        openalex_api_key = self.settings.openalex_api_key.strip()
        if openalex_api_key:
            params["api_key"] = openalex_api_key
        response = await self.client.get("https://api.openalex.org/works", params=params)
        response.raise_for_status()

        papers: list[Paper] = []
        for item in response.json().get("results", []):
            paper_id = str(item.get("id", "")).rstrip("/").split("/")[-1]
            primary = item.get("primary_location") or {}
            best_oa = item.get("best_oa_location") or {}
            pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url")
            url = item.get("doi") or primary.get("landing_page_url") or item.get("id", "")
            abstract = _inverted_abstract(item.get("abstract_inverted_index"))
            title = " ".join((item.get("display_name") or "").split())
            authors = [
                authorship.get("author", {}).get("display_name", "")
                for authorship in item.get("authorships", [])
                if authorship.get("author", {}).get("display_name")
            ]
            if (
                not _OPENALEX_WORK_ID_RE.fullmatch(paper_id)
                or not title
                or not authors
                or not _valid_publication_url(url)
                or (not doi and len(abstract) < self.settings.academic_min_abstract_length)
            ):
                continue

            open_access = item.get("open_access") or {}
            papers.append(
                {
                    "paper_id": paper_id,
                    "title": title,
                    "authors": authors,
                    "year": item.get("publication_year"),
                    "doi": _clean_doi(item.get("doi")),
                    "url": url,
                    "abstract": abstract,
                    "cited_by_count": int(item.get("cited_by_count") or 0),
                    "is_open_access": bool(open_access.get("is_oa")),
                    "pdf_url": pdf_url,
                    "source": "openalex",
                }
            )
        return papers

    @classmethod
    async def _wait_for_semantic_scholar_slot(cls) -> None:
        async with cls._semantic_scholar_rate_lock:
            now = monotonic()
            if cls._semantic_scholar_last_request_at is not None:
                delay = get_settings().academic_semantic_scholar_min_interval_seconds - (
                    now - cls._semantic_scholar_last_request_at
                )
                if delay > 0:
                    await asyncio.sleep(delay)
            cls._semantic_scholar_last_request_at = monotonic()

    async def _search_semantic_scholar(self, query: str, limit: int) -> list[Paper]:
        headers = {}
        if self.settings.semantic_scholar_api_key.strip():
            headers["x-api-key"] = self.settings.semantic_scholar_api_key.strip()
        response: httpx.Response
        for attempt in range(self.settings.academic_semantic_scholar_max_retries + 1):
            await self._wait_for_semantic_scholar_slot()
            response = await self.client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": min(limit, 100),
                    "fields": "paperId,title,abstract,authors,year,externalIds,citationCount,openAccessPdf,url",
                },
                headers=headers,
            )
            if response.status_code != 429:
                response.raise_for_status()
                break

            retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            delay = (
                retry_after if retry_after is not None else self.settings.academic_semantic_scholar_min_interval_seconds
            )
            if attempt == self.settings.academic_semantic_scholar_max_retries:
                event(
                    logger,
                    "search.provider_failed",
                    level=logging.WARNING,
                    source="semantic_scholar",
                    attempt=attempt + 1,
                    max_retries=self.settings.academic_semantic_scholar_max_retries,
                    failure_code="PROVIDER_RATE_LIMITED",
                )
                logger.warning(
                    "Semantic Scholar rate-limited request after %s retries; continuing with other sources.",
                    self.settings.academic_semantic_scholar_max_retries,
                )
                response.raise_for_status()
            logger.warning(
                "Semantic Scholar rate-limited request; retrying in %.2f seconds (attempt %s/%s).",
                delay,
                attempt + 1,
                self.settings.academic_semantic_scholar_max_retries,
            )
            event(
                logger,
                "search.provider_retry",
                level=logging.WARNING,
                source="semantic_scholar",
                attempt=attempt + 1,
                max_retries=self.settings.academic_semantic_scholar_max_retries,
                delay_seconds=delay,
                failure_code="PROVIDER_RATE_LIMITED",
            )
            await asyncio.sleep(delay)

        papers: list[Paper] = []
        for item in response.json().get("data", []):
            abstract = " ".join((item.get("abstract") or "").split())
            title = " ".join((item.get("title") or "").split())
            authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
            paper_id = str(item.get("paperId") or "")
            if not paper_id or not title or not authors or len(abstract) < self.settings.academic_min_abstract_length:
                continue
            ids = item.get("externalIds") or {}
            papers.append(
                {
                    "paper_id": f"s2:{paper_id}",
                    "title": title,
                    "authors": authors,
                    "year": item.get("year"),
                    "doi": _clean_doi(ids.get("DOI")),
                    "url": item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}",
                    "abstract": abstract,
                    "cited_by_count": int(item.get("citationCount") or 0),
                    "is_open_access": bool(item.get("openAccessPdf")),
                    "source": "semantic_scholar",
                    "pdf_url": (item.get("openAccessPdf") or {}).get("url"),
                }
            )
        return papers

    async def _search_arxiv(self, query: str, limit: int) -> list[Paper]:
        response = await self.client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(limit, self.settings.academic_arxiv_max_results),
            },
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        papers: list[Paper] = []
        for entry in root.findall("atom:entry", ns):
            raw_id = entry.findtext("atom:id", default="", namespaces=ns).rstrip("/")
            arxiv_id = raw_id.rsplit("/", 1)[-1]
            title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
            abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
            authors = [n.text.strip() for n in entry.findall("atom:author/atom:name", ns) if n.text and n.text.strip()]
            if not arxiv_id or not title or not authors or len(abstract) < self.settings.academic_min_abstract_length:
                continue
            published = entry.findtext("atom:published", default="", namespaces=ns)
            year = int(published[:4]) if published[:4].isdigit() else None
            papers.append(
                {
                    "paper_id": f"arxiv:{arxiv_id}",
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": f"10.48550/arXiv.{arxiv_id}",
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "abstract": abstract,
                    "cited_by_count": 0,
                    "is_open_access": True,
                    "source": "arxiv",
                    "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                }
            )
        return papers

    @staticmethod
    def _deduplicate(papers: Iterable[Paper]) -> list[Paper]:
        """Keep one canonical record for the same scholarly work.

        Search providers commonly return both a preprint and its later journal
        version under different DOIs.  DOI-only deduplication treats those as
        independent evidence, which can inflate corpus and reference counts.
        A normalized title is the cross-provider identity; when records
        collide, prefer a non-preprint version before metadata richness.
        """
        unique: dict[str, Paper] = {}
        for paper in papers:
            if not paper["title"] or not paper["abstract"]:
                continue
            title_key = " ".join(sorted(_tokens(paper["title"])))
            key = f"title:{title_key}" if title_key else f"doi:{str(paper.get('doi') or '').lower()}"
            current = unique.get(key)
            if current is None or _paper_record_quality(paper) > _paper_record_quality(current):
                unique[key] = paper
        return list(unique.values())


def _paper_record_quality(paper: Paper) -> tuple[int, int, int, int]:
    """Rank duplicate metadata records without mistaking versions for sources."""
    doi = str(paper.get("doi") or "").lower()
    url = str(paper.get("url") or "").lower()
    source = str(paper.get("source") or "").lower()
    is_preprint = (
        "preprints.org" in url
        or "arxiv.org" in url
        or doi.startswith("10.20944/preprints")
        or doi.startswith("10.48550/arxiv")
        or source == "arxiv"
    )
    return (
        int(not is_preprint),
        int(bool(doi)),
        len(str(paper.get("abstract") or "")),
        int(paper.get("cited_by_count") or 0),
    )


def rank_papers(
    papers: list[Paper],
    queries: str | list[str],
    limit: int,
    *,
    required_terms: list[str] | None = None,
    excluded_terms: list[str] | None = None,
) -> list[RankedPaper]:
    """Rank against each approved sub-query instead of one concatenated string."""
    raw_queries = [queries] if isinstance(queries, str) else queries
    query_tokens: list[tuple[set[str], bool]] = []
    for query in raw_queries:
        tokens = _tokens(str(query))
        if not tokens:
            continue
        # Generic academic words ("review", "evolution", "study", …) occur
        # in many unrelated papers. Prefer subject-bearing terms when present.
        subject_tokens = tokens - _RANKING_STOPWORDS
        query_tokens.append((subject_tokens or tokens, bool(subject_tokens)))
    if not query_tokens:
        return []

    required_token_sets = [_tokens(term) for term in required_terms or []]
    required_token_sets = [tokens for tokens in required_token_sets if tokens]
    excluded_token_sets = [_tokens(term) for term in excluded_terms or []]
    excluded_token_sets = [tokens for tokens in excluded_token_sets if tokens]

    current_year = datetime.now().year
    scored: list[tuple[float, Paper]] = []
    for paper in papers:
        title_tokens = _tokens(paper["title"])
        abstract_tokens = _tokens(paper["abstract"])
        paper_tokens = title_tokens | abstract_tokens
        # Required terms are alternatives that describe the intended scope;
        # excluded terms remove a known false-positive interpretation.
        if required_token_sets and not any(tokens <= paper_tokens for tokens in required_token_sets):
            continue
        if any(tokens <= paper_tokens for tokens in excluded_token_sets):
            continue
        lexical_scores: list[float] = []
        for tokens, has_subject_tokens in query_tokens:
            # A paper may satisfy one focused branch of the research plan. It
            # must cover the distinctive subject phrase, not merely share one
            # generic-looking term with it. This prevents "Quantum Telepathy"
            # from silently becoming papers about quantum teleportation.
            overlap = tokens & paper_tokens
            required_overlap = min(2, len(tokens)) if has_subject_tokens else 1
            if has_subject_tokens and len(overlap) < required_overlap:
                continue
            title_overlap = len(tokens & title_tokens) / max(1, len(tokens))
            abstract_overlap = len(tokens & abstract_tokens) / max(1, len(tokens))
            lexical_scores.append(0.4 * title_overlap + 0.35 * abstract_overlap)
        if not lexical_scores:
            continue

        age = max(0, current_year - paper["year"]) if paper["year"] else 20
        recency = max(0.0, 1 - age / 20)
        citations = min(1.0, math.log1p(paper["cited_by_count"]) / math.log(1001))
        subquery_coverage = len(lexical_scores) / len(query_tokens)
        score = max(lexical_scores) + 0.05 * subquery_coverage + 0.1 * recency + 0.1 * citations
        scored.append((score, paper))
    scored.sort(key=lambda item: (-item[0], -item[1]["cited_by_count"], -(item[1]["year"] or 0)))
    return [
        {**paper, "relevance_score": round(score, 4), "rank": index}
        for index, (score, paper) in enumerate(scored[:limit], start=1)
    ]
