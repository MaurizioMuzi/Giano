# processes/firma_ruoli/step_operazioni_iniziali.py
from datetime import date
from core.batch_logger import BatchLogger
from processes.firma_ruoli.context import FirmaRuoliContext, Ar


class OperazioniInizialiStep:
    """Paragrafo: TEST-PILOTA (ADCAVV11)."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FirmaRuoliContext) -> None:
        BatchLogger.info("OPERAZIONI-INIZIALI-FIRMA", "Inizializzazione delle aree utilizzate dal programma", depth=0)

        ctx.data_sql_com = date.today().strftime("%Y%m%d")

        #INITIALIZE WS-CDCAR01
        ctx.ar = Ar()

        # AR-INPUT
        ctx.ar.cdas = "FR"
        ctx.ar.csed = "00"
        ctx.ar.czon = "00"
        ctx.ar.ccop = "00"
        ctx.ar.csed = "00"
        ctx.ar.cdip = "DCSIT"
        ctx.ar.cambapp = "3"
        ctx.ar.rtrnims = "BATCH   "
        ctx.ar.cunilgc = "PDCFRPROVA"
        ctx.ar.cpgmges = "JCLPROVA"

        ctx.ar.nlnginp = 0
        ctx.ar.ntottab = 1

        # AR-OUTPUT
        ctx.ar.frcrdas = "0"  # SET FRCRDAS-TUTTO-OK TO TRUE
        ctx.ar.ntab = ""
        ctx.ar.cmsg= ""
        ctx.ar.htmslog = ""
        ctx.ar.nlngout = 0

        # AR-SERVIZIO
        ctx.ar.fsgndbg = '0'

        ctx.ar.nlnginp = Ar.LENGTH