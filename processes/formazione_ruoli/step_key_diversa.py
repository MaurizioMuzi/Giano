# processes/formazione_ruoli/step_key_diversa.py
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
from core.batch_logger import BatchLogger
from .context import FormazioneRuoliContext


class CicloDettaglioKeyDStep:
    """
    Gestione del ciclo di rottura della chiave composita dell'avviso.
    Corrisponde alla gestione della condizione 'NOT STESSA-CHIAVE':
        1. Chiusura e consolidamento dell'avviso precedente (_on_rottura_avviso)
        2. Reimpostazione delle variabili di chiave e controllo (IMP-COMODI-KEY)
        3. Reset dello switch di controllo avviso (WS-SW-KEYAVV = 0)
    """

    def __init__(self, engine):
        self.engine = engine

    def execute_rottura_chiave(self, ctx: FormazioneRuoliContext, row_t01: dict, row_t10: Optional[dict] = None, depth: int = 4) -> None:
        """
        Struttura principale richiamata alla rilevazione di rottura chiave avviso:
        """
        BatchLogger.info(
            "ROTTURA-CHIAVE",
            f"Rilevata nuova chiave avviso [CATT={ctx.ws_catt}, CGES={ctx.ws_cges}, ANNO={ctx.ws_annoavv}, PROG={ctx.ws_progavv}]",
            depth=depth
        )

        try:

            if ctx.ws_ver_ok == 1:
                BatchLogger.info(
                    "GESTIONE-KEY-DIVERSA",
                    "Aggiornamento tabelle per rielaborazione nuova chiave (WS-VER-OK = 1) -> Procedo con AGGIORNA-TABELLE",
                    depth=depth + 1
                )

                # 1. Chiusura contabile e verifica di consolidamento dell'avviso precedente
                self._aggiorna_tabelle(ctx, row_t01=row_t01, row_t10=row_t10, depth=depth + 1)
            elif ctx.ws_ver_er == 1:
                ctx.ws_ver_er = 0

                BatchLogger.warn(
                    "GESTIONE-KEY-DIVERSA",
                    "Cancellazione chiave in errore e storicizzazione (WS-VER-ER = 1) -> Eseguo annullamento",
                    depth=depth + 1
                )

                # 1. PERFORM LEGGILA-TAB03 THRU LEGGILA-TAB03-EX
                row_t03 = self._db_leggi_tab03(ctx, depth=depth + 1)

                if row_t03:
                    row_t03 = row_t03[0]
                    ctx.ws_cesaavv = row_t03.get("codEsattoriaAvviso")
                    ctx.timestampInsStato = row_t03.get("timestampInsStato")
                    ctx.ws_cstacar = row_t03.get("statoCartella")

                # 2. PERFORM ANNULLA-TAB03 THRU ANNULLA-TAB03-EX
                self._db_delete_tab03(ctx, depth=depth + 1)

                # PERFORM INSERT-ADC03DEL THRU INSERT-ADC03DEL-EX
                self._db_insert_tabC03(ctx, depth=depth + 1)

                # 3. PERFORM RECUPERA-NRAV THRU RECUPERA-NRAV-EX
                row_nrav = self._db_recupero_nrav(ctx, depth=depth + 1)

                if row_nrav:
                    row_nrav = row_nrav[0]
                    ctx.cesa_nrav = row_nrav.get("codConcessione")
                    ctx.prog_nrav = row_nrav.get("progRav")
                    ctx.cabi_nrav = row_nrav.get("codAbi")
                    ctx.ciderav_min = row_nrav.get("codRavMin")
                    ctx.ciderav_max = row_nrav.get("codRavMax")

                    self._db_insert_nrav(ctx, depth=depth)

            # 4. Acquisizione dei nuovi comodi chiave sul context
            ctx.imp_comodi_key(row_t01, row_t10 or {})
            ctx.initialize_working_storage()

            BatchLogger.debug(
                "ROTTURA-CHIAVE",
                f"Nuova chiave memorizzata: CGES={ctx.ws_cges}, CSED={ctx.ws_sede}, CZON={ctx.ws_zona}, "
                f"ANNOAVV={ctx.ws_annoavv}, PROGAVV={ctx.ws_progavv}",
                depth=depth + 1
            )

        except Exception as err:
            BatchLogger.error(
                "ROTTURA-CHIAVE-ERR",
                f"Errore critico durante l'elaborazione di rottura chiave per Atto CATT={ctx.ws_catt}: {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("ROTTURA-CHIAVE-ERR", "Rollback transazionale eseguito a fronte del fallimento", depth=depth)
                except Exception as rollback_err:
                    BatchLogger.error("ROTTURA-CHIAVE-ERR", f"Fallito il rollback: {rollback_err}", depth=depth)

            ctx.indic_errore = "X"
            return -1

    def _aggiorna_tabelle(self, ctx: FormazioneRuoliContext, row_t01: Optional[dict] = None, row_t10: Optional[dict] = None, depth: int = 5) -> None:
        """
        Equivalente del paragrafo AGGIORNA-TABELLE:
        - INSERISCE-T09
        - INSERISCI-TAB02
        - SELECT-MAX-T02
        """

        # 1. valorizzazione tabella T09
        self.valorizza_t09(ctx, row_t10, depth=depth + 1)

        if ctx.indic_errore != "X":
            # 2. valorizzazione tabella T02
            self.valorizza_t02(ctx, row_t10, depth=depth + 1)
            self.commit()

            # 3. select max su tabella T02
            rows_max = self._db_fetch_max_ruolo_t02(ctx, depth=1)

            max_nruo = None

            if rows_max:
                row_val = rows_max[0] if isinstance(rows_max, list) else rows_max
                max_nruo = row_val.get("numRuolo") or row_val.get("MAX:numRuolo")

            if max_nruo is None:
                ctx.ws_ctr_nruo = 1
            else:
                ctx.ws_ctr_nruo = int(max_nruo) + 1


        sw_errore = 1 if (str(getattr(ctx, "indic_errore", "") or "").strip() == "X" or str(getattr(ctx, "ws_erravv", "")).strip()) else 0

        if sw_errore == 0:
            BatchLogger.info(
                "CHIUSURA-AVV",
                f"Avviso {getattr(ctx, 'ws_annoavv', '')}/{getattr(ctx, 'ws_progavv', '')} REGOLARE -> "
                f"Tot. Tributi: {getattr(ctx, 'ws_itrbavv', 0)} | Articoli: {getattr(ctx, 'ws_nespart', 0)} | Consolidamento eseguito",
                depth=depth
            )
        else:
            BatchLogger.warn(
                "CHIUSURA-AVV",
                f"Avviso {getattr(ctx, 'ws_annoavv', '')}/{getattr(ctx, 'ws_progavv', '')} SCARTATO ({getattr(ctx, 'ws_erravv', '')}) -> "
                f"Tot. Tributi: 0.00 | Articoli: 0 | Consolidamento escluso",
                depth=depth
            )

        # Reset totalizzatori e comodi contabili dell'avviso chiuso
        ctx.ws_itrbavv = Decimal("0")
        ctx.ws_iaggavv = Decimal("0")
        ctx.ws_nespart = 0
        ctx.ws_erravv = ""
        ctx.indic_errore = " "

    def _imposta_comodi_key_t10(self, ctx: Any, t01: dict, t10: dict) -> None:
        """Valorizza le variabili di chiave e controllo nel context a partire dai record T01 e T10."""
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
        """Esegue la valorizzazione dei campi propedeutici alla gestione della tabella ADCFRT09."""
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        anno_dcon = int(ws_dcon) if ws_dcon.isdigit() else 0
        ws_t09_icrc_t = ctx.ws_t10_itrb_t + ctx.ws_t10_iarr_t

        record_t09 = {}
        record_t09.update({
            "codEsattoria": int(getattr(ctx, "ws_cesa", 0) or 0),
            "annoRif": anno_dcon,
            "numRuolo": int(getattr(ctx, "ws_ctr_nruo", 0) or 0),
            "codTributoCnc": str(getattr(ctx, "ws_ctrbcnc", "") or "").strip(),
            "annoRifCont": anno_dcon,
            "numRate": int(getattr(ctx, "ws_ntotrat", 0) or 0),
            "codRata": str(getattr(ctx, "ws_crat", "") or "").strip(),
            "flgResiduo": str(getattr(ctx, "ws_fres", getattr(ctx, "ws_key_fres", "")) or "").strip(),
            "impTributo": ctx.ws_t10_itrb_t,
            "numArticoli": int(getattr(ctx, "ws_nart", 0) or 0),
            "impAggioAnt": ctx.ws_t10_iaggant_t,
            "impAggioTot": ctx.ws_t10_iaggtot_t,
            "impArrotondamento": ctx.ws_t10_iarr_t,
            "impCarico": ws_t09_icrc_t
        })

        righe = self._db_insert_t09(ctx, record_t09, depth=depth)

        BatchLogger.info(
            "INSERISCE-T09",
            f"Inserimento ADCFRT09 completato (Righe inserite: {righe}): CESA={record_t09.get('codEsattoria')}, "
            f"ARIFRUO={record_t09.get('annoRif')}, NRUO={record_t09.get('numRuolo')}, "
            f"CTRBCNC={record_t09.get('codTributoCnc')}, ARIFCON={record_t09.get('annoRifCont')}, "
            f"NRAT={record_t09.get('numRate')}, CRAT={record_t09.get('codRata')}, "
            f"FRES={record_t09.get('flgResiduo')}",
            depth=depth
        )

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_insert_t09(self, ctx: FormazioneRuoliContext, record_t09: Dict[str, Any], depth: int) -> int:
        """Insert tabella ADCFRT09."""
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


    def valorizza_t02(self, ctx: FormazioneRuoliContext, row_t10: Dict[str, Any], depth: int = 4) -> None:
        """Esegue la valorizzazione dei campi propedeutici alla gestione della tabella ADCFRT02."""
        ws_dcon = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        anno_dcon = int(ws_dcon) if ws_dcon.isdigit() else 0
        ws_t09_icrc_t = ctx.ws_t10_itrb_t + ctx.ws_t10_iarr_t

        if ctx.ws_ntotrat == 0:
            codRuoloCoa = 1
        else:
            codRuoloCoa = 2

        t02_icrc_t = (
                ctx.ws_t02_itrb_t
                + ctx.ws_t02_isan_t
                + ctx.ws_t02_iint_t
                + ctx.ws_t02_ialt_t
                + ctx.ws_t02_iarr_t
        )

        d_zero = "0001-01-01"
        d_spazi = " "

        record_t02 = {}
        record_t02.update({
            "codStRuolo": "P",
            "codEsattoria": ctx.ws_cesa,
            "annoRif": anno_dcon,
            "numRuolo": int(getattr(ctx, "ws_ctr_nruo", 0) or 0),
            "sede": ctx.ws_sede,
            "zona": ctx.ws_zona,
            "codCentro": ctx.current_cod_centro,
            "tipoRuolo": "1",
            "codRuoloCoa": codRuoloCoa,
            "dataFormazione": date.today(),
            "dataConsegna": ctx.dcon,
            "flgEuro": ctx.ws_feur,
            "impTributo": ctx.ws_t02_itrb_t,
            "impSanzione": ctx.ws_t02_isan_t,
            "impInteressi": ctx.ws_t02_iint_t,
            "impAltro": ctx.ws_t02_ialt_t,
            "impAggioAnticipato": ctx.ws_t02_iaggant_t,
            "impAggioTot": ctx.ws_t02_iaggtot_t,
            "impCarico": t02_icrc_t,
            "impArrotondamento": ctx.ws_t02_iarr_t,
            "impImponibile": 0,
            "aliqIva": 0,
            "impIva": 0,
            "dataVisto": d_zero,
            "codDipendente": d_spazi,
            "dataInvioCNC": d_zero,
            "numRecRuolo": 0,
            "numRecR5B": 0,
            "numRecR7A": 0,
            "numRecR7B": 0,
            "numRecR7C": 0,
            "numRecR7D": 0,
            "numRecR7E": 0,
            "numRecR7G": 0,
            "anno_rif_invio": 0,
            "num_file_invio": 0,
            "dataTimbro": d_zero,
            "anno_rif_timbro": 0,
            "num_file_timbro": d_spazi,
            "dataTransStato": d_zero,
            "tasso": ctx.ws_tasSanz_2,
            "numRecR7L": 0
        })

        righe = self._db_insert_t02(ctx, record_t02, depth=depth)

        BatchLogger.info(
            "INSERISCE-T02",
            f"Inserimento ADCFRT02 completato (Righe inserite: {righe}): CESA={record_t02.get('codEsattoria')}, "
            f"ARIFRUO={record_t02.get('annoRif')}, NRUO={record_t02.get('numRuolo')}",
            depth=depth
        )

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_insert_t02(self, ctx, record_t02: Dict[str, Any], depth: int) -> int:
        """Insert tabella ADCFRT02"""
        try:
            ins = self.engine.dataset("ADCFRT02").compile_insert(record_t02)
            return self.engine.execute_mutation(ins, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-INS-T02",
                f"Errore insert ADCFRT02 [CESA={record_t02.get('codEsattoria')}, ARIFRUO={record_t02.get('annoRif')},"
                f" NRUO={record_t02.get('numRuolo')}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_fetch_max_ruolo_t02(self, ctx: Any, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera il valore MAX(numRuolo) da ADCFRT02."""

        # Estrazione del numero massimo del ruolo registrato su ADCFRT02
        ws_annorif = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]

        try:
            query = (
                self.engine.dataset("ADCFRT02")
                .select("MAX:numRuolo")
                .filter_by("codEsattoria", "=", ctx.ws_cesa)
                .filter_by("annoRif", "=", ws_annorif)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-MAX-T02-ERR",
                f"Errore DB durante recupero MAX(numRuolo) da ADCFRT02 [CESA={ctx.ws_cesa}, ANNO={ws_annorif}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_leggi_tab03(self, ctx: FormazioneRuoliContext, depth: int) -> List[Any]:
        """Accesso atomico DB: lettura tabella ADCFRT03 per CESA - ACAR - NCAR."""

        ctx.ws_prov = (ctx.ws_cesaavv or 0) - 300

        try:

            query_t03 = (
                self.engine.dataset("ADCFRT03")
                .select("codConcessione", "annoCartella", "numCartella",
                        "codEsattoriaAvviso", "timestampInsStato", "statoCartella")
                .filter_by("codConcessione", "=", ctx.ws_prov)
                .filter_by("annoCartella", "=", ctx.ws_annoavv)
                .filter_by("numCartella", "=", ctx.ws_progavv)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )

            rows = self.engine.fetch(query_t03, depth=depth)
            if not rows:
                return None

            t03_map = self.engine.get_table_map("ADCFRT03")
            return t03_map.normalize(rows[0]) if hasattr(t03_map, "normalize") else rows[0]

        except Exception as err:
            BatchLogger.error(
                "DB-LEGGI-TAB03-ERR",
                f"Errore lettura ADCFRT03 [CESA={ctx.ws_cesa}, ANNO={ctx.ws_annoavv}, PROG={ctx.ws_progavv}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_delete_tab03(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Delete tabella ADCFRT03 per CGES - ACAR - NCAR."""
        BatchLogger.info(
            "DELETE-TAB03",
            f"Delete tabella ADCFRT03 per Atto CGES={ctx.ws_cges}, ACAR={ctx.ws_annoavv}, NCAR={ctx.ws_progavv}",
            depth=depth
        )

        try:
            query_delT03 = (
                self.engine.dataset("ADCFRT03")
                .filter_by("codConcessione", "=", ctx.ws_cesa)
                .filter_by("annoCartella", "=", ctx.ws_annoavv)
                .filter_by("numCartella", "=", ctx.ws_progavv)
                .compile_delete()
            )
            return self.engine.execute_mutation(query_delT03, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DELETE-TAB03",
                f"Errore delete tabella ADCFRT03 [CESA={ctx.ws_cesa}, ACAR={ctx.ws_annoavv}, NCAR={ctx.ws_progavv}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_recupero_nrav(self, ctx: Any, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera dati da ADCAVV03."""

        nrav = str(ctx.ws_codRav or "").strip()
        nrav_cid = nrav[5:14]
        ctx.ws_nrav_cid = nrav_cid

        nrav_cabi = nrav[2:6]

        BatchLogger.info(
            "RECUPERA-NRAV",
            f"Recupero dati da tabella ADCAVV03 per Atto CESA={ctx.ws_cges}, CABI={nrav_cabi}, "
            f"CIDERAV_MIN={nrav_cid}, CIDERAV_MAX={nrav_cid}",
            depth=depth
        )

        try:
            query_nrav = (
                self.engine.dataset("ADCAVV03")
                .select("codConcessione",
                        "progRav",
                        "codRavMin",
                        "codRavMax",
                        "codAbi",
                        "flgAttrRav")
                .filter_by("codConcessione", "=", ctx.ws_cesa)
                .filter_by("codAbi", "=", nrav_cabi)
                .filter_by("codRavMin", "<=", nrav_cid)
                .filter_by("codRavMax", ">=", nrav_cid)
                .filter_by("flgAttrRav", "=", "0")
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            return self.engine.fetch(query_nrav, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "RECUPERA-NRAV",
                f"Errore DB durante recupero dati da ADCAVV03 [CESA={ctx.ws_cges}, CABI={nrav_cabi}, CIDERAV_MIN={nrav_cid}, CIDERAV_MAX={nrav_cid}]: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    def _db_insert_nrav(self, ctx: Any, depth: int) -> int:
        """Inserimento su ADCAVV03 per censimento NRAV."""

        timestampIns = "0001-01-01-00.00.00.000000"

        try:
            query_ins_AV03 = (
                self.engine.dataset("ADCAVV03").compile_insert({
                    "codConcessione": ctx.cesa_nrav,
                    "progRav": ctx.prog_nrav,
                    "codRavMin": ctx.ciderav_min,
                    "codRavMax": ctx.ciderav_max,
                    "codAbi": ctx.cabi_nrav,
                    "codRav": ctx.ws_codRav,
                    "flgAttrRav": "0",
                    "timestampIns": timestampIns,
                    "timestampUpd": datetime.now()
                })
            )
            righe_AV03 = self.engine.execute_mutation(query_ins_AV03, depth=depth)

            BatchLogger.info(
                "INSERISCI-NRAV",
                f"Storicizzazione avviso cancellato su ADC03DEL per CESA={ctx.cesa_nrav}, PROG={ctx.prog_nrav}"
                f", CIDERAV_MIN={ctx.ciderav_min}, CIDERAV_MAX={ctx.ciderav_max}, righe: {righe_AV03}",
                depth=depth
            )
            return righe_AV03

        except Exception as err:
            BatchLogger.error(
                "INSERISCI-NRAV",
                f"Errore Storicizzazione avviso su ADC03DEL per [CESA={ctx.cesa_nrav}, PROG={ctx.prog_nrav}, CIDERAV_MIN={ctx.ciderav_min}, CIDERAV_MAX={ctx.ciderav_max}]"
                f": {err}",
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
            query_delT14 = (
                self.engine.dataset("ADCFRT14")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .compile_delete()
            )
            return self.engine.execute_mutation(query_delT14, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DELETE-TAB14",
                f"Errore delete tabella ADCFRT14 [CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_insert_tabC03(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Storicizzazione cancellazione su ADC03DEL."""

        try:
            query_ins_C03 = (
                self.engine.dataset("ADC03DEL").compile_insert({
                    "codConcessione": ctx.ws_cesa,
                    "acar": ctx.ws_annoavv,
                    "ncar": ctx.ws_progavv,
                    "cesaavv": ctx.ws_cesaavv,
                    "tms_ins_csacar": ctx.timestampInsStato,
                    "cstacar": ctx.ws_cstacar,
                    "tms_del": datetime.now()
                })
            )
            righe = self.engine.execute_mutation(query_ins_C03, depth=depth)
            BatchLogger.info(
                "INSERT-ADC03DEL",
                f"Storicizzazione avviso cancellato su ADC03DEL per CESA={ctx.ws_cesa}, ACAR={ctx.ws_annoavv}"
                f", NCAR={ctx.ws_progavv}, CESAAVV={ctx.ws_cesaavv}, TMS_INS_CSTACAR={ctx.timestampInsStato}, righe: {righe}",
                depth=depth
            )
            return righe
        except Exception as err:
            BatchLogger.error(
                "INSERT-ADC03DEL",
                f"Errore Storicizzazione avviso su ADC03DEL per [CESA={ctx.ws_cesa}, CATT={ctx.ws_catt}, NCAR={ctx.ws_progavv}, CESAAVV={ctx.ws_cesaavv}, TMS_INS_CSTACAR={ctx.timestampInsStato}]"
                f": {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return -1


    def _db_update_tab01(self, ctx: Any, row_t01: dict, depth: int) -> int:
        """Update tabella ADCFRT01 per CGES e CATT a stato 0X."""
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