from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MESI_SENZA_VALANGHE_DEFAULT = frozenset({6, 7, 8, 9})


@dataclass(frozen=True)
class DecisioneValanghe:
    includi: bool
    motivo: str


def rilevanza_valanghe(*, giorno: date, includi_valanghe: bool | None) -> DecisioneValanghe:
    if includi_valanghe is True:
        return DecisioneValanghe(True, "forzato")
    if includi_valanghe is False:
        return DecisioneValanghe(False, "escluso")
    if giorno.month in MESI_SENZA_VALANGHE_DEFAULT:
        return DecisioneValanghe(False, "stagione")
    return DecisioneValanghe(True, "auto_stagione")
