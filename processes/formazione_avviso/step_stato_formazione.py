# processes/formazione_avviso/step_stato_formazione.py
from datetime import date, datetime
from typing import List, Any
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class StatoFormazioneStep:
    """Paragrafi: CNTR-STATO-FORMAZIONE e UPD-STATO-INI-FORM (ADCFRT18)."""

    def __init__(self, engine):
        self.engine = engine


    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        try:
            # 1. CNTR-STATO-FORMAZIONE: Recupero della finestra operativa pilota su ADCFRT18
            rows = self._db_fetch_finestra_t18(current_system_date, fixed_dfinfor_date, depth=1)
            if not rows:
                BatchLogger.error(
                    "INI-STATO-FOR",
                    "Nessun record valido in ADCFRT18. Formazione non consentita.",
                    depth=1,
                    is_last=True
                )
                raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE NON CONSENTITA: Nessun record valido.")

            row = t18_map.normalize(rows[0])
            ctx.dcon = row.get("dcon")
            ctx.diniinf = row.get("diniinf")
            ctx.dfininf = row.get("dfininf")
            ctx.dinifor = row.get("dinifor")
            ctx.dfinfor = row.get("dfinfor")
            ctx.fstfor = row.get("fstfor")

            BatchLogger.info(
                "REC-FINESTRA",
                f"DCON={ctx.dcon} | Finestra Infasamento: {ctx.diniinf} -> {ctx.dfininf} | Stato={ctx.fstfor}",
                depth=1
            )

            # 2. UPD-STATO-INI-FORM: Imposta lo stato a '1' (IN CORSO) e memorizza il timestamp di avvio
            righe_modificate = self._db_update_inizio_formazione_t18(ctx, depth=1)
            BatchLogger.info(
                "UPD-STATO-T18",
                f"UPDATE ADCFRT18 SET FSTFOR='1' -> Record impattati: {righe_modificate}",
                depth=1,
                is_last=True
            )
            BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "INI-STATO-FOR",
                f"Errore critico durante la gestione dello stato formazione su ADCFRT18: {err}",
                depth=0
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("INI-STATO-FOR", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("INI-STATO-FOR", f"Fallito il rollback: {rollback_err}", depth=0)

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_finestra_t18(self, current_date: date, fixed_date: date, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera il record della finestra attiva da ADCFRT18."""
        try:
            query = (
                self.engine.dataset("ADCFRT18")
                .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
                .filter_by("dinifor", "<=", current_date)
                .filter_by("dfinfor", ">=", fixed_date)
                .filter_by("fstfor", "<>", "2")
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-T18-ERR",
                f"Errore DB durante la SELECT su ADCFRT18 [CURR_DATE={current_date}, FIXED_DATE={fixed_date}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_update_inizio_formazione_t18(self, ctx: FormazioneAvvisoContext, depth: int) -> int:
        """Accesso atomico DB: aggiorna fstfor='1' e valorizza tmsini su ADCFRT18."""
        try:
            upd = (
                self.engine.dataset("ADCFRT18")
                .filter_by("dcon", "=", ctx.dcon)
                .filter_by("diniinf", "=", ctx.diniinf)
                .compile_update({
                    "fstfor": "1",
                    "tmsini": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-INI-T18-ERR",
                f"Errore DB durante l'UPDATE iniziale su ADCFRT18 [DCON={ctx.dcon}, DINIINF={ctx.diniinf}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1