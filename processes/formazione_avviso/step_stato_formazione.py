# processes/formazione_avviso/step_stato_formazione.py
from datetime import date, datetime
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class StatoFormazioneStep:
    """Paragrafi: CNTR-STATO-FORMAZIONE e UPD-STATO-INI-FORM (ADCFRT18)."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        query = (
            self.engine.dataset("ADCFRT18")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date)
            .filter_by("fstfor", "<>", "2")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)
        if not rows:
            BatchLogger.error("INI-STATO-FOR", "Nessun record valido in ADCFRT18. Formazione non consentita.", depth=1, is_last=True)
            raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE NON CONSENTITA: Nessun record valido.")

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
                "fstfor": "1",
                "tmsini": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(upd, depth=1)
        BatchLogger.info("UPD-STATO-T18", f"UPDATE ADCFRT18 SET FSTFOR='1' -> Record impattati: {righe_modificate}", depth=1, is_last=True)
        BatchLogger.separator(depth=0)