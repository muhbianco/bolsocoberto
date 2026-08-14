from __future__ import annotations

import pytest

from app.models.job import EditorJob, EditorJobSource, FetchStatus, JobStatus
from app.services.llm import _EXTRACT_PROMPT, _VERIFY_PROMPT, _WRITE_PROMPT


@pytest.mark.parametrize(
    ("prompt", "placeholders"),
    [
        (_EXTRACT_PROMPT, ["FACTS_PLACEHOLDER"]),
        (
            _WRITE_PROMPT,
            [
                "OUTLINE_PLACEHOLDER",
                "TOPIC_PLACEHOLDER",
                "ANGLE_PLACEHOLDER",
                "MACRO_PLACEHOLDER",
                "LEDGER_PLACEHOLDER",
            ],
        ),
        (_VERIFY_PROMPT, ["LEDGER_PLACEHOLDER", "MACRO_PLACEHOLDER", "DRAFT_PLACEHOLDER"]),
    ],
)
def test_prompts_use_placeholders_not_str_format(prompt: str, placeholders: list[str]) -> None:
    for token in placeholders:
        assert token in prompt
    assert "{angle}" not in prompt
    assert "{facts}" not in prompt


def test_write_prompt_forbids_model_written_sources() -> None:
    # A seção de fontes é montada em código para garantir a política de link.
    assert "Não escreva a seção de fontes" in _WRITE_PROMPT


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
