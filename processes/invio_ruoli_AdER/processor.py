# processes/invio_ruoli_AdER/processor.py
from typing import Optional
from core.base_process import BaseProcessModel
from core.batch_logger import BatchLogger
from .context import InvioRuoliAdREContext

from .steps.step_operazioni_iniziali import OperazioniInizialiStep
from .steps.step_controllo_lavori import ControlloLavoriStep
from .steps.steps import ElaborazioneCicloPrincipaleStep
from .step_statistiche import StatisticheStep
from .step_operazioni_finali import OperazioniFinaliStep


class InvioRuoliAdREEngineProcessor(BaseProcessModel):
    """Orchestratore principale per il programma batch COBOL PDCINCRE con gestione transazionale a blocchi."""

    def __init__(self, context: Optional[InvioRuoliAdREContext] = None, dry_run: bool = False,
                 size_commit: int = 1000):
        super().__init__(process_name="Invio_Ruoli_AdRE", dry_run=dry_run)
        self.context = context if context is not None else InvioRuoliAdREContext()

        # Dichiariamo esplicitamente l'attributo ereditato/configurato
        self.size_commit = size_commit
        # Manteniamo anche un alias per compatibilità con il controllo dello step
        self.commit_threshold = size_commit

        self.step_ope_iniziali = OperazioniInizialiStep(self)
        self.step_controllo_lavori = ControlloLavoriStep(self)

        self.step_ciclo_principale = ElaborazioneCicloPrincipaleStep(self)
        self.step_statistiche = StatisticheStep(self)
        self.step_finali = OperazioniFinaliStep(self)

    def _execute_business_logic(self):
        BatchLogger.banner(f"AVVIO TASK: {self.process_name} [{self.provider.upper()}]")

        try:
            # 1. Controllo operazioni iniziali
            self.step_ope_iniziali.execute(self.context)

            # 2. Controllo lavori (ADCTET17 - ADCFRT02)
            self.step_controllo_lavori.execute(self.context)
            self.commit()

            if self.context.indic_errore == " ":
                if self.context.indic_bloccata == "X":
                    BatchLogger.error(
                        "CONTROLLO-LAVORI",
                        "Stato ruolo non congruente con la richiesta. Elaborazione non consentita.",
                        depth=1,
                        is_last=True
                    )
                    raise RuntimeError(
                        "[COBOL_EXCEPTION] ELABORAZIONE NON PERMESSA: Stato ruolo non congruente con la richiesta.")
                else:
                    self.step_ciclo_principale.execute_record(self.context)

            # 3. Scansione sedi operative e formazione avvisi (CURJOI-1 gestito con transazioni per singola sede)
            #self.step_curjoi1.execute(self.context)

            # 4. Elaborazione statistiche finali per stato servizio (CURT17 su ADCTET17)
            self.step_statistiche.execute(self.context, depth=1)

            # 5. Operazioni conclusive di consolidamento finestra (ADCFRT18 -> FSTFOR='2')
            self.step_finali.execute(self.context, depth=1)
            self.commit()

            BatchLogger.info("RUOLI-FORMATI", "Elaborazione formazione ruoli completata con successo", depth=0)

        except Exception as err:
            BatchLogger.error("BATCH-ERROR",
                              f"Errore critico durante l'esecuzione del batch. Esecuzione ROLLBACK globale: {err}",
                              depth=0)
            self.rollback()
            raise err