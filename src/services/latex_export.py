"""Create editable LaTeX artifacts from a grounded literature-review report."""

from __future__ import annotations

from hashlib import sha1
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def _escape_latex(value: object) -> str:
    """Render untrusted report text as LaTeX text rather than LaTeX commands."""

    text = str(value or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text).replace("\n", "\n\n")


def _citation_key(reference: dict) -> str:
    paper_id = str(reference.get("paper_id") or reference.get("doi") or reference.get("title") or "source")
    author = next(iter(reference.get("authors") or []), "source")
    year = reference.get("year") or "nd"
    stem = "".join(char.lower() for char in str(author) if char.isalnum())[:18] or "source"
    return f"{stem}{year}{sha1(paper_id.encode()).hexdigest()[:6]}"


def _claim_citations(claim: dict, reference_keys: dict[str, str]) -> str:
    paper_ids = list(claim.get("supporting_paper_ids") or [])
    paper_ids.extend(item.get("paper_id") for item in claim.get("evidence", []) if item.get("paper_id"))
    keys = list(dict.fromkeys(reference_keys[paper_id] for paper_id in paper_ids if paper_id in reference_keys))
    return f" \\cite{{{','.join(keys)}}}" if keys else ""


def render_latex_bundle(report: dict) -> bytes:
    """Return a zip with an editable ``main.tex`` and ``references.bib``.

    The original report stays unchanged; the generated files are a portable
    derivative artifact.  Only grounded claims are included in the narrative.
    """

    references = list(report.get("references") or [])
    reference_keys = {str(reference.get("paper_id")): _citation_key(reference) for reference in references}
    claims = {
        str(claim.get("claim_id")): claim
        for claim in report.get("claims", [])
        if claim.get("validation_status") == "valid"
    }

    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{hyperref}",
        r"\usepackage{url}",
        r"\title{" + _escape_latex(report.get("topic") or report.get("original_topic") or "Literature Review") + "}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\section{Research question}",
        _escape_latex(report.get("original_topic") or report.get("topic")),
    ]

    keywords = [str(keyword).strip() for keyword in report.get("keywords", []) if str(keyword).strip()]
    sub_queries = [str(query).strip() for query in report.get("sub_queries", []) if str(query).strip()]
    if keywords or sub_queries:
        lines.append(r"\section{Approved keyword and query plan}")
    if keywords:
        lines.extend([r"\subsection*{Keywords}", r"\begin{itemize}"])
        lines.extend(f"  \\item {_escape_latex(keyword)}" for keyword in keywords)
        lines.append(r"\end{itemize}")
    if sub_queries:
        lines.extend([r"\subsection*{Search queries}", r"\begin{itemize}"])
        lines.extend(f"  \\item {_escape_latex(query)}" for query in sub_queries)
        lines.append(r"\end{itemize}")

    themes = list(report.get("themes") or [])
    lines.append(r"\section{Literature review}")
    if themes:
        for theme in themes:
            summary = claims.get(str(theme.get("summary_claim_id")))
            lines.append(r"\subsection{" + _escape_latex(theme.get("title") or "Theme") + "}")
            if summary:
                lines.append(_escape_latex(summary.get("text")) + _claim_citations(summary, reference_keys))
    else:
        for claim in claims.values():
            lines.append(_escape_latex(claim.get("text")) + _claim_citations(claim, reference_keys))

    gaps = list(report.get("potential_gaps") or [])
    if gaps:
        lines.extend([r"\section{Potential research gaps}", r"\begin{itemize}"])
        for gap in gaps:
            metadata = ", ".join(
                str(value)
                for value in (gap.get("gap_type"), gap.get("confidence"), gap.get("verification_status"))
                if value
            )
            item = f"  \\item \\textbf{{{_escape_latex(gap.get('aspect') or 'Gap')}}}: " + _escape_latex(
                gap.get("scope_statement") or ""
            )
            if metadata:
                item += " (" + _escape_latex(metadata) + ")"
            lines.append(item)
            if gap.get("counter_search_query"):
                lines.append("  \\item[] \\emph{Counter-search query:} " + _escape_latex(gap["counter_search_query"]))
        lines.append(r"\end{itemize}")

    disclaimer = report.get("scope_disclaimer")
    if disclaimer:
        lines.extend([r"\section{Scope note}", _escape_latex(disclaimer)])
    lines.extend([r"\bibliographystyle{plain}", r"\bibliography{references}", r"\end{document}", ""])

    bib_entries = []
    for reference in references:
        key = reference_keys[str(reference.get("paper_id"))]
        authors = " and ".join(_escape_latex(author) for author in reference.get("authors", []) if author) or "Unknown"
        fields = [
            f"  title = {{{_escape_latex(reference.get('title') or 'Untitled')}}}",
            f"  author = {{{authors}}}",
        ]
        if reference.get("year"):
            fields.append(f"  year = {{{_escape_latex(reference['year'])}}}")
        if reference.get("doi"):
            fields.append(f"  doi = {{{_escape_latex(reference['doi'])}}}")
        if reference.get("url"):
            fields.append(f"  url = {{{_escape_latex(reference['url'])}}}")
        bib_entries.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}\n")

    readme = (
        "# LitReview LaTeX export\n\n"
        "`main.tex` is an editable export of the grounded report. Compile it with a LaTeX engine and BibTeX/Biber. "
        "Edit this artifact freely; changes do not alter the source report, evidence, or review audit trail.\n"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("main.tex", "\n".join(lines))
        archive.writestr("references.bib", "\n".join(bib_entries))
        archive.writestr("README.md", readme)
    return buffer.getvalue()
