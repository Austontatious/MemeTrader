import pytest

from app.main import _build_parser


def test_invalid_chain_intel_choice() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mock-e2e", "--chain-intel", "mockk"])
