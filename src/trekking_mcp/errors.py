from __future__ import annotations


class ErroreSentieri(Exception):
    """Base di tutti gli errori previsti del server."""

    def messaggio_utente(self) -> str:
        return str(self)


class FonteNonDisponibile(ErroreSentieri):
    """La fonte remota non risponde o risponde male, dopo i retry."""

    def __init__(self, fonte: str, dettaglio: str) -> None:
        self.fonte = fonte
        self.dettaglio = dettaglio
        super().__init__(f"Fonte '{fonte}' non raggiungibile: {dettaglio}")

    def messaggio_utente(self) -> str:
        return (
            f"La fonte dati '{self.fonte}' non e' al momento raggiungibile ({self.dettaglio}). "
            "Puo' trattarsi di un rate limit temporaneo: conviene riprovare tra qualche minuto."
        )


class NonTrovato(ErroreSentieri):
    """Entita' inesistente. Include suggerimenti quando possibile."""

    def __init__(self, cosa: str, chiave: str, alternative: list[str] | None = None) -> None:
        self.cosa = cosa
        self.chiave = chiave
        self.alternative = alternative or []
        super().__init__(f"{cosa} '{chiave}' non trovato")

    def messaggio_utente(self) -> str:
        base = f"Nessun risultato per {self.cosa} '{self.chiave}'."
        if self.alternative:
            return base + " Valori validi: " + ", ".join(self.alternative)
        return base


class ParametriNonValidi(ErroreSentieri):
    """Combinazione di argomenti incoerente, oltre a quanto cattura lo schema."""
