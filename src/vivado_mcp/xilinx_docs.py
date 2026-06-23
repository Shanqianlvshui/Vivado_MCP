from __future__ import annotations

import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .official_docs import OFFICIAL_REFERENCES, OfficialReference, local_docs_root

KHUB_SEARCH_URL = "https://docs.amd.com/api/khub/documents/search"
KHUB_MAPS_URL = "https://docs.amd.com/api/khub/maps"
KHUB_DOCUMENTS_URL = "https://docs.amd.com/api/khub/documents"
AMD_GO_PREFIX = "https://docs.amd.com/go/en-US/"
USER_AGENT = "vivado-mcp-xilinx-doc-downloader"


@dataclass(frozen=True)
class PdfCandidate:
    content_url: str
    filename: str
    doc_id: str | None = None
    title: str | None = None
    version: str | None = None
    release_date: str | None = None
    viewer_url: str | None = None
    source: str | None = None


def search_xilinx_docs(query: str, limit: int = 10, timeout_seconds: int = 30) -> dict[str, object]:
    """Search AMD KHub for Xilinx/AMD documents without downloading content."""
    results = _khub_search(query=query, limit=limit, timeout_seconds=timeout_seconds)
    return {"ok": True, "query": query, "results": [_search_result_to_dict(item) for item in results]}


def download_xilinx_pdf(
    source: str,
    output_name: str | None = None,
    out_dir: str | None = None,
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Download a real AMD/Xilinx PDF through KHub APIs and verify the %PDF signature."""
    target_dir = Path(out_dir or local_docs_root())
    target_dir.mkdir(parents=True, exist_ok=True)

    candidate = _resolve_pdf_candidate(source, timeout_seconds=timeout_seconds)
    filename = _safe_pdf_filename(output_name or candidate.filename)
    target = target_dir / filename

    if target.exists() and not overwrite:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already exists",
            "path": str(target),
            "bytes": target.stat().st_size,
            "candidate": _candidate_to_dict(candidate),
        }

    content = _download_bytes(candidate.content_url, timeout_seconds=timeout_seconds)
    if content[:4] != b"%PDF":
        raise ValueError(f"downloaded content is not a PDF for {source!r}; first bytes: {content[:16]!r}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".part", dir=str(target_dir)) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)
    temp_path.replace(target)
    return {
        "ok": True,
        "skipped": False,
        "path": str(target),
        "bytes": target.stat().st_size,
        "candidate": _candidate_to_dict(candidate),
    }


def sync_official_docs(
    doc_ids: list[str] | None = None,
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Download all or selected packaged Vivado official references into the docs root."""
    selected = _select_official_references(doc_ids)
    downloaded = []
    failed = []
    for reference in selected:
        output_name = reference.local_filenames[0] if reference.local_filenames else f"{reference.doc_id.lower()}.pdf"
        try:
            result = download_xilinx_pdf(
                _go_url_for_reference(reference),
                output_name=output_name,
                out_dir=local_docs_root(),
                overwrite=overwrite,
                timeout_seconds=timeout_seconds,
            )
        except Exception as first_error:
            try:
                result = download_xilinx_pdf(
                    f"{reference.doc_id} {reference.title}",
                    output_name=output_name,
                    out_dir=local_docs_root(),
                    overwrite=overwrite,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as second_error:
                failed.append(
                    {
                        "doc_id": reference.doc_id,
                        "source": reference.url,
                        "error": str(second_error),
                        "fallback_from": str(first_error),
                    }
                )
                continue
        row = dict(result)
        row["doc_id"] = reference.doc_id
        downloaded.append(row)

    return {
        "ok": not failed,
        "local_docs_root": local_docs_root(),
        "requested": [reference.doc_id for reference in selected],
        "downloaded": downloaded,
        "failed": failed,
    }


def clean_bad_pdfs(root: str | None = None, delete_bad: bool = False) -> dict[str, object]:
    """Find PDFs that do not start with %PDF, optionally deleting only those bad files."""
    docs_root = Path(root or local_docs_root())
    bad = []
    for path in docs_root.rglob("*.pdf"):
        try:
            sig = path.read_bytes()[:4]
        except OSError as exc:
            bad.append({"path": str(path), "error": str(exc), "deleted": False})
            continue
        if sig == b"%PDF":
            continue
        deleted = False
        if delete_bad:
            path.unlink()
            deleted = True
        bad.append({"path": str(path), "first_bytes": repr(sig), "deleted": deleted})
    return {"ok": True, "root": str(docs_root), "bad": bad, "bad_count": len(bad)}


def _select_official_references(doc_ids: list[str] | None) -> list[OfficialReference]:
    if not doc_ids:
        return list(OFFICIAL_REFERENCES)
    requested = {doc_id.strip().upper() for doc_id in doc_ids}
    selected = [reference for reference in OFFICIAL_REFERENCES if reference.doc_id in requested]
    missing = sorted(requested - {reference.doc_id for reference in selected})
    if missing:
        raise KeyError(f"unknown official document IDs: {', '.join(missing)}")
    return selected


def _go_url_for_reference(reference: OfficialReference) -> str:
    slug = reference.url.rstrip("/").split("/")[-1]
    return f"{AMD_GO_PREFIX}{slug}"


def _resolve_pdf_candidate(source: str, timeout_seconds: int) -> PdfCandidate:
    normalized = source.strip()
    if not normalized:
        raise ValueError("source must not be empty")

    if normalized.startswith("http://") or normalized.startswith("https://"):
        candidate = _candidate_from_url(normalized, timeout_seconds=timeout_seconds)
        if candidate is not None:
            return candidate
        query = _query_from_url(normalized)
        return _best_pdf_from_search(query, timeout_seconds=timeout_seconds)

    if _looks_like_slug(normalized):
        candidate = _candidate_from_url(f"{AMD_GO_PREFIX}{normalized}", timeout_seconds=timeout_seconds)
        if candidate is not None:
            return candidate

    return _best_pdf_from_search(normalized, timeout_seconds=timeout_seconds)


def _candidate_from_url(url: str, timeout_seconds: int) -> PdfCandidate | None:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if "/api/khub/" in path and path.endswith("/content"):
        return PdfCandidate(content_url=url, filename=_filename_from_url(url), viewer_url=url, source=url)

    if parsed.netloc.endswith("docs.amd.com") and path.startswith("/r/en-US/"):
        slug = path.rsplit("/", 1)[-1]
        return _candidate_from_url(f"{AMD_GO_PREFIX}{slug}", timeout_seconds=timeout_seconds)

    if parsed.netloc.endswith("docs.amd.com") and path.startswith("/go/en-US/"):
        final_url = _resolve_redirect_url(url, timeout_seconds=timeout_seconds)
        return _candidate_from_url(final_url, timeout_seconds=timeout_seconds)

    map_id = _map_id_from_root_url(url)
    if map_id:
        return _candidate_from_map(map_id, source=url, timeout_seconds=timeout_seconds)

    if parsed.netloc.endswith("docs.amd.com") and path.startswith("/v/u/"):
        query = _query_from_url(url)
        return _best_pdf_from_search(query, timeout_seconds=timeout_seconds)

    return None


def _resolve_redirect_url(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:
        return response.geturl()


def _map_id_from_root_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    match = re.match(r"^/r/([^/]+)/root$", parsed.path)
    if match:
        return match.group(1)
    return None


def _candidate_from_map(map_id: str, source: str, timeout_seconds: int) -> PdfCandidate:
    url = f"{KHUB_MAPS_URL}/{urllib.parse.quote(map_id, safe='')}/attachments"
    data = _get_json(url, timeout_seconds=timeout_seconds)
    attachments = data.get("value") if isinstance(data, dict) else data
    if not isinstance(attachments, list):
        raise ValueError(f"unexpected attachment response for map {map_id!r}")
    pdfs = [item for item in attachments if item.get("mimeType") == "application/pdf"]
    if not pdfs:
        raise ValueError(f"no PDF attachment found for AMD map {map_id!r}")
    attachment = sorted(pdfs, key=lambda item: int(item.get("size") or 0), reverse=True)[0]
    attachment_id = attachment["id"]
    return PdfCandidate(
        content_url=f"{KHUB_MAPS_URL}/{urllib.parse.quote(map_id, safe='')}/attachments/{urllib.parse.quote(attachment_id, safe='')}/content",
        filename=attachment.get("file") or f"{map_id}.pdf",
        title=attachment.get("name"),
        viewer_url=urllib.parse.urljoin("https://docs.amd.com", attachment.get("viewerUrl") or ""),
        source=source,
    )


def _best_pdf_from_search(query: str, timeout_seconds: int) -> PdfCandidate:
    results = _khub_search(query=query, limit=20, timeout_seconds=timeout_seconds)
    pdfs = [item for item in results if item.get("mimeType") == "application/pdf"]
    if not pdfs:
        raise ValueError(f"no PDF result found in AMD KHub for {query!r}")
    pdfs.sort(key=lambda item: _release_sort_key(_metadata(item).get("Release_Date")), reverse=True)
    item = pdfs[0]
    metadata = _metadata(item)
    return PdfCandidate(
        content_url=item["contentUrl"],
        filename=item.get("filename") or f"{metadata.get('Document_ID', 'xilinx-doc').lower()}.pdf",
        doc_id=metadata.get("Document_ID"),
        title=item.get("title"),
        version=metadata.get("Doc_Version"),
        release_date=metadata.get("Release_Date"),
        viewer_url=item.get("viewerUrl"),
        source=query,
    )


def _khub_search(query: str, limit: int, timeout_seconds: int) -> list[dict[str, object]]:
    payload = {
        "query": query,
        "contentLocale": "en-US",
        "paging": {"page": 1, "perPage": max(1, limit)},
    }
    data = _post_json(KHUB_SEARCH_URL, payload, timeout_seconds=timeout_seconds)
    results = data.get("results", [])
    if not isinstance(results, list):
        return []
    return results


def _search_result_to_dict(item: dict[str, object]) -> dict[str, object]:
    metadata = _metadata(item)
    return {
        "doc_id": metadata.get("Document_ID"),
        "version": metadata.get("Doc_Version"),
        "release_date": metadata.get("Release_Date"),
        "mime_type": item.get("mimeType"),
        "filename": item.get("filename"),
        "title": item.get("title"),
        "viewer_url": item.get("viewerUrl"),
        "content_url": item.get("contentUrl"),
    }


def _metadata(item: dict[str, object]) -> dict[str, str]:
    rows = item.get("metadata") or []
    metadata = {}
    if not isinstance(rows, list):
        return metadata
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = row.get("values")
        if isinstance(values, list) and values:
            metadata[str(row.get("key"))] = str(values[0])
    return metadata


def _release_sort_key(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _post_json(url: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Ft-Calling-App": USER_AGENT, "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, timeout_seconds: int) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_bytes(url: str, timeout_seconds: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while downloading {url}") from exc


def _query_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    return urllib.parse.unquote(path.rsplit("/", 1)[-1]).replace(".pdf", "")


def _filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    filename = Path(urllib.parse.unquote(parsed.path)).name
    return filename if filename.lower().endswith(".pdf") else "xilinx-doc.pdf"


def _looks_like_slug(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$", value)) and " " not in value


def _safe_pdf_filename(value: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(value).name.strip())
    if not filename:
        filename = "xilinx-doc.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    return filename


def _candidate_to_dict(candidate: PdfCandidate) -> dict[str, object]:
    return {
        "content_url": candidate.content_url,
        "filename": candidate.filename,
        "doc_id": candidate.doc_id,
        "title": candidate.title,
        "version": candidate.version,
        "release_date": candidate.release_date,
        "viewer_url": candidate.viewer_url,
        "source": candidate.source,
    }
