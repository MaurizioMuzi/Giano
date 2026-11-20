# processes/firma_ruoli/step_operazioni_finali.py
from core.batch_logger import BatchLogger
from firma_ruoli.context import FirmaRuoliContext


class OperazioniFinaliStep:
    """Paragrafo: TEST-PILOTA (ADCAVV11)."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FirmaRuoliContext) -> None:
        BatchLogger.info("OPERAZIONI-FINALI-FIRMA-RUOLI", "FINE PROGRAMMA PDCFRPRO", depth=0)