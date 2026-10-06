# processes/preparazione_postalizzazione/processor.py
from typing import Optional
from core.base_process import BaseProcessModel
from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext
from .step_operazioni_iniziali import StatoFormazioneStep
from .steps import ElaborazioneCurt17Step

class PreparazionePostalizzazioneEngineProcessor(BaseProcessModel):
    """Orchestratore principale per il programma batch COBOL PDCPOAVV."""

    def __init__(self, context: Optional[PreparazionePostalizzazioneContext] = None, dry_run: bool = False,
                 size_commit: int = 1000):
        super().__init__(process_name="Preparazione-Postalizzazione", dry_run=dry_run)
        self.context = context if context is not None else PreparazionePostalizzazioneContext()

        # Dichiariamo esplicitamente l'attributo ereditato/configurato
        self.size_commit = size_commit
        # Manteniamo anche un alias per compatibilità con il controllo dello step
        self.commit_threshold = size_commit

        self.step_stato = StatoFormazioneStep(self)
        self.step_curt17 = ElaborazioneCurt17Step(self)


    def _execute_business_logic(self):
        BatchLogger.banner(f"AVVIO TASK: {self.process_name} [{self.provider.upper()}]")
        try:
            # 1. Operazioni iniziali - Controllo stato lavori (formazione) sulla T18 per la postalizzazione +
            #    accesso tabella pilota (ADCAVV11) e insert pilota
            self.step_stato.execute(self.context)
            #self.commit() nel COBOL non è presente la commit in questa sezione

            # 2. Scansione sedi operative + elaborazione di tutte le occorrenze formate (CSTACAR = 'Q' (avviso postalizzato), CIDERAV = RAV-17 calcolato)
            self.step_curt17.execute(self.context)

            # 3. Operazioni conclusive di consolidamento finestra
            #self.step_finali.execute(self.context, depth=1)
            #self.commit()

        except Exception as err:
            BatchLogger.error("BATCH-ERROR",
                              f"Errore critico durante l'esecuzione del batch. Esecuzione ROLLBACK globale: {err}",
                              depth=0)
            self.rollback()
            raise err