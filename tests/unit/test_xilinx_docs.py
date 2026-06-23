from __future__ import annotations

import vivado_mcp.xilinx_docs as xilinx_docs
from vivado_mcp.xilinx_docs import PdfCandidate, download_xilinx_pdf, search_xilinx_docs, sync_official_docs


def test_search_xilinx_docs_returns_khub_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        xilinx_docs,
        "_khub_search",
        lambda query, limit, timeout_seconds: [
            {
                "mimeType": "application/pdf",
                "filename": "ug835-vivado-tcl-commands.pdf",
                "title": "Vivado Tcl Commands",
                "viewerUrl": "https://docs.amd.com/v/u/example",
                "contentUrl": "https://docs.amd.com/api/khub/documents/example/content",
                "metadata": [
                    {"key": "Document_ID", "values": ["UG835"]},
                    {"key": "Doc_Version", "values": ["2025.2 English"]},
                    {"key": "Release_Date", "values": ["2025-11-20"]},
                ],
            }
        ],
    )

    result = search_xilinx_docs("UG835", limit=1)

    assert result["ok"] is True
    assert result["results"][0]["doc_id"] == "UG835"
    assert result["results"][0]["mime_type"] == "application/pdf"


def test_download_xilinx_pdf_writes_verified_pdf(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        xilinx_docs,
        "_resolve_pdf_candidate",
        lambda source, timeout_seconds: PdfCandidate(
            content_url="https://docs.amd.com/api/khub/documents/example/content",
            filename="ug835.pdf",
            doc_id="UG835",
            source=source,
        ),
    )
    monkeypatch.setattr(xilinx_docs, "_download_bytes", lambda url, timeout_seconds: b"%PDF fake content")

    result = download_xilinx_pdf("UG835", out_dir=str(tmp_path))

    assert result["ok"] is True
    assert result["skipped"] is False
    assert (tmp_path / "ug835.pdf").read_bytes().startswith(b"%PDF")


def test_sync_official_docs_uses_catalog_filename(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIVADO_MCP_DOCS_ROOT", str(tmp_path))
    calls = []

    def fake_download_xilinx_pdf(source, output_name, out_dir, overwrite, timeout_seconds):
        calls.append((source, output_name, out_dir, overwrite, timeout_seconds))
        target = tmp_path / output_name
        target.write_bytes(b"%PDF fake")
        return {"ok": True, "path": str(target), "bytes": target.stat().st_size, "skipped": False}

    monkeypatch.setattr(xilinx_docs, "download_xilinx_pdf", fake_download_xilinx_pdf)

    result = sync_official_docs(doc_ids=["UG835"], overwrite=True, timeout_seconds=5)

    assert result["ok"] is True
    assert result["downloaded"][0]["doc_id"] == "UG835"
    assert calls[0][1] == "ug835.pdf"
