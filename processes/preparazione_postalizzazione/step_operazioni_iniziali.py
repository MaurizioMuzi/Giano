# processes/preparazione_postalizzazione/step_operazioni_iniziali.py
from datetime import date, datetime
from typing import List, Any
from .context import PreparazionePostalizzazioneContext
from core.batch_logger import BatchLogger
from .step_gestisci_pilota import GestiscePilota


class StatoFormazioneStep:
    """Paragrafi:
    - CNTR-STATO-FORMAZIONE
    - UPD-STATO-INI-FORM (ADCFRT18)
    - ACCEDI-PILOTA + INSERT-PILOTA (ADCAVV11)"""
    def __init__(self, engine):
        self.engine = engine
        self.step_gestisce_pilota = GestiscePilota(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24) #per test

        try:
            # 1. CNTR-STATO-FORMAZIONE: Recupero della finestra operativa pilota su ADCFRT18
            rows = self._db_fetch_finestra_t18(current_system_date, fixed_dfinfor_date, depth=1)
            if not rows:
                BatchLogger.error(
                    "INI-STATO-FOR",
                    "Nessun record valido in ADCFRT18. Postalizzazione non consentita.",
                    depth=1,
                    is_last=True
                )
                raise RuntimeError("[COBOL_EXCEPTION] POSTALIZZAZIONE NON CONSENTITA: Nessun record valido.")

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

            # 2. UPD-STATO-INI-FORM: Imposta lo stato a '9' (IN FASE DI POSTALIZZAZIONE) e memorizza il timestamp di avvio
            righe_modificate = self._db_update_inizio_formazione_t18(ctx, depth=1)
            BatchLogger.info(
                "UPD-STATO-T18",
                f"UPDATE ADCFRT18 SET FSTFOR='9' -> Record impattati: {righe_modificate}",
                depth=1,
                is_last=True
            )
            BatchLogger.separator(depth=0)

            # 3. ACCEDI-PILOTA + INSERT-PILOTA
            self.step_gestisce_pilota.execute(ctx, depth=1)

        except Exception as err:
            BatchLogger.error(
                "OPERAZIONI-INIZIALI",
                f"Errore critico durante la gestione dello stato formazione su ADCFRT18: {err}",
                depth=0
            )
            ctx.indic_errore = "X"
            try:
                self.engine.rollback()
                BatchLogger.warn("OPERAZIONI-INIZIALI", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
            except Exception as rollback_err:
                BatchLogger.error("OPERAZIONI-INIZIALI", f"Fallito il rollback: {rollback_err}", depth=0)
            raise


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_finestra_t18(self, current_date: date, fixed_date: date, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera il record della finestra attiva da ADCFRT18."""
        query = (
                self.engine.dataset("ADCFRT18")
                .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
                .filter_by("dinifor", "<=", current_date)
                .filter_by("dfinfor", ">=", fixed_date)  # TODO: lasciato così per test, deve andarci la 'current_system_date'
                .filter_by("fstfor", "IN", ("3", "9"))
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
        )
        try:
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-T18-ERR",
                f"Errore DB durante la SELECT su ADCFRT18 [CURR_DATE={current_date}, FIXED_DATE={fixed_date}]: {err}",
                depth=depth
            )
            raise


    def _db_update_inizio_formazione_t18(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiorna fstfor='9' e valorizza tmsini su ADCFRT18."""
        try:
            upd = (
                self.engine.dataset("ADCFRT18")
                .filter_by("dcon", "=", ctx.dcon)
                .filter_by("diniinf", "=", ctx.diniinf)
                .compile_update({
                    "fstfor": "9",
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
            raise