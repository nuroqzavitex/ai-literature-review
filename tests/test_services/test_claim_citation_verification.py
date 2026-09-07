from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.claim_citation_verification import (
    ClaimCitationVerifier,
    extract_claim_citation_pairs,
)


def _settings():
    return SimpleNamespace(
        document_review_claim_max_pairs=30,
        document_review_claim_concurrency=3,
        document_review_claim_timeout_seconds=5,
        document_review_claim_temperature=0,
        document_review_citation_lookup_timeout_seconds=5,
    )


def test_extracts_latex_claim_and_resolves_doi_from_bibtex():
    content = (
        "QMugs contains hundreds of thousands of drug-like molecules \\cite{isert2022qmugs}.\n"
        "\\bibliography{references}\n"
    )
    bibliography = """
@article{isert2022qmugs,
  title={QMugs, quantum mechanical properties of drug-like molecules},
  doi={10.1038/s41597-022-01390-7}
}
"""

    pairs = extract_claim_citation_pairs(content, bibliography)

    assert len(pairs) == 1
    assert pairs[0].citation_label == "isert2022qmugs"
    assert pairs[0].doi == "10.1038/s41597-022-01390-7"
    assert pairs[0].claim in content


def test_extracts_numbered_pdf_citation_and_resolves_reference_doi():
    content = """QMugs provides quantum-mechanical properties for drug-like molecules [12].

# References
[12] Isert et al. QMugs. https://doi.org/10.1038/s41597-022-01390-7
"""

    pairs = extract_claim_citation_pairs(content)

    assert [(pair.citation_label, pair.doi) for pair in pairs] == [("12", "10.1038/s41597-022-01390-7")]


def test_normalizes_arxiv_doi_version_before_lookup():
    pairs = extract_claim_citation_pairs(
        "Waveforms support prediction \\cite{waveforms}.",
        "@article{waveforms, doi={10.48550/arXiv.2407.17856v4}}",
    )

    assert pairs[0].doi == "10.48550/arXiv.2407.17856"


@pytest.mark.asyncio
async def test_verifier_keeps_only_verbatim_abstract_evidence(monkeypatch):
    abstract = "QMugs contains quantum mechanical properties for more than 665,000 molecules."

    class SearchService:
        async def lookup_doi(self, _doi):
            return [
                {
                    "title": "QMugs",
                    "authors": ["Author"],
                    "year": 2022,
                    "url": "https://example.test/qmugs",
                    "abstract": abstract,
                }
            ]

        async def close(self):
            pass

    class Candidate:
        native_schema_supported = True

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "verdict": "supported",
                "confidence": 0.94,
                "rationale": "The abstract directly supports the dataset-size claim.",
                "evidence_quotes": [abstract],
                "atomic_subclaims": ["QMugs contains more than 665,000 molecules."],
            }

    monkeypatch.setattr("src.services.claim_citation_verification.AcademicSearchService", SearchService)
    monkeypatch.setattr("src.services.claim_citation_verification.get_llm", lambda **_kwargs: Candidate())
    content = "QMugs contains more than 665,000 molecules \\cite{qmugs}."
    bibliography = "@article{qmugs, doi={10.1038/s41597-022-01390-7}}"

    findings = await ClaimCitationVerifier(_settings()).verify(content, bibliography)

    assert findings[0]["verdict"] == "supported"
    assert findings[0]["evidence_quotes"] == [abstract]
    assert findings[0]["source_scope"] == "abstract"


@pytest.mark.asyncio
async def test_verifier_falls_back_to_json_when_native_schema_fails(monkeypatch):
    abstract = "The review describes machine learning use in emergency care."

    class SearchService:
        async def lookup_doi(self, _doi):
            return [{"title": "Emergency AI review", "abstract": abstract}]

        async def close(self):
            pass

    class BrokenStructuredCandidate:
        async def ainvoke(self, _messages):
            raise ValueError("structured schema failed")

    class Candidate:
        native_schema_supported = True

        def with_structured_output(self, _schema):
            return BrokenStructuredCandidate()

        async def ainvoke(self, _messages):
            return SimpleNamespace(
                content=(
                    '{"verdict":"supported","confidence":0.8,'
                    '"rationale":"The abstract supports the claim.",'
                    f'"evidence_quotes":["{abstract}"],'
                    '"atomic_subclaims":["Machine learning is used in emergency care."]}'
                )
            )

    monkeypatch.setattr("src.services.claim_citation_verification.AcademicSearchService", SearchService)
    monkeypatch.setattr("src.services.claim_citation_verification.get_llm", lambda **_kwargs: Candidate())

    findings = await ClaimCitationVerifier(_settings()).verify(
        "Machine learning is used in emergency care \\cite{review}.",
        "@article{review, doi={10.1000/review}}",
    )

    assert findings[0]["verdict"] == "supported"
    assert findings[0]["evidence_quotes"] == [abstract]


@pytest.mark.asyncio
async def test_verifier_downgrades_invented_quote_to_unverifiable(monkeypatch):
    class SearchService:
        async def lookup_doi(self, _doi):
            return [{"title": "Paper", "abstract": "The observed effect was small."}]

        async def close(self):
            pass

    class Candidate:
        native_schema_supported = True

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "verdict": "supported",
                "confidence": 0.9,
                "rationale": "Supported.",
                "evidence_quotes": ["An invented supporting quote."],
                "atomic_subclaims": ["The effect was large."],
            }

    monkeypatch.setattr("src.services.claim_citation_verification.AcademicSearchService", SearchService)
    monkeypatch.setattr("src.services.claim_citation_verification.get_llm", lambda **_kwargs: Candidate())

    findings = await ClaimCitationVerifier(_settings()).verify(
        "The effect was large \\cite{paper}.",
        "@article{paper, doi={10.1000/example}}",
    )

    assert findings[0]["verdict"] == "unverifiable"
    assert findings[0]["evidence_quotes"] == []
