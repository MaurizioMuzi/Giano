# processes/formazione_avviso/step_imp_errore.py
from datetime import datetime, date
from typing import List, Any, Iterator
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

        try:
            # 1. Aggiorna lo stato e l'errore dell'atto corrente su ADCFRT01 e ADCFRT10
            self._aggiorna_stato_t01(cges, catt_primario, coderr_primario, depth=depth + 1)
            self._aggiorna_stato_t10(cges, catt_primario, depth=depth + 1)

            # 2. Equivalente COBOL OPEN CURT01 -> FETCH -> AGGIORNA ALTRI ATTI CON EXX399
            self._scarta_atti_correlati_avviso(ctx, cges, catt_primario, depth=depth + 1)

            # 3. Imposta switch / indicatori di errore sul contesto
            ctx.indic_errore = "X"
            ctx.sw_errore = 1

        except Exception as err:
            BatchLogger.error(
                "IMP-ERRORE",
                f"Errore critico durante l'impostazione errore per avviso [{ctx.ws_annoavv}/{ctx.ws_progavv}] (CATT={catt_primario}): {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("IMP-ERRORE", "Rollback transazionale eseguito a fronte del fallimento scarto", depth=depth)
                except Exception as rollback_err:
                    BatchLogger.error("IMP-ERRORE", f"Fallito il rollback: {rollback_err}", depth=depth)

            ctx.indic_errore = "X"
            ctx.sw_errore = 1
            return -1

    # =========================================================================
    # METODI DI COORDINAMENTO LOGICO
    # =========================================================================
    def _aggiorna_stato_t01(self, cges: str, catt: str, coderr: str, depth: int) -> int:
        """Equivalente di PERFORM AGGIORNA-STATO-T01."""
        return self._db_update_t01_errore(cges, catt, coderr, depth=depth)

    def _aggiorna_stato_t10(self, cges: str, catt: str, depth: int) -> int:
        """Equivalente di PERFORM AGGIORNA-STATO-T10."""
        return self._db_update_t10_errore(cges, catt, depth=depth)

    def _scarta_atti_correlati_avviso(self, ctx: FormazioneAvvisoContext, cges: str, catt_escluso: str, depth: int) -> None:
        """
        Emulazione cursore CURT01:
        Cerca tutti gli altri atti di ADCFRT01 appartenenti allo stesso avviso (ancora in stato '0I')
        e applica l'errore a catena 'EXX399'.
        """
        t01_map = self.engine.get_table_map("ADCFRT01")
        atti_correlati = []

        for chunk in self._db_stream_curt01_correlati(ctx, cges, depth=depth):
            for raw_row in chunk:
                r = t01_map.normalize(raw_row)
                catt = r.get("codiceAtto")
                if catt != catt_escluso:
                    atti_correlati.append(catt)

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


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_update_t01_errore(self, cges: str, catt: str, coderr: str, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato e codice errore su ADCFRT01."""
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
            BatchLogger.error(
                "DB-UPD-T01-ERR",
                f"Errore DB durante l'aggiornamento stato T01 [CGES={cges}, CATT={catt}, STATO={self.ko_stato}, ERR={coderr}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_update_t10_errore(self, cges: str, catt: str, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato articoli su ADCFRT10."""
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
            BatchLogger.error(
                "DB-UPD-T10-ERR",
                f"Errore DB durante l'aggiornamento stato T10 [CGES={cges}, CATT={catt}, STATO={self.ko_stato}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_stream_curt01_correlati(self, ctx: FormazioneAvvisoContext, cges: str, depth: int) -> Iterator[List[Any]]:
        """Accesso atomico DB: cursore streaming per individuare tutti gli atti dello stesso avviso."""
        try:
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
            return self.engine.cursor_stream(query_curt01, buffer_size=100, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-STREAM-CURT01-ERR",
                f"Errore DB durante l'apertura del cursore atti correlati per avviso [{ctx.ws_annoavv}/{ctx.ws_progavv}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1