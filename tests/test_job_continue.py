from __future__ import annotations

from app.models.job import EditorJob, EditorJobSource, FetchStatus, JobStatus
from app.services.llm import _PROMPT


def test_prompt_uses_placeholders_not_str_format() -> None:
    assert "ANGLE_PLACEHOLDER" in _PROMPT
    assert "FACTS_PLACEHOLDER" in _PROMPT
    assert "{angle}" not in _PROMPT
    assert "{facts}" not in _PROMPT
    assert "{url" not in _PROMPT


def test_usable_source_count_ignores_failed() -> None:
    job = EditorJob(
        status=JobStatus.FAILED,
        source_urls=["https://a.example/x", "https://b.example/y"],
        created_by_email="editor@example.com",
    )
    job.sources = [
        EditorJobSource(
            url="https://a.example/x",
            fetch_status=FetchStatus.FAILED,
            extracted_text=None,
            error_message="HTTP 403",
        ),
        EditorJobSource(
            url="https://b.example/y",
            fetch_status=FetchStatus.OK,
            extracted_text="texto extraido da pauta com tamanho suficiente",
        ),
    ]
    assert job.usable_source_count() == 1
