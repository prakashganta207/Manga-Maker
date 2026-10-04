"""Shared test setup: everything runs in MOCK mode, outputs go to a temp folder."""

import os

# Set before app.config is imported, so a developer's real .env can't leak into tests.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402

SAMPLE_STORY = (
    'Mira climbed the stairs to the school rooftop. The wind tugged at her scarf. '
    'Below, the city lights flickered on one by one. '
    'Kaito was already there, leaning on the fence. "You came," Kaito said quietly. '
    '"I promised," Mira answered with a small smile. '
    'Suddenly a strange glow rose from the river. They ran to the edge and stared. '
    '"What is that?" Mira whispered.'
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings.from_env()
    s.llm_provider = "mock"
    s.image_provider = "mock"
    s.output_dir = tmp_path / "output"
    s.image_base_size = 512  # small mock images keep the tests fast
    return s


@pytest.fixture
def story() -> str:
    return SAMPLE_STORY
