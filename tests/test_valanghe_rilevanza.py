from datetime import date

from trekking_mcp.valanghe_rilevanza import rilevanza_valanghe


def test_estate_di_default_esclude():
    d = rilevanza_valanghe(giorno=date(2026, 7, 15), includi_valanghe=None)
    assert d.includi is False
    assert d.motivo == "stagione"


def test_inverno_di_default_include():
    d = rilevanza_valanghe(giorno=date(2026, 1, 10), includi_valanghe=None)
    assert d.includi is True
    assert d.motivo == "auto_stagione"


def test_override_true_in_estate():
    d = rilevanza_valanghe(giorno=date(2026, 8, 1), includi_valanghe=True)
    assert d.includi is True
    assert d.motivo == "forzato"


def test_override_false_in_inverno():
    d = rilevanza_valanghe(giorno=date(2026, 2, 1), includi_valanghe=False)
    assert d.includi is False
    assert d.motivo == "escluso"
