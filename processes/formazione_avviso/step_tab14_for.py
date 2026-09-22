# processes/formazione_avviso/step_tab14_for.py
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class CicloDettaglioTab14Step:
    """
    Ciclo interno di dettaglio:
    Scansiona e controlla i singoli record anagrafici della partita correlata.
    Reingegnerizza il ciclo PERFORM UNTIL FINE-FILE-T14 OR SCARTO-T14 OR (uguali...).
    """

    def __init__(self, engine):
        self.engine = engine

    def execute_dettaglio(self, ctx: FormazioneAvvisoContext, record_master: dict, depth: int = 5) -> None:
        t01_map = self.engine.get_table_map("ADCFRT01")
        t14_map = self.engine.get_table_map("ADCFRT14")

        # Memorizzazione dati master (WS-...)
        ws_cognome = (record_master.get("cognome") or "").strip()
        ws_nome = (record_master.get("nome") or "").strip()
        ws_indirizzo = (record_master.get("indAnagrafeTrib") or "").strip()
        ws_provincia = (record_master.get("siglaProvAnagrafeTrib") or "").strip()
        ws_codcomune = (record_master.get("comuneAnagrafeTrib") or "").strip()
        ws_cap = (record_master.get("capAnagrafeTrib") or "").strip()
        ws_localita = (record_master.get("locAnagrafeTrib") or "").strip()

        query_dett = (
            self.engine.dataset("ADCFRT01")
            .join(t14_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
            .select("gestione", "codiceAtto")
            .select_joined(
                "cognome", "nome", "indAnagrafeTrib", "siglaProvAnagrafeTrib",
                "comuneAnagrafeTrib", "capAnagrafeTrib", "locAnagrafeTrib"
            )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .filter_by("statoAttivita", "=", "0I")
            .filter_by_joined("codiceAnag", "=", "I")
            .order_by_desc("timestampInsStato")
            .with_uncommitted_read()
            .compile_select()
        )

        for chunk in self.engine.cursor_stream(query_dett, buffer_size=500, depth=depth):
            for raw_row in chunk:
                if getattr(ctx, "scarto_t14", False):
                    BatchLogger.warn("UNTIL-T14-FOR", "Interruzione ciclo: condizione SCARTO-T14 rilevata", depth=depth + 1)
                    return

                row_t14 = t14_map.normalize(raw_row)
                row_t01 = t01_map.normalize(raw_row)

                # Dati del record corrente su CDCFRT14
                scog = (row_t14.get("cognome") or "").strip()
                snom = (row_t14.get("nome") or "").strip()
                sindatr = (row_t14.get("indAnagrafeTrib") or "").strip()
                cproatr = (row_t14.get("siglaProvAnagrafeTrib") or "").strip()
                ccomatr = (row_t14.get("comuneAnagrafeTrib") or "").strip()
                ccapatr = (row_t14.get("capAnagrafeTrib") or "").strip()
                slocatr = (row_t14.get("locAnagrafeTrib") or "").strip()

                # Condizione di congruenza: dati identici al master
                indirizzo_uguale = (
                    ws_cognome == scog and
                    ws_nome == snom and
                    ws_indirizzo == sindatr and
                    ws_provincia == cproatr and
                    ws_codcomune == ccomatr and
                    ws_cap == ccapatr and
                    ws_localita == slocatr
                )

                if indirizzo_uguale:
                    BatchLogger.info(
                        "UNTIL-T14-FOR",
                        f"Atto CATT={row_t01.get('codiceAtto')}: recapito conforme al master",
                        depth=depth + 1
                    )
                    continue
                else:
                    BatchLogger.warn(
                        "UNTIL-T14-FOR",
                        f"Atto CATT={row_t01.get('codiceAtto')}: recapito disallineato per CF bloccato -> Errore EXX638",
                        depth=depth + 1
                    )
                    ctx.ws_erravv = "EXX638"
                    ctx.indic_errore = "X"
                    return

        BatchLogger.info("FINE-CICLO-T14-FOR", "Elaborazione dettaglio completata.", depth=depth)


class AllineamentoAnagrafeStep:
    """
    Ciclo principale di scansione avvisi correlati per CF (attivato se WS-COUNT-CF > 0).
    Acquisisce esclusivamente il primo record master (più recente) ed esegue il dettaglio.
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_dettaglio = CicloDettaglioTab14Step(engine)

    def execute_allineamento_for(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> None:
        BatchLogger.info("ALLINEA-INDIRIZZO", f"Verifica recapito anagrafico per CF bloccato: {ctx.ws_cfis}", depth=depth)
        t01_map = self.engine.get_table_map("ADCFRT01")
        t14_map = self.engine.get_table_map("ADCFRT14")

        # Selezione dell'avviso master cronologicamente più recente (FETCH FIRST 1 ROW ONLY)
        query_master = (
            self.engine.dataset("ADCFRT01")
            .join(t14_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
            .select_joined(
                "cognome", "nome", "indAnagrafeTrib", "siglaProvAnagrafeTrib",
                "comuneAnagrafeTrib", "capAnagrafeTrib", "locAnagrafeTrib"
            )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .filter_by("statoAttivita", "=", "0I")
            .filter_by_joined("codiceAnag", "=", "I")
            .order_by_desc("timestampInsStato")
            .limit(1)
            .with_uncommitted_read()
            .compile_select()
        )

        rows = self.engine.fetch(query_master, depth=depth)
        if not rows:
            BatchLogger.warn("MASTER-T14-FOR", "Nessun record anagrafico master individuato su CDCFRT14", depth=depth)
            return

        raw_master = rows[0]
        master_row = {**t14_map.normalize(raw_master), **t01_map.normalize(raw_master)}

        BatchLogger.info(
            "MASTER-T14-FOR",
            f"Record Master selezionato: CATT={master_row.get('codiceAtto')} | "
            f"CGES={master_row.get('gestione')} | DINF={master_row.get('dataInf')} | "
            f"Nominativo: {master_row.get('cognome')} {master_row.get('nome')}",
            depth=depth + 1
        )

        # Invocazione del ciclo di controllo sui record di dettaglio
        self.step_dettaglio.execute_dettaglio(ctx, master_row, depth=depth + 1)