# processes/formazione_ruoli/step_key_uguale.py
from typing import Optional, Dict, Any
from core.batch_logger import BatchLogger
from .context import FormazioneRuoliContext


class CicloDettaglioKeyUStep:
    """
    Verifica esistenza dell'avviso di addebito in stato postalizzato.
    Viene effettuato il controllo di avvenuta postalizzazione --> VERIFICA-AVD-POST
    Nel caso in cui l'avviso sia postalizzato si procede nell'elaborazione (CICLO-PRINCIPALE / CNTR-2-CHIAVE),
    altrimenti l'avviso viene deinfasato (LEGGI-TAB-ERRORE / DEINFASA-ANNULLA) impostando lo stato '0X'.
    """

    def __init__(self, engine):
        self.engine = engine

    def execute_controllo_flusso(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict] = None,
                                 depth: int = 4) -> None:
        """
        Struttura principale corrispondente a:
            PERFORM VERIFICA-AVD-POST THRU VERIFICA-AVD-POST-EX
            IF WS-VER-OK = 1
               PERFORM CICLO-PRINCIPALE    THRU CICLO-PRINCIPALE-EX
               IF NOT ERRORE
                  PERFORM CNTR-2-CHIAVE    THRU CNTR-2-CHIAVE-EX
               END-IF
            ELSE
               IF WS-VER-ER = 1
                  PERFORM LEGGI-TAB-ERRORE THRU LEGGI-TAB-ERRORE-EX
                  PERFORM DEINFASA-ANNULLA THRU DEINFASA-ANNULLA-EX
               END-IF
            END-IF
        """
        BatchLogger.info("VERIFICA-POST", f"Avvio controllo postalizzazione per Atto CATT={row_t01.get('codiceAtto')}",
                         depth=depth)

        # 1. VERIFICA-AVD-POST
        self._verifica_avd_post(ctx, row_t01, depth=depth + 1)

        # 2. IF WS-VER-OK = 1
        if ctx.ws_ver_ok == 1:
            BatchLogger.info("ESITO-VERIFICA",
                             "Postalizzazione accertata (WS-VER-OK = 1) -> Procedo con CICLO-PRINCIPALE",
                             depth=depth + 1)

            # PERFORM CICLO-PRINCIPALE THRU CICLO-PRINCIPALE-EX
            self._ciclo_principale(ctx, row_t01, row_t10, depth=depth + 1)

            # IF NOT ERRORE
            if not getattr(ctx, "errore", False):
                # PERFORM CNTR-2-CHIAVE THRU CNTR-2-CHIAVE-EX
                self._cntr_2_chiave(ctx, row_t01, row_t10, depth=depth + 2)
            else:
                BatchLogger.warn("CNTR-CHIAVE", "Rilevata condizione di ERRORE: controllo seconda chiave saltato",
                                 depth=depth + 2)

        # 3. ELSE: IF WS-VER-ER = 1
        elif ctx.ws_ver_er == 1:
            BatchLogger.warn("ESITO-VERIFICA",
                             "Postalizzazione assente/irregolare (WS-VER-ER = 1) -> Eseguo deinfasamento",
                             depth=depth + 1)

            # PERFORM LEGGI-TAB-ERRORE THRU LEGGI-TAB-ERRORE-EX
            self._leggi_tab_errore(ctx, row_t01, depth=depth + 1)

            # PERFORM DEINFASA-ANNULLA THRU DEINFASA-ANNULLA-EX
            self._deinfasa_annulla(ctx, row_t01, row_t10, depth=depth + 1)


    def _verifica_avd_post(self, ctx: FormazioneRuoliContext, row_t01: dict, depth: int) -> None:
        """
        Equivalente del paragrafo VERIFICA-AVD-POST:
        Verifica se l'avviso risulta postalizzato
        """

        t03_map = self.engine.get_table_map("ADCFRT03")
        v12_map = self.engine.get_table_map("ADCAVV12")

        # Reset variabili e contatori dell'avviso corrente con isolamento del singolo credito
        ctx.ws_cesaavv = row_t01.get('codEsattoriaAvviso')
        ctx.ws_acar = row_t01.get('annoCarico')
        ctx.ws_ncar = row_t01.get('numCarico')
        ctx.ws_nchkcar = row_t01.get('numChkCarico')

        ctx.ws_prov = ctx.ws_cesaavv - 300

        query_post = (
            self.engine.dataset("ADCFRT03")
            .join(v12_map, alias_self="A", alias_target="B")
            .select_joined(
                "statoLettera", "codConcessione", "codErr", "codRav", "identificativoAvviso"
            )
            .filter_by("codConcessione", "=", ctx.ws_prov)
            .filter_by("annoCarico", "=", ctx.ws_acar)
            .filter_by("numCarico", "=", ctx.ws_ncar)
            .filter_by("numChkCarico", "=", ctx.ws_nchkcar)
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        record_art_totali = 0
        first_record = True
        avviso_interrotto_per_errore = False

        res = self.engine.fetch(query_post, depth=depth)

        if not res:
            ctx.ws_flgblk = "0"
            BatchLogger.info("CNTR-BLOCCO-CF", "Record CDCFRT62 assente -> CF non bloccato (WS-FLGBLK='0')",
                             depth=depth)
            return 0

        BatchLogger.debug(
            "VERIFICA-AVD-POST",
            f"Atto={row_t01.get('codiceAtto')} -> WS-VER-OK={ctx.ws_ver_ok}, WS-VER-ER={ctx.ws_ver_er}",
            depth=depth
        )

    def _ciclo_principale(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict],
                          depth: int) -> None:
        """Equivalente del paragrafo CICLO-PRINCIPALE."""
        BatchLogger.info("CICLO-PRINCIPALE", f"Esecuzione ciclo principale per atto {row_t01.get('codiceAtto')}",
                         depth=depth)
        # Resetta o valorizza flag errore se necessario
        ctx.errore = False
        # Logica operativa principale del ciclo...

    def _cntr_2_chiave(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict], depth: int) -> None:
        """
        Equivalente del paragrafo CNTR-2-CHIAVE:
        Controllo della rottura della seconda chiave composita.
        """
        BatchLogger.info("CNTR-2-CHIAVE", "Verifica della seconda chiave avviso", depth=depth)

        t10 = row_t10 or {}
        # Verifica congruenza con le variabili salvate nel contesto
        chiave_uguale = (
                ctx.ws_cesa == row_t01.get("codEsattoria") and
                ctx.ws_feur == row_t01.get("flgEuro") and
                ctx.ws_cges == t10.get("gestione") and
                ctx.ws_cfasamm == t10.get("codFasAmm") and
                ctx.ws_ntotrat == t10.get("numTotRate")
        )

        if not chiave_uguale:
            BatchLogger.debug("CNTR-2-CHIAVE", "Rilevata discrepanza sulla seconda chiave", depth=depth + 1)
            # Logica rottura o memorizzazione nuove chiavi

    def _leggi_tab_errore(self, ctx: FormazioneRuoliContext, row_t01: dict, depth: int) -> None:
        """
        Equivalente del paragrafo LEGGI-TAB-ERRORE:
        Recupera il codice o la descrizione dell'errore associato alla mancata postalizzazione.
        """
        BatchLogger.info("LEGGI-TAB-ERRORE", "Lettura causale di scarto per mancata postalizzazione", depth=depth)
        # Imposta nel contesto l'errore da scrivere su ADCFRT01 (es. codice '0X' o codice specifico)
        ctx.cod_errore_post = getattr(ctx, "cod_errore_post", "0X")

    def _deinfasa_annulla(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict],
                          depth: int) -> None:
        """
        Equivalente del paragrafo DEINFASA-ANNULLA:
        Imposta lo stato '0X' sia su ADCFRT01 che su ADCFRT10 e traccia l'errore su ADCFRT01.
        """
        cges = row_t01.get("gestione")
        catt = row_t01.get("codiceAtto")

        BatchLogger.warn("DEINFASA-ANNULLA",
                         f"Deinfasamento e annullamento per Atto CATT={catt}, CGES={cges} -> Stato '0X'", depth=depth)

        # 1. Aggiornamento ADCFRT01: imposta stato '0X' ed eventuale codice errore
        upd_t01 = (
            self.engine.dataset("ADCFRT01")
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .compile_update({
                "statoAttivita": "0X",
                "codiceErrore": getattr(ctx, "cod_errore_post", "0X")
            })
        )
        righe_t01 = self.engine.execute_mutation(upd_t01, depth=depth + 1)
        BatchLogger.info("DEINFASA-ANNULLA", f"UPDATE ADCFRT01 CATT={catt} -> Righe impattate: {righe_t01}",
                         depth=depth + 1)

        # 2. Aggiornamento ADCFRT10: imposta stato '0X'
        upd_t10 = (
            self.engine.dataset("ADCFRT10")
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .compile_update({
                "statoAttivita": "0X"
            })
        )
        righe_t10 = self.engine.execute_mutation(upd_t10, depth=depth + 1)
        BatchLogger.info("DEINFASA-ANNULLA", f"UPDATE ADCFRT10 CATT={catt} -> Righe impattate: {righe_t10}",
                         depth=depth + 1)