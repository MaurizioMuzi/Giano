# processes/formazione_avviso/step_operazioni_finali.py
from datetime import datetime
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class OperazioniFinaliStep:
    """
    Reingegnerizzazione del paragrafo OPERAZIONI-FINALI THRU OPERAZIONI-FINALI-EX:
    Aggiorna la tabella pilota ADCFRT18 per la colonna FSTFOR = '3' (TERMINATO/FASE SUCCESSIVA).
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneAvvisoContext, depth: int = 1) -> None:
        BatchLogger.info("OPERAZIONI-FINALI", "Elaborazione finale del flusso", depth=depth)

        try:
            righe_modificate = self._db_update_pilota_t18(ctx, depth=depth)
            BatchLogger.info(
                "UPD-STATO-T18",
                f"Aggiornamento per fase successiva di Postalizzazione -> Record impattati: {righe_modificate}",
                depth=depth,
                is_last=True
            )
            BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "OPERAZIONI-FINALI",
                f"Errore durante l'aggiornamento pilota finale su ADCFRT18 (DCON={ctx.dcon}, DINIINF={ctx.diniinf}): {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("OPERAZIONI-FINALI", "Rollback transazionale eseguito a fronte del fallimento finale", depth=depth)
                except Exception as rollback_err:
                    BatchLogger.error("OPERAZIONI-FINALI", f"Fallito il rollback: {rollback_err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_update_pilota_t18(self, ctx: FormazioneAvvisoContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato finale pilota su ADCFRT18."""
        try:
            upd = (
                self.engine.dataset("ADCFRT18")
                .filter_by("dcon", "=", ctx.dcon)
                .filter_by("diniinf", "=", ctx.diniinf)
                .compile_update({
                    "fstfor": "3",
                    "tmsfin": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-T18-ERR",
                f"Errore DB durante l'UPDATE pilota ADCFRT18 [DCON={ctx.dcon}, DINIINF={ctx.diniinf}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1