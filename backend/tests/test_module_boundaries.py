"""Keep product tabs independent while allowing shared infrastructure."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding='utf-8')


def test_audio_studio_does_not_import_other_product_modules():
    source = _source('backend/app/modules/audio_studio/routes.py')
    assert 'modules.atlas' not in source
    assert 'website_ingest' not in source
    assert 'wechat_draft' not in source
    assert 'agents.intheloop' not in source


def test_intheloop_catalogue_does_not_import_other_product_modules():
    source = _source('backend/app/modules/atlas/routes.py')
    assert 'audio_studio' not in source
    assert 'website_ingest' not in source
    assert 'wechat_draft' not in source


def test_audio_storage_is_initialized_without_atlas_catalogue_migrations():
    source = _source('backend/app/modules/audio_studio/store.py')
    assert 'from ..atlas' not in source
    assert 'audio_projects' in source
    assert 'audio_settings' in source
    assert 'unify_tags' not in source


def test_route_specific_styles_are_scoped_to_their_page():
    audio = _source('app/ops/audio/audio.css')
    studio = _source('app/ops/intheloop/studio.css')
    for selector in ('.connection-cards', '.source-box', '.output-pane', '.article-workspace'):
        assert f'.audio-studio {selector}' in audio
    for selector in ('.studio-nav', '.studio-layout', '.companion-row', '.tag-level-group'):
        assert f'.studio {selector}' in studio
