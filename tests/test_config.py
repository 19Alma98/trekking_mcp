from __future__ import annotations

from dataclasses import replace

from trekking_mcp.config import Config
from trekking_mcp.constants import OVERPASS_MARGINE_TIMEOUT_S


def test_max_retry_zero_diventa_almeno_uno():
    assert replace(Config(), max_retry=0).max_retry == 1
    assert replace(Config(), max_retry=-3).max_retry == 1


def test_timeout_sotto_il_margine_overpass_viene_alzato():
    minimo = float(OVERPASS_MARGINE_TIMEOUT_S + 1)
    assert replace(Config(), timeout_s=1.0).timeout_s == minimo
    assert replace(Config(), timeout_s=0.0).timeout_s == minimo


def test_ttl_negativi_diventano_zero():
    cfg = replace(Config(), ttl_meteo_s=-10, ttl_nominatim_s=-1)
    assert cfg.ttl_meteo_s == 0
    assert cfg.ttl_nominatim_s == 0


def test_burst_almeno_uno_se_rate_limit_attivo():
    assert replace(Config(), http_rate_limit_rpm=30, http_rate_limit_burst=0).http_rate_limit_burst == 1


def test_burst_puo_essere_zero_se_rate_limit_disattivo():
    assert replace(Config(), http_rate_limit_rpm=0, http_rate_limit_burst=0).http_rate_limit_burst == 0
