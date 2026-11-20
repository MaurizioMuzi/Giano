# processes/invio_ruoli_AdER/steps/step_calcola_ruoli.py
from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext
from .step_gestione_R5A import GestioneR5AStep
from .step_gestione_R5B import GestioneR5BStep


class CalcolaRuoliStep:
    """
    Reingegnerizzazione del paragrafo COBOL CALCOLA-RUOLI:
    Gestisce la rottura di chiave ruolo (ARIFRUO, NRUO, CESA) e orchestra
    l'emissione del record di testa ruolo (R5A) e dei successivi record di dettaglio.
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_R5A = GestioneR5AStep(engine)
        self.step_R5B = GestioneR5BStep(engine)

    def execute(self, ctx: InvioRuoliAdREContext, row_t02: dict, depth: int = 1) -> None:
        try:
            arifruo_curr = row_t02.get("annoRif")
            nruo_curr = row_t02.get("numRuolo")
            cesa_curr = row_t02.get("codEsattoria")

            # Rottura ruolo: esegue IMPOSTA-CAMPI-R5A solo al cambio di (ARIFRUO, NRUO, CESA)
            if (
                arifruo_curr != ctx.ws_arifruo_t02
                or nruo_curr != ctx.ws_nruo_t02
                or cesa_curr != ctx.ws_cesa_t02_2
            ):
                ctx.ws_arifruo_t02 = arifruo_curr
                ctx.ws_nruo_t02 = nruo_curr
                ctx.ws_cesa_t02_2 = cesa_curr

                BatchLogger.info(
                    "ROTTURA-RUOLO",
                    f"Elaborazione ruolo CESA={cesa_curr} | ARIFRUO={arifruo_curr} | NRUO={nruo_curr}",
                    depth=depth
                )

                # 1. IMPOSTA-CAMPI-R5A: valorizzazione e scrittura record di testa ruolo R5A
                self.step_R5A.execute_controllo_flusso(
                    ctx=ctx,
                    row_t02=row_t02,
                    depth=depth + 1
                )

                if ctx.indic_errore != "X":
                    # 2. IMPOSTA-CAMPI-R5B: valorizzazione e scrittura record di testa ruolo R5B (Riepilogo ruolo per tributo)
                    self.step_R5B.execute_controllo_flusso(
                        ctx=ctx,
                        row_t02=row_t02,
                        depth=depth + 1
                    )

            # Qui andranno gli step di dettaglio ruolo (R5B, R7A, R7B, R7L, R5Z...)

        except Exception as err:
            BatchLogger.error(
                "CALCOLA-RUOLI-ERR",
                f"Errore critico durante l'elaborazione CALCOLA-RUOLI "
                f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise err