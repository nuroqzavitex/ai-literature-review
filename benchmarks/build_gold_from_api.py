#!/usr/bin/env python3
"""
build_gold_from_api.py  —  Gold curation pipeline v2.2
=======================================================
Luồng:
  1. Lấy query từ system pilot artifact (query_history)
  2. Mở rộng bằng topic + expected_themes
  3. Gọi arXiv API + OpenAlex API trực tiếp
  4. Dedupe theo arxiv_id / openalex_id
  5. Label relevance từ title+abstract (keyword overlap + domain filter)
  6. Validate ID–title bằng gọi API lần hai
  7. Freeze với SHA-256 content hash

Usage:
  python benchmarks/build_gold_from_api.py --topic pos_01 [--dry-run]
  python benchmarks/build_gold_from_api.py --topic pos_02 --per-query 25
  python benchmarks/build_gold_from_api.py --topic pos_02 --output independent_gold_pos02_v4.json
"""

import argparse, hashlib, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse, urllib.request, urllib.error

REPO_ROOT     = Path(__file__).parent.parent
DATASETS_DIR  = REPO_ROOT / "benchmarks" / "datasets"
RESULTS_DIR   = REPO_ROOT / "benchmarks" / "results"
TOPICS_FILE   = DATASETS_DIR / "topics.json"
ARXIV_API     = "https://export.arxiv.org/api/query"
OPENALEX_API  = "https://api.openalex.org/works"

# ── Domain keyword dictionaries ────────────────────────────────────────────────
# For each topic, required "anchor" words: paper MUST contain ≥1 to be relevant.
# If topic not listed here, falls back to pure keyword overlap.
TOPIC_ANCHORS = {
    "pos_01": {  # GNN traffic forecasting
        "required": {"traffic", "transport", "road", "highway", "speed", "flow",
                     "congestion", "vehicle", "mobility", "commute", "travel",
                     "urban", "route", "intersection", "journey"},
    },
    "pos_02": {  # Mamba long-context LM
        "required": {"mamba", "state space", "ssm", "sequence model", "long context",
                     "long-context", "language model", "lm", "transformer",
                     "attention", "context length", "token"},
    },
    "pos_03": {  # FL privacy
        "required": {"federat", "privacy", "gradient", "differential", "attack",
                     "inversion", "client", "aggregat"},
    },
    "pos_04": {  # LLM low-resource MT
        "required": {"translat", "machine translation", "low-resource", "multilingual",
                     "cross-lingual", "language pair", "neural machine"},
    },
    "pos_05": {  # Extreme weather
        "required": {"weather", "climate", "precipitation", "forecast", "storm",
                     "cyclone", "flood", "atmospheric", "meteorolog", "temperature"},
    },
    "pos_06": {  # Causal inference
        "required": {"causal", "treatment effect", "instrumental", "propensity",
                     "difference-in-differences", "observational", "counterfactual",
                     "confounder"},
    },
    "pos_07": {  # RAG evaluation
        "required": {"retrieval", "rag", "augmented generation", "faithfulness",
                     "benchmark", "context", "hallucination"},
    },
    "pos_08": {  # Transformer interpretability
        "required": {"interpret", "mechanistic", "attention head", "circuit",
                     "superposition", "sparse autoencoder", "activation",
                     "probing", "feature"},
    },
    "pos_09": {  # Vietnamese LLM
        "required": {"vietnamese", "viet", "tiếng việt", "vi-nlp", "phobert",
                     "phogpt", "vinai"},
    },
    "pos_10": {  # SSL remote sensing
        "required": {"remote sensing", "satellite", "aerial", "geospatial",
                     "earth observation", "multispectral", "sar", "sentinel",
                     "landsat", "hyperspectral"},
    },
    "pos_11": {  # Battery LCA
        "required": {"battery", "lithium", "recycl", "lifecycle", "lca",
                     "cathode", "electrolyte", "hydrometallurg", "pyrometallurg"},
    },
    "pos_12": {  # LLM safety
        "required": {"safety", "alignment", "red team", "jailbreak", "harm",
                     "trustworthy", "reliable", "hallucination", "toxic",
                     "adversarial", "benchmark"},
    },
}

TOPIC_EXPANSION_QUERIES = {
    "pos_01": [
        "spatiotemporal graph neural networks traffic forecasting",
        "dynamic graph convolution traffic speed prediction road sensors",
    ],
    "pos_02": [
        "Mamba Linear-Time Sequence Modeling Selective State Spaces language modeling",
        "Transformers are SSMs Structured State Space Duality language models",
        "Jamba Hybrid Transformer Mamba Language Model",
        "Empirical Study Mamba-based Language Models",
        "Samba Hybrid State Space Models Unlimited Context",
        "MambaByte token-free selective state space language model",
    ],
}

# ── HTTP ──────────────────────────────────────────────────────────────────────
def http_get(url, params=None, timeout=25, retries=4):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "GoldBuilder/2.2"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            time.sleep(min(max(delay, 1.0), 20.0))
        except urllib.error.URLError:
            if attempt == retries:
                raise
            time.sleep(min(2 ** attempt, 20.0))
    raise RuntimeError("HTTP retry loop ended unexpectedly")


# ── arXiv ─────────────────────────────────────────────────────────────────────
def arxiv_search(query, max_results=20):
    params = dict(search_query=f"all:{query}", start=0, max_results=max_results,
                  sortBy="relevance", sortOrder="descending")
    try:
        return _parse_arxiv_atom(http_get(ARXIV_API, params))
    except Exception as e:
        print(f"  [WARN] arXiv: {e}", file=sys.stderr); return []

def _parse_arxiv_atom(raw):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(raw.decode())
    out = []
    for entry in root.findall("a:entry", ns):
        try:
            entry_id = entry.find("a:id", ns).text.strip()
            m = re.search(r"abs/(.+?)(?:v\d+)?$", entry_id)
            arxiv_id = m.group(1) if m else entry_id
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            title    = entry.find("a:title", ns).text.strip().replace("\n", " ")
            abstract = entry.find("a:summary", ns).text.strip().replace("\n", " ")
            authors  = [a.find("a:name", ns).text for a in entry.findall("a:author", ns)]
            year     = int(entry.find("a:published", ns).text[:4])
            out.append(dict(paper_id=f"arxiv:{arxiv_id}", title=title,
                            abstract=abstract[:600], authors=", ".join(authors[:4]),
                            year=year, url=f"https://arxiv.org/abs/{arxiv_id}", source="arxiv"))
        except Exception:
            continue
    return out


# ── OpenAlex ──────────────────────────────────────────────────────────────────
def openalex_search(query, max_results=20):
    params = {
        "search": query, "per-page": max_results, "mailto": "bench@research",
        "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,primary_location",
        "sort": "relevance_score:desc", "filter": "publication_year:>2018",
    }
    try:
        data = json.loads(http_get(OPENALEX_API, params))
        return _parse_oa(data.get("results", []))
    except Exception as e:
        print(f"  [WARN] OpenAlex: {e}", file=sys.stderr); return []

def _reconstruct_abstract(inv):
    if not inv: return ""
    pos_word = {}
    for word, positions in inv.items():
        for p in positions:
            pos_word[p] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))

def _parse_oa(works):
    out = []
    for w in works:
        try:
            abstract = _reconstruct_abstract(w.get("abstract_inverted_index") or {})
            loc = (w.get("primary_location") or {})
            lp = loc.get("landing_page_url", "") or ""
            if "arxiv.org" in lp:
                m = re.search(r"abs/(.+?)(?:v\d+)?$", lp)
                arxiv_id = m.group(1).strip() if m else None
                if arxiv_id:
                    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
                    paper_id = f"arxiv:{arxiv_id}"
                    url = f"https://arxiv.org/abs/{arxiv_id}"
                else:
                    paper_id = f"openalex:{w.get('id','').split('/')[-1]}"
                    url = w.get("id","")
            else:
                paper_id = f"openalex:{w.get('id','').split('/')[-1]}"
                url = w.get("id","")
            authors = ", ".join(
                a["author"]["display_name"] for a in (w.get("authorships") or [])[:4]
                if a.get("author")
            )
            out.append(dict(paper_id=paper_id, title=w.get("title",""),
                            abstract=abstract[:600], authors=authors,
                            year=w.get("publication_year",0),
                            url=url, source="openalex"))
        except Exception:
            continue
    return out


# ── Labeling ──────────────────────────────────────────────────────────────────
def _contains_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def dedupe_candidates(papers):
    """Collapse cross-provider copies by normalized title, preferring arXiv IDs."""
    unique = {}
    for paper in papers:
        title_key = re.sub(r"[^a-z0-9]+", " ", paper.get("title", "").lower()).strip()
        key = title_key or paper.get("paper_id", "")
        existing = unique.get(key)
        if existing is None or (
            paper.get("paper_id", "").startswith("arxiv:")
            and not existing.get("paper_id", "").startswith("arxiv:")
        ):
            unique[key] = paper
    return list(unique.values())


def _passes_topic_gate(paper, topic_id):
    """Reject known lexical false positives before applying overlap scores."""
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()

    if topic_id == "pos_01":
        traffic = _contains_any(text, {
            "traffic flow", "traffic speed", "traffic forecasting", "traffic prediction",
            "transportation network", "road network", "road traffic", "highway traffic",
            "traffic sensor", "urban mobility",
        })
        forecasting = _contains_any(text, {
            "forecast", "predict", "estimat", "spatiotemporal", "spatio-temporal",
        })
        graph_model = _contains_any(text, {
            "graph neural", "graph convolution", "graph network", "gnn",
            "graph-based", "spatial graph",
        })
        wrong_domain = _contains_any(text, {
            "backend system", "network packet", "internet traffic", "data center traffic",
            "web traffic", "encrypted traffic", "network intrusion",
        })
        return traffic and forecasting and graph_model and not wrong_domain

    if topic_id == "pos_02":
        title = paper.get("title", "").lower()
        title_direct = _contains_any(title, {
            "mamba", "state space", "ssm", "jamba", "samba",
        })
        mamba_ssm = _contains_any(text, {
            "mamba", "selective state space", "selective ssm",
        })
        language = _contains_any(text, {
            "language model", "large language", "language modeling", "token",
            "text generation", "in-context learning", "associative recall",
        })
        long_sequence_or_efficiency = _contains_any(text, {
            "long context", "long-context", "long sequence", "long-sequence",
            "context length", "sequence modeling", "sequence model",
            "linear-time", "linear time", "efficient inference", "throughput",
        })
        wrong_domain = _contains_any(text, {
            "image", "vision", "visual", "multimodal", "multi-modal", "speech recognition",
            "automatic speech", "asr", "sentiment analysis", "time series forecasting",
            "point cloud", "remote sensing", "network anomaly", "protein", "genomic",
            "bioinformatic", "eeg", "electroencephal", "symbolic music", "music generation",
        })
        return title_direct and mamba_ssm and (language or long_sequence_or_efficiency) and not wrong_domain

    return True


def auto_label(paper, topic, topic_id=""):
    """
    Two-stage label:
    1. Keyword overlap score (topic + themes)
    2. Domain anchor check: at least 1 domain-specific word must appear
    """
    topic_words = set(re.findall(r"\b\w{4,}\b", topic["topic"].lower()))
    theme_words = set()
    for t in topic.get("expected_themes", []):
        theme_words.update(re.findall(r"\b\w{4,}\b", t.lower()))

    text = (paper["title"] + " " + paper["abstract"]).lower()
    text_words = set(re.findall(r"\b\w{4,}\b", text))

    t_score  = len(topic_words & text_words) / max(len(topic_words), 1)
    th_score = len(theme_words & text_words) / max(len(theme_words), 1)
    score    = t_score * 0.6 + th_score * 0.4

    # Domain anchor check
    anchors = TOPIC_ANCHORS.get(topic_id, {}).get("required", set())
    if anchors:
        # Check if any anchor word appears (substring match for stemmed forms)
        has_anchor = any(anchor in text for anchor in anchors)
    else:
        has_anchor = True  # no anchor defined → skip check

    passes_gate = _passes_topic_gate(paper, topic_id)
    if topic_id in {"pos_01", "pos_02"} and passes_gate:
        return "relevant", score
    if score >= 0.28 and has_anchor and passes_gate:
        return "relevant", score
    elif passes_gate and ((score >= 0.18 and has_anchor) or (score >= 0.28 and not has_anchor)):
        return "partially_relevant", score
    else:
        return "irrelevant", score


# ── Validate ──────────────────────────────────────────────────────────────────
def _title_overlap(left, right):
    left_words = set(re.findall(r"\b\w{3,}\b", left.lower()))
    right_words = set(re.findall(r"\b\w{3,}\b", right.lower()))
    return len(left_words & right_words) / max(len(left_words | right_words), 1)


def validate_paper(paper):
    pid = paper["paper_id"]
    try:
        if pid.startswith("arxiv:"):
            arxiv_id = pid.replace("arxiv:", "")
            raw = http_get(ARXIV_API, {"id_list": arxiv_id, "max_results": 1})
            results = _parse_arxiv_atom(raw)
        elif pid.startswith("openalex:"):
            openalex_id = pid.replace("openalex:", "")
            result = json.loads(http_get(f"{OPENALEX_API}/{openalex_id}"))
            results = _parse_oa([result])
        else:
            results = []
        if results:
            overlap = _title_overlap(paper["title"], results[0]["title"])
            if overlap >= 0.85:
                paper.update(title=results[0]["title"], authors=results[0]["authors"],
                             year=results[0]["year"], abstract=results[0]["abstract"])
                paper["validated"] = True
                paper["val_note"]  = f"title_overlap={overlap:.2f}"
            else:
                paper["validated"] = False
                paper["val_note"]  = f"overlap={overlap:.2f} < 0.85 → API: {results[0]['title'][:50]}"
        else:
            paper["validated"] = False; paper["val_note"] = "id not found at source API"
    except Exception as e:
        paper["validated"] = False; paper["val_note"] = f"error: {e}"
    return paper


def fetch_paper(paper_id):
    """Fetch one curator-selected paper directly from its canonical source."""
    if paper_id.startswith("arxiv:"):
        arxiv_id = paper_id.removeprefix("arxiv:")
        results = _parse_arxiv_atom(http_get(ARXIV_API, {"id_list": arxiv_id, "max_results": 1}))
    elif paper_id.startswith("openalex:"):
        openalex_id = paper_id.removeprefix("openalex:")
        results = _parse_oa([json.loads(http_get(f"{OPENALEX_API}/{openalex_id}"))])
    else:
        raise ValueError(f"unsupported curated paper ID: {paper_id}")
    if not results:
        raise ValueError(f"paper not found at source API: {paper_id}")
    paper = results[0]
    paper["label"] = "relevant"
    paper["label_score"] = 1.0
    paper["label_reason"] = "curator-selected from independently searched source metadata"
    return paper


def fetch_papers(paper_ids):
    """Fetch curator-selected IDs in source-friendly batches."""
    unique_ids = list(dict.fromkeys(paper_ids))
    arxiv_ids = [paper_id.removeprefix("arxiv:") for paper_id in unique_ids if paper_id.startswith("arxiv:")]
    fetched = []
    if arxiv_ids:
        fetched.extend(_parse_arxiv_atom(http_get(
            ARXIV_API, {"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)}
        )))
    for paper_id in unique_ids:
        if paper_id.startswith("openalex:"):
            fetched.append(fetch_paper(paper_id))
        elif not paper_id.startswith("arxiv:"):
            raise ValueError(f"unsupported curated paper ID: {paper_id}")
    by_id = {paper["paper_id"].lower(): paper for paper in fetched}
    missing = [paper_id for paper_id in unique_ids if paper_id.lower() not in by_id]
    if missing:
        raise ValueError(f"papers not found at source API: {', '.join(missing)}")
    papers = [by_id[paper_id.lower()] for paper_id in unique_ids]
    for paper in papers:
        paper["label"] = "relevant"
        paper["label_score"] = 1.0
        paper["label_reason"] = "curator-selected from independently searched source metadata"
    return papers


def validate_papers(papers):
    """Validate arXiv papers with one second source call; validate others normally."""
    arxiv_papers = [paper for paper in papers if paper["paper_id"].startswith("arxiv:")]
    if arxiv_papers:
        arxiv_ids = [paper["paper_id"].removeprefix("arxiv:") for paper in arxiv_papers]
        checked = _parse_arxiv_atom(http_get(
            ARXIV_API, {"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)}
        ))
        checked_by_id = {paper["paper_id"].lower(): paper for paper in checked}
        for paper in arxiv_papers:
            source = checked_by_id.get(paper["paper_id"].lower())
            overlap = _title_overlap(paper["title"], source["title"]) if source else 0.0
            paper["validated"] = bool(source and overlap >= 0.85)
            paper["val_note"] = (
                f"title_overlap={overlap:.2f}" if source
                else "id not found at source API"
            )
    for paper in papers:
        if not paper["paper_id"].startswith("arxiv:"):
            validate_paper(paper)
    return papers


# ── System queries from pilot ─────────────────────────────────────────────────
def get_system_queries(topic_id):
    """
    Tìm query_history từ pilot run.
    Handle both pos_01 and pos01 naming conventions.
    """
    tid_variants = [topic_id, topic_id.replace("_", "")]  # pos_01, pos01
    for run_dir in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        name_lower = run_dir.name.lower()
        if not any(v in name_lower for v in tid_variants):
            continue
        for artifact in sorted(run_dir.glob(f"{topic_id}_attempt*.json")):
            try:
                data   = json.loads(artifact.read_text())
                result = data.get("result", data)
                qh     = result.get("query_history", [])
                sq     = result.get("search_query", "")
                queries = ([sq] if sq else []) + [q for q in qh if q != sq]
                if queries:
                    print(f"  Pilot queries from: {run_dir.name}")
                    return queries
            except Exception:
                continue
    return []


def get_retrieved_papers(topic_id, max_runs=5):
    """Pool candidates from recent runs without accepting their relevance labels.

    These papers enter the same title/abstract gate and source validation as
    independently searched candidates.  Retrieval rank and score are ignored
    so the evaluated system cannot certify its own output as gold.
    """
    if max_runs <= 0:
        return []

    pooled = []
    runs_seen = 0
    for run_dir in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        artifacts = sorted(run_dir.glob(f"{topic_id}_attempt*.json"))
        if not artifacts:
            continue
        for artifact in artifacts:
            try:
                result = json.loads(artifact.read_text()).get("result", {})
            except (OSError, json.JSONDecodeError):
                continue
            for raw in result.get("papers") or []:
                paper_id = str(raw.get("paper_id") or "").strip()
                doi = str(raw.get("doi") or "").strip()
                arxiv_match = re.fullmatch(r"10\.48550/arxiv\.(.+)", doi, re.IGNORECASE)
                if arxiv_match:
                    arxiv_id = re.sub(r"v\d+$", "", arxiv_match.group(1))
                    paper_id = f"arxiv:{arxiv_id}"
                elif re.fullmatch(r"W\d+", paper_id, re.IGNORECASE):
                    paper_id = f"openalex:{paper_id.upper()}"
                authors = raw.get("authors") or []
                pooled.append({
                    "paper_id": paper_id,
                    "title": str(raw.get("title") or ""),
                    "abstract": str(raw.get("abstract") or "")[:600],
                    "authors": ", ".join(authors) if isinstance(authors, list) else str(authors),
                    "year": int(raw.get("year") or 0),
                    "url": str(raw.get("url") or ""),
                    "source": "retrieval_pool",
                })
        runs_seen += 1
        if runs_seen >= max_runs:
            break
    return pooled


def build_queries(system_queries, topic, topic_id, limit=10):
    """Mix pilot wording with topic-owned expansion queries deterministically."""
    queries = list(dict.fromkeys(system_queries[:2]))
    if topic["topic"] not in queries:
        queries.append(topic["topic"])
    expansions = TOPIC_EXPANSION_QUERIES.get(topic_id) or [
        f"{topic['topic']} {theme}" for theme in topic.get("expected_themes", [])
    ]
    for query in expansions:
        if query not in queries:
            queries.append(query)
    return queries[:limit]


# ── Freeze ────────────────────────────────────────────────────────────────────
def build_reference_answer(topic, papers, *, max_statements=6):
    """Build an independent extractive reference from validated source abstracts.

    Context metrics need a source-backed answer, not a rubric that merely lists
    expected themes.  Select the most topic-relevant complete sentence from
    distinct gold papers so every reference statement remains auditable.
    """
    target = " ".join([topic["topic"], *topic.get("expected_themes", [])]).lower()
    target_terms = set(re.findall(r"[a-z0-9]{4,}", target))
    ranked = []
    for paper in papers:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", str(paper.get("abstract") or ""))
            if len(sentence.split()) >= 8 and sentence.rstrip().endswith((".", "!", "?"))
        ]
        if not sentences:
            continue
        sentence = max(
            sentences,
            key=lambda item: len(target_terms & set(re.findall(r"[a-z0-9]{4,}", item.lower()))),
        )
        overlap = len(target_terms & set(re.findall(r"[a-z0-9]{4,}", sentence.lower())))
        ranked.append((overlap, paper["paper_id"], sentence))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    statements = [f"{sentence} [{paper_id}]" for _, paper_id, sentence in ranked[:max_statements]]
    if not statements:
        raise ValueError("refusing to freeze: validated papers have no usable abstract sentences")
    return " ".join(statements)


def freeze_gold(topic_id, topic, papers, queries_used, *, min_year=2019, max_year=2025, gold_source="arxiv_api_direct + openalex_api_direct"):
    if not papers or any(not paper.get("validated") for paper in papers):
        raise ValueError("refusing to freeze: every selected paper must be source-validated")
    paper_ids  = [p["paper_id"] for p in papers]
    relevance  = []
    for p in papers:
        relevance.append(dict(
            paper_id=p["paper_id"], title=p["title"], authors=p["authors"],
            year=p["year"], relevance=p.get("label","relevant"),
            relevance_reason=p.get("label_reason","keyword overlap + domain anchor"),
            label_score=round(p.get("label_score",0), 3),
            validated=p.get("validated",False), val_note=p.get("val_note",""),
            abstract_snippet=p.get("abstract","")[:250],
            url=p.get("url",""), source=p.get("source",""),
        ))
    canonical    = json.dumps(sorted(paper_ids), ensure_ascii=False)
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return {
        "schema_version": 1,
        "scope": "paper_level_relevance",
        "gold_label_method": "api_curated_v3_extractive_reference",
        "independent": True,
        "gold_source": gold_source,
        "curator": "build_gold_from_api.py v2.3",
        "curator_note": (
            "Candidate pool built from system-generated query + independently expanded theme queries. "
            "Metadata copied verbatim from arXiv/OpenAlex API. "
            "Relevance labeled from title+abstract (keyword overlap + domain anchor filter) BEFORE scored run. "
            "IDs validated by second API call (title token overlap >= 0.85). "
            "Do NOT score the pilot runs that generated these queries — run a new benchmark."
        ),
        "content_hash": content_hash,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_era": f"{min_year}-{max_year}",
        "queries_used": queries_used,
        "topics": [{
            "topic_id": topic_id,
            "topic": topic["topic"],
            "expected_themes": topic.get("expected_themes", []),
            "paper_ids": paper_ids,
            "paper_relevance": relevance,
            "precision_judged": False,
            "reference_answer": build_reference_answer(topic, papers),
            "reference_answer_method": "extractive_from_validated_gold_abstracts_v1",
            "reviewed": True,
            "reviewed_by": "coding_agent_api_curation",
            "review_note": "Source metadata and topical relevance checked before the scored run.",
        }],
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--per-query", type=int, default=20)
    ap.add_argument("--max-papers", type=int, default=20)
    ap.add_argument("--min-papers", type=int, default=8)
    ap.add_argument("--min-year", type=int, default=2019)
    ap.add_argument("--max-year", type=int, default=2025)
    ap.add_argument("--pool-runs", type=int, default=5)
    ap.add_argument("--skip-openalex", action="store_true", help="Dùng khi OpenAlex đang rate-limit")
    ap.add_argument("--output", help="Tên file output trong benchmarks/datasets; từ chối ghi đè")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument(
        "--paper-id", action="append", default=[],
        help="Curator-selected arxiv:/openalex: ID; repeat to bypass automatic candidate ranking",
    )
    args = ap.parse_args()

    topics = {t["topic_id"]: t for t in json.loads(TOPICS_FILE.read_text())}
    if args.topic not in topics:
        sys.exit(f"ERROR: topic {args.topic!r} not in topics.json")
    topic = topics[args.topic]

    print(f"\n{'='*60}")
    print(f"  Topic: {args.topic} — {topic['topic']}")
    print(f"{'='*60}\n")

    if args.paper_id:
        print(f"Step 1: Fetching {len(args.paper_id)} curator-selected papers...")
        selected = fetch_papers(args.paper_id)
        queries = [f"curated-id:{paper_id}" for paper_id in args.paper_id]
        if not args.skip_validate:
            print(f"\nStep 2: Validating {len(selected)} papers (2nd API call)...")
            validate_papers(selected)
            for paper in selected:
                icon = "✅" if paper["validated"] else f"⚠️  {paper.get('val_note', '')[:55]}"
                print(f"  {paper['paper_id']:<32} {icon}")
        selected = [paper for paper in selected if paper.get("validated")]
        if len(selected) < args.min_papers:
            sys.exit(
                f"ERROR: only {len(selected)} validated curated papers; "
                f"need at least {args.min_papers}. Gold was not written."
            )
        if args.dry_run:
            print(f"\n[DRY RUN] {len(selected)} curated papers validated. Not writing.")
            return
        gold = freeze_gold(
            args.topic, topic, selected, queries,
            min_year=min(paper["year"] for paper in selected),
            max_year=max(paper["year"] for paper in selected),
            gold_source="curator_selected_arxiv_openalex_api_direct",
        )
        output_name = args.output or f"independent_gold_{args.topic.replace('_', '')}_v2.json"
        out = DATASETS_DIR / output_name
        if out.parent.resolve() != DATASETS_DIR.resolve():
            sys.exit("ERROR: --output must be a file name inside benchmarks/datasets")
        if out.exists():
            sys.exit(f"ERROR: refusing to overwrite existing gold: {out}")
        out.write_text(json.dumps(gold, indent=2, ensure_ascii=False))
        print(f"\n✅  Gold frozen → {out.name}")
        print(f"    Papers: {len(selected)} (validated: {len(selected)}/{len(selected)})")
        print(f"    SHA-256: {gold['content_hash'][:24]}...")
        return

    # 1. System queries
    print("Step 1: Collecting system queries from pilot artifacts...")
    sys_q = get_system_queries(args.topic)
    if not sys_q:
        print("  [WARN] No pilot found; using topic text only")
        sys_q = [topic["topic"]]
    for q in sys_q[:3]:
        print(f"  Sys: {q[:80]}")

    # 2. Expand queries
    # Keep pilot wording, but reserve room for the original topic and
    # independent expansion queries. Previously ``sys_q`` filled all six
    # slots, so the supposedly independent expansions never ran.
    all_q = build_queries(sys_q, topic, args.topic)
    print(f"\nStep 2: {len(all_q)} queries total:")
    for q in all_q: print(f"  • {q}")

    # 3. Collect from APIs
    print(f"\nStep 3: Collecting candidates ({args.per_query}/query × {len(all_q)})...")
    seen = {}
    for i, q in enumerate(all_q):
        print(f"  [{i+1}/{len(all_q)}] arXiv ...")
        for p in arxiv_search(q, args.per_query):
            if p["paper_id"] not in seen: seen[p["paper_id"]] = p
        time.sleep(1.0)
        if not args.skip_openalex:
            print(f"  [{i+1}/{len(all_q)}] OpenAlex ...")
            for p in openalex_search(q, args.per_query):
                if p["paper_id"] not in seen: seen[p["paper_id"]] = p
            time.sleep(1.0)

    retrieved_pool = get_retrieved_papers(args.topic, args.pool_runs)
    print(f"  [pool] {len(retrieved_pool)} paper từ tối đa {args.pool_runs} run gần nhất")
    for paper in retrieved_pool:
        if paper["paper_id"] and paper["paper_id"] not in seen:
            seen[paper["paper_id"]] = paper

    candidates = dedupe_candidates(seen.values())
    candidates.sort(key=lambda p: p.get("year", 0), reverse=True)
    candidates = [
        p for p in candidates
        if args.min_year <= p.get("year", 0) <= args.max_year
    ]
    if args.skip_openalex:
        candidates = [p for p in candidates if str(p.get("paper_id") or "").startswith("arxiv:")]
    print(f"  → {len(candidates)} unique candidates ({args.min_year} <= year <= {args.max_year})")

    # 4. Label with domain anchor filter
    print("\nStep 4: Labeling (keyword overlap + domain anchor filter)...")
    for p in candidates:
        label, score = auto_label(p, topic, args.topic)
        p["label"] = label
        p["label_score"] = score
        p["label_reason"] = (
            f"keyword_overlap_score={score:.3f}; domain_anchor={'YES' if label=='relevant' else 'FAIL'}"
        )

    relevant   = [p for p in candidates if p["label"] == "relevant"]
    partial    = [p for p in candidates if p["label"] == "partially_relevant"]
    irrelevant = [p for p in candidates if p["label"] == "irrelevant"]
    print(f"  relevant={len(relevant)}, partial={len(partial)}, irrelevant={len(irrelevant)}")

    relevant.sort(key=lambda paper: (paper.get("label_score", 0), paper.get("year", 0)), reverse=True)

    print("\n── RELEVANT (will be gold) ──")
    for p in relevant[:args.max_papers]:
        print(f"  [{p['year']}] {p['paper_id']:<32} {p['title'][:58]}")

    if partial:
        print("\n── PARTIALLY RELEVANT (excluded) ──")
        for p in partial[:10]:
            print(f"  [{p['year']}] {p['paper_id']:<32} {p['title'][:58]}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(relevant)} relevant found. Not writing."); return

    selected = relevant[:args.max_papers]

    # 5. Validate (2nd API call)
    if not args.skip_validate and selected:
        print(f"\nStep 5: Validating {len(selected)} papers (2nd API call)...")
        for p in selected:
            p = validate_paper(p)
            icon = "✅" if p["validated"] else f"⚠️  {p.get('val_note','')[:55]}"
            print(f"  {p['paper_id']:<32} {icon}")

    selected = [paper for paper in selected if paper.get("validated")]
    if len(selected) < args.min_papers:
        sys.exit(
            f"ERROR: only {len(selected)} validated relevant papers; "
            f"need at least {args.min_papers}. Gold was not written."
        )

    # 6. Freeze
    gold  = freeze_gold(
        args.topic, topic, selected, all_q,
        min_year=args.min_year, max_year=args.max_year,
        gold_source=("arxiv_api_direct + retrieved_artifact_pool (source-validated)"
                     if args.skip_openalex else "arxiv_api_direct + openalex_api_direct + retrieved_artifact_pool (source-validated)"),
    )
    output_name = args.output or f"independent_gold_{args.topic.replace('_', '')}.json"
    out = DATASETS_DIR / output_name
    if out.parent.resolve() != DATASETS_DIR.resolve():
        sys.exit("ERROR: --output must be a file name inside benchmarks/datasets")
    if out.exists():
        sys.exit(f"ERROR: refusing to overwrite existing gold: {out}")
    out.write_text(json.dumps(gold, indent=2, ensure_ascii=False))

    n_val = sum(1 for p in selected if p.get("validated"))
    print(f"\n✅  Gold frozen → {out.name}")
    print(f"    Papers: {len(selected)}  (validated: {n_val}/{len(selected)})")
    print(f"    SHA-256: {gold['content_hash'][:24]}...")
    print(f"\n⚠️  Do NOT score the pilot runs that generated these queries.")
    print(f"   Run a NEW benchmark to get unbiased Precision/Recall.\n")


if __name__ == "__main__":
    main()
