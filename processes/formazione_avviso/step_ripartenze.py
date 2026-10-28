# processes/formazione_avviso/step_ripartenze.py
from datetime import datetime
from typing import List, Any
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class GestioneRipartenzeStep:
    """
    Reingegnerizzazione dei paragrafi:
      - GESTIONE-RIPARTENZE
      - CONTA-SEDI
      - CONTA-LAVORI
      - AGGIORNA-LAVORI
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("CHK-RIPARTENZE", "GESTIONE-RIPARTENZE (ADCTET17)", depth=0)

        try:
            # 1. CONTA-SEDI: Recupera il conteggio complessivo delle sedi su ADCTET17
            res_sedi = self._db_count_sedi(depth=1)
            ctx.count_sedi = int(list(res_sedi[0].values())[0]) if res_sedi else 0

            # 2. CONTA-LAVORI: Recupera il conteggio dei lavori qualificati (IF/AV)
            res_lavori = self._db_count_lavori(depth=1)
            ctx.count_lavori = int(list(res_lavori[0].values())[0]) if res_lavori else 0

            BatchLogger.info(
                "CONTA-LAV-T17",
                f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IF/AV): {ctx.count_lavori}",
                depth=1
            )

            # 3. AGGIORNA-LAVORI: Se tutti i lavori sono qualificati, esegue il reset massivo
            if ctx.count_lavori == ctx.count_sedi and ctx.count_sedi > 0:
                righe_aggiornate = self._db_update_reset_lavori(depth=1)
                BatchLogger.info(
                    "RESET-LAV-T17",
                    f"WS-COUNT = WS-COUNT-SED -> Reset massivo eseguito. Impattati: {righe_aggiornate}",
                    depth=1,
                    is_last=True
                )
            else:
                BatchLogger.info(
                    "CHECK-LAV-T17",
                    "WS-COUNT <> WS-COUNT-SED -> Nessun riallineamento massivo necessario",
                    depth=1,
                    is_last=True
                )

            BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "CHK-RIPARTENZE",
                f"Errore critico durante la gestione ripartenze su ADCTET17: {err}",
                depth=0
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("CHK-RIPARTENZE", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("CHK-RIPARTENZE", f"Fallito il rollback: {rollback_err}", depth=0)

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_count_sedi(self, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio totale record (sedi) in ADCTET17."""
        try:
            q_sedi = (
                self.engine.dataset("ADCTET17")
                .count()
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_sedi, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COUNT-SEDI-ERR", f"Errore DB durante conteggio totale record ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    def _db_count_lavori(self, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio record qualificati con codServizio in ('IF', 'AV') in ADCTET17."""
        try:
            q_lavori = (
                self.engine.dataset("ADCTET17")
                .count()
                .filter_by("codServizio", "IN", ("IF", "AV"))
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_lavori, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COUNT-LAVORI-ERR", f"Errore DB durante conteggio record qualificati ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    def _db_update_reset_lavori(self, depth: int) -> int:
        """Accesso atomico DB: reset massivo dei lavori su ADCTET17 impostando codServizio='AV'."""
        try:
            upd_reset = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "AV",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            return self.engine.execute_mutation(upd_reset, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-UPD-RESET-T17-ERR", f"Errore DB durante UPDATE di reset su ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1