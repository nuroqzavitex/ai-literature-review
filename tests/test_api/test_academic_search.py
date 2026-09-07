import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.academic_search import (
    AcademicSearchService,
    OpenAlexClientError,
    OpenAlexRateLimitError,
    OpenAlexServerError,
    extract_doi,
)


@pytest.mark.asyncio
async def test_search_openalex_success():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "id": "W12345",
                "display_name": "Test Paper",
                "doi": "https://doi.org/10.1234/abc",
                "authorships": [{"author": {"display_name": "Author A"}}],
                "publication_year": 2024,
                # Mock a long enough abstract to pass validation (200 chars)
                "abstract_inverted_index": {
                    word: [i]
                    for i, word in enumerate(
                        "This is a mock abstract that is intentionally made very long to bypass the two hundred characters limit imposed by the validation logic in the OpenAlex academic search service adapter. We need to make sure this is really long so we don't get filtered out. Here are some more words to fill the space.".split()
                    )
                },
            }
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client.get.return_value = mock_response

    service = AcademicSearchService(client=mock_client)
    papers, warnings = await service.search("test topic", 10)

    assert len(papers) == 1
    assert papers[0]["paper_id"] == "W12345"
    assert papers[0]["title"] == "Test Paper"
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_doi_lookup_uses_exact_openalex_filter_and_rejects_nonmatching_record():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "id": "https://openalex.org/W7404017",
                "display_name": "Deep Convolutional Neural Networks for Computer-Aided Detection",
                "doi": "https://doi.org/10.1109/TMI.2016.2528162",
                "authorships": [{"author": {"display_name": "Hoo-Chang Shin"}}],
                "publication_year": 2016,
                "abstract_inverted_index": {},
            },
            {
                "id": "https://openalex.org/W999",
                "display_name": "An unrelated result",
                "doi": "https://doi.org/10.9999/unrelated",
                "authorships": [{"author": {"display_name": "Other Author"}}],
                "publication_year": 2025,
                "abstract_inverted_index": {},
            },
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_client.get.return_value = mock_response

    service = AcademicSearchService(client=mock_client)
    papers, warnings = await service.search("tìm báo DOI: 10.1109/TMI.2016.2528162", 3)

    assert warnings == []
    assert [paper["doi"] for paper in papers] == ["10.1109/TMI.2016.2528162"]
    params = mock_client.get.call_args.kwargs["params"]
    assert params["filter"] == "doi:10.1109/TMI.2016.2528162"
    assert "search" not in params


def test_extract_doi_from_text_and_url():
    assert extract_doi("doi: 10.1109/TMI.2016.2528162.") == "10.1109/TMI.2016.2528162"
    assert extract_doi("https://doi.org/10.1109/TMI.2016.2528162") == "10.1109/TMI.2016.2528162"


@pytest.mark.asyncio
async def test_search_openalex_does_not_send_placeholder_email():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.raise_for_status.return_value = None
    mock_client.get.return_value = mock_response

    service = AcademicSearchService(client=mock_client)
    service.settings.openalex_email = "your-email@example.com"
    await service.search("test topic", 10)

    params = mock_client.get.call_args.kwargs["params"]
    assert "mailto" not in params


@pytest.mark.asyncio
async def test_search_openalex_sends_configured_api_key():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.raise_for_status.return_value = None
    mock_client.get.return_value = mock_response

    service = AcademicSearchService(client=mock_client)
    service.settings.openalex_api_key = "test-openalex-key"
    await service.search("test topic", 10)

    assert mock_client.get.call_args.kwargs["params"]["api_key"] == "test-openalex-key"


@pytest.mark.asyncio
async def test_semantic_scholar_retries_429_after_retry_after_header():
    mock_client = AsyncMock()
    rate_limited = httpx.Response(
        429,
        headers={"Retry-After": "2.5"},
        request=httpx.Request("GET", "https://api.semanticscholar.org/graph/v1/paper/search"),
    )
    success = MagicMock(status_code=200)
    success.raise_for_status.return_value = None
    success.json.return_value = {"data": []}
    mock_client.get.side_effect = [rate_limited, success]

    service = AcademicSearchService(client=mock_client)
    with (
        patch.object(AcademicSearchService, "_wait_for_semantic_scholar_slot", new_callable=AsyncMock) as wait_for_slot,
        patch("src.services.academic_search.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        papers = await service._search_semantic_scholar("test topic", 10)

    assert papers == []
    assert mock_client.get.call_count == 2
    assert wait_for_slot.await_count == 2
    mock_sleep.assert_awaited_once_with(2.5)


@pytest.mark.asyncio
async def test_multi_source_search_warns_and_returns_other_source_results(caplog):
    service = AcademicSearchService(client=AsyncMock())
    arxiv_paper = {
        "paper_id": "arxiv:1234.5678",
        "title": "Arxiv Paper",
        "authors": ["Author A"],
        "year": 2024,
        "doi": "10.48550/arXiv.1234.5678",
        "url": "https://arxiv.org/abs/1234.5678",
        "abstract": "A" * 250,
        "cited_by_count": 0,
        "is_open_access": True,
        "source": "arxiv",
    }
    with (
        patch("src.services.academic_search._extract_search_keywords", new_callable=AsyncMock, return_value="test"),
        patch.object(
            service,
            "_search_openalex_with_retry",
            new_callable=AsyncMock,
            side_effect=OpenAlexRateLimitError("limited"),
        ),
        patch.object(
            service,
            "_search_semantic_scholar",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "limited", request=httpx.Request("GET", "https://api.semanticscholar.org"), response=httpx.Response(429)
            ),
        ),
        patch.object(service, "_search_arxiv", new_callable=AsyncMock, return_value=[arxiv_paper]),
        caplog.at_level(logging.WARNING, logger="src.services.academic_search"),
    ):
        papers, warnings = await service.search_all_sources("test", 10)

    assert papers == [arxiv_paper]
    assert len(warnings) == 2
    assert "continuing with remaining sources" in caplog.text


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_search_openalex_rate_limit_retry(mock_sleep):
    mock_client = AsyncMock()

    # Create a 429 error
    rate_limit_response = httpx.Response(429, request=httpx.Request("GET", "https://api.openalex.org/works"))
    rate_limit_error = httpx.HTTPStatusError(
        "Too Many Requests", request=rate_limit_response.request, response=rate_limit_response
    )

    mock_client.get.side_effect = [rate_limit_error, rate_limit_error, rate_limit_error]

    service = AcademicSearchService(client=mock_client)

    with pytest.raises(OpenAlexRateLimitError) as exc_info:
        await service.search("test topic", 10)

    assert "rate limit exceeded after 2 retries" in str(exc_info.value)
    assert mock_client.get.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_search_openalex_server_error_retry(mock_sleep):
    mock_client = AsyncMock()

    # Create a 503 error
    server_error_response = httpx.Response(503, request=httpx.Request("GET", "https://api.openalex.org/works"))
    server_error = httpx.HTTPStatusError(
        "Service Unavailable", request=server_error_response.request, response=server_error_response
    )

    mock_client.get.side_effect = [server_error, server_error, server_error]

    service = AcademicSearchService(client=mock_client)

    with pytest.raises(OpenAlexServerError) as exc_info:
        await service.search("test topic", 10)

    assert "server error (503) after 2 retries" in str(exc_info.value)
    assert mock_client.get.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_search_openalex_client_error_no_retry(mock_sleep):
    mock_client = AsyncMock()

    # Create a 400 error
    client_error_response = httpx.Response(400, request=httpx.Request("GET", "https://api.openalex.org/works"))
    client_error = httpx.HTTPStatusError(
        "Bad Request", request=client_error_response.request, response=client_error_response
    )

    mock_client.get.side_effect = [client_error]

    service = AcademicSearchService(client=mock_client)

    with pytest.raises(OpenAlexClientError) as exc_info:
        await service.search("test topic", 10)

    assert "client error: 400. Do not retry" in str(exc_info.value)
    assert mock_client.get.call_count == 1
    assert mock_sleep.call_count == 0


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_search_openalex_network_error_retry(mock_sleep):
    mock_client = AsyncMock()

    network_error = httpx.RequestError("Network unreachable")
    mock_client.get.side_effect = [network_error, network_error, network_error]

    service = AcademicSearchService(client=mock_client)

    with pytest.raises(OpenAlexServerError) as exc_info:
        await service.search("test topic", 10)

    assert "network error after 2 retries" in str(exc_info.value)
    assert mock_client.get.call_count == 3
    assert mock_sleep.call_count == 2
