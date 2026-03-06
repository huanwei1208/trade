import pytest
from trade_py.cli import data, model, report, account


@pytest.mark.parametrize("mod,name", [
    (data, "data"), (model, "model"), (report, "report"), (account, "account"),
])
def test_make_parser_contract(mod, name):
    assert hasattr(mod, "make_parser"), f"trade_py/cli/{name}.py missing make_parser()"
    p = mod.make_parser()
    assert p.description,  f"{name}.make_parser() has empty description"
    assert p.epilog,        f"{name}.make_parser() has empty epilog"
