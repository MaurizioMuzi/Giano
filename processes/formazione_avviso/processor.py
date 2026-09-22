# processes/formazione_avviso/processor.py
from typing import Optional
from core.base_process import BaseProcessModel
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext
from .steps import (
    StatoFormazioneStep,
    GestioneRipartenzeStep,
    ElaborazioneCurjoi1Step
)


class FormazioneAvvisoEngineProcessor(BaseProcessModel):
    """Orchestratore principale per il programma batch COBOL PDCFOAVV."""

    def __init__(self, context: Optional[FormazioneAvvisoContext] = None, dry_run: bool = False):
        super().__init__(process_name="Formazione_Avviso", dry_run=dry_run)
        self.context = context if context is not None else FormazioneAvvisoContext()

        self.step_stato = StatoFormazioneStep(self)
        self.step_ripartenze = GestioneRipartenzeStep(self)
        self.step_curjoi1 = ElaborazioneCurjoi1Step(self)

    def _execute_business_logic(self):
        BatchLogger.banner(f"AVVIO TASK: {self.process_name} [{self.provider.upper()}]")

        # 1. Controllo finestre ed eleggibilità T18
        self.step_stato.execute(self.context)

        # 2. Controllo e quadratura lavori T17
        self.step_ripartenze.execute(self.context)

        # 3. Cursore CURJOI-1
        self.step_curjoi1.execute(self.context)

        # 4. Tabella pilota
        self._accedi_pilota()

    def _accedi_pilota(self):
        BatchLogger.info("ACCEDI-PILOTA", f"Controllo tabella pilota per DCON={self.context.dcon}...", depth=0)