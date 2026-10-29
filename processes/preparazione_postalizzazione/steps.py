# processes/preparazione_postalizzazione/steps.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import PreparazionePostalizzazioneContext
from core.batch_logger import BatchLogger
from .step_recupero_rav import DettaglioRecuperoRav
from .step_elabora_avviso import DettaglioElaboraAvviso

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

    def execute_record(self, ctx: PreparazionePostalizzazioneContext, row, depth: int = 1, is_last_cartella: bool = False) -> None:
        csed_corrente = ctx.current_sede
        czon_corrente = ctx.current_zona
        #csed_corrente = row.get("csed")
        #czon_corrente = row.get("czon")

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

            self._select_agesedi(ctx, depth=depth + 1)

            # Rif. COBOL: verifica che tutti i campi della sede siano valorizzati.
            # Se anche uno solo è vuoto, la sede non è valida: tutti gli avvisi
            # di quella sede vengono marcati per riciclo ('0R') invece di proseguire.
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

                self._imp_errore_sede(ctx, depth=depth + 1)

                    # Rif. COBOL: UPDATE-T03-SEDE
                self._update_t03_sede(ctx, depth=depth + 1)
        else:
            ctx.ws_cstatt = "0X"
            ctx.ws_cstaart = "0X"
            ctx.ws_erravv = "EXX391"

            self._imp_errore_sede(ctx, depth=depth + 1)
            self._salva_delete_t03(ctx, depth=depth + 1)

        # Quando la sede è valida: RECUPERO-RAV e ELABORA-AVVISO-OK
        if ctx.indic_sede_nonval!= "X":

            #L'importo totale dell'AVA deve essere > 50 euro + spese notifica
            ctx.ws_itrbcar_50 = 5000 + 690
            ctx.ws_itrbcar_12 = 12000 + 690

            idAvvisoGest = row.get("idAvvisoGest")

            idgest_primo_carattere = (idAvvisoGest or "")[:1]

            soglia = ctx.ws_itrbcar_50 if idgest_primo_carattere in ("E", "F") else ctx.ws_itrbcar_12

            if ctx.impCaricoCartella is not None and ctx.impCaricoCartella >= soglia:
                self.step_recupero_rav.execute_dettaglio(ctx, depth=depth)

                # se trovo RAV --> elaborazione dell'avviso
                if ctx.indic_rav_presente != "X":
                    self.step_elabora_avviso.execute_dettaglio(ctx, depth=depth)
                else:
                    ctx.ws_cstatt = "0R"
                    ctx.ws_cstaart = "0R"
                    ctx.ws_cstacar = "K"
                    ctx.ws_erravv = "EXX393"


    def _update_t03_sede(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False,
                            depth: int = 2) -> None:
        current_system_date = date.today()
        """Aggiorna lo stato del record su ADCFRT03 impostando lo stato dell'avviso a 'K' """
        upd_tab03_sede = (
            self.engine.dataset("ADCFRT03")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("statoCartella", "IN", ("G", "R"))
            .compile_update({
                    "statoCartella": ctx.ws_cstacar,
                    "timestampUpdStato" : current_system_date
                })
            )

        righe_impattate = self.engine.execute_mutation(upd_tab03_sede, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T03", f"UPDATE ADCTET03 -> CSTACAR= {ctx.ws_cstacar} (Righe impattate: {righe_impattate})",
                             depth=depth,
                             is_last=is_last)

    def _salva_delete_t03(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False,
                            depth: int = 2) -> None:

        BatchLogger.info("SALVA-CHIAVI", "Scrittura su ADC03DEL delle chiavi cancellate", depth=depth+1)
        t03_map = self.engine.get_table_map("ADCFRT03")

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
        row_t03 = []
        for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth):
            for raw_row in chunk:
                row_t03.append(t03_map.normalize(raw_row))

        tot_cartelle = len(row_t03)
        ctx.righe_elaborate_sede = tot_cartelle

        if tot_cartelle == 0:
            BatchLogger.info("SALVA-T03", "Nessuna cartella da salvare in ADC03DEL", depth=depth)
            return


        # Rif. COBOL: PERFORM UNTIL FINE-CURT03-DEL -> INSERT-ADC03DEL
        for idx, row in enumerate(row_t03, start=1):
            BatchLogger.info(
                "AVVISI-DA-ELIMINARE",
                f"[{idx}/{tot_cartelle}] NCAR={row['numCartella']} | ANNO={row['annoCartella']}",
                depth=depth + 1,
                is_last=False
            )

            BatchLogger.info(
                "INSERT-ADC03DEL",
                f"Avvio inserimento per [{idx}/{tot_cartelle}] NCAR={row['numCartella']} | ANNO={row['annoCartella']}",
                depth=1
            )
            self._insert_adc03del(ctx, row, depth=depth + 1)

        # Ref. COBOL DELETE-T03
        # Cancellazione fisica dalla ADCFRT03 per CSED e CZON relativamente a sedi non attive su AGESEDI

        delete_t03 = (
            self.engine.dataset("ADCFRT03")
                .filter_by("sede", "=", ctx.current_sede)
                .filter_by("zona", "=", ctx.current_zona)
                .compile_delete({
                    "statoCartella", "IN", ("G", "R")
                })
            )

        righe_impattate = self.engine.execute_mutation(delete_t03, depth=depth + 1)
        BatchLogger.info("DELETE-T03", f"DELETE ADCFRT03 -> CSED= {ctx.current_sede} e CZON = {ctx.current_zona} (Righe impattate: {righe_impattate})", depth=depth,
                     is_last=is_last)

    def _insert_adc03del(self, ctx, row, depth: int) -> None:
        """Rif. COBOL: INSERT-ADC03DEL.
        Inserimento tabella ADC03DEL (salvataggio chiavi cancellate da ADCFRT03) """

        record_adc03del = {
            "cesa": row.get("cesa") ,
            "acar": row.get("acar") ,
            "ncar": row.get("ncar") ,
            "cesaavv": row.get("cesaavv") ,
            "tms_ins_csacar": row.get("tms_ins_csacar") ,
            "cstacar": row.get("cstacar") ,
            "tms_del": datetime.now()
        }
        query = self.engine.dataset("ADC03DEL").compile_insert(record_adc03del)


        try:
            self.engine.execute_mutation(query, depth=2)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-ADC03DEL",
                f"Inserita riga CESA={row.get('cesa')} | ACAR={row.get('acar')} | NCAR={row.get('ncar')}",
                depth=2
            )
        except Exception as e:
            BatchLogger.error(
                "INSERT-ADC03DEL-ERRORE",
                f"Fallito inserimento CESA={row.get('cesa')} | ACAR={row.get('acar')} | NCAR={row.get('ncar')}: {e}",
                depth=2, is_last=True
            )
            raise

    def _select_agesedi(self, ctx: PreparazionePostalizzazioneContext,
                            depth: int = 2) -> None:
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
        tVSedi_map = self.engine.get_table_map("VSEDI_ADDEBITI")

        ctx.sszz = f"{str(ctx.current_sede).ljust(2)}{str(ctx.current_zona).ljust(2)}"

        query = (
            self.engine.dataset("VSEDI_ADDEBITI")
            .select("nomedir", "cogndir", "sede", "pr", "indir_sedi", "cap_sedi", "nomedir_prov", "cogndir_prov",
                    "tipo_sup", "comune_sedi", "nome_respproc", "cogn_respproc", "flag_e")
            .filter_by("sszz", "=", ctx.sszz)
            .with_uncommitted_read()
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)

        if not rows:
            BatchLogger.error("SELECT-AGESEDI", "SEDE NON PRESENTE O NON VALIDA: Nessun record valido in VSEDI_ADDEBITI.", depth=1, is_last=True)
            ctx.indic_errore = "X"
            ctx.indic_sede_nonval = "X"
            return

        row = tVSedi_map.normalize(rows[0])
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
            depth=1
        )

    def _imp_errore_sede(self, ctx: PreparazionePostalizzazioneContext, depth: int = 4) -> None:
       """Imposta errore riferito alla sede non valida su ADCFRT01 e ADCFRT10"""

        # ctx.indic_errore = "X"
        # BatchLogger.error(
        #     "SCARTO-AVVISO",
        #     f"Avviso scartato [{ctx.ws_annoavv}/{ctx.ws_progavv}] CATT={row_t01.get('codiceAtto')} -> Errore bloccante: {ctx.ws_erravv}",
        #     depth=depth
        # )

class ElaborazioneCurt03Step:
    """ELABORAZIONE - Apertura cursore su ADCFRT03"""

    def __init__(self, engine):
        self.engine = engine
        self.step_ciclo_curt03 = ElaborazioneCicloCurt03Step(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione principale", depth=0)
        t03_map = self.engine.get_table_map("ADCFRT03")

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
        row_t03 = []
        for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth):
            for raw_row in chunk:
                row_t03.append(t03_map.normalize(raw_row))


        tot_cartelle = len(row_t03)
        ctx.righe_elaborate_sede = tot_cartelle

        if tot_cartelle == 0:
            BatchLogger.info("SCAN-CARTELLE-T03", "Cartelle esattoriali rilevate in stato G o R: 0", depth=depth)
            return

        BatchLogger.info("SCAN-CARTELLE-T03", f"Cartelle esattoriali rilevate in stato G o R: {tot_cartelle}",
                         depth=depth)

        tbl_sep = "+--------+------+------+------+---------+------------+"
        header = f"| {'CESA':<6} | {'ACAR':<5} | {'NCAR':<5} | {'CSTACAR':<10} | {'CSED':<4} | {'CZON':<4} |"
        BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth)
        BatchLogger.info("ELENCO-CARTELLE", header, depth=depth)
        BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth)
        for row in row_t03:
            row_str = (
                f"| {str(row['codConcessione']):<6} | {str(row['annoCartella']):<5} | {str(row['numCartella']):<5} "
                f"| {str(row['statoCartella']):<10} | {str(row['sede']):<4} | {str(row['zona']):<4} |"
            )
            BatchLogger.info("ELENCO-CARTELLE", row_str, depth=depth)
        BatchLogger.info("ELENCO-CARTELLE", tbl_sep, depth=depth)

        for idx, row in enumerate(row_t03, start=1):
            is_last_cartella = (idx == tot_cartelle)

            ctx.cesa = row.get("codConcessione")
            ctx.annoCartella = row.get("annoCartella")
            ctx.numeroCartella = row.get("numeroCartella")
            ctx.chkCartella = row.get("chkCartella")
            ctx.idAvviso = row.get("identificativoAvviso")
            ctx.impAvvisoRav = row.get("impAvvisoRav")
            ctx.impCaricoCartella = row.get("impCaricoCartella")
            ctx.impAggio = row.get("impAggio")

            BatchLogger.info(
                "AVVISI-FORMATI",
                f"[{idx}/{tot_cartelle}] NCAR={ctx.numeroCartella} | ANNO={ctx.annoCartella}",
                depth=depth + 1,
                is_last=False
            )

            self.step_ciclo_curt03.execute_record(
                ctx=ctx,
                row=row,
                depth=depth + 1,
                is_last_cartella=is_last_cartella
            )

            # Rif. COBOL: UPDATE-T03-FINE
        self._update_t03_fine(ctx, depth=depth + 1)

    def _update_t03_fine(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False,
                            depth: int = 2) -> None:
        current_system_date = date.today()
        """Aggiorna lo stato del record su ADCFRT03 impostando lo stato dell'avviso da 'K' a 'R'"""
        upd_tab03 = (
            self.engine.dataset("ADCFRT03")
            .filter_by("statoCartella", "=", 'K')
            .compile_update({
                    "statoCartella": "R",
                    "timestampUpdStato": current_system_date
                })
            )

        righe_impattate = self.engine.execute_mutation(upd_tab03, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T03", f"UPDATE ADCTET03 -> CSTACAR='R' (Righe impattate: {righe_impattate})",
                             depth=depth,
                             is_last=is_last)

class ElaborazioneCurt17Step:
    """ELABORA-T17 - Scansione delle sedi su ADCTET17 + elaborazione"""

    def __init__(self, engine):
        self.engine = engine
        self.step_curt03 = ElaborazioneCurt03Step(engine)

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("ELABORA-T17", "Avvio scansione sedi operative", depth=0)
        t17_map = self.engine.get_table_map("ADCTET17")

        #OPEN-CURT17 + FETCH-CURT17 (estrazione infasamento crediti 'IF')
        query = (
            self.engine.dataset("ADCTET17")
            .distinct()
            .select("csed", "czon", "ccop", "cdas")
            .filter_by("cdas", "=", "IF")
            .filter_by("dataPre", "<=", date.today())
            .order_by("csed", "czon", "ccop")
            .with_uncommitted_read()
            .compile_select()
        )

        rows = []
        for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth):
            for raw_row in chunk:
                rows.append(t17_map.normalize(raw_row))

        if not rows:
            BatchLogger.info("CURT17", "Nessun dato disponibile su ADCTET17 per infasamento crediti", depth=depth + 1)
            return

        tot_sedi = len(rows)
        ctx.totale_record_curt17 = tot_sedi
        ctx.indic_aggiorna = False

        # PERFORM UNTIL FINE-CURT17 OR ERRORE
        for idx, row in enumerate(rows, start=1):
            is_last_sede = (idx == tot_sedi)

            ctx.current_sede = row.get("sede")
            ctx.current_zona = row.get("zona")
            ctx.current_cod_centro = row.get("codCentro")
            ctx.current_cod_servizio = row.get("codServizio")
            ctx.righe_elaborate_sede = 0
            ctx.indic_errore = " "

            BatchLogger.info(
                "SEDE-OPERATIVA",
                f"[{idx}/{tot_sedi}] CSED={ctx.current_sede} | CZON={ctx.current_zona} | CCOP={ctx.current_cod_centro}",
                depth=1
            )

            self.step_curt03.execute(ctx, depth=2)  # PERFORM ELABORAZIONE
            self._aggiorna_tab17(ctx, is_last=is_last_sede, depth=depth + 1)  # PERFORM UPDATE-T17

            #self._ciclo_curt17(ctx, row, is_last=is_last_sede, depth=depth)
            if ctx.indic_errore != " ":
                break

    def _aggiorna_tab17(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCTET17 impostando il servizio a 'PO'."""
        upd_tab17 = (
            self.engine.dataset("ADCTET17")
            .filter_by("csed", "=", ctx.current_sede)
            .filter_by("czon", "=", ctx.current_zona)
            .filter_by("ccop", "=", ctx.current_cod_centro)
            .compile_update({
                "cdas": "PO"
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_tab17, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='PO' (Righe impattate: {righe_impattate})", depth=depth,
                     is_last=is_last)