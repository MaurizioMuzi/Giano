# processes/firma_ruoli/processor.py
from typing import Optional
from core.base_process import BaseProcessModel
from core.batch_logger import BatchLogger
from .context import FirmaRuoliContext

from .steps.step_operazioni_iniziali import OperazioniInizialiStep
from .steps.steps import ElaborazioneCicloPrincipaleStep
from .steps.step_operazioni_finali import OperazioniFinaliStep


class FirmaRuoliEngineProcessor(BaseProcessModel):
    """Orchestratore principale per il programma batch COBOL PDCFRPRO con gestione transazionale a blocchi."""

    def __init__(self, context: Optional[FirmaRuoliContext] = None, dry_run: bool = False,
                 size_commit: int = 1000):
        super().__init__(process_name="Invio_Ruoli_AdRE", dry_run=dry_run)
        self.context = context if context is not None else FirmaRuoliContext()

        # Dichiariamo esplicitamente l'attributo ereditato/configurato
        self.size_commit = size_commit
        # Manteniamo anche un alias per compatibilità con il controllo dello step
        self.commit_threshold = size_commit

        self.step_ope_iniziali = OperazioniInizialiStep(self)
        #self.step_controllo_lavori = ControlloLavoriStep(self)

        self.step_ciclo_principale = ElaborazioneCicloPrincipaleStep(self)
        self.step_finali = OperazioniFinaliStep(self)

    def _execute_business_logic(self):
        BatchLogger.banner(f"AVVIO TASK: {self.process_name} [{self.provider.upper()}]")

        try:
            # 1. Controllo operazioni iniziali
            self.step_ope_iniziali.execute(self.context)

            # 2. Elaborazione firma ruoli
            self.step_ciclo_principale.execute_record(self.context)
            #self.commit()

            # 3. Fine programma
            self.step_finali.execute(self.context)
            self.commit()

            BatchLogger.info("RUOLI-FORMATI", "Elaborazione firma ruoli completata con successo", depth=0)

        except Exception as err:
            BatchLogger.error("BATCH-ERROR",
                              f"Errore critico durante l'esecuzione del batch. Esecuzione ROLLBACK globale: {err}",
                              depth=0)
            self.rollback()
            raise err