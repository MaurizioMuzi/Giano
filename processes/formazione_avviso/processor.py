# processes/formazione_avviso/processor.py
from typing import Optional
from core.base_process import BaseProcessModel
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext
from .step_stato_formazione import StatoFormazioneStep
from .step_ripartenze import GestioneRipartenzeStep
from .steps import ElaborazioneCurjoi1Step
from .step_statistiche import StatisticheStep
from .step_operazioni_finali import OperazioniFinaliStep


class FormazioneAvvisoEngineProcessor(BaseProcessModel):
    """Orchestratore principale per il programma batch COBOL PDCFOAVV."""

    def __init__(self, context: Optional[FormazioneAvvisoContext] = None, dry_run: bool = False):
        super().__init__(process_name="Formazione_Avviso", dry_run=dry_run)
        self.context = context if context is not None else FormazioneAvvisoContext()

        # Istanziazione lineare e indipendente dei singoli step del flusso batch
        self.step_stato = StatoFormazioneStep(self)
        self.step_ripartenze = GestioneRipartenzeStep(self)
        self.step_curjoi1 = ElaborazioneCurjoi1Step(self)
        self.step_statistiche = StatisticheStep(self)
        self.step_finali = OperazioniFinaliStep(self)

    def _execute_business_logic(self):
        BatchLogger.banner(f"AVVIO TASK: {self.process_name} [{self.provider.upper()}]")

        # 1. Controllo finestra temporale ed eleggibilità iniziale (ADCFRT18 -> FSTFOR='1')
        self.step_stato.execute(self.context)

        # 2. Controllo e quadratura iniziale delle ripartenze (ADCTET17 -> CDAS='AV')
        self.step_ripartenze.execute(self.context)

        # 3. Scansione sedi operative e formazione avvisi (CURJOI-1 -> CURJOI-2A -> CURJOI-2)
        self.step_curjoi1.execute(self.context)

        # 4. Elaborazione statistiche finali per stato servizio (CURT17 su ADCTET17)
        self.step_statistiche.execute(self.context, depth=1)

        # 5. Operazioni conclusive di consolidamento finestra (ADCFRT18 -> FSTFOR='2')
        self.step_finali.execute(self.context, depth=1)

        BatchLogger.info("AVVISI-FORMATI", "Elaborazione avvisi completata con successo", depth=0)
