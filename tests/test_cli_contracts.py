import pytest
from trade_py.cli import (
    account,
    backup,
    daily,
    data,
    dev,
    evaluate,
    event,
    factor,
    inspect,
    kg,
    model,
    ops,
    run,
    start,
    status,
    web,
)


@pytest.mark.parametrize("mod,name", [
    (daily, "daily"),
    (ops, "ops"),
    (dev, "dev"),
    (run, "run"),
    (status, "status"),
    (inspect, "inspect"),
    (backup, "backup"),
    (data, "data"),
    (model, "model"),
    (factor, "factor"),
    (account, "account"),
    (event, "event"),
    (evaluate, "evaluate"),
    (kg, "kg"),
    (start, "start"),
    (web, "web"),
])
def test_make_parser_contract(mod, name):
    assert hasattr(mod, "make_parser"), f"trade_py/cli/{name}.py missing make_parser()"
    p = mod.make_parser()
    assert p.description,  f"{name}.make_parser() has empty description"


@pytest.mark.parametrize("mod,name", [
    (data, "data"),
    (model, "model"),
    (factor, "factor"),
    (account, "account"),
    (event, "event"),
    (evaluate, "evaluate"),
    (kg, "kg"),
    (run, "run"),
    (start, "start"),
    (web, "web"),
])
def test_make_parser_examples_for_primary_domains(mod, name):
    p = mod.make_parser()
    assert p.epilog, f"{name}.make_parser() has empty epilog"
