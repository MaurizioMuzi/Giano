# processes/formazione_ruoli/step_ripartenze.py
from datetime import datetime, date
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

        BatchLogger.info("TEST-PILOTA", "Controllo Stato su Tabella pilota (ADCAVV11)", depth=0)
        tv11_map = self.engine.get_table_map("ADCAVV11")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        query = (
            self.engine.dataset("ADCAVV11")
            .select("cstacom", "dcon", "dinifor")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date)
            .filter_by("cstacom", "=", "2")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)
        if not rows:
            BatchLogger.error("CHK-RIPARTENZE", "Nessun record valido in ADCAVV11. Formazione Ruoli non consentita."
                                                "Postalizzazione non avvenuta.", depth=1, is_last=True)
            raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE RUOLI NON CONSENTITA: Nessun record valido. Postalizzazione non avvenuta.")

        row = tv11_map.normalize(rows[0])
        ctx.dcon_vv11 = row.get("dcon")
        ctx.ws_cstacom = row.get("cstacom")
        ctx.dinifor_vv11 = row.get("dinifor")

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
        righe_aggiornate = self.engine.execute_mutation(upd_av11, depth=1)
        BatchLogger.info("UPD-STATO-COMUNE",
                         f"WS-COUNT = WS-COUNT-SED -> Formazione ed invio ruoli in corso. Impattati: {righe_aggiornate}", depth=1,
                         is_last=True)

        # COMMIT transazione dopo l'aggiornamento pilota ADCAVV11
        self.engine.commit()

        # CONTA-SEDI
        q_sedi = (
            self.engine.dataset("ADCTET17")
            .count()
            .with_uncommitted_read()
            .compile_select()
        )
        res_sedi = self.engine.fetch(q_sedi, depth=1)
        ctx.count_sedi = int(list(res_sedi[0].values())[0]) if res_sedi else 0

        # CONTA-LAVORI con CDAS = IN
        q_lavori_in = (
            self.engine.dataset("ADCTET17")
            .count()
            .filter_by("codServizio", "=", "IN")
            .with_uncommitted_read()
            .compile_select()
        )
        res_lavori_in = self.engine.fetch(q_lavori_in, depth=1)
        ctx.count_lavori_in = int(list(res_lavori_in[0].values())[0]) if res_lavori_in else 0

        BatchLogger.info("CONTA-LAV-T17", f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IN): {ctx.count_lavori_in}", depth=1)

        if ctx.count_lavori_in == ctx.count_sedi and ctx.count_sedi > 0:
            upd_reset_in = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "FO",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            righe_aggiornate = self.engine.execute_mutation(upd_reset_in, depth=1)
            BatchLogger.info("RESET-LAV-T17", f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}", depth=1, is_last=True)
        else:
            # CONTA-LAVORI con CDAS = FI
            q_lavori_fi = (
                self.engine.dataset("ADCTET17")
                .count()
                .filter_by("codServizio", "=", "FI")
                .with_uncommitted_read()
                .compile_select()
            )
            res_lavori_fi = self.engine.fetch(q_lavori_fi, depth=1)
            ctx.count_lavori_fi = int(list(res_lavori_fi[0].values())[0]) if res_lavori_fi else 0

            BatchLogger.info("CONTA-LAV-T17",
                             f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (FI): {ctx.count_lavori_fi}", depth=1)

            if ctx.count_lavori_fi == ctx.count_sedi and ctx.count_sedi > 0:
                upd_reset_fi = (
                    self.engine.dataset("ADCTET17")
                    .compile_update({
                        "codServizio": "FO",
                        "timestamp": datetime(1, 1, 1, 0, 0, 0)
                    })
                )
                righe_aggiornate = self.engine.execute_mutation(upd_reset_fi, depth=1)
                BatchLogger.info("RESET-LAV-T17",
                                 f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}", depth=1,
                                 is_last=True)
            else:
                # CONTA-LAVORI con CDAS = IF
                q_lavori_if = (
                    self.engine.dataset("ADCTET17")
                    .count()
                    .filter_by("codServizio", "=", "IF")
                    .with_uncommitted_read()
                    .compile_select()
                )
                res_lavori_if = self.engine.fetch(q_lavori_if, depth=1)
                ctx.count_lavori_if = int(list(res_lavori_if[0].values())[0]) if res_lavori_if else 0

                BatchLogger.info("CONTA-LAV-T17",
                                 f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IF): {ctx.count_lavori_if}",
                                 depth=1)

                if ctx.count_lavori_if == ctx.count_sedi and ctx.count_sedi > 0:
                    upd_reset_if = (
                        self.engine.dataset("ADCTET17")
                        .compile_update({
                            "codServizio": "FO",
                            "timestamp": datetime(1, 1, 1, 0, 0, 0)
                        })
                    )
                    righe_aggiornate = self.engine.execute_mutation(upd_reset_if, depth=1)
                    BatchLogger.info("RESET-LAV-T17",
                                     f"WS-COUNT = WS-COUNT-SED -> Formazione Ruoli. Impattati: {righe_aggiornate}",
                                     depth=1,
                                     is_last=True)
                else:
                    BatchLogger.info("CHECK-LAV-T17",
                                     "WS-COUNT <> WS-COUNT-SED -> Mancato aggiornamento Lavori", depth=1,
                                     is_last=True)
                    BatchLogger.separator(depth=0)
