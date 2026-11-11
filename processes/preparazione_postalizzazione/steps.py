# processes/preparazione_postalizzazione/steps.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator, List, Any

from .context import PreparazionePostalizzazioneContext
from core.batch_logger import BatchLogger
from .step_recupero_rav import DettaglioRecuperoRav
from .step_elabora_avviso import DettaglioElaboraAvviso
from .step_imposta_errori import DettaglioErrori

class ElaborazioneCicloCurt03Step:
    """
    Reingegnerizzazione del paragrafo CICLO-CURT03:
    CICLO DI ELABORAZIONE CURSORE SU ADCFRT03 PER L'ELABORAZIONE DELLE OCCORRENZE IN STATO FORMATO:
    - Gestione rottura sedi
    - Gestione RAV
    """

    def __init__(self, engine):
        self.engine = engine
        self.ws_csed_prec = None
        self.ws_czon_prec = None

        self.step_recupero_rav = DettaglioRecuperoRav(engine)
        self.step_elabora_avviso = DettaglioElaboraAvviso(engine)
        self.step_imposta_errori = DettaglioErrori(engine)

    def execute_record(self, ctx: PreparazionePostalizzazioneContext, row, depth: int = 1, is_last_cartella: bool = False) -> None:
        csed_corrente = ctx.current_sede
        czon_corrente = ctx.current_zona
        #csed_corrente = row.get("csed")
        #czon_corrente = row.get("czon")

        try:
            # Se c'è rottura di sede si accede a tabella AGESEDI per recupero dati direttore di sede
            # Rif. COBOL: IF CSED/CZON NOT = WS-CSED-PREC/WS-CZON-PREC -> cambio sede/zona
            if (csed_corrente, czon_corrente) != (self.ws_csed_prec, self.ws_czon_prec):
                self.ws_csed_prec = csed_corrente
                self.ws_czon_prec = czon_corrente

                BatchLogger.debug(
                    "CAMBIO-SEDE-ZONA",
                    f"CSED={csed_corrente} | CZON={czon_corrente}",
                    depth=depth
                )

                BatchLogger.info("SELECT-AGESEDI", "Accesso a tabella (VSEDI_ADDEBITI) per recupero informazioni sulle sedi", depth=depth)
                tVSedi_map = self.engine.get_table_map("VSEDI_ADDEBITI")
                rows_sedi = self._select_agesedi(ctx, depth=depth + 1)

                if not rows_sedi:
                    BatchLogger.error("SELECT-AGESEDI",
                                      "SEDE NON PRESENTE O NON VALIDA: Nessun record valido in VSEDI_ADDEBITI.",
                                      depth=depth+1, is_last=True)
                    ctx.indic_sede_nonval = "X"

                row = tVSedi_map.normalize(rows_sedi[0])
                ctx.nomedir = row.get("nomedir")
                ctx.cogndir = row.get("cogndir")
                ctx.sede = row.get("sede")
                ctx.pr = row.get("pr")
                ctx.indir_sedi = row.get("indir_sedi")
                ctx.cap_sedi = row.get("cap_sedi")
                # ctx.nomedir_prov = row.get("nomedir_prov")
                # ctx.cogndir_prov = row.get("cogndir_prov")
                ctx.comune_sedi = row.get("comune_sedi")

                BatchLogger.info(
                    "REC-DIRETTORE",
                    f"NOMEDIR={ctx.nomedir} | COGNDIR: {ctx.cogndir} | Sede={ctx.sede}",
                    depth=depth+1
                )

                '''Rif. COBOL: verifica che tutti i campi della sede siano valorizzati.
                Se anche uno solo è vuoto, la sede non è valida: tutti gli avvisi
                di quella sede vengono marcati per riciclo ('0R') invece di proseguire.'''
                campi_sede = [
                    ctx.nomedir, ctx.cogndir, ctx.sede,
                    ctx.pr, ctx.indir_sedi, ctx.cap_sedi, ctx.comune_sedi
                ]

                if any(not campo or not str(campo).strip() for campo in campi_sede):
                    ctx.indic_sede_nonval = "X"
                    ctx.ws_cstatt = "0R"
                    ctx.ws_cstaart = "0R"
                    ctx.ws_cstacar = "K"
                    ctx.ws_erravv = "EXX392"

                    BatchLogger.info(
                        "SEDE-NON-VALIDA",
                        f"Dati sede incompleti per SSZZ={ctx.sszz}: avvisi marcati per riciclo (0R)",
                        depth=depth + 1
                    )

                    self.step_imposta_errori.imp_errore_sede(ctx, depth=depth + 1)

                        # Rif. COBOL: UPDATE-T03-SEDE
                    self._aggiorna_t03_sede(ctx, depth=depth + 1)
            else:
                ctx.ws_cstatt = "0X"
                ctx.ws_cstaart = "0X"
                ctx.ws_erravv = "EXX391"

                self.step_imposta_errori.imp_errore_sede(ctx, depth=depth + 1)
                self._salva_delete_t03(ctx, depth=depth + 1)

            # Quando la sede è valida: RECUPERO-RAV e ELABORA-AVVISO-OK
            if ctx.indic_sede_nonval!= "X":

                #L'importo totale dell'AVA deve essere > 50 euro + spese notifica
                ctx.ws_itrbcar_50 = Decimal(5000 + 690)
                ctx.ws_itrbcar_12 = Decimal(12000 + 690)

                idgest_primo_carattere = (ctx.idAvvisoGest or "")[:1]

                soglia = ctx.ws_itrbcar_50 if idgest_primo_carattere in ("E", "F") else ctx.ws_itrbcar_12

                if ctx.impCaricoCartella is not None and ctx.impCaricoCartella >= soglia:
                    self.step_recupero_rav.execute_dettaglio(ctx, depth=depth+1)

                    # se trovo RAV --> elaborazione dell'avviso
                    if ctx.indic_rav_presente != "X":
                        self.step_elabora_avviso.execute_dettaglio(ctx, depth=depth+1)
                    else:
                        ctx.ws_cstatt = "0R"
                        ctx.ws_cstaart = "0R"
                        ctx.ws_cstacar = "K"
                        ctx.ws_erravv = "EXX393"

                        cstacar = str(row.get("statoCartella") or "")
                        if cstacar == "G":
                            self.step_imposta_errori.imp_errore_cesa(ctx, depth)

                        # UPDATE-T03-RAV
                        self._aggiorna_t03_rav(ctx, depth)
                else:
                    '''SCARTO AVVISO:
                    Se importo tributo dell'avviso è minore di 50 euro
                    e la gestione è pensioni (E o F) o se importo è minore di 12 euro
                    e gestione è diversa da pensioni, si procede allo scarto dell'avviso'''
                    if (ctx.idAvvisoGest or "")[:1] in ("E", "F"):
                             ctx.ws_erravv = "EXX396"
                    else:
                        ctx.ws_erravv = "EXX636"

                    ctx.ws_cstatt = "0X"
                    ctx.ws_cstaart = "0X"
                    ctx.indic_rav_presente = "X"
                    self.step_imposta_errori.imp_errore_importo(ctx, depth)
                    self._insert_adc03del(ctx, row, depth+1)
                    self._delete_t03_key(ctx, depth+1)

                self.engine.commit(depth=depth)

                BatchLogger.info(
                    "COMMIT",
                    f"COMMIT eseguito con successo",
                    depth=depth + 1)

                ctx.ws_ctr_t03 = 0

            if (ctx.indic_sede_nonval!= "X" and
                ctx.indic_rav_presente!="X" and ctx.indic_imp_avv != "X"):

                self._aggiorna_t03(ctx, depth+1)

            if ctx.ws_cstatt == 2000:
                self.engine.commit(depth=depth)

                BatchLogger.info(
                    "COMMIT",
                    f"COMMIT eseguito con successo",
                    depth=depth + 1)

                ctx.ws_ctr_t03 = 0
        except Exception as err:
            BatchLogger.error(
                "CICLO-CURT03-ERR",
                f"Errore critico durante elaborazione occorrenze in stato formato: {err}",
                depth=depth
                )
            ctx.indic_errore = "X"
            raise

    def _aggiorna_t03_sede(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 1) -> None:
        """Aggiorna massivamente lo stato del record su ADCFRT03 impostando lo stato in 'K'."""
        righe_impattate = self._db_update_t03_sede(ctx, depth=depth + 1)
        BatchLogger.info("UPD-T03-SEDE", f"UPDATE ADCTET03 -> CSTACAR= {ctx.ws_cstacar} (Righe impattate: {righe_impattate})",
                         depth=depth,
                         is_last=is_last)

    def _db_update_t03_sede(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False,
                            depth: int= 1) -> int:
        """Aggiorna lo stato del record su ADCFRT03 impostando lo stato dell'avviso a 'K' """
        upd_tab03_sede = (
            self.engine.dataset("ADCFRT03")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("statoCartella", "IN", ("G", "R"))
            .compile_update({
                    "statoCartella": ctx.ws_cstacar,
                    "timestampUpdStato" : datetime.now()
                })
            )
        try:
            return self.engine.execute_mutation(upd_tab03_sede, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T03-SEDE-ERR",
            f"Errore DB durante UPDATE ADCFRT03 : {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

    def _salva_delete_t03(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False,
                            depth: int = 1) -> None:

        BatchLogger.info("SALVA-CHIAVI", "Scrittura su ADC03DEL delle chiavi cancellate", depth=depth)
        t03_map = self.engine.get_table_map("ADCFRT03")
        try:
            raw_rows = self._db_fetch_curt03_del(ctx, depth=depth + 1)
            rows_t03_del = [t03_map.normalize(r) for r in raw_rows]

            tot_cartelle = len(rows_t03_del)
            ctx.righe_elaborate_sede = tot_cartelle

            if tot_cartelle == 0:
                    BatchLogger.info("SALVA-T03", "Nessuna cartella da salvare in ADC03DEL", depth=depth)

            # Rif. COBOL: PERFORM UNTIL FINE-CURT03-DEL -> INSERT-ADC03DEL
            for idx, row_t03_del in enumerate(rows_t03_del, start=1):
                BatchLogger.info(
                    "AVVISI-DA-ELIMINARE",
                    f"[{idx}/{tot_cartelle}] CESA= {ctx.cesa} | NCAR={ctx.numeroCartella} | ANNO={ctx.annoCartella}",
                    depth=depth,
                    is_last=False
                )

                BatchLogger.info(
                    "INSERT-ADC03DEL",
                    f"Avvio inserimento per [{idx}/{tot_cartelle}] CESA= {ctx.cesa} | NCAR={ctx.numeroCartella} | ANNO={ctx.annoCartella}",
                    depth=depth
                )
                righe_inserite = self._insert_adc03del(ctx, row=row_t03_del, depth=depth + 1)

                BatchLogger.info(
                    "INSERT-PILOTA-COMPLETATO",
                    f"Inserite {righe_inserite} righe in ADC03DE",
                    depth=depth
                )

            # Ref. COBOL DELETE-T03
            # Cancellazione fisica dalla ADCFRT03 per CSED e CZON relativamente a sedi non attive su AGESEDI

            righe_eliminate = self._delete_t03(ctx, depth = depth + 1)


            BatchLogger.info("DELETE-T03", f"DELETE ADCFRT03 -> CSED= {ctx.current_sede} e CZON = {ctx.current_zona} (Righe impattate: {righe_eliminate})", depth=depth,
                         is_last=is_last)

        except Exception as err:
            BatchLogger.error(
                "INSERT-DELETE-T03-ERR",
                f"Errore critico durante salvataggio chiave di ADCFRT03: {err}",
                depth=depth
                )
            ctx.indic_errore = "X"
            raise

    def _db_fetch_curt03_del(self, ctx:PreparazionePostalizzazioneContext, depth: int) -> List[Any]:
        """Accesso atomico DB: apertura cursore sedi operative su ADCFRT03 con statoCartella='G'."""
        #OPEN-CURT03-DEL + FETCH-CURT03-DEL (estrazione degli avvisi formati o riciclati)
        query = (
            self.engine.dataset("ADCFRT03")
            .select(
                "codConcessione", "annoCartella", "numCartella", "chkCartella", "codiceFiscale", "statoCartella", "dataCartella",
                "impCaricoCartella", "divisa", "dataNotifica", "dataRegNotifica", "ambitoDelegato", "dataProvvDelega", "dataRegDelega",
                "annoRifFormazione", "numProgrAnnoForm", "annoRifNotifica", "numProgrAnnoNotif", "annoRifDelega", "numProgrAnnoDelega",
                "keyTabEventi", "soggetto", "timestampInsStato", "timestampUpdStato", "codEsattoriaAvviso",
                "idAvvisoGest", "tipoAvviso", "impAvvisoRav", "impAggio", "numPartiteAvviso", "codRav",
                "esitoNotifica", "motivoNotifica", "annoSpedNotifca", "numProgrAnnoSped", "statoSped", "dataConsegna",
                "sede", "zona", "identificativoAvviso", "cinesi", "codErroreEsito"
            )
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("statoCartella", "IN", ("G", "R"))
            .order_by("sede", "zona")
            .with_uncommitted_read()
            .compile_select()
        )
        try:
            return [raw for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth)
                    for raw in chunk]

        except Exception as err:
            BatchLogger.error("DB-FETCH-CURT03-DEL-ERR",
                              f"Errore DB durante apertura cursore avvisi su ADCFRT03 per SEDE = {ctx.current_sede} e ZONA = {ctx.current_zona}: {err}", depth=depth)
            raise

    def _insert_adc03del(self, ctx, row, depth: int) -> int:
        """Rif. COBOL: INSERT-ADC03DEL.
        Inserimento tabella ADC03DEL (salvataggio chiavi cancellate da ADCFRT03) """

        ins_adc03del = self.engine.dataset("ADC03DEL").compile_insert()({
            "cesa": ctx.cesa ,
            "acar": ctx.annoCartella ,
            "ncar": ctx.numeroCartella ,
            "cesaavv": row.get("cesaavv") ,
            "tms_ins_csacar": row.get("tms_ins_csacar") ,
            "cstacar": row.get("cstacar") ,
            "tms_del": datetime.now()
            })

        try:
            righe = self.engine.execute_mutation(ins_adc03del, depth=depth)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-ADC03DEL",
                f"Inserita riga CESA={ctx.cesa} | ACAR={ctx.annoCartella} | NCAR={ctx.numeroCartella}",
                depth=depth
            )
            return righe
        except Exception as e:
            BatchLogger.error(
                "INSERT-ADC03DEL-ERRORE",
                f"Fallito inserimento CESA={ctx.cesa} | ACAR={ctx.annoCartella} | NCAR={ctx.numeroCartella}: {e}",
                depth=depth, is_last=True
            )
            raise

    def _delete_t03(self, ctx, row, depth: int) -> int:
        """Rif. COBOL: DELETE-T03.
        Cancellazione fisica dalla tabella ADCFRT03 per sede e zona relativamente a sedi non attive su AGESEDI """

        BatchLogger.info(
            "DELETE-T03",
            f"Delete tabella ADCFRT03 per SEDE={ctx.current_sede}, ZONA={ctx.current_zona}",
            depth=depth
        )

        delete_t03 = (
            self.engine.dataset("ADCFRT03")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("statoCartella", "IN", ("G", "R"))
            .compile_delete()
        )

        try:
            righe = self.engine.execute_mutation(delete_t03, depth=depth)

            return righe
        except Exception as e:
            BatchLogger.error(
                "DELETE-T03-ERRORE",
                f"Fallita cancellazione CESA={ctx.cesa} | ACAR={ctx.annoCartella} | NCAR={ctx.numeroCartella}: {e}",
                depth=depth, is_last=True
            )
            raise

    def _select_agesedi(self, ctx: PreparazionePostalizzazioneContext,
                            depth: int) -> List[Any]:
        """Accesso a tabella VSEDI_ADDEBITI per ricavare i seguenti dati relativi alla sede INPS:
            - NOME DEL DIRETTORE DI SEDE
            - COGNOME DEL DIRETTORE DI SEDE
            - SEDE
            - PROVINCIA SEDE
            - INDIRIZZO SEDE
            - CAP DELLA SEDE
            - COMUNE SEDE
            - NOME DEL RESPONSABILE DEL PROCEDIMENTO
            - COGNOME DEL RESPONSABILE DEL PROCEDIMENTO   """

        ctx.sszz = f"{str(ctx.current_sede).ljust(2)}{str(ctx.current_zona).ljust(2)}"

        query = (
            self.engine.dataset("VSEDI_ADDEBITI")
            .select("nomedir", "cogndir", "sede", "pr", "indir_sedi", "cap_sedi", "nomedir_prov", "cogndir_prov",
                    "tipo_sup", "comune_sedi", "nome_respproc", "cogn_respproc", "flag_e")
            .filter_by("sszz", "=", ctx.sszz)
            .with_uncommitted_read()
            .compile_select()
        )

        try:
            return self.engine.fetch(query, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-SELECT-AGESEDI-ERR",
                f"Errore DB durante la SELECT su VSEDI_ADDEBITI [SSZZ={ctx.sszz}]: {err}",
                depth=depth
            )
            raise

    def _aggiorna_t03_rav(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCFRT03 impostando lo stato dell'avviso a 'K' """
        upd_tab03_rav = (
            self.engine.dataset("ADCFRT03")
            .filter_by("codConcessione", "=", ctx.cesa)
            .filter_by("annoCartella", "=", ctx.annoCartella)
            .filter_by("statoCartella", "=", "G")
            .compile_update({
                    "statoCartella": ctx.ws_cstacar,
                    "timestampInsStato" : datetime.now()
                })
            )

        righe_impattate = self.engine.execute_mutation(upd_tab03_rav, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T03", f"UPDATE ADCTET03 -> CSTACAR= {ctx.ws_cstacar} (Righe impattate: {righe_impattate})",
                             depth=depth)

    def _delete_t03_key(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        # Ref. COBOL DELETE-T03-KEY
        # Cancellazione fisica dalla ADCFRT03 per chiave

        delete_t03_key = (
            self.engine.dataset("ADCFRT03")
                .filter_by("codConcessione", "=", ctx.cesa)
                .filter_by("annoCartella", "=", ctx.annoCartella)
                .filter_by("chkCartella", "=", ctx.chkCartella)
                .filter_by("statoCartella", "IN", ("G", "R"))
                .compile_delete()
            )

        righe_impattate = self.engine.execute_mutation(delete_t03_key, depth=depth + 1)
        BatchLogger.info("DELETE-T03", f"DELETE ADCFRT03 -> CESA= {ctx.cesa}, ACAR = {ctx.annoCartella} e NCAR = {ctx.numeroCartella}(Righe impattate: {righe_impattate})", depth=depth)

    def _aggiorna_t03(self, ctx: PreparazionePostalizzazioneContext,
                            depth: int = 2) -> None:
        """Aggiorna la tabella ADCFRT03 impostando lo stato dell'avviso a 'Q'
         e inserisce il campo RAV-17 calcolato"""
        upd_tab03 = (
            self.engine.dataset("ADCFRT03")
            .filter_by("codConcessione", "=", ctx.cesa)
            .filter_by("annoCartella", "=", ctx.annoCartella)
            .filter_by("numCartella", "=", ctx.numeroCartella)
            .compile_update({
                    "statoCartella": "Q",
                    "codRav": ctx.rav_17,
                    "dataCartella" : ctx.dinifor,
                    "timestampUpdStato" : datetime.now()
                })
            )

        righe_impattate = self.engine.execute_mutation(upd_tab03, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T03", f"UPDATE ADCTET03 -> CSTACAR= 'Q' (Righe impattate: {righe_impattate})",
                             depth=depth)


class ElaborazioneCurt03Step:
    """ELABORAZIONE - Apertura cursore su ADCFRT03"""

    def __init__(self, engine):
        self.engine = engine
        self.step_ciclo_curt03 = ElaborazioneCicloCurt03Step(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione principale", depth=0)
        ctx.ws_ctr_t03 = 0
        t03_map = self.engine.get_table_map("ADCFRT03")

        try:
            raw_rows = self._db_fetch_curt03(ctx, depth=depth + 1)
            rows_t03 = [t03_map.normalize(r) for r in raw_rows]

            tot_cartelle = len(rows_t03)
            ctx.righe_elaborate_sede = tot_cartelle

            if tot_cartelle == 0:
                BatchLogger.info("SCAN-CARTELLE-T03", "Nessuna cartella esattoriale rilevata in stato G o R", depth=depth+1)

            BatchLogger.info("SCAN-CARTELLE-T03", f"Cartelle esattoriali rilevate in stato G o R: {tot_cartelle}",
                             depth=depth+1)

            tbl_sep = "+--------+------+------+------+---------+------------+"
            header = f"| {'CESA':<6} | {'ACAR':<5} | {'NCAR':<5} | {'CSTACAR':<10} | {'CSED':<4} | {'CZON':<4} |"
            BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth+1)
            BatchLogger.info("ELENCO-CARTELLE", header, depth=depth+1)
            BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth+1)
            for row in rows_t03:
                row_str = (
                    f"| {str(row['codConcessione']):<6} | {str(row['annoCartella']):<5} | {str(row['numCartella']):<5} "
                    f"| {str(row['statoCartella']):<10} | {str(row['sede']):<4} | {str(row['zona']):<4} |"
                )
                BatchLogger.info("ELENCO-CARTELLE", row_str, depth=depth+1)
            BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth+1)

            # PERFORMA UNTIL FINE-CURT03 OR ERRORE
            for idx, row_t03 in enumerate(rows_t03, start=1):
                is_last_cartella = (idx == tot_cartelle)
                ctx.ws_ctr_t03 += 1

                ctx.cesa = row_t03.get("codConcessione")
                ctx.annoCartella = row_t03.get("annoCartella")
                ctx.numeroCartella = row_t03.get("numeroCartella")
                ctx.chkCartella = row_t03.get("chkCartella")
                ctx.idAvviso = row_t03.get("identificativoAvviso")
                ctx.impAvvisoRav = row_t03.get("impAvvisoRav")
                ctx.impCaricoCartella = row_t03.get("impCaricoCartella")
                ctx.impAggio = row_t03.get("impAggio")
                ctx.idAvvisoGest = row_t03.get("idAvvisoGest")

                BatchLogger.info(
                    "AVVISI-FORMATI",
                    f"[{idx}/{tot_cartelle}] CESA={ctx.cesa}, NCAR={ctx.numeroCartella} | ANNO={ctx.annoCartella}",
                    depth=depth + 1,
                    is_last=False
                )

                self.step_ciclo_curt03.execute_record(
                    ctx=ctx,
                    row=row_t03,
                    depth=depth + 1,
                    is_last_cartella=is_last_cartella
                )

                # Rif. COBOL: UPDATE-T03-FINE
            self._aggiorna_t03_fine(ctx, depth=depth + 1)

        except Exception as err:
            BatchLogger.error(
                "CURT03-ERR",
                f"Errore critico durante la scansione cartelle distinte per sede {ctx.current_sede}: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise

    # =========================================================================
    # =========================================================================
    # ACCESSI AL DATABASE CURT03 (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_curt03(self, ctx:PreparazionePostalizzazioneContext, depth: int) -> List[Any]:
        """Accesso atomico DB: apertura cursore sedi operative su ADCFRT03 con statoCartella='G'."""
        #OPEN-CURT03 + FETCH-CURT03 (estrazione degli avvisi formati o riciclati su ADCFRT03, CSTACAR = 'G' o CSTACAR = 'R')
        query = (
            self.engine.dataset("ADCFRT03")
            .select(
                "codConcessione", "annoCartella", "numCartella", "chkCartella", "codiceFiscale", "statoCartella", "dataCartella",
                "impCaricoCartella", "divisa", "dataNotifica", "dataRegNotifica", "ambitoDelegato", "dataProvvDelega", "dataRegDelega",
                "annoRifFormazione", "numProgrAnnoForm", "annoRifNotifica", "numProgrAnnoNotif", "annoRifDelega", "numProgrAnnoDelega",
                "keyTabEventi", "soggetto", "timestampInsStato", "timestampUpdStato", "codEsattoriaAvviso",
                "idAvvisoGest", "tipoAvviso", "impAvvisoRav", "impAggio", "numPartiteAvviso", "codRav",
                "esitoNotifica", "motivoNotifica", "annoSpedNotifca", "numProgrAnnoSped", "statoSped", "dataConsegna",
                "sede", "zona", "identificativoAvviso", "cinesi", "codErroreEsito"
            )
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("statoCartella", "IN", ("G", "R"))
            .order_by("sede", "zona")
            .with_uncommitted_read()
            .compile_select()
        )
        try:
            return [raw for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth)
                    for raw in chunk]

        except Exception as err:
            BatchLogger.error("DB-FETCH-CURT03-ERR",
                              f"Errore DB durante apertura cursore avvisi formati ADCFRT03: {err}", depth=depth)
            raise

    def _aggiorna_t03_fine(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 1) -> None:
        """Aggiorna massivamente lo stato del record su ADCFRT03 impostando lo stato in 'R'."""
        righe_impattate = self._db_update_t03(ctx, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T03", f"UPDATE ADCTET03 -> CSTACAR='R' (Righe impattate: {righe_impattate})",
                         depth=depth,
                         is_last=is_last)


    def _db_update_t03(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento massivo di fine ciclo a CSTACAR='R'."""
        upd_tab03 = (
            self.engine.dataset("ADCFRT03")
            .filter_by("statoCartella", "=", 'K')
            .compile_update({
                    "statoCartella": "R",
                    "timestampUpdStato": datetime.now()
                })
            )
        try:
            return self.engine.execute_mutation(upd_tab03, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T03-FINE-ERR",
            f"Errore DB durante UPDATE ADCFRT03 a 'R' "
                 f"[CESA={ctx.cesa} | ANNO={ctx.annoCartella} | NCAR={ctx.numeroCartella}]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

class ElaborazioneCurt17Step:
    """ELABORA-T17 - Scansione delle sedi su ADCTET17 + elaborazione"""

    def __init__(self, engine):
        self.engine = engine
        self.step_curt03 = ElaborazioneCurt03Step(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> None:
        BatchLogger.info("ELABORA-T17", "Avvio scansione sedi operative", depth=0)
        t17_map = self.engine.get_table_map("ADCTET17")
        # rows = []

        try:
            raw_rows = self._db_fetch_curt17(depth=depth + 1)
            rows = [t17_map.normalize(r) for r in raw_rows]

            tot_sedi = len(rows)
            ctx.totale_record_curt17 = tot_sedi

            # Rif. COBOL: IF SQL-KEY-NON-TROVATA -> SEGNALA-LOG-001 (avviso, non blocca)
            if tot_sedi == 0:
                BatchLogger.warn("CURT17", "Nessuna sede operativa trovata su ADCTET17 (CDAS='IF')", depth=depth + 1)

            # PERFORM UNTIL FINE-CURT17 OR ERRORE
            for idx, row in enumerate(rows, start=1):
                is_last_sede = (idx == tot_sedi)

                ctx.current_sede = row.get("sede")
                ctx.current_zona = row.get("zona")
                ctx.current_cod_centro = row.get("codCentro")
                ctx.current_cod_servizio = row.get("codServizio")
                ctx.righe_elaborate_sede = 0


                BatchLogger.info(
                    "SEDE-OPERATIVA",
                    f"[{idx}/{tot_sedi}] CSED={ctx.current_sede} | CZON={ctx.current_zona} | CCOP={ctx.current_cod_centro}",
                    depth=depth+1
                )
                # CICLO-CURT17
                self.step_curt03.execute(ctx, depth=depth + 1)  # PERFORM ELABORAZIONE
                self._aggiorna_tet17(ctx, is_last=is_last_sede, depth=depth + 1)  # PERFORM UPDATE-T17

        except Exception as err:
            BatchLogger.error(
                "CURT17-ERR",
                f"Errore critico durante la scansione sedi operative CURT17: {err}",
                depth=0
            )
            ctx.indic_errore = "X"
            if hasattr(self.engine, "rollback"):
                try:
                    self.engine.rollback()
                    BatchLogger.warn("CURT17-ERR", "Rollback transazionale eseguito a fronte del fallimento sedi", depth=0)
                except Exception as rollback_err:
                    BatchLogger.error("CURT17-ERR", f"Fallito il rollback: {rollback_err}", depth=0)
            raise
    # =========================================================================
    # =========================================================================
    # ACCESSI AL DATABASE CURT17 (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_curt17(self, depth: int) -> List[Any]:
        """Accesso atomico DB: apertura cursore sedi operative su ADCTET17 con codServizio='IF'."""
        #OPEN-CURT17 + FETCH-CURT17 (estrazione infasamento crediti 'IF')
        query = (
            self.engine.dataset("ADCTET17")
            .distinct()
            .select("sede", "zona", "codCentro", "codServizio")
            .filter_by("codServizio", "=", "IF")
            .filter_by("dataPre", "<=", date.today())
            .order_by("sede", "zona", "codCentro")
            .with_uncommitted_read()
            .compile_select()
        )
        try:
            return [raw for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth)
                    for raw in chunk]

        except Exception as err:
            BatchLogger.error("DB-FETCH-CURT17-ERR",
                              f"Errore DB durante apertura cursore sedi ADCTET17: {err}", depth=depth)
            raise

    def _aggiorna_tet17(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 1) -> None:
        """Aggiorna massivamente lo stato del record su ADCTET17 impostando il servizio a 'PO' a fine elaborazione."""
        righe_impattate_po = self._db_update_tet17_po(ctx, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='PO' (Righe impattate: {righe_impattate_po})", depth=depth, is_last=is_last)

        # Rif. COBOL: IF NOT ERRORE -> EXEC SQL COMMIT
        #if ctx.indic_errore != "X":
        self.engine.commit(depth=depth)


    def _db_update_tet17_po(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento massivo di fine ciclo a CDAS='PO'."""
        upd_tet17 = (
                self.engine.dataset("ADCTET17")
                .filter_by("csed", "=", ctx.current_sede)
                .filter_by("czon", "=", ctx.current_zona)
                .filter_by("ccop", "=", ctx.current_cod_centro)
                .compile_update({
                    "cdas": "PO"
                })
        )
        try:
            return self.engine.execute_mutation(upd_tet17, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-TET17-PO-ERR",
            f"Errore DB durante UPDATE ADCTET17 a 'PO' "
                 f"[CSED={ctx.current_sede} | CZON={ctx.current_zona} | CCOP={ctx.current_cod_centro}]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise