from pathlib import Path

import pytest

from app.core.fixtures import load_fixture
from app.jupiter.schemas import JupiterQuoteResponse, JupiterSwapResponse


def test_quote_schema_parses_fixture():
    payload = load_fixture(Path("tests/fixtures/jupiter"), "quote_ok.json")
    quote = JupiterQuoteResponse.model_validate(payload)
    assert quote.input_mint
    assert quote.output_mint
    assert int(quote.in_amount) > 0
    assert int(quote.out_amount) > 0
    assert quote.route_plan


def test_swap_schema_parses_fixture():
    payload = load_fixture(Path("tests/fixtures/jupiter"), "swap_ok.json")
    swap = JupiterSwapResponse.model_validate(payload)
    assert swap.swap_transaction
    assert swap.last_valid_block_height == 987654


def test_quote_schema_rejects_missing_fields():
    with pytest.raises(Exception):
        JupiterQuoteResponse.model_validate({"inputMint": "AAA"})
