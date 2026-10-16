# processes/formazione_avviso/step_imp_errore.py
from datetime import datetime, date
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class ImpostaErroreAvvisoStep:
    """
    Reingegnerizzazione del paragrafo COBOL IMP-ERRORE:
    - Imposta l'errore primario (WS-ERRAVV) e aggiorna lo stato su T01 e T10 per l'atto corrente.
    - Scansiona (equivalente di CURT01) tutti gli altri atti legati allo stesso avviso
      assegnando loro il codice errore a cascata 'EXX399' e aggiornando gli stati su T01 e T10.
    - Valorizza l'indicatore di errore su contesto per impedire il consolidamento contabile.
    """

    def __init__(self, engine, ko_stato: str = "0X"):
        self.engine = engine
        self.ko_stato = ko_stato

    def execute(self, ctx: FormazioneAvvisoContext, row_t01: dict, depth: int = 4) -> None:
        cges = row_t01.get("gestione")
        catt_primario = row_t01.get("codiceAtto")
        coderr_primario = ctx.ws_erravv.strip() or "EXX999"

        BatchLogger.error(
            "IMP-ERRORE",
            f"Avvio scarto avviso [{ctx.ws_annoavv}/{ctx.ws_progavv}] su atto principale {catt_primario} con errore '{coderr_primario}'",
            depth=depth
        )

        # 1. Aggiorna lo stato e l'errore dell'atto corrente su ADCFRT01 e ADCFRT10
        self._aggiorna_stato_t01(cges, catt_primario, coderr_primario, depth=depth + 1)
        self._aggiorna_stato_t10(cges, catt_primario, depth=depth + 1)

        # 2. Equivalente COBOL OPEN CURT01 -> FETCH -> AGGIORNA ALTRI ATTI CON EXX399
        self._scarta_atti_correlati_avviso(ctx, cges, catt_primario, depth=depth + 1)

        # 3. Imposta switch / indicatori di errore sul contesto
        ctx.indic_errore = "X"
        ctx.sw_errore = 1

    def _aggiorna_stato_t01(self, cges: str, catt: str, coderr: str, depth: int) -> int:
        """Equivalente di PERFORM AGGIORNA-STATO-T01."""
        try:
            upd_t01 = (
                self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", cges)
                .filter_by("codiceAtto", "=", catt)
                .compile_update({
                    "statoAttivita": self.ko_stato,
                    "codiceErrore": coderr,
                    "timestampVarStato": datetime.now(),
                    "dataTransizioneStato": date.today()
                })
            )
            rows = self.engine.execute_mutation(upd_t01, depth=depth)
            BatchLogger.debug("UPD-T01", f"T01 aggiornato: CATT={catt}, STATO={self.ko_stato}, ERR={coderr} (Rows: {rows})", depth=depth)
            return rows
        except Exception as err:
            BatchLogger.error("UPD-T01", f"Errore DB durante l'aggiornamento stato T01 per atto {catt}: {err}", depth=depth)
            return -1

    def _aggiorna_stato_t10(self, cges: str, catt: str, depth: int) -> int:
        """Equivalente di PERFORM AGGIORNA-STATO-T10."""
        try:
            upd_t10 = (
                self.engine.dataset("ADCFRT10")
                .filter_by("gestione", "=", cges)
                .filter_by("codiceAtto", "=", catt)
                .compile_update({
                    "statoArticolo": self.ko_stato,
                    "timestampUpd": datetime.now()
                })
            )
            rows = self.engine.execute_mutation(upd_t10, depth=depth)
            BatchLogger.debug("UPD-T10", f"T10 aggiornato: CATT={catt}, STATO={self.ko_stato} (Rows: {rows})", depth=depth)
            return rows
        except Exception as err:
            BatchLogger.error("UPD-T10", f"Errore DB durante l'aggiornamento stato T10 per atto {catt}: {err}", depth=depth)
            return -1

    def _scarta_atti_correlati_avviso(self, ctx: FormazioneAvvisoContext, cges: str, catt_escluso: str, depth: int) -> None:
        """
        Emulazione cursore CURT01:
        Cerca tutti gli altri atti di ADCFRT01 appartenenti allo stesso avviso (ancora in stato '0I')
        e applica l'errore a catena 'EXX399'.
        """
        t01_map = self.engine.get_table_map("ADCFRT01")
        query_curt01 = (
            self.engine.dataset("ADCFRT01")
            .select("gestione", "codiceAtto", "statoAttivita")
            .filter_by("gestione", "=", cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .filter_by("statoAttivita", "=", "0I")
            .order_by("gestione", "annoAvviso", "progAvviso", "numEspAvviso")
            .with_uncommitted_read()
            .compile_select()
        )

        atti_correlati = []
        for chunk in self.engine.cursor_stream(query_curt01, buffer_size=100, depth=depth):
            for raw_row in chunk:
                r = t01_map.normalize(raw_row)
                atti_correlati.append(r.get("codiceAtto"))

        if not atti_correlati:
            return

        BatchLogger.info(
            "SCARTO-CASCADE",
            f"Trovati {len(atti_correlati)} atti correlati per avviso [{ctx.ws_annoavv}/{ctx.ws_progavv}]. Assegnazione errore cascata 'EXX399'",
            depth=depth
        )

        for catt_corr in atti_correlati:
            self._aggiorna_stato_t01(cges, catt_corr, coderr="EXX399", depth=depth + 1)
            self._aggiorna_stato_t10(cges, catt_corr, depth=depth + 1)