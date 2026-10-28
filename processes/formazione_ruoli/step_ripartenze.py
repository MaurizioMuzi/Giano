# processes/formazione_ruoli/step_ripartenze.py
from datetime import datetime, date
from typing import List, Any
from core.batch_logger import BatchLogger
from .context import FormazioneRuoliContext


class GestioneRipartenzeStep:
    """
    Reingegnerizzazione dei paragrafi:
      - TEST-PILOTA
      - UPD-STATO-COMUNE
      - CONTA-SEDI
      - CONTA-LAVORI
      - AGGIORNA-LAVORI
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneRuoliContext) -> None:
        BatchLogger.info("CHK-RIPARTENZE", "GESTIONE-RIPARTENZE", depth=0)

        try:
            # 1. TEST-PILOTA
            BatchLogger.info("TEST-PILOTA", "Controllo Stato su Tabella pilota (ADCAVV11)", depth=0)
            tv11_map = self.engine.get_table_map("ADCAVV11")
            current_system_date = date.today()
            fixed_dfinfor_date = date(2026, 8, 24)

            rows = self._db_fetch_pilota_v11(current_system_date, fixed_dfinfor_date, depth=1)
            if not rows:
                BatchLogger.error(
                    "CHK-RIPARTENZE",
                    "Nessun record valido in ADCAVV11. Formazione Ruoli non consentita. Postalizzazione non avvenuta.",
                    depth=1,
                    is_last=True
                )
                raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE RUOLI NON CONSENTITA: Nessun record valido. Postalizzazione non avvenuta.")

            # 2. UPD-STATO-COMUNE
            row = tv11_map.normalize(rows[0])
            ctx.dcon_vv11 = row.get("dcon")
            ctx.ws_cstacom = row.get("cstacom")
            ctx.dinifor_vv11 = row.get("dinifor")

            righe_aggiornate = self._db_update_pilota_v11(ctx, depth=1)
            BatchLogger.info(
                "UPD-STATO-COMUNE",
                f"WS-COUNT = WS-COUNT-SED -> Formazione ed invio ruoli in corso. Impattati: {righe_aggiornate}",
                depth=1,
                is_last=True
            )

            # COMMIT transazione dopo l'aggiornamento pilota ADCAVV11
            self._db_commit(depth=1)

            # 3. CONTA-SEDI
            res_sedi = self._db_count_sedi_t17(depth=1)
            ctx.count_sedi = int(list(res_sedi[0].values())[0]) if res_sedi else 0

            # 4. CONTA-LAVORI con CDAS = IN
            res_lavori_in = self._db_count_lavori_t17("IN", depth=1)
            ctx.count_lavori_in = int(list(res_lavori_in[0].values())[0]) if res_lavori_in else 0

            BatchLogger.info(
                "CONTA-LAV-T17",
                f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IN): {ctx.count_lavori_in}",
                depth=1
            )

            if ctx.count_lavori_in == ctx.count_sedi and ctx.count_sedi > 0:
                righe_aggiornate = self._db_update_reset_lavori_t17(depth=1)
                BatchLogger.info(
                    "RESET-LAV-T17",
                    f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}",
                    depth=1,
                    is_last=True
                )
            else:
                # CONTA-LAVORI con CDAS = FI
                res_lavori_fi = self._db_count_lavori_t17("FI", depth=1)
                ctx.count_lavori_fi = int(list(res_lavori_fi[0].values())[0]) if res_lavori_fi else 0

                BatchLogger.info(
                    "CONTA-LAV-T17",
                    f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (FI): {ctx.count_lavori_fi}",
                    depth=1
                )

                if ctx.count_lavori_fi == ctx.count_sedi and ctx.count_sedi > 0:
                    righe_aggiornate = self._db_update_reset_lavori_t17(depth=1)
                    BatchLogger.info(
                        "RESET-LAV-T17",
                        f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}",
                        depth=1,
                        is_last=True
                    )
                else:
                    # CONTA-LAVORI con CDAS = IF
                    res_lavori_if = self._db_count_lavori_t17("IF", depth=1)
                    ctx.count_lavori_if = int(list(res_lavori_if[0].values())[0]) if res_lavori_if else 0

                    BatchLogger.info(
                        "CONTA-LAV-T17",
                        f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IF): {ctx.count_lavori_if}",
                        depth=1
                    )

                    if ctx.count_lavori_if == ctx.count_sedi and ctx.count_sedi > 0:
                        righe_aggiornate = self._db_update_reset_lavori_t17(depth=1)
                        BatchLogger.info(
                            "RESET-LAV-T17",
                            f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}",
                            depth=1,
                            is_last=True
                        )
                    else:
                        BatchLogger.info(
                            "CHECK-LAV-T17",
                            "WS-COUNT <> WS-COUNT-SED -> Mancato aggiornamento Lavori",
                            depth=1,
                            is_last=True
                        )
                        BatchLogger.separator(depth=0)

        except Exception as err:
            BatchLogger.error(
                "CHK-RIPARTENZE",
                f"Errore critico durante la gestione delle ripartenze ruoli: {err}",
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
    def _db_fetch_pilota_v11(self, current_date: date, fixed_date: date, depth: int) -> List[Any]:
        """Accesso atomico DB: recupero record pilota da ADCAVV11."""
        try:
            query = (
                self.engine.dataset("ADCAVV11")
                .select("cstacom", "dcon", "dinifor")
                .filter_by("dinifor", "<=", current_date)
                .filter_by("dfinfor", ">=", fixed_date)
                .filter_by("cstacom", "=", "2")
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-V11-ERR",
                f"Errore DB durante la SELECT su ADCAVV11 [CURR_DATE={current_date}, FIXED_DATE={fixed_date}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_update_pilota_v11(self, ctx: FormazioneRuoliContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato pilota su ADCAVV11 ad avvio formazione ruoli."""
        try:
            upd_av11 = (
                self.engine.dataset("ADCAVV11")
                .filter_by("dcon", "=", ctx.dcon_vv11)
                .filter_by("dinifor", "=", ctx.dinifor_vv11)
                .compile_update({
                    "cstacom": "0",
                    "cstaavv": "3",
                    "tms_inveq": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd_av11, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-V11-ERR",
                f"Errore DB durante l'UPDATE pilota ADCAVV11 [DCON={ctx.dcon_vv11}, DINIFOR={ctx.dinifor_vv11}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_commit(self, depth: int) -> None:
        """Accesso atomico DB: esecuzione esplicita del COMMIT della transazione."""
        try:
            self.engine.commit()
            BatchLogger.debug("DB-COMMIT", "COMMIT eseguito con successo", depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COMMIT-ERR", f"Errore durante l'esecuzione del COMMIT su database: {err}", depth=depth)
            raise


    def _db_count_sedi_t17(self, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio totale sedi censite su ADCTET17."""
        try:
            q_sedi = (
                self.engine.dataset("ADCTET17")
                .count()
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_sedi, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COUNT-SEDI-T17-ERR", f"Errore DB durante il conteggio sedi su ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    def _db_count_lavori_t17(self, cod_servizio: str, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio sedi qualificate per codice servizio su ADCTET17."""
        try:
            q_lavori = (
                self.engine.dataset("ADCTET17")
                .count()
                .filter_by("codServizio", "=", cod_servizio)
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_lavori, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-COUNT-LAVORI-T17-ERR",
                f"Errore DB durante il conteggio lavori su ADCTET17 [COD_SERVIZIO={cod_servizio}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_update_reset_lavori_t17(self, depth: int) -> int:
        """Accesso atomico DB: aggiornamento massivo sedi su ADCTET17 a codServizio='FO'."""
        try:
            upd_reset = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "FO",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            return self.engine.execute_mutation(upd_reset, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-UPD-RESET-T17-ERR", f"Errore DB durante UPDATE di reset a 'FO' su ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1