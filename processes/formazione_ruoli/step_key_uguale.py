# processes/formazione_ruoli/step_key_uguale.py
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
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
        catt = row_t01.get("codiceAtto")
        BatchLogger.info("VERIFICA-POST", f"Avvio controllo postalizzazione per Atto CATT={catt}", depth=depth)

        try:
            # 1. VERIFICA-AVD-POST
            self._verifica_avd_post(ctx, row_t01, depth=depth + 1)

            # 2. IF WS-VER-OK = 1
            if ctx.ws_ver_ok == 1:
                BatchLogger.info(
                    "ESITO-VERIFICA",
                    "Postalizzazione accertata (WS-VER-OK = 1) -> Procedo con CICLO-PRINCIPALE",
                    depth=depth + 1
                )

                # PERFORM CICLO-PRINCIPALE THRU CICLO-PRINCIPALE-EX
                self._ciclo_principale(ctx, row_t01, row_t10, depth=depth + 1)

                # IF NOT ERRORE
                #if not getattr(ctx, "errore", False):
                if ctx.indic_errore != "X":
                    # PERFORM CNTR-2-CHIAVE THRU CNTR-2-CHIAVE-EX
                    self._cntr_2_chiave(ctx, row_t01, row_t10, depth=depth + 2)
                else:
                    BatchLogger.warn(
                        "CNTR-CHIAVE",
                        "Rilevata condizione di ERRORE: controllo seconda chiave saltato",
                        depth=depth + 2
                    )

            # 3. ELSE: IF WS-VER-ER = 1
            elif ctx.ws_ver_er == 1:
                BatchLogger.warn(
                    "ESITO-VERIFICA",
                    "Postalizzazione assente/irregolare (WS-VER-ER = 1) -> Eseguo deinfasamento",
                    depth=depth + 1
                )

                # PERFORM LEGGI-TAB-ERRORE THRU LEGGI-TAB-ERRORE-EX
                self._leggi_tab_errore(ctx, row_t01, depth=depth + 1)

                # PERFORM DEINFASA-ANNULLA THRU DEINFASA-ANNULLA-EX
                self._deinfasa_annulla(ctx, row_t01, row_t10, depth=depth + 1)



        except Exception as err:
            BatchLogger.error(
                "VERIFICA-POST",
                f"Errore critico durante il controllo flusso per Atto CATT={catt}: {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("VERIFICA-POST", "Rollback transazionale eseguito a fronte del fallimento", depth=depth)
                except Exception as rollback_err:
                    BatchLogger.error("VERIFICA-POST", f"Fallito il rollback: {rollback_err}", depth=depth)

            ctx.indic_errore = "X"
            ctx.errore = True
            #raise err
            return -1

    def _verifica_avd_post(self, ctx: FormazioneRuoliContext, row_t01: dict, depth: int) -> None:
        """
        Equivalente del paragrafo VERIFICA-AVD-POST:
        Verifica se l'avviso risulta postalizzato
        """
        v12_map = self.engine.get_table_map("ADCAVV12")

        # Reset variabili e contatori dell'avviso corrente con isolamento del singolo credito
        ctx.ws_cesaavv = row_t01.get("codEsattoriaAvviso")
        ctx.ws_acar = row_t01.get("annoCarico")
        ctx.ws_ncar = row_t01.get("numCarico")
        ctx.ws_nchkcar = row_t01.get("numChkCarico")

        # Formattazione con zero-padding a lunghezza fissa COBOL:
        cesa = str(ctx.ws_cesaavv or 0).strip().zfill(3)
        anno = str(ctx.ws_acar or 0).strip().zfill(4)
        numavv = str(ctx.ws_ncar or 0).strip().zfill(8)
        chkcar = str(ctx.ws_nchkcar or 0).strip().zfill(2)
        app_num = "0".zfill(3)

        # Composizione di ws_idavv (20 caratteri complessivi)
        ctx.ws_idavv = f"{cesa}{anno}{numavv}{chkcar}{app_num}"
        ctx.ws_prov = (ctx.ws_cesaavv or 0) - 300

        try:
            res = self._db_fetch_verifica_post(ctx, v12_map, depth=depth)

            # Corrisponde a: IF NOT SQL-TUTTO-OK AND SQL-KEY-NON-TROVATA (record non trovato)
            if not res:
                ctx.ws_ver_ok = 0
                ctx.ws_ver_er = 0
            else:
                # Corrisponde a: ELSE (SQL-TUTTO-OK -> record trovato)
                row = res[0] if isinstance(res, list) else res
                stato_lettera = str(row.get("statoLettera") or "").strip()
                ctx.ws_codConcessione = str(row.get("codConcessione") or "").strip()
                ctx.ws_codErr = str(row.get("codErr") or "").strip()
                ctx.ws_codRav = str(row.get("codRav") or "").strip()
                ctx.ws_identificativoAvviso = str(row.get("identificativoAvviso") or "").strip()

                # IF CSTALET OF CDCAVV12 = '2'
                if stato_lettera == "2":
                    ctx.ws_ver_ok = 1
                # IF CSTALET OF CDCAVV12 = '3'
                elif stato_lettera == "3":
                    ctx.ws_ver_ok = 0
                    ctx.ws_ver_er = 1

        except Exception as ex:
            # Corrisponde al ramo ELSE di SQL-KEY-NON-TROVATA (errore SQL/Database):
            ctx.ws_ver_ok = 0
            BatchLogger.error(
                "SEGNALA-LOG-001",
                f"Errore DB durante la verifica avviso (Atto={row_t01.get('codiceAtto')}): {ex}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return

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
        catt = row_t01.get("codiceAtto")
        BatchLogger.info("CICLO-PRINCIPALE", f"Esecuzione ciclo principale per atto {catt}", depth=depth)
        ctx.errore = False

        # 1. Aggiornamento ADCFRT01 (AGGIORNA-TAB01)
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]

        if ctx.indic_errore != "X":
            righe_t01 = self._db_update_t01_ruolo(ctx, ws_dcon, depth=depth + 1)
            BatchLogger.info(
                "Formazione ruoli eseguita",
                (
                    f"TABELLA ADCFRT01 CGES={ctx.ws_cges} "
                    f"CATT={ctx.ws_key_catt} "
                    f"-> Righe impattate: {righe_t01}"
                ),
                depth=depth + 1
            )

        # 2. Controllo del tributo
        if row_t10:
            row_t10["impTributoCalc"] = row_t10.get("impTributo")
            val_tributo = row_t10.get("impTributoCalcolato") or row_t10.get("impTributoCalc") or row_t10.get("ITRBCAL") or 0
            ctx.ws_t02_itrbcal = Decimal(str(val_tributo))

            natura_tributo = str(row_t10.get("codNaturaTrb") or row_t10.get("CNATTRB") or "").strip().upper()
            importo_calcolato = ctx.ws_t02_itrbcal

            match natura_tributo:
                case "I":
                    ctx.ws_t02_itrb_t += importo_calcolato
                case "S":
                    ctx.ws_t02_isan_t += importo_calcolato
                case "T":
                    ctx.ws_t02_iint_t += importo_calcolato
                case _:
                    ctx.ws_t02_ialt_t += importo_calcolato

            ctx.ws_t10_iaggant = Decimal("0")
            ctx.ws_t10_iaggtot = Decimal("0")

            # 3. Aggiornamento ADCFRT10 (AGGIORNA-TAB10)
            righe_t10_0P = self._db_update_t10_ruolo(ctx, row_t10["impTributoCalc"], depth=depth + 1)
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

            # Accumulo importi di testata T02
            val_iaggant = row_t10.get("impAggioAnt") or row_t10.get("IAGGANT") or 0
            ctx.ws_t02_iaggant = Decimal(str(val_iaggant))
            ctx.ws_t02_iaggant_t += ctx.ws_t02_iaggant

            val_iaggtot = row_t10.get("impAggio") or row_t10.get("IAGGIO") or 0
            ctx.ws_t02_iaggtot = Decimal(str(val_iaggtot))
            ctx.ws_t02_iaggtot_t += ctx.ws_t02_iaggtot

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
            return

        t01 = row_t01 or {}
        t10 = row_t10

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
            self._imposta_comodi_key_t10(ctx, t01, t10)
            ctx.ws_nart += 1
            val_t10_itrb = row_t10.get("impTributo") or row_t10.get("ITRB") or 0
            ctx.ws_t10_itrb = Decimal(str(val_t10_itrb))
            self.accumula_importi_t10(ctx, row_t10, depth=depth + 1)
        else:
            BatchLogger.debug("CNTR-2-CHIAVE", "Rilevata discrepanza sulla seconda chiave", depth=depth + 1)
            self.valorizza_t09(ctx, row_t10, depth=depth + 1)
            self._imposta_comodi_key_t10(ctx, t01, t10)
            ctx.ws_nart += 1
            val_t10_itrb = row_t10.get("impTributo") or row_t10.get("ITRB") or 0
            ctx.ws_t10_itrb = Decimal(str(val_t10_itrb))
            self.accumula_importi_t10(ctx, row_t10, depth=depth + 1)


    def _imposta_comodi_key_t10(self, ctx: Any, t01: dict, t10: dict) -> None:
        """
        Valorizza le variabili di chiave e controllo nel context a partire dai record T01 e T10.
        """
        ctx.ws_key_ctrbcnc = t10.get("codTributoCnc") or t10.get("CTRB")
        ctx.ws_key_crat = t10.get("codRata") or t10.get("CRAT")
        ctx.ws_key_ntotrat = t10.get("numTotRate") or t10.get("NRAT")
        ctx.ws_key_fres = t10.get("flgResiduo") or t10.get("FRES")
        ctx.ws_key_cfasamm = t10.get("codFasAmm") or t10.get("CFASAMM")
        ctx.ws_key_cesa = t01.get("codEsattoria") or t01.get("CES")

    def accumula_importi_t10(self, ctx: FormazioneRuoliContext, row_t10: Dict[str, Any], depth: int = 4) -> None:
        """
        Esegue la lettura, la normalizzazione e l'accumulo contabile
        dei singoli importi di riga T10 nei rispettivi totalizzatori di contesto.
        """
        val_itrbcal = row_t10.get("impTributoCalcolato") or row_t10.get("impTributoCalc") or row_t10.get("ITRBCAL") or 0
        ctx.ws_t10_itrb = Decimal(str(val_itrbcal))
        ctx.ws_t10_itrb_t += ctx.ws_t10_itrb

        val_iaggio = row_t10.get("impAggio") or row_t10.get("IAGGIO") or 0
        ctx.ws_t10_iaggtot = Decimal(str(val_iaggio))
        ctx.ws_t10_iaggtot_t += ctx.ws_t10_iaggtot

        val_iaggant = row_t10.get("impAggioAnt") or row_t10.get("IAGGANT") or 0
        ctx.ws_t10_iaggant = Decimal(str(val_iaggant))
        ctx.ws_t10_iaggant_t += ctx.ws_t10_iaggant

        val_iarr = row_t10.get("impArrotondamento") or row_t10.get("IARR") or 0
        ctx.ws_t10_iarr = Decimal(str(val_iarr))
        ctx.ws_t10_iarr_t += ctx.ws_t10_iarr

        BatchLogger.debug(
            "ACCUMULA-T10",
            f"Accumulo riga completato: ITRB={ctx.ws_t10_itrb}, IAGGTOT={ctx.ws_t10_iaggtot}, "
            f"IAGGANT={ctx.ws_t10_iaggant}, IARR={ctx.ws_t10_iarr}",
            depth=depth
        )

    def valorizza_t09(self, ctx: FormazioneRuoliContext, row_t10: Dict[str, Any], depth: int = 4) -> None:
        """
        Esegue la valorizzazione dei campi prpepdeutici alla gestione della tabella ADCFRT09.
        """
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        ws_t09_icrc_t = ctx.ws_t10_itrb_t + ctx.ws_t10_iarr_t

        record_t09 = {}

        record_t09.update({
            "codEsattoria": ctx.ws_cesa,
            "annoRif": ws_dcon,
            "numRuolo": ctx.ws_ctr_nruo,
            "codTributoCnc": ctx.ws_ctrbcnc,
            "annoRifCont": ws_dcon,
            "numRate": ctx.ws_ntotrat,
            "codRata": ctx.ws_crat,
            "flgResiduo": ctx.ws_cfasamm,
            "impTributo": ctx.ws_t10_itrb_t,
            "numArticoli": ctx.ws_nart,
            "impAggioAnt": ctx.ws_t10_iaggant_t,
            "impAggioTot": ctx.ws_t10_iaggtot_t,
            "impArrotondamento": ctx.ws_t10_iarr_t,
            "impCarico": ws_t09_icrc_t
        })

        righe = self._db_insert_t09(record_t09, depth=depth)

        BatchLogger.info(
            "INSERISCE-T09",
            f"Inserimento ADCFRT09 completato (Righe inserite: {righe}): CESA={record_t09.get('codEsattoria')}, "
            f"ARIFRUO={record_t09.get('annoRif')}, NRUO={record_t09.get('numRuolo')}, "
            f"CTRBCNC={record_t09.get('codTributoCnc')}, ARIFCON={record_t09.get('annoRifCont')}, "
            f"NRAT={record_t09.get('numRate')}, CRAT={record_t09.get('codRata')}, "
            f"FRES={record_t09.get('flgResiduo')}",
            depth=depth
        )


    def _db_insert_t09(self, record_t09: Dict[str, Any], depth: int) -> int:
        try:
            ins = self.engine.dataset("ADCFRT09").compile_insert(record_t09)
            return self.engine.execute_mutation(ins, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-INS-T09",
                f"Errore insert ADCFRT09 [CESA={record_t09.get('codEsattoria')}, ARIFRUO={record_t09.get('annoRif')},"
                f" NRUO={record_t09.get('numRuolo')}, CTRBCNC={record_t09.get('codTributoCnc')},"
                f" ARIFCON={record_t09.get('annoRifCont')}, NRAT={record_t09.get('numRate')},"
                f" CRAT={record_t09.get('codRata')}, FRES={record_t09.get('flgResiduo')}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _leggi_tab_errore(self, ctx: FormazioneRuoliContext, row_t01: dict, depth: int) -> None:
        """Equivalente del paragrafo LEGGI-TAB-ERRORE."""
        BatchLogger.info("LEGGI-TAB-ERRORE", "Lettura per decodifica errore da impostare su ADCFRT01", depth=depth)

        try:
            t17_map = self.engine.get_table_map("ADCAVV17")
            queryErr = (
                self.engine.dataset("ADCAVV17")
                .select("codErrRuolo")
                .filter_by("codErr", "=", ctx.ws_codErr)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(queryErr, depth=depth)

            if rows:
                row_err = t17_map.normalize(rows[0])
                cod_err_estratto = str(row_err.get("codErrRuolo") or "").strip()
                # Valorizzazione della variabile di contesto
                ctx.ws_codErrRuo = cod_err_estratto

                BatchLogger.info(
                    "LEGGI-TAB-ERRORE",
                    f"Decodifica errore trovata su ADCAVV17: {ctx.ws_codErrRuo} per codErr={ctx.ws_codErr}",
                    depth=depth + 1
                )
            else:
                ctx.ws_codErrRuo = ""

                BatchLogger.warn(
                    "LEGGI-TAB-ERRORE",
                    f"Nessuna decodifica trovata su ADCAVV17 per codErr={ctx.ws_codErr}",
                    depth=depth + 1
                )

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-VERIF-POST-ERR",
                f"Errore DB durante verifica postalizzazione [CONC={ctx.ws_prov}, ANNO={ctx.ws_acar}, NUM={ctx.ws_ncar}, ID={ctx.ws_idavv}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _deinfasa_annulla(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict], depth: int) -> None:
        """
        Equivalente del paragrafo DEINFASA-ANNULLA:
        Imposta lo stato '0X' sia su ADCFRT01 che su ADCFRT10 e traccia l'errore su ADCFRT01.
        """
        cges = row_t01.get("gestione")
        catt = row_t01.get("codiceAtto")
        cod_err = getattr(ctx, "cod_errore_post", "0X")

        BatchLogger.info(
            "DEINFASA-ANNULLA",
            f"Deinfasamento e annullamento per Atto CATT={catt}, CGES={cges} -> Stato '0X'",
            depth=depth
        )

        righe_t01 = self._deinfasa_tab01(ctx, row_t01, depth=depth + 1)
        BatchLogger.info("DEINFASA-TAB01", f"UPDATE ADCFRT01 CATT={catt} -> Righe impattate: {righe_t01}", depth=depth + 1)

        righe_t10 = self._deinfasa_tab10(ctx, row_t10, depth=depth + 1)
        BatchLogger.info("DEINFASA-TAB10", f"UPDATE ADCFRT10 CATT={catt} -> Righe impattate: {righe_t10}", depth=depth + 1)


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_verifica_post(self, ctx: FormazioneRuoliContext, v12_map: Any, depth: int) -> List[Any]:
        """Accesso atomico DB: verifica presenza avviso postalizzato tramite ADCFRT03 join ADCAVV12."""
        try:
            query = (
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
            return self.engine.fetch(query, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-VERIF-POST-ERR",
                f"Errore DB durante verifica postalizzazione [CONC={ctx.ws_prov}, ANNO={ctx.ws_acar}, NUM={ctx.ws_ncar}, ID={ctx.ws_idavv}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_update_t01_ruolo(self, ctx: FormazioneRuoliContext, anno_ruolo: str, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato attività a '0P' su ADCFRT01."""
        try:
            upd = (
                self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_update({
                    "annoRifRuolo": anno_ruolo,
                    "numRuolo": ctx.ws_ctr_nruo,
                    "statoAttivita": "0P",
                    "timestampVarStato": datetime.now(),
                    "dataTransizioneStato": date.today()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-T01-RUOLO-ERR",
                f"Errore DB aggiornamento ruolo T01 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}, ANNO={anno_ruolo}, NRUO={ctx.ws_ctr_nruo}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_update_t10_ruolo(self, ctx: FormazioneRuoliContext, imp_tributo_calc: Any, depth: int) -> int:
        """Accesso atomico DB: aggiornamento stato articolo a '0P' su ADCFRT10."""
        try:
            upd = (
                self.engine.dataset("ADCFRT10")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .filter_by("progArticolo", "=", ctx.ws_key_nprgart)
                .compile_update({
                    "statoAttivita": "0P",
                    "impTributoCalc": imp_tributo_calc,
                    "impAggioAnt": ctx.ws_t10_iaggant,
                    "impAggioTot": ctx.ws_t10_iaggtot,
                    "timestampUpd": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-UPD-T10-RUOLO-ERR",
                f"Errore DB aggiornamento ruolo T10 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}, NPRGART={ctx.ws_key_nprgart}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _deinfasa_tab01(self, ctx: Any, row_t01: dict, depth: int = 4) -> int:
        """Accesso atomico DB: deinfasamento record ADCFRT01 a stato '0X'."""
        BatchLogger.info(
            "DEINFASA-TAB01",
            f"Deinfasamento tabella ADCFRT01 per Atto CATT={ctx.ws_catt}, CGES={ctx.ws_cges} -> Stato '0X'",
            depth=depth
        )

        # 1. Estrazione dei dati sorgente dal contesto (ctx)
        cges = ctx.ws_cges
        catt = ctx.ws_catt
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        anno_ruolo = ws_dcon
        num_ruolo = ctx.ws_ctr_nruo
        codice_errore = ctx.ws_codErrRuo

        # controllo per verifica della partita.
        # 1. se partita relativa alle spese di notifica vengono cancellati partita ed articolo
        # 2. altrimenti viene effettuato il deinfaso con 0X
        if catt == ctx.ws_identificativoAvviso and cges == "N":
            self._db_delete_tab01(ctx, row_t01, depth=depth + 1)
            self._db_delete_tab14(ctx, row_t01, depth=depth + 1)
            self._db_insert_tabC01(ctx, row_t01, depth=depth + 1)
        else:
            self._db_update_tab01(ctx, row_t01, depth=depth + 1)


    def _db_delete_tab01(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Delete tabella ADCFRT01 per CGES e CATT."""
        BatchLogger.info(
            "DELETE-TAB01",
            f"Delete tabella ADCFRT01 per Atto CGES={ctx.ws_cges}, CATT={ctx.ws_catt}",
            depth=depth
        )

        try:
            dataset = self.engine.dataset("ADCFRT01")
            query_delT01 = (
                dataset
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_delete()
            )
            self.engine.execute_mutation(query_delT01, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DELETE-TAB01",
                f"Errore delete tabella ADCFRT01 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_delete_tab14(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Delete tabella ADCFRT14 per CGES e CATT."""
        BatchLogger.info(
            "DELETE-TAB14",
            f"Delete tabella ADCFRT14 per Atto CGES={ctx.ws_cges}, CATT={ctx.ws_catt}",
            depth=depth
        )

        try:
            dataset = self.engine.dataset("ADCFRT14")
            query_delT14 = (
                dataset
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_delete()
            )
            self.engine.execute_mutation(query_delT14, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DELETE-TAB14",
                f"Errore delete tabella ADCFRT14 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_insert_tabC01(self, ctx: Any, row_t01: dict, depth: int) -> int:

        # Estrazione con formattazione e allineamento fedele al layout COBOL
        cges = str(row_t01.get("gestione") or row_t01.get("CGES") or "").strip()[:1].ljust(1)
        csed = str(row_t01.get("sede") or row_t01.get("CSED") or "").strip()[:2].zfill(2)
        czon = str(row_t01.get("zona") or row_t01.get("CZON") or "").strip()[:2].zfill(2)
        anno_avv = str(row_t01.get("annoAvviso") or row_t01.get("ANNOAVV") or "").strip()[:4].ljust(4)
        prog_avv = str(row_t01.get("progAvviso") or row_t01.get("PROGAVV") or "").strip()[:10].ljust(10)

        # Composizione di ID-GEST OF CDC01DEL (1 + 2 + 2 + 4 + 10 = 19 caratteri)
        id_gest = f"{cges}{csed}{czon}{anno_avv}{prog_avv}"

        try:
            query_ins_C01 = (
                self.engine.dataset("ADC01DEL").compile_insert({
                "gestione": ctx.ws_cges,
                "codiceAtto": ctx.ws_catt,
                "timestampIns": row_t01["timestampIns"],
                "timestampDel": datetime.now(),
                "idAvvGest": id_gest,
                "codDipendente": row_t01["codDipendente"]
            }))
            righe = self.engine.execute_mutation(query_ins_C01, depth=depth)

            BatchLogger.info(
                "INSERT-ADC01DEL",
                f"Storicizzazione avviso cancellato su ADC01DEL per CGES={ctx.ws_cges}, CATT={ctx.ws_catt}, righe: {righe})",
                depth=depth
            )
            return righe
        except Exception as err:
            BatchLogger.error("INSERT-ADC01DEL", f"Errore Storicizzazione avviso su ADC01DEL per [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1


    def _db_update_tab01(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Update tabella ADCFRT01 per CGES e CATT."""
        BatchLogger.info(
            "UPDATE-TAB01",
            f"Aggiornamento tabella ADCFRT01 per Atto CGES={ctx.ws_cges}, CATT={ctx.ws_catt}",
            depth=depth
        )

        cod_err = row_t01.get("codiceErrore")

        try:
            upd_T01 = (
                self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_update({
                    "statoAttivita": "0X",
                    "codiceErrore": cod_err,
                    "timestampVarStato": datetime.now(),
                    "dataTransizioneStato": date.today()
                })
            )
            return self.engine.execute_mutation(upd_T01, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "UPDATE-TAB01",
                f"Errore DB deinfasamento ADCFRT01 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}, COD_ERR={cod_err}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _deinfasa_tab10(self, ctx: Any, row_t10: dict, depth: int = 4) -> int:
        """Accesso atomico DB: deinfasamento record ADCFRT10 a stato '0X'."""
        BatchLogger.info(
            "DEINFASA-TAB10",
            f"Deinfasamento tabella ADCFRT10 per Atto CATT={ctx.ws_catt}, CGES={ctx.ws_cges} -> Stato '0X'",
            depth=depth
        )

        # 1. Estrazione dei dati sorgente dal contesto (ctx)
        cges = ctx.ws_cges
        catt = ctx.ws_catt
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        anno_ruolo = ws_dcon
        num_ruolo = ctx.ws_ctr_nruo
        codice_errore = ctx.ws_codErrRuo

        # controllo per verifica della partita.
        # 1. se partita relativa alle spese di notifica vengono cancellati partita ed articolo
        # 2. altrimenti viene effettuato il deinfaso con 0X
        if catt == ctx.ws_identificativoAvviso and cges == "N":
            self._db_delete_tab10(ctx, row_t10, depth=depth + 1)
            self._db_insert_tabC10(ctx, row_t10, depth=depth + 1)
        else:
            self._db_update_tab10(ctx, row_t10, depth=depth + 1)


    def _db_delete_tab10(self, ctx: Any, row_t10: dict, depth: int) -> int:
        """Delete tabella ADCFRT01 per CGES e CATT."""
        BatchLogger.info(
            "DELETE-TAB10",
            f"Delete tabella ADCFRT10 per Atto CGES={ctx.ws_cges}, CATT={ctx.ws_catt}",
            depth=depth
        )

        try:
            dataset = self.engine.dataset("ADCFRT10")
            query_delT10 = (
                dataset
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_delete()
            )
            self.engine.execute_mutation(query_delT10, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DELETE-TAB10",
                f"Errore delete tabella ADCFRT10 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_insert_tabC10(self, ctx: Any, row_t10: dict, depth: int) -> int:

        # Estrazione con formattazione e allineamento fedele al layout COBOL
        ctx.ws_cges = str(row_t10.get("gestione") or row_t10.get("CGES") or "").strip()[:1].ljust(1)
        ctx.ws_catt = str(row_t10.get("codiceAtto") or row_t10.get("CATT") or "").strip()[:2].zfill(2)
        progArticolo = 1

        try:
            query_ins_C10 = (
                self.engine.dataset("ADC10DEL").compile_insert({
                "gestione": ctx.ws_cges,
                "codiceAtto": ctx.ws_catt,
                "progArticolo": progArticolo,
                "timestampIns": row_t10["timestampIns"],
                "timestampDel": datetime.now()
            }))
            righe = self.engine.execute_mutation(query_ins_C10, depth=depth)

            BatchLogger.info(
                "INSERT-ADC10DEL",
                f"Storicizzazione avviso cancellato su ADC10DEL per CGES={ctx.ws_cges}, CATT={ctx.ws_catt}, righe: {righe})",
                depth=depth
            )
            return righe
        except Exception as err:
            BatchLogger.error("INSERT-ADC10DEL", f"Errore Storicizzazione avviso su ADC10DEL per [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1


    def _db_update_tab10(self, ctx: Any, row_t10: dict, depth: int) -> int:
        """Update tabella ADCFRT10 per CGES e CATT."""
        BatchLogger.info(
            "UPDATE-TAB10",
            f"Aggiornamento tabella ADCFRT10 per Atto CGES={ctx.ws_cges}, CATT={ctx.ws_catt}",
            depth=depth
        )

        try:
            upd_T10 = (
                self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_update({
                    "statoAttivita": "0X",
                    "impAggioAnt": row_t10["impAggioAnt"],
                    "impAggioTot": row_t10["impAggioTot"],
                    "timestampVarStato": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd_T10, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "UPDATE-TAB10",
                f"Errore DB deinfasamento ADCFRT10 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1
