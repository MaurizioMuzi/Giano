# processes/preparazione_postalizzazione/step_ciclo_curt_01.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import PreparazionePostalizzazioneContext
from .step_valorizza_inserisci_t13 import DettaglioValorizzaT13
from core.batch_logger import BatchLogger

class DettaglioCicloCurt01:
    """
    Reingegnerizzazione del paragrafo CICLO-CURT01:
    CICLO DI ELABORAZIONE CURSORE SU ADCFRT01 PER L'ELABORAZIONE DELLE PARTITE CHE CONFLUISCONO IN UN AVVISO
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_valorizza_inserisci_t13 = DettaglioValorizzaT13(engine)

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, rowt01, depth: int) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione intestatari dell'avviso pensioni", depth=0)

        self.step_valorizza_inserisci_t13.execute_dettaglio(ctx, rowt01, depth=depth+1)

