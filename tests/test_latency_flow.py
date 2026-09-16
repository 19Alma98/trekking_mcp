from __future__ import annotations

from trekking_mcp.models import Coord, Sentiero
from trekking_mcp.tools import sentieri as tool_sentieri


def _sentiero(osm_id: int, ref: str | None, lat: float, lon: float) -> Sentiero:
    return Sentiero(
        osm_relation_id=osm_id,
        ref=ref,
        centro=Coord(lat=lat, lon=lon),
        osm_url=f"https://www.openstreetmap.org/relation/{osm_id}",
    )


def test_ordina_sentieri_per_distanza_tiene_i_piu_vicini():
    # Punto query: Biella ~45.57, 8.05
    lontani_prima_per_ref = [
        _sentiero(1, "Z99", 46.0, 8.5),   # lontano
        _sentiero(2, "A01", 45.58, 8.06),  # vicino
        _sentiero(3, None, 45.575, 8.055), # vicinissimo, senza ref
    ]
    esito = tool_sentieri.ordina_sentieri_per_distanza(
        lontani_prima_per_ref, lat=45.57, lon=8.05, limite=2
    )
    assert [s.osm_relation_id for s in esito] == [3, 2]
    assert esito[0].distanza_km is not None
    assert esito[0].distanza_km <= esito[1].distanza_km
    # arrotondato a 0.1 km
    assert esito[0].distanza_km == round(esito[0].distanza_km, 1)
