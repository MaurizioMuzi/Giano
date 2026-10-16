# processes/formazione_ruoli/step_key_uguale.py
from datetime import datetime, date
from decimal import Decimal
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

        # Formattazione con zero-padding a lunghezza fissa COBOL:
        cesa = str(ctx.ws_cesaavv or 0).strip().zfill(3)
        anno = str(ctx.ws_acar or 0).strip().zfill(4)
        numavv = str(ctx.ws_ncar or 0).strip().zfill(8)
        chkcar = str(ctx.ws_nchkcar or 0).strip().zfill(2)
        app_num = "0".zfill(3)

        # Composizione di ws_idavv (20 caratteri complessivi)
        ctx.ws_idavv = f"{cesa}{anno}{numavv}{chkcar}{app_num}"

        ctx.ws_prov = ctx.ws_cesaavv - 300

        try:
            query_post = (
                self.engine.dataset("ADCFRT03")
                .join(v12_map, alias_self="A", alias_target="B")
                .select_joined(
                    "statoLettera", "codConcessione", "codErr", "codRav", "identificativoAvviso"
                )
                .filter_by("codConcessione", "=", ctx.ws_prov)
                .filter_by("annoCarico", "=", ctx.ws_acar)
                .filter_by("numCarico", "=", ctx.ws_ncar)
                .filter_by_joined("identificativoAvviso", "=", ctx.ws_idavv)
                .filter_by_joined("statoLettera", "IN", ["2", "3"])
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )

            res = self.engine.fetch(query_post, depth=depth)

            # Corrisponde a: IF NOT SQL-TUTTO-OK AND SQL-KEY-NON-TROVATA (record non trovato)
            if not res:
                ctx.ws_ver_ok = 0
                ctx.ws_ver_er = 0
            else:
                # Corrisponde a: ELSE (SQL-TUTTO-OK -> record trovato)
                row = res[0] if isinstance(res, list) else res
                stato_lettera = str(row.get("statoLettera") or "").strip()

                # IF CSTALET OF CDCAVV12 = '2'
                if stato_lettera == "2":
                    ctx.ws_ver_ok = 1
                # IF CSTALET OF CDCAVV12 = '3'
                elif stato_lettera == "3":
                    ctx.ws_ver_ok = 0
                    ctx.ws_ver_er = 1

        except Exception as ex:
            # Corrisponde al ramo ELSE di SQL-KEY-NON-TROVATA (errore SQL/Database):
            # PERFORM SEGNALA-LOG-001 THRU SEGNALA-LOG-001-EX
            # MOVE ZERO TO WS-VER-OK
            # MOVE 'X' TO INDIC-ERRORE
            ctx.ws_ver_ok = 0
            ctx.indic_errore = "X"
            BatchLogger.error(
                "SEGNALA-LOG-001",
                f"Errore DB durante la verifica avviso (Atto={row_t01.get('codiceAtto')}): {ex}",
                depth=depth
            )

        finally:
            BatchLogger.debug(
                "VERIFICA-AVD-POST",
                f"Atto={row_t01.get('codiceAtto')} -> WS-VER-OK={getattr(ctx, 'ws_ver_ok', None)}, "
                f"WS-VER-ER={getattr(ctx, 'ws_ver_er', None)}, INDIC-ERRORE={getattr(ctx, 'indic_errore', '')}",
                depth=depth
            )


    def _ciclo_principale(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict],
                          depth: int) -> None:
        """Equivalente del paragrafo CICLO-PRINCIPALE."""
        BatchLogger.info("CICLO-PRINCIPALE", f"Esecuzione ciclo principale per atto {row_t01.get('codiceAtto')}",
                         depth=depth)
        # Resetta o valorizza flag errore se necessario
        ctx.errore = False

        # 1. Aggiornamento ADCFRT01 (AGGIORNA-TAB01)
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        try:
            upd_t01 = (
                self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_update({
                    "annoRifRuolo": ws_dcon,
                    "numRuolo": ctx.ws_ctr_nruo,
                    "statoAttivita": "0P",
                    "timestampVarStato": datetime.now(),
                    "dataTransizioneStato": date.today()
                })
            )
            righe_t01 = self.engine.execute_mutation(upd_t01, depth=depth + 1)
            BatchLogger.info(
                "Formazione ruoli eseguita",
                (
                    f"TABELLA ADCFRT01 CGES={ctx.ws_cges} "
                    f"CATT={ctx.ws_key_catt} "
                    f"-> Righe impattate: {righe_t01}"
                ),
                depth=depth + 1
            )
        except Exception as ex:
            BatchLogger.error(
                "Formazione ruoli",
                f"Errore durante l'aggiornamento ADCFRT01 per Atto CATT={ctx.ws_catt}, CGES={ctx.ws_cges}: {ex}",
                depth=depth + 1
            )
            ctx.indic_errore = "X"

        # 2. Controllo del tributo
        row_t10["impTributoCalc"] = row_t10.get("impTributo")
        ctx.indic_errore = " "
        val_tributo = row_t10.get("impTributoCalcolato") or row_t10.get("impTributoCalc") or row_t10.get("ITRBCAL") or 0
        ctx.ws_t02_itrbcal = Decimal(str(val_tributo))

        natura_tributo = str(row_t10.get("codNaturaTrb") or row_t10.get("CNATTRB") or "").strip().upper()
        importo_calcolato = ctx.ws_t02_itrbcal

        match natura_tributo:
            case "I":
                ctx.ws_t02_itrb_t += importo_calcolato
            case "S":
                # La sanzione di una-tantum ha sempre il tetto a zero, quindi non sarà adeguata
                ctx.ws_t02_isan_t += importo_calcolato
            case "T":
                ctx.ws_t02_iint_t += importo_calcolato
            case _:
                # Corrisponde a WHEN OTHER
                ctx.ws_t02_ialt_t += importo_calcolato

        ctx.ws_t10_iaggant = Decimal("0")
        ctx.ws_t10_iaggtot = Decimal("0")

        # 3. Aggiornamento ADCFRT10 (AGGIORNA-TAB10)
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        try:
            upd_t10_0P = (
                self.engine.dataset("ADCFRT10")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .filter_by("progArticolo", "=", ctx.ws_key_nprgart)
                .compile_update({
                    "statoAttivita": "0P",
                    "impTributoCalc": row_t10["impTributoCalc"],
                    "impAggioAnt": ctx.ws_t10_iaggant,
                    "impAggioTot": ctx.ws_t10_iaggtot,
                    "timestampUpd": datetime.now()
                })
            )
            righe_t10_0P = self.engine.execute_mutation(upd_t10_0P, depth=depth + 1)
            BatchLogger.info(
                "Formazione ruoli eseguita",
                (
                    f"TABELLA ADCFRT10 CGES={ctx.ws_cges} "
                    f"CATT={ctx.ws_key_catt} "
                    f"NPRGART={ctx.ws_key_nprgart} "
                    f"-> Righe impattate: {righe_t10_0P}"
                ),
                depth=depth + 1
            )
        except Exception as ex:
            BatchLogger.error(
                "Formazione ruoli",
                f"Errore durante l'aggiornamento ADCFRT10 per Atto CATT={ctx.ws_catt}, CGES={ctx.ws_cges}, NPRGART={ctx.ws_key_nprgart}: {ex}",
                depth=depth + 1
            )
            ctx.indic_errore = "X"

        # 1. IAGGANT -> WS-T02-IAGGANT / WS-T02-IAGGANT-T
        val_iaggant = row_t10.get("impAggioAnt") or row_t10.get("IAGGANT") or 0
        ctx.ws_t02_iaggant = Decimal(str(val_iaggant))
        ctx.ws_t02_iaggant_t += ctx.ws_t02_iaggant

        # 2. IAGGIO -> WS-T02-IAGGTOT / WS-T02-IAGGTOT-T (modifica 221210)
        val_iaggtot = row_t10.get("impAggio") or row_t10.get("IAGGIO") or 0
        ctx.ws_t02_iaggtot = Decimal(str(val_iaggtot))
        ctx.ws_t02_iaggtot_t += ctx.ws_t02_iaggtot

        # 3. IARR -> WS-T02-IARR / WS-T02-IARR-T
        val_iarr = row_t10.get("impArrotondamento") or row_t10.get("IARR") or 0
        ctx.ws_t02_iarr = Decimal(str(val_iarr))
        ctx.ws_t02_iarr_t += ctx.ws_t02_iarr


    def _cntr_2_chiave(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict], depth: int) -> None:
        """
        Equivalente del paragrafo CNTR-2-CHIAVE:
        Controllo della rottura della seconda chiave composita.
        """
        BatchLogger.info("CNTR-2-CHIAVE", "Verifica della seconda porzione di chiave avviso", depth=depth)

        if not row_t10:
            return False

        t01 = row_t01 or {}
        t10 = row_t10

        # Verifica congruenza con le variabili salvate nel contesto
        chiave_uguale = (
                ctx.ws_cesa == t01.get("codEsattoria") and
                ctx.ws_feur == t01.get("flgEuro") and
                ctx.ws_cges == t10.get("gestione") and
                ctx.ws_ctrbcnc == t10.get("codTributoCnc") and
                ctx.ws_crat == t10.get("codRata") and
                ctx.ws_ntotrat == t10.get("numTotRate") and
                ctx.ws_fres == t10.get("flgResiduo") and
                ctx.ws_cfasamm == t10.get("codFasAmm")
        )

        if chiave_uguale:
            # Esecuzione dei MOVE verso WS-KEY
            ctx.ws_key_ctrbcnc = t10.get("codTributoCnc")
            ctx.ws_key_crat = t10.get("codRata")
            ctx.ws_key_ntotrat = t10.get("numTotRate")
            ctx.ws_key_fres = t10.get("flgResiduo")
            ctx.ws_key_cfasamm = t10.get("codFasAmm")
            ctx.ws_key_cesa = t01.get("codEsattoria")

            ctx.ws_nart += 1
            val_t10_itrb = row_t10.get("impTributo") or row_t10.get("ITRB") or 0
            ctx.ws_t10_itrb = Decimal(str(val_t10_itrb))

            self.accumula_importi_t10(ctx, row_t10, depth=depth + 1)
        #else:


        if not chiave_uguale:
            BatchLogger.debug("CNTR-2-CHIAVE", "Rilevata discrepanza sulla seconda chiave", depth=depth + 1)
            # Logica rottura o memorizzazione nuove chiavi


    def accumula_importi_t10(
            self,
            ctx: FormazioneRuoliContext,
            row_t10: Dict[str, Any],
            depth: int = 4
    ) -> None:
        """
        Esegue la lettura, la normalizzazione e l'accumulo contabile
        dei singoli importi di riga T10 nei rispettivi totalizzatori di contesto:
          - ITRBCAL -> WS-T10-ITRB    / WS-T10-ITRB-T
          - IAGGIO  -> WS-T10-IAGGTOT / WS-T10-IAGGTOT-T
          - IAGGANT -> WS-T10-IAGGANT / WS-T10-IAGGANT-T
          - IARR    -> WS-T10-IARR    / WS-T10-IARR-T
        """
        # 1. ITRBCAL -> WS-T10-ITRB / WS-T10-ITRB-T
        val_itrbcal = row_t10.get("impTributoCalcolato") or row_t10.get("impTributoCalc") or row_t10.get("ITRBCAL") or 0
        ctx.ws_t10_itrb = Decimal(str(val_itrbcal))
        ctx.ws_t10_itrb_t += ctx.ws_t10_itrb

        # 2. IAGGIO -> WS-T10-IAGGTOT / WS-T10-IAGGTOT-T
        val_iaggio = row_t10.get("impAggio") or row_t10.get("IAGGIO") or 0
        ctx.ws_t10_iaggtot = Decimal(str(val_iaggio))
        ctx.ws_t10_iaggtot_t += ctx.ws_t10_iaggtot

        # 3. IAGGANT -> WS-T10-IAGGANT / WS-T10-IAGGANT-T
        val_iaggant = row_t10.get("impAggioAnt") or row_t10.get("IAGGANT") or 0
        ctx.ws_t10_iaggant = Decimal(str(val_iaggant))
        ctx.ws_t10_iaggant_t += ctx.ws_t10_iaggant

        # 4. IARR -> WS-T10-IARR / WS-T10-IARR-T (corretto l'uso di val_iarr)
        val_iarr = row_t10.get("impArrotondamento") or row_t10.get("IARR") or 0
        ctx.ws_t10_iarr = Decimal(str(val_iarr))
        ctx.ws_t10_iarr_t += ctx.ws_t10_iarr

        BatchLogger.debug(
            "ACCUMULA-T10",
            f"Accumulo riga completato: ITRB={ctx.ws_t10_itrb}, IAGGTOT={ctx.ws_t10_iaggtot}, "
            f"IAGGANT={ctx.ws_t10_iaggant}, IARR={ctx.ws_t10_iarr}",
            depth=depth
        )

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