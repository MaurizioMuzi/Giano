# processes/formazione_avviso/step_operazioni_finali.py
from datetime import datetime
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class OperazioniFinaliStep:
    """
    Reingegnerizzazione del paragrafo OPERAZIONI-FINALI THRU OPERAZIONI-FINALI-EX:
    Aggiorna la tabella pilota ADCFRT18 per la colonna FSTFOR = '2' (TERMINATO).
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneAvvisoContext, depth: int = 1) -> None:
        BatchLogger.info("OPERAZIONI-FINALI", "Elaborazione finale del flusso", depth=depth)

        upd = (
            self.engine.dataset("ADCFRT18")
            .filter_by("dcon", "=", ctx.dcon)
            .filter_by("diniinf", "=", ctx.diniinf)
            .compile_update({
                "fstfor": "2",
                "tmsfin": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(upd, depth=depth)
        BatchLogger.info("UPD-STATO-T18", f"UPDATE ADCFRT18 SET FSTFOR='2' -> Record impattati: {righe_modificate}", depth=depth, is_last=True)
        BatchLogger.separator(depth=0)