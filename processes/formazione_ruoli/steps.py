# processes/formazione_ruoli/steps.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Any, Iterator
from .context import FormazioneRuoliContext
from core.batch_logger import BatchLogger
from .step_key_uguale import CicloDettaglioKeyUStep as DettaglioKeyStep
from .step_key_diversa import CicloDettaglioKeyDStep as DettaglioKeyDStep


class ElaborazioneCurjoi2Step:
    """
    Reingegnerizzazione del paragrafo CICLO-CURJOI-2:
    Join tra ADCFRT01 e ADCFRT10 con gestione rottura e valorizzazione IMP-COMODI-KEY.
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_key = DettaglioKeyStep(engine)
        self.step_Dkey = DettaglioKeyDStep(engine)

    def execute_record(self, ctx: FormazioneRuoliContext, cges: str, anno_avv: int, prog_avv: int, depth: int = 3, is_last_credit: bool = False) -> None:
        t01_map = self.engine.get_table_map("ADCFRT01")
        t10_map = self.engine.get_table_map("ADCFRT10")

        # Reset variabili e contatori dell'avviso corrente con isolamento del singolo credito
        ctx.sw_keyavv = 0
        ctx.ws_erravv = ""
        ctx.ws_catt = ""
        ctx.ws_nespavv = 0
        ctx.ws_ntotpar = 0
        ctx.ws_itrbavv = Decimal("0")
        ctx.ws_iaggavv = Decimal("0")
        ctx.ws_nespart = 0
        ctx.indic_errore = " "

        record_art_totali = 0
        first_record = True
        avviso_interrotto_per_errore = False

        try:
            # Pre-verifica presenza record infasati (stato '0Q')
            res = self._db_fetch_precheck_curjoi2(ctx, depth=depth)
            if not res:
                ctx.indic_non_trov = "X"
                BatchLogger.info("CICLO-CURJOI-2", "Assenza di avvisi da elaborare", depth=depth)
                return

            # Estrazione del numero massimo del ruolo registrato su ADCFRT02
            ws_annoruo_dec = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
            rows_max = self._db_fetch_max_ruolo_t02(ctx.current_sede, ws_annoruo_dec, depth=1)
            max_nruo = None
            if rows_max:
                row_val = rows_max[0] if isinstance(rows_max, list) else rows_max
                max_nruo = row_val.get("numRuolo") or row_val.get("MAX:numRuolo")

            if max_nruo is None:
                ctx.ws_ctr_nruo = 1
            else:
                ctx.ws_ctr_nruo = int(max_nruo) + 1

            # Ciclo di elaborazione con gestione di rottura chiave
            for chunk in self._db_stream_curjoi2(ctx, t10_map, depth=depth):
                for raw_row in chunk:
                    record_art_totali += 1
                    row_t01 = t01_map.normalize(raw_row)
                    row_t10 = t10_map.normalize(raw_row)

                    if first_record:
                        ctx.imp_comodi_key(row_t01, row_t10)
                        first_record = False
                        ctx.sw_keyavv = 0
                    else:
                        stessa_chiave = (
                            ctx.ws_cesa == row_t01.get("codEsattoria") and
                            ctx.ws_feur == row_t01.get("flgEuro") and
                            ctx.ws_cges == row_t10.get("gestione") and
                            ctx.ws_cfasamm == row_t10.get("codFasAmm") and
                            ctx.ws_ntotrat == row_t10.get("numTotRate")
                        )

                        if not stessa_chiave:
                            self.step_Dkey.execute_rottura_chiave(
                                ctx=ctx,
                                row_t01=row_t01,
                                row_t10=row_t10,
                                depth=depth + 1
                            )
                        else:

                            # INVOCAZIONE STEP CHIAVE UGUALE (ELABORAZIONE RECORD / DETTAGLIO)
                            self.step_key.execute_controllo_flusso(
                                ctx=ctx,
                                row_t01=row_t01,
                                row_t10=row_t10,
                                depth=depth + 1
                            )

            # --- GESTIONE FINE FILE / ULTIMO RECORD ---
            # Se è stato elaborato almeno un record, è necessario consolidare l'ultimo gruppo
            if record_art_totali > 0:
                self.step_Dkey.execute_rottura_chiave(
                                ctx=ctx,
                                row_t01=row_t01,
                                row_t10=row_t10,
                                depth=depth + 1
                            )

            ctx.record_art_totali = record_art_totali

        except Exception as err:
            BatchLogger.error(
                "CURJOI2-RUOLI-ERR",
                f"Errore critico durante l'elaborazione dell'avviso ruoli {anno_avv}/{prog_avv} (CGES={cges}): {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("CURJOI2-RUOLI-ERR", "Rollback transazionale eseguito a fronte del fallimento", depth=depth)
                except Exception as rollback_err:
                    BatchLogger.error("CURJOI2-RUOLI-ERR", f"Fallito il rollback: {rollback_err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE CURJOI-2 (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_precheck_curjoi2(self, ctx: FormazioneRuoliContext, depth: int) -> List[Any]:
        """Accesso atomico DB: verifica presenza record infasati (stato '0Q') per la sede/zona corrente."""
        try:
            datainf_val = getattr(ctx, "datainf", getattr(ctx, "ws_datainf", date.today()))
            query = (
                self.engine.dataset("ADCFRT01")
                .select("codiceAtto")
                .filter_by("sede", "=", ctx.current_sede)
                .filter_by("zona", "=", ctx.current_zona)
                .filter_by("codCentro", "=", ctx.current_cod_centro)
                .filter_by("dataInf", "<=", datainf_val)
                .filter_by("dataInf", "<>", date.today())
                .filter_by("dataInf", ">=", ctx.diniinf)
                .filter_by("dataInf", "<=", ctx.dfininf)
                .filter_by("statoAttivita", "=", "0Q")
                .limit(1)
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error("DB-FETCH-PRECHECK-CURJOI2-ERR", f"Errore DB durante pre-check su ADCFRT01: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    def _db_fetch_max_ruolo_t02(self, cod_esattoria: Any, anno_rif: str, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera il valore MAX(numRuolo) da ADCFRT02."""
        try:
            query = (
                self.engine.dataset("ADCFRT02")
                .select("MAX:numRuolo")
                .filter_by("codEsattoria", "=", cod_esattoria)
                .filter_by("annoRif", "=", anno_rif)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-MAX-T02-ERR",
                f"Errore DB durante recupero MAX(numRuolo) da ADCFRT02 [CESA={cod_esattoria}, ANNO={anno_rif}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_stream_curjoi2(self, ctx: FormazioneRuoliContext, t10_map: Any, depth: int) -> Iterator[List[Any]]:
        """Accesso atomico DB: apertura cursore in streaming join ADCFRT01 e ADCFRT10."""
        try:
            datainf_val = getattr(ctx, "datainf", getattr(ctx, "ws_datainf", date.today()))
            query = (
                self.engine.dataset("ADCFRT01")
                .join(t10_map, alias_self="A", alias_target="B")
                .on("gestione", "gestione")
                .on("codiceAtto", "codiceAtto")
                .select(
                    "codEsattoria", "flgEuro", "dataRifCon", "dataFallimento", "sede",
                    "zona", "codCentro", "flgCessione", "flgDecadenza", "codEsattoriaAvviso", "annoCarico",
                    "numCarico", "numChkCarico", "timestampInsStato", "codDipendente"
                )
                .select_joined(
                    "codTributoCnc", "codRata", "numTotRate", "flgResiduo", "impTributo",
                    "impInteressi", "codNaturaTrb", "impTributoCalc", "impAggioTot", "impAggioAnt",
                    "impArrotondamento", "gestione", "codiceAtto", "progArticolo", "numIdDecre",
                    "tasso", "impCapitale", "dataFineCalc", "codFasAmm", "impAggio", "timestampIns"
                )
                .filter_by("sede", "=", ctx.current_sede)
                .filter_by("zona", "=", ctx.current_zona)
                .filter_by("codCentro", "=", ctx.current_cod_centro)
                .filter_by("dataInf", "<=", datainf_val)
                .filter_by("dataInf", "<>", date.today())
                .filter_by("dataInf", ">=", ctx.diniinf)
                .filter_by("dataInf", "<=", ctx.dfininf)
                .filter_by("statoAttivita", "=", "0Q")
                .order_by("codEsattoria", "flgEuro")
                .order_by_joined("gestione", "codFasAmm", "numTotRate", "codTributoCnc", "codRata", "flgResiduo")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.cursor_stream(query, buffer_size=500, depth=depth)

        except Exception as err:
            BatchLogger.error("DB-STREAM-CURJOI2-RUOLI-ERR", f"Errore DB durante l'apertura cursore CURJOI2 ruoli: {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1


    def _parse_decimal(self, value) -> Decimal:
        if value is None:
            return Decimal("0")
        val_str = str(value).strip()
        if not val_str:
            return Decimal("0")
        try:
            return Decimal(val_str)
        except (InvalidOperation, ValueError):
            return Decimal("0")


    def execute(self, ctx: FormazioneRuoliContext) -> None:
        pass


class ElaborazioneCurjoi12AStep:
    """Esecuzione diretta di ElaborazioneCurjoi2Step senza pre-query distinta (CURJOI-2A)."""

    def __init__(self, engine):
        self.engine = engine
        self.step_curjoi2 = ElaborazioneCurjoi2Step(engine)


    def execute(self, ctx: FormazioneRuoliContext, depth: int = 2) -> None:
        cges = getattr(ctx, "current_cges", getattr(ctx, "ws_cges", ""))
        anno_avv = getattr(ctx, "current_anno_avv", getattr(ctx, "ws_annoavv", 0))
        prog_avv = getattr(ctx, "current_prog_avv", getattr(ctx, "ws_progavv", 0))

        BatchLogger.info(
            "CREDITO-ATTIVO",
            f"Esecuzione diretta CURJOI-2: CGES={cges} | ANNO={anno_avv} | PROG={prog_avv}",
            depth=depth,
            is_last=False
        )

        self.step_curjoi2.execute_record(
            ctx=ctx,
            cges=cges,
            anno_avv=anno_avv,
            prog_avv=prog_avv,
            depth=depth + 1,
            is_last_credit=True
        )


class ElaborazioneCurjoi1Step:
    """Estrazione di tutti i lavori con CDAS = 'FO' su tabella ADCTET17."""

    def __init__(self, engine):
        self.engine = engine
        self.step_curjoi_2a = ElaborazioneCurjoi12AStep(engine)


    def execute(self, ctx: FormazioneRuoliContext) -> None:
        BatchLogger.info("SCAN-SEDI-T17", "Avvio scansione sedi operative (CURJOI-1 su ADCTET17)", depth=0)
        t17_map = self.engine.get_table_map("ADCTET17")
        rows = []

        try:
            for chunk in self._db_stream_curjoi1(depth=1):
                for raw_row in chunk:
                    rows.append(t17_map.normalize(raw_row))

            tot_sedi = len(rows)
            ctx.totale_record_curjoi1 = tot_sedi
            ctx.indic_aggiorna = False
            riepilogo_sedi = []

            for idx, row in enumerate(rows, start=1):
                is_last_sede = (idx == tot_sedi)

                ctx.current_sede = row.get("sede")
                ctx.current_zona = row.get("zona")
                ctx.current_cod_centro = row.get("codCentro")
                ctx.righe_elaborate_sede = 0
                ctx.indic_errore = " "

                BatchLogger.info(
                    "SEDE-OPERATIVA",
                    f"[{idx}/{tot_sedi}] CSED={ctx.current_sede} | CZON={ctx.current_zona} | CCOP={ctx.current_cod_centro}",
                    depth=1
                )

                self.step_curjoi_2a.execute(ctx, depth=2)

                stato_aggiornamento = "NON AGGIORNATO"
                if ctx.indic_errore != "X":
                    self._aggiorna_tab17(ctx, is_last=is_last_sede, depth=2)
                    stato_aggiornamento = "FI (AGGIORNATO)"
                    ctx.indic_aggiorna = True

                riepilogo_sedi.append({
                    "prog": idx,
                    "csed": ctx.current_sede,
                    "czon": ctx.current_zona,
                    "ccop": ctx.current_cod_centro,
                    "crediti": ctx.righe_elaborate_sede,
                    "stato": stato_aggiornamento
                })
                ctx.righe_elaborate_sede = 0

            # Fine ciclo sedi: se non ci sono errori bloccanti, aggiorna lo stato generale IF
            if ctx.indic_errore != "X":
                self._aggiorna_tet17(ctx, is_last=True, depth=1)
                ctx.indic_aggiorna_if = True

            if riepilogo_sedi:
                BatchLogger.separator(depth=1)
                BatchLogger.info("RIEPILOGO-SEDI", f"Elenco complessivo sedi esaminate ({tot_sedi} totali):", depth=1)
                tbl_sep = "+--------+------+------+------+---------+----------------+"
                header = f"| {'PROG':<6} | {'CSED':<4} | {'CZON':<4} | {'CCOP':<4} | {'CREDITI':<7} | {'STATO AGG.':<14} |"
                BatchLogger.info("RIEPILOGO-SEDI", tbl_sep, depth=1)
                BatchLogger.info("RIEPILOGO-SEDI", header, depth=1)
                BatchLogger.info("RIEPILOGO-SEDI", tbl_sep, depth=1)
                for s in riepilogo_sedi:
                    row_str = f"| {s['prog']:<6} | {str(s['csed']):<4} | {str(s['czon']):<4} | {str(s['ccop']):<4} | {s['crediti']:<7} | {s['stato']:<14} |"
                    BatchLogger.info("RIEPILOGO-SEDI", row_str, depth=1)
                BatchLogger.info("RIEPILOGO-SEDI", tbl_sep, depth=1)

            BatchLogger.separator(depth=0)
            BatchLogger.info("CHIUSURA-CUR1", "Elaborazione CURJOI-1 terminata per tutte le sedi", depth=0, is_last=True)

            if not ctx.indic_aggiorna:
                BatchLogger.warn("SEGNALAZIONE", "Nessun ruolo generato per questa elaborazione.", depth=1, is_last=True)

        except Exception as err:
            BatchLogger.error(
                "CURJOI1-RUOLI-ERR",
                f"Errore critico durante la scansione sedi operative CURJOI-1: {err}",
                depth=0
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("CURJOI1-RUOLI-ERR", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("CURJOI1-RUOLI-ERR", f"Fallito il rollback: {rollback_err}", depth=0)

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE CURJOI-1 (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_stream_curjoi1(self, depth: int) -> Iterator[List[Any]]:
        """Accesso atomico DB: apertura cursore sedi su ADCTET17 con codServizio='FO'."""
        try:
            query = (
                self.engine.dataset("ADCTET17")
                .distinct()
                .select("sede", "zona", "codCentro", "codServizio")
                .filter_by("codServizio", "=", "FO")
                .filter_by("timestamp", "=", datetime(1, 1, 1, 0, 0, 0))
                .filter_by("dataPre", "<=", date.today())
                .order_by("sede", "zona", "codCentro")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.cursor_stream(query, buffer_size=500, depth=depth)

        except Exception as err:
            BatchLogger.error("DB-STREAM-CURJOI1-RUOLI-ERR", f"Errore DB durante apertura cursore sedi ADCTET17: {err}", depth=depth)
            raise

    def _aggiorna_tab17(self, ctx: FormazioneRuoliContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCTET17 impostando il servizio a 'FI'."""

        righe_impattate = self._db_update_tab17_fi(ctx, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='FI' (Righe impattate: {righe_impattate})", depth=depth, is_last=is_last)


    def _db_update_tab17_fi(self, ctx: FormazioneRuoliContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento di singola sede a CDAS='IN'."""
        try:
            upd_tab17 = (
                self.engine.dataset("ADCTET17")
                .filter_by("sede", "=", ctx.current_sede)
                .filter_by("zona", "=", ctx.current_zona)
                .filter_by("codCentro", "=", ctx.current_cod_centro)
                .compile_update({
                    "codServizio": "FI",
                    "timestamp": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd_tab17, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "AGGIORNA-TAB17",
                f"Errore DB UPDATE su ADCTET17 [SEDE={ctx.current_sede}, ZONA={ctx.current_zona}, CENTRO={ctx.current_cod_centro}] a 'FI': {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _aggiorna_tet17(self, ctx: FormazioneRuoliContext, is_last: bool = False, depth: int = 1) -> None:
        """Aggiorna massivamente lo stato del record su ADCTET17 impostando il servizio a 'FI' a fine elaborazione."""

        righe_impattate_if = self._db_update_tet17_fi(depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='FI' (Righe impattate: {righe_impattate_fi})", depth=depth, is_last=is_last)


    def _db_update_tet17_fi(self, depth: int) -> int:
        """Accesso atomico DB: aggiornamento massivo di fine ciclo a CDAS='FI'."""

        try:
            upd_tet17 = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "FI",
                    "timestamp": datetime.now()
                })
            )
            return self.engine.execute_mutation(upd_tet17, depth=depth)

        except Exception as err:
            BatchLogger.error("DB-UPD-TET17-IF-ERR", f"Errore DB durante UPDATE massivo ADCTET17 a 'FI': {err}", depth=depth)

            ctx.indic_errore = "X"
            return -1