# processes/invio_ruoli_AdRE/step_controllo_lavori.py
from datetime import date, datetime
from typing import List, Any
from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext


class ControlloLavoriStep:
    """Paragrafo: CONTA-TAB17 (FI - IN)
                  CONTA-TAB02
                  AGGIORNA-LAVORI
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: InvioRuoliAdREContext) -> None:
        BatchLogger.info("CONTROLLO-LAVORI", "CONTROLLO-LAVORI (ADCTET17 - ADCFRT02)", depth=0)

        #tab17_map = self.engine.get_table_map("ADCTET17")

        try:
            # 1. CONTA-TAB17: EFFETTUA IL CONTEGGIO DEI RECORD CON CDAS DI RIFERIMENTO
            # valorizzazione CDAS per ADCTET17 per CONTEGGIO FIRMATI
            ws_cdas = "FI"
            res_sedi_fi = self._db_conta_tab17(ctx, ws_cdas, depth=1)
            ctx.count_sedi = int(list(res_sedi_fi[0].values())[0]) if res_sedi_fi else 0

            if ctx.count_sedi == 0:
                # valorizzazione CDAS per ADCTET17 per CONTEGGIO INVIATI
                ws_cdas = "IN"
                res_sedi_in = self._db_conta_tab17(ctx, ws_cdas, depth=1)
                ctx.count_sedi = int(list(res_sedi_in[0].values())[0]) if res_sedi_in else 0

                if ctx.count_sedi == 0:
                    ctx.indic_bloccata = "X"
                else:
                    pass
            else:
                res_ruoli = self._db_conta_tab02(ctx, depth=1)
                ctx.count_ruoli = int(list(res_ruoli[0].values())[0]) if res_ruoli else 0
                if ctx.count_ruoli == 0:
                    ctx.indic_bloccata = "X"
                else:
                    righe_aggiornate = self._db_aggiorna_lavori(ctx, depth=1)
                    BatchLogger.info(
                        "AGGIORNA-LAVORI",
                        f"Aggiornamnto lavori eseguito. Impattati: {righe_aggiornate}",
                        depth=1,
                        is_last=True
                    )

        except Exception as err:
            BatchLogger.error(
                "CONTROLLO-LAVORI",
                f"Errore critico durante la verifica delle tabelle ADCTET17 - ADCFRT02: {err}",
                depth=0
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("CONTROLLO-LAVORI", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("CONTROLLO-LAVORI", f"Fallito il rollback: {rollback_err}", depth=0)

            ctx.indic_errore = "X"
            raise err

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_conta_tab17(self, ctx: InvioRuoliAdREContext, cdas: str, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio totale record (sedi) in ADCTET17."""
        try:
            q_sedi = (
                self.engine.dataset("ADCTET17")
                .count()
                .filter_by("codServizio", "=", cdas)
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_sedi, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COUNT-SEDI-ERR", f"Errore DB durante conteggio totale record ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return []

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_conta_tab02(self, ctx: InvioRuoliAdREContext, depth: int) -> List[Any]:
        """Accesso atomico DB: conteggio totale record (sedi) in ADCFRT02."""
        try:
            q_sedi = (
                self.engine.dataset("ADCFRT02")
                .count()
                .filter_by("codStRuolo", "=", "P")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(q_sedi, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-COUNT-RUOLI-ERR", f"Errore DB durante conteggio totale record ADCFRT02: {err}", depth=depth)

            ctx.indic_errore = "X"
            return []

    # =========================================================================
    # AGGIORNAMENTO TABELLA ADCTET17 PER INVIO LAVORI
    # =========================================================================
    def _db_aggiorna_lavori(self, ctx: Any, depth: int) -> int:
        """Accesso atomico DB: reset massivo dei lavori su ADCTET17 impostando codServizio='IN'."""
        try:
            upd_t17 = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "IN",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            return self.engine.execute_mutation(upd_t17, depth=depth)
        except Exception as err:
            BatchLogger.error("AGGIORNA-LAVORI-ERR", f"Errore DB durante UPDATE di reset su ADCTET17: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1