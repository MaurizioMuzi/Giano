# processes/preparazione_postalizzazione/step_recupero_rav.py
from datetime import date

from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext

class DettaglioRecuperoRav:
    """
    - Estrazione da ADCAVV03 prendendo il primo CIDERAV disponibile
    - Calcolo CIDERAV e ATTRIBUZIONE
    - UPDATE su ADCAVV03
    """

    def __init__(self, engine):
        self.engine = engine

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("ACCEDI-TABELLA-RAV-ADCAVV03", "Estrazione del primo codice RAV disponibile", depth=1)
        tavv03_map = self.engine.get_table_map("ADCAVV03")

        # Equivalente di OPEN-CURV03 + FETCH-CURV03: prendo il primo codice RAV disponibile
        query = (
            self.engine.dataset("ADCAVV03")
            .select("codConcessione", "prog", "codiceRavMin", "codiceRavMax", "codiceAbi", "codiceRav", "flagAttribRav")
            .filter_by("codConcessione", "=", ctx.cesa)
            .filter_by("flagAttribRav", "=", "0") #record valido
            .order_by("prog", "codiceRavMax")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )
        rows_avv03 = self.engine.fetch(query, depth=1)

        if rows_avv03:
            row_avv03 = tavv03_map.normalize(rows_avv03[0])
        else:
            BatchLogger.error("SELECT-AVV03", f"Nessun record attivo in ADCAVV03 per CESA={ctx.cesa}:", depth=1, is_last=True)
            ctx.indic_rav_presente = "X"
            return

        if ctx.indic_rav_presente!= "X":
            ctx.ws_cabi = row_avv03.get("codiceAbi")
            ctx.ws_ciderav = row_avv03.get("codiceRav")
            ctx.ws_ciderav_max = row_avv03.get("codiceRavMax")

            ctx.ws_delta_rav = ctx.ws_ciderav_max - ctx.ws_ciderav

            if ctx.ws_delta_rav > 0:
                ctx.ws_ciderav_new = ctx.ws_ciderav + 1
                ctx.ws_flag_attr = '0'

                # Ref. COBOL UPDATE-V03
                self._update_v03(ctx, depth=depth+1)
            else:
                ctx.ws_flag_attr = '1'
                ctx.ws_ciderav_new = ctx.ws_ciderav
                self._update_v03(ctx, row_avv03, depth=depth+1)

    def _update_v03(self, ctx: PreparazionePostalizzazioneContext, row, is_last: bool = False,
                                 depth: int = 2) -> None:

                current_system_date = date.today()

                """Aggiorna lo stato del record su ADCAVV03:
                 - Codice RAV = ws_ciderav_new (il codice RAV calcolato)
                 - FlagAttribRav = ws_flag_attr (0 o 1)
                 """
                upd_tab_avv03 = (
                    self.engine.dataset("ADCAVV03")
                    .filter_by("prog", "=", row.get("prog"))
                    .filter_by("codiceRavMin", "=", row.get("codiceRavMin"))
                    .filter_by("codiceRavMax", "=", row.get("codiceRavMax"))
                    .compile_update({
                        "codiceRav": ctx.ws_ciderav_new,
                        "flagAttribRav": ctx.ws_flag_attr,
                        "timestampUpd": current_system_date
                    })
                )

                righe_impattate = self.engine.execute_mutation(upd_tab_avv03, depth=depth + 1)
                BatchLogger.info("UPD-RAV-AVV03",
                                 f"UPDATE ADCAVV03 -> RAV = {ctx.ws_ciderav_new} (Righe impattate: {righe_impattate})",
                                 depth=depth,
                                 is_last=is_last)

