# processes/formazione_avviso/step_ripartenze.py
from datetime import datetime
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

        # CONTA-SEDI
        q_sedi = (
            self.engine.dataset("ADCTET17")
            .count()
            .with_uncommitted_read()
            .compile_select()
        )
        res_sedi = self.engine.fetch(q_sedi, depth=1)
        ctx.count_sedi = int(list(res_sedi[0].values())[0]) if res_sedi else 0

        # CONTA-LAVORI
        q_lavori = (
            self.engine.dataset("ADCTET17")
            .count()
            .filter_by("codServizio", "IN", ("IF", "AV"))
            .with_uncommitted_read()
            .compile_select()
        )
        res_lavori = self.engine.fetch(q_lavori, depth=1)
        ctx.count_lavori = int(list(res_lavori[0].values())[0]) if res_lavori else 0

        BatchLogger.info("CONTA-LAV-T17", f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IF/AV): {ctx.count_lavori}", depth=1)

        if ctx.count_lavori == ctx.count_sedi and ctx.count_sedi > 0:
            upd_reset = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "AV",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            righe_aggiornate = self.engine.execute_mutation(upd_reset, depth=1)
            BatchLogger.info("RESET-LAV-T17", f"WS-COUNT = WS-COUNT-SED -> Reset massivo eseguito. Impattati: {righe_aggiornate}", depth=1, is_last=True)
        else:
            BatchLogger.info("CHECK-LAV-T17", "WS-COUNT <> WS-COUNT-SED -> Nessun riallineamento massivo necessario", depth=1, is_last=True)
        BatchLogger.separator(depth=0)