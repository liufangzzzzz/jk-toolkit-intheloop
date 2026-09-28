from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_compose_forwards_every_documented_environment_variable():
    """A value in server .env is useless unless Compose passes it to a service."""
    example = (ROOT / '.env.example').read_text(encoding='utf-8')
    compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
    documented = set(re.findall(r'^([A-Z][A-Z0-9_]+)=', example, re.MULTILINE))
    forwarded = set(re.findall(r'^\s{6}([A-Z][A-Z0-9_]+):', compose, re.MULTILINE))
    assert documented <= forwarded, (
        'compose.yaml 没有传入这些 .env 变量：'
        + '、'.join(sorted(documented - forwarded))
    )
