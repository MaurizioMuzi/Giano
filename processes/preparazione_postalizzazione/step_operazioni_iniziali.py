# processes/preparazione_postalizzazione/step_operazioni_iniziali.py
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import PreparazionePostalizzazioneContext
from core.batch_logger import BatchLogger
from .step_gestisci_pilota import GestiscePilota


class BaseFormazioneStep(ABC):
    """Classe base astratta per tutti gli step della pipeline di preparazione postalizzazione."""

    def __init__(self, engine):
        self.engine = engine

    @abstractmethod
    def execute(self, ctx: PreparazionePostalizzazioneContext) -> None:
        """Esegue l'elaborazione specifica dello step aggiornando il contesto condiviso."""
        pass


class StatoFormazioneStep(BaseFormazioneStep):
    """Paragrafi:
    - CNTR-STATO-FORMAZIONE
    - UPD-STATO-INI-FORM (ADCFRT18)
    - ACCEDI-PILOTA + INSERT-PILOTA (ADCAVV11)"""
    def __init__(self, engine):
        super().__init__(engine)
        self.step_gestisce_pilota = GestiscePilota(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24) #per test

        query = (
            self.engine.dataset("ADCFRT18")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date) #lasciato così per test, deve andarci la 'current_system_date'
            .filter_by("fstfor", "IN", ("3","9"))
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)
        if not rows:
            BatchLogger.error("INI-STATO-FOR", "Nessun record valido in ADCFRT18. Postalizzazione non consentita.", depth=1, is_last=True)
            #ctx.indic_errore = "X"
            raise RuntimeError("[COBOL_EXCEPTION] POSTALIZZAZIONE NON CONSENTITA: Nessun record valido.")

        row = t18_map.normalize(rows[0])
        ctx.dcon = row.get("dcon")
        ctx.diniinf = row.get("diniinf")
        ctx.dfininf = row.get("dfininf")
        ctx.dinifor = row.get("dinifor")
        ctx.dfinfor = row.get("dfinfor")
        ctx.fstfor = row.get("fstfor")

        BatchLogger.info(
            "REC-FINESTRA",
            f"DCON={ctx.dcon} | Finestra Infasamento: {ctx.diniinf} -> {ctx.dfininf} | Stato={ctx.fstfor}",
            depth=1
        )

        upd = (
            self.engine.dataset("ADCFRT18")
            .filter_by("dcon", "=", ctx.dcon)
            .filter_by("diniinf", "=", ctx.diniinf)
            .compile_update({
                "fstfor": "9",
                "tmsini": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(upd, depth=1)
        BatchLogger.info("UPD-STATO-T18", f"UPDATE ADCFRT18 SET FSTFOR='9' -> Record impattati: {righe_modificate}", depth=1, is_last=True)
        BatchLogger.separator(depth=0)

        # ACCEDI-PILOTA + INSERT-PILOTA
        self.step_gestisce_pilota.execute(ctx)