# processes/preparazione_postalizzazione/step_operazioni_finali.py
from datetime import datetime
from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext


class OperazioniFinaliStep:
    """
    Reingegnerizzazione del paragrafo OPERAZIONI-FINALI THRU OPERAZIONI-FINALI-EX:
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("OPERAZIONI-FINALI", "Elaborazione finale del flusso", depth=depth)

        try:
            # PERFORM-UPD-STATO-FIN-FORM
            righe_modificate_t18 = self._db_update_pilota_t18(ctx, depth=depth)
            BatchLogger.info(
                "UPD-STATO-FIN-FORM",
                f"Aggiornamento per fase successiva di Formazione Ruoli -> Record impattati: {righe_modificate_t18}",
                depth=depth,
                is_last=True
            )
            BatchLogger.separator(depth=0)

            # PERFORM UPDATE-T17-FINE
            righe_modificate_t17 = self._db_update_t17(ctx, depth=depth)
            BatchLogger.info(
                "UPDATE-T17-FINE",
                f"Aggiornamento tabella T17 -> Record impattati: {righe_modificate_t17}",
                depth=depth,
                is_last=True
            )
            BatchLogger.separator(depth=0)

            # PERFORM DELETE-PILOTA
            righe_eliminate_avv11 = self._db_delete_avv11(ctx, depth=depth)
            BatchLogger.info(
                "DELETE-PILOTA",
                f"Eliminazione gestioni su ADCAVV11 che non hanno avvisi elaborati -> Record impattati: {righe_eliminate_avv11}",
                depth=depth,
                is_last=True
            )
            BatchLogger.separator(depth=0)

            # PERFORM UPDATE-PILOTA
            righe_modificate_t11 = self._db_update_t11(ctx, depth=depth)
            righe_modificate_t12 = self._db_update_t12(ctx, depth=depth)
            BatchLogger.info(
                "UPDATE-PILOTA",
                f"Aggiornamento tabella AVV11 e AVV12 -> Record impattati per AVV11: {righe_modificate_t11} e per AVV12: {righe_modificate_t12}",
                depth=depth,
                is_last=True
            )
            BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "OPERAZIONI-FINALI",
                f"Errore durante le operazioni finali): {err}",
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
    def _db_update_pilota_t18(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato finale pilota su ADCFRT18 con stato = 4 (TERMINATO)."""
        try:
            upd = (
                self.engine.dataset("ADCFRT18")
                .filter_by("dcon", "=", ctx.dcon)
                .filter_by("diniinf", "=", ctx.diniinf)
                .compile_update({
                    "fstfor": "4",
                    "tmsfin": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-T18-ERR",
                f"Errore DB durante UPDATE pilota ADCFRT18 [DCON={ctx.dcon}, DINIINF={ctx.diniinf}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1

    def _db_update_t17(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato finale pilota su ADCTET17 con CDAS = 'IF'."""
        try:
            upd = (
                self.engine.dataset("ADCTET17")
                .filter_by("codServizio", "=", "PO")
                .compile_update({
                    "codServizio": "IF",
                    "timestamp": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-T18-ERR",
                f"Errore DB durante UPDATE tabella ADCTET17 [CDAS='PO']: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1

    def _db_delete_avv11(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
            """Accesso atomico DB: elimina gestioni ADCAVV11 che non hanno avvisi su ADCAVV12"""
            t01_dataset = self.engine.dataset("ADCAVV11")
            try:
                t11_map = self.engine.get_table_map("ADCAVV11")
                t12_map = self.engine.get_table_map("ADCAVV12")

                # 1. Costruzione della sottoquery EXISTS (B correlata ad A)
                exists_subquery = (
                    self.engine.dataset("ADCAVV12")
                    .exists(target_table_map=t12_map, alias="B")
                    .correlate("numElab", "numElab", parent_table_map=t11_map)
                    .correlate("prgCens", "prgcens", parent_table_map=t11_map)
                )

                # 2. Costruzione della query principale su ADCAVV11 A
                query = (
                    self.engine.dataset("ADCAVV11")
                    .filter_by("numElab", "=", ctx.ws_num_elab)
                    .where_not_exists(exists_subquery)
                    .compile_select()
                )

                return self.engine.execute_mutation(query, depth=depth)

            except Exception as err:
                BatchLogger.error("DB-DELETE-AVV11",
                                  f"Errore DB in eliminazione gestione, NUMELAB {ctx.ws_num_elab}: {err}", depth=depth)

                ctx.indic_errore = "X"
                return -1

    def _db_update_t11(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento CSTACOM = '2' e  CSTAAVV ='2 ADCAVV11"""
        try:
            upd_avv11 = (
                self.engine.dataset("ADCAVV11")
                .filter_by("numElab", "=", ctx.ws_num_elab)
                .compile_update({
                    "cstacom": "2",
                    "cstaavv": "2",
                    "tms_finform": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd_avv11, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-AVV11-ERR",
                f"Errore DB durante UPDATE tabella ADCAVV11 [NUMELAB={ctx.ws_num_elab}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1

    def _db_update_t12(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento CSTALET = '2' ADCAVV12"""
        try:
            upd_avv12 = (
                self.engine.dataset("ADCAVV12")
                .filter_by("numElab", "=", ctx.ws_num_elab)
                .compile_update({
                    "statoLettera": "2"
                })
            )
            return self.engine.execute_mutation(upd_avv12, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-AVV12-ERR",
                f"Errore DB durante UPDATE tabella ADCAVV12 [NUMELAB={ctx.ws_num_elab}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1