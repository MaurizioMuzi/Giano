# processes/invio_ruoli_AdRE/step_operazioni_iniziali.py
from datetime import date
from typing import List, Any
from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext


class OperazioniInizialiStep:
    """Paragrafo: TEST-PILOTA (ADCAVV11)."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: InvioRuoliAdREContext) -> None:
        BatchLogger.info("TEST-PILOTA", "TEST-PILOTA (ADCAVV11)", depth=0)
        avv11_map = self.engine.get_table_map("ADCAVV11")

        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        # Inizializzazione indicatori
        ctx.indic_prima_volta_T02 = "X"
        ctx.indic_primo_ciclo_T02 = "X"
        ctx.indic_prima_volta_R5A = "X"
        ctx.indic_fine_file_T02 = " "
        ctx.indic_errore = " "

        try:
            # 1. TEST-PILOTA: CONTROLLA STATO FLAG TABELLA PILOTA
            rows = self._db_fetch_stato_pilota(ctx, current_system_date, fixed_dfinfor_date, depth=1)

            if not rows:
                BatchLogger.error(
                    "TEST-PILOTA",
                    "Nessun record valido in ADCAVV11. Invio Ruoli AdER non consentita.",
                    depth=1,
                    is_last=True
                )
                raise RuntimeError("[COBOL_EXCEPTION] INVIO ADER NON CONSENTITA: Nessun record valido.")

            row = avv11_map.normalize(rows[0])
            ctx.ws_cstacom = row.get("codStatoElab")
            ctx.dcon_vv11 = row.get("dataConsegna")
            ctx.dinifor_vv11 = row.get("dataIniForm")

            BatchLogger.info(
                "REC-PILOTA",
                f"DCON={ctx.dcon_vv11} | DINIFOR={ctx.dinifor_vv11} | CSTACOM={ctx.ws_cstacom} | NUMELAB={row.get('numelab')}",
                depth=1,
                is_last=True
            )
            BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "TEST-PILOTA",
                f"Errore critico durante la verifica della tabella pilota ADCAVV11: {err}",
                depth=0
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("TEST-PILOTA", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("TEST-PILOTA", f"Fallito il rollback: {rollback_err}", depth=0)

            ctx.indic_errore = "X"
            raise err

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_stato_pilota(self, ctx: InvioRuoliAdREContext, current_date: date, fixed_date: date, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera il record della tabella pilota da ADCAVV11."""
        try:
            # 1. Recupero del MAX(numelab) tramite TableMap e query builder
            sub_map = self.engine.get_table_map("ADCAVV11")
            query_max = (
                self.engine.dataset("ADCAVV11")
                .select_raw(f"MAX({sub_map.numelab}) AS MAX_NUMELAB")
                .filter_by("dataIniForm", "<=", current_date)
                # valorizzata solo per test
                .filter_by("dataFinForm", ">=", fixed_date)
                # da attivare per esecuzione reale
                # .filter_by("dataFinForm", ">=", current_date)
                .filter_by("codStatoElab", "=", "0")
                .with_uncommitted_read()
                .compile_select()
            )

            res_max = self.engine.fetch(query_max, depth=depth)
            max_numelab = res_max[0].get("MAX_NUMELAB") if res_max else None

            # Se non esiste alcun max_numelab valido, si evita la query
            if max_numelab is None:
                return []

            query_pilota = (
                self.engine.dataset("ADCAVV11")
                .select("codStatoElab", "dataConsegna", "dataIniForm", "numelab")
                .filter_by("dataIniForm", "<=", current_date)
                # valorizzata solo per test
                .filter_by("dataFinForm", ">=", fixed_date)
                # da attivare per esecuzione reale
                # .filter_by("dataFinForm", ">=", current_date)
                .filter_by("codStatoElab", "=", "0")
                .filter_by("numelab", "=", max_numelab)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query_pilota, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-PILOTA-ERR",
                f"Errore DB durante la SELECT su ADCAVV11 [CURR_DATE={current_date}, FIXED_DATE={fixed_date}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return []