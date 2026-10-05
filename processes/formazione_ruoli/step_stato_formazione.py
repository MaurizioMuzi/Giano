# processes/formazione_ruoli/step_stato_formazione.py
from datetime import date, datetime
from core.batch_logger import BatchLogger
from .context import FormazioneRuoliContext
from decimal import Decimal


class StatoFormazioneStep:
    """Paragrafi: CNTR-STATO-FORMAZIONE e UPD-STATO-INI-FORM (ADCFRT18)."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneRuoliContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        query = (
            self.engine.dataset("ADCFRT18")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date)
            .filter_by("fstfor", "IN", ("4", "5"))
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)
        if not rows:
            BatchLogger.error("INI-STATO-FOR", "Nessun record valido in ADCFRT18. Formazione Ruoli non consentita.", depth=1, is_last=True)
            raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE RUOLI NON CONSENTITA: Nessun record valido.")

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
                "fstfor": "5",
                "tmsini": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(upd, depth=1)
        BatchLogger.info("UPD-STATO-T18", f"UPDATE ADCFRT18 SET FSTFOR='5' -> Record impattati: {righe_modificate}", depth=1, is_last=True)
        BatchLogger.separator(depth=0)

        tas_map = self.engine.get_table_map("TRATTAS")
        query_tassi = (
            self.engine.dataset("TRATTAS")
            .select("tasSanz_2", "dataDec")
            .filter_by("tasSanz2", "<", Decimal("99.999"))
            .filter_by("dataDec", "<=", current_system_date)
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query_tassi, depth=1)
        if not rows:
            BatchLogger.error("ESTRAI-TASSO", "Nessun tasso presente. Formazione Ruoli non consentita.", depth=1, is_last=True)
            raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE RUOLI NON CONSENTITA: Nessun record valido per tasso.")

        row = tas_map.normalize(rows[0])
        ctx.ws_tasSanz_2 = row.get("tasSanz_2")
        ctx.dataDec = row.get("dataDec")

        BatchLogger.info(
            "ESTRAI-TASSO",
            f"DATADEC={ctx.dataDec} | Recupero Tasso corrente: {ctx.ws_tasSanz_2}",
            depth=1
        )
