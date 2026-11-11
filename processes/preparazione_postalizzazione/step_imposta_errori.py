# processes/preparazione_postalizzazione/step_recupero_rav.py
from datetime import date, datetime
from typing import Optional

from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext

class DettaglioErrori:
    """
    Impostazione errori:
    - IMP-ERRORE-SEDE: riferito a sede non valida
    - IMP-ERRORE-CESA: riferito al range rave non presente per il CESA
    - IMP-ERRORE-IMPORTO: riferito all'importo del tributo maggiore di 200000 o minore di 50
    """

    def __init__(self, engine):
        self.engine = engine

    def imp_errore_sede(self, ctx: PreparazionePostalizzazioneContext, depth: int = 4) -> None:
       """Imposta errore riferito alla sede non valida su ADCFRT01 e ADCFRT10"""
       BatchLogger.info("CURSORE-CURT01-SEDE", "Estrazione delle partite su ADCFRT01 per sede", depth=1)
       t01_map = self.engine.get_table_map("ADCFRT01")

       # Equivalente di OPEN-CURT01-SEDE + FETCH-CURT01-SEDE: CURSORE DI ESTRAZIONE DELLE PARTITE SU ADCFRT01 PER SEDE
       query = (
           self.engine.dataset("ADCFRT01")
           .select("gestione", "codiceAtto", "codiceFiscale", "sede", "zona",
                   "codCentro", "partitaIva", "dataInf", "dataNot", "codDipendente", "dataRifCon",
                   "codAzienda", "descrizioneAtto", "annoEmissione", "numEmissione", "numInail", "codSegnalazione",
                   "flgDecadenza", "meseInizioPeriodo", "meseFinePeriodo", "dataFallimento", "numSogg", "numRate",
                   "statoAttivita", "codEsattoria", "flgValFiscale", "annoRifRuolo", "numRuolo", "flgEuro",
                   "codEsattoriaDel",
                   "annoCarico", "numCarico", "numChkCarico", "dataTransizioneStato", "flgIscrizione", "flgCessione",
                   "codCausale",
                   "codFasAmm", "statoAzienda", "dataStatoAzienda", "descrizioneAttoBi", "timestampInsStato",
                   "timestampVarStato",
                   "tipoAvviso", "annoAvviso", "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi",
                   "sedeOrigine",
                   "flgSanzioni", "flgCessioneRuolo", "flgRateizzazione", "codEsattoriaAvviso", "codiceErrore",
                   "flgSanzioniAdr")
           .filter_by("sede", "=", ctx.current_sede)
           .filter_by("zona", "=", ctx.current_zona)
           .filter_by("statoAttivita", "IN", "(0G, 0R)")
           .with_uncommitted_read()
           .compile_select()
       )
       rows_t01 = self.engine.fetch(query, depth=1)
       tot_t01 = len(rows_t01)

       if tot_t01 == 0:
           BatchLogger.error("PARTITE-ESTRATTE-ADCFRT01", f"Nessuna partita estratta su ADCFRT01", depth=depth)
           ctx.indic_errore = "X"

    # Rif. COBOL: PERFORM UNTIL FINE-CURT01-SEDE
       for idx, raw_row in enumerate(rows_t01, start=1):
           row_t01 = t01_map.normalize(raw_row)

           BatchLogger.info(
               "PARTITE-ESTRATTE-ADCFRT01",
               f"[{idx}/{tot_t01}]",
               depth=depth + 1,
               is_last=(idx == tot_t01)
           )

           # Rif. COBOL: MOVE WS-ERRAV TO CODERR OF CDCFRT01
           #             MOVE CGES/CATT OF CDCFRT01 TO CGES/CATT OF CDCFRT10
           coderr = ctx.ws_erravv
           cges = str(row_t01.get("gestione") or "").strip()
           catt = str(row_t01.get("codiceAtto") or "").strip()

           if ctx.ws_cstatt == "0X":
               idavv = str(ctx.idAvviso or "").strip()
               if ctx.ws_cges != "N" and ctx.catt != ctx.idAvviso:
                    self._aggiorna_stato_t01(ctx, row_t01, coderr, depth=depth + 2)
                    self._aggiorna_stato_t10(ctx, row_t01, cges, catt, depth=depth + 2)
               else:
                   # Se errore su avviso, si provvede a cancellazione fisica della partita creata per le spese di notifica
                    self._delete_t01(ctx, row_t01, cges, catt, depth=depth + 2)
                    self._delete_t10_t14(ctx, row_t01, cges, catt, depth=depth + 2)
           else:
               self._aggiorna_stato_t01(ctx, row_t01, coderr, depth=depth + 2)
               self._aggiorna_stato_t10(ctx, row_t01, cges, catt, depth=depth + 2)

        # ctx.indic_errore = "X"
        # BatchLogger.error(
        #     "SCARTO-AVVISO",
        #     f"Avviso scartato [{ctx.ws_annoavv}/{ctx.ws_progavv}] CATT={row_t01.get('codiceAtto')} -> Errore bloccante: {ctx.ws_erravv}",
        #     depth=depth
        # )
    def _aggiorna_stato_t01(self, ctx: PreparazionePostalizzazioneContext, row_t01, coderr, depth: int) -> None:

                """Aggiorna tabella ADCFRT01:
                 - Stato = '0X' o '0R'
                 - CODERR = ws_coderr
                 """
                upd_stato_t01 = (
                    self.engine.dataset("ADCFRT01")
                    .filter_by("gestione", "=", row_t01.get("gestione"))
                    .filter_by("codiceAtto", "=", row_t01.get("codiceAtto"))
                    .compile_update({
                        "statoAttivita": ctx.ws_cstatt,
                        "codiceErrore": coderr,
                        "timestampVarStato": datetime.now(),
                        "dataTransizioneStato" : date.today()
                    })
                )

                righe_impattate = self.engine.execute_mutation(upd_stato_t01, depth=depth + 1)
                BatchLogger.info("UPD-STATO-ADCFRT01",
                                 f"UPDATE ADCFRT01 -> STATO = {ctx.ws_cstatt} (Righe impattate: {righe_impattate})",
                                 depth=depth)
    def _aggiorna_stato_t10(self, ctx: PreparazionePostalizzazioneContext, row_t01, cges, catt, depth: int) -> None:

                """Aggiorna tabella ADCFRT10:
                 - Stato = '0X' o '0R'
                 """
                upd_stato_t10 = (
                    self.engine.dataset("ADCFRT10")
                    .filter_by("gestione", "=", cges)
                    .filter_by("codiceAtto", "=", catt)
                    .compile_update({
                        "statoArticolo": ctx.ws_cstaart,
                        "timestampUpd": datetime.now()
                    })
                )

                righe_impattate = self.engine.execute_mutation(upd_stato_t10, depth=depth + 1)
                BatchLogger.info("UPD-STATO-ADCFRT10",
                                 f"UPDATE ADCFRT10 -> STATO = {ctx.ws_cstatt} (Righe impattate: {righe_impattate})",
                                 depth=depth)
    def _delete_t01(self, ctx: PreparazionePostalizzazioneContext, row_t01, cges, catt, depth: int) -> None:
        # Ref. COBOL DELETE-T01
        # Accede all'archivio T01 per cancellazione partita relativa alle spes di notifica

        self._insert_adc01del(ctx,row_t01, depth)

        delete_t01 = (
            self.engine.dataset("ADCFRT01")
                .filter_by("gestione", "=", cges)
                .filter_by("codiceAtto", "=", catt)
                .compile_delete()
            )

        righe_impattate = self.engine.execute_mutation(delete_t01, depth=depth + 1)
        BatchLogger.info("DELETE-T03", f"DELETE ADCFRT01 -> CGES= {cges}, CATT = {catt} (Righe eliminate: {righe_impattate})", depth=depth)

    def _insert_adc01del(self, ctx: PreparazionePostalizzazioneContext, row_t01, depth: int) -> None:
        """Rif. COBOL: INSERT-ADC01DEL.
        Inserimento tabella ADC01DEL (salvataggio della partita prima della cancellazione) """
        appo_annoavv = row_t01.get("annoAvviso")
        appo_progravv = row_t01.get("progAvviso")

        idGest = ((row_t01.get("gestione") or "")
                  + (row_t01.get("sede") or "")
                  + (row_t01.get("zona") or "")
                  + appo_annoavv
                  + appo_progravv)

        cdip = str(row_t01.get("codDipendente") or "").strip()

        record_adc01del = {
            "gestione": row_t01.get("gestione"),
            "codiceAtto": row_t01.get("codiceAtto"),
            "timestampIns" : row_t01.get("timestampInsStato"),
            "timestampDel" : datetime.now(),
            "idAvvGest": idGest,
            "codDipendente": cdip
        }
        query = self.engine.dataset("ADC01DEL").compile_insert(record_adc01del)


        try:
            self.engine.execute_mutation(query, depth=2)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-ADC01DEL",
                f"Inserita riga CGES={row_t01.get('gestione')} | CATT={row_t01.get('codiceAtto')}",
                depth=2
            )
        except Exception as e:
            BatchLogger.error(
                "INSERT-ADC03DEL-ERRORE",
                f"Fallito inserimento CGES={row_t01.get('gestione')} | CATT={row_t01.get('codiceAtto')}: {e}",
                depth=2, is_last=True
            )
            raise

    def _delete_t10_t14(self, ctx: PreparazionePostalizzazioneContext, row_t01, cges, catt, depth: int) -> None:
        # Ref. COBOL DELETE-T10
        # Accede agli archivi 10 e 14 per cancellazione dei crediti relativi alla partita legata alle spese di notifica

        prog_articolo = self._cerca_art_10(ctx,row_t01, depth + 1)

        delete_t10 = (
            self.engine.dataset("ADCFRT10")
                .filter_by("gestione", "=", cges)
                .filter_by("codiceAtto", "=", catt)
                .filter_by("progArticolo", "=", prog_articolo)
                .compile_delete()
            )

        righe_impattate = self.engine.execute_mutation(delete_t10, depth=depth + 1)
        BatchLogger.info("DELETE-T10", f"DELETE ADCFRT10 -> CGES= {cges} | CATT = {catt} | NPRGART = {prog_articolo} (Righe eliminate: {righe_impattate})", depth=depth)

        delete_t14 = (
            self.engine.dataset("ADCFRT14")
                .filter_by("gestione", "=", cges)
                .filter_by("codiceAtto", "=", catt)
                .compile_delete()
            )

        righe_impattate_t14 = self.engine.execute_mutation(delete_t14, depth=depth + 1)
        BatchLogger.info("DELETE-T14", f"DELETE ADCFRT14 -> CGES= {cges} | CATT = {catt} (Righe eliminate: {righe_impattate_t14})", depth=depth)

    def _cerca_art_10(self, ctx: PreparazionePostalizzazioneContext, row_t01, depth: int) -> Optional[int]:
        """Rif. COBOL: CERCA-ART-T10.
        Ricerca dell'articolo collegato alla partita spesa notifica
        """
        BatchLogger.info("CERCA-ART-T10", "Ricerca dell'articolo collegato alla partita spesa notifica", depth=1)
        t10_map = self.engine.get_table_map("ADCFRT10")

        query = (
            self.engine.dataset("ADCFRT10")
            .select("progArticolo", "timestampIns")
            .filter_by("gestione", "=", row_t01.get("gestione"))
            .filter_by("codiceAtto", "=", row_t01.get("codiceAtto"))
            .filter_by("codTributoCnc", "=", "8340")
            .compile_select()
        )
        rows_t10 = self.engine.fetch(query, depth=1)

        if not rows_t10:
            BatchLogger.error(
                "ARTICOLI-ESTRATTI-ADCFRT10",
                f"Nessun articolo estratto su ADCFRT10 (gestione={row_t01.get('gestione')}, codiceAtto={row_t01.get('codiceAtto')})",
                depth=depth
            )
            ctx.indic_errore = "X"
            return None

        row_t10 = t10_map.normalize(rows_t10[0])
        self._insert_adc10del(ctx, row_t01, row_t10, depth)
        return row_t10.get("progArticolo")

    def _insert_adc10del(self, ctx: PreparazionePostalizzazioneContext, row_t01, row_t10, depth: int) -> None:
        """Rif. COBOL: INSERT-ADC10DEL.
        Inserimento tabella ADC10DEL (salvataggio della partita prima della cancellazione) """

        record_adc10del = {
            "gestione": row_t01.get("gestione"),
            "codiceAtto": row_t01.get("codiceAtto"),
            "progArticolo" : row_t10.get("progArticolo"),
            "timestampIns" : row_t10.get("timestampIns"),
            "timestampDel": datetime.now()
        }
        query = self.engine.dataset("ADC10DEL").compile_insert(record_adc10del)


        try:
            self.engine.execute_mutation(query, depth=depth)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-ADC10DEL",
                f"Inserita riga CGES={record_adc10del['gestione']} | CATT={record_adc10del['codiceAtto']}",
                depth=depth
            )
        except Exception as e:
            BatchLogger.error(
                "INSERT-ADC10DEL-ERRORE",
                f"Fallito inserimento CGES={record_adc10del['gestione']} | CATT={record_adc10del['codiceAtto']}: {e}",
                depth=depth, is_last=True
            )
            raise

    def imp_errore_cesa(self, ctx: PreparazionePostalizzazioneContext, depth: int = 4) -> None:
       """Imposta errore riferito al range rave non presente per il CESA"""
       BatchLogger.info("CURSORE-CURT01-CESA", "Estrazione delle partite su ADCFRT01 per sede", depth=1)
       t01_map = self.engine.get_table_map("ADCFRT01")

       # Equivalente di OPEN-CURT01-CESA + FETCH-CURT01-CESA: CURSORE DI ESTRAZIONE DELLE PARTITE SU ADCFRT01 PER CESA
       query_cesa = (
           self.engine.dataset("ADCFRT01")
           .select("gestione", "codiceAtto", "codiceFiscale", "sede", "zona",
                   "codCentro", "partitaIva", "dataInf", "dataNot", "codDipendente", "dataRifCon",
                   "codAzienda", "descrizioneAtto", "annoEmissione", "numEmissione", "numInail", "codSegnalazione",
                   "flgDecadenza", "meseInizioPeriodo", "meseFinePeriodo", "dataFallimento", "numSogg", "numRate",
                   "statoAttivita", "codEsattoria", "flgValFiscale", "annoRifRuolo", "numRuolo", "flgEuro",
                   "codEsattoriaDel",
                   "annoCarico", "numCarico", "numChkCarico", "dataTransizioneStato", "flgIscrizione", "flgCessione",
                   "codCausale",
                   "codFasAmm", "statoAzienda", "dataStatoAzienda", "descrizioneAttoBi", "timestampInsStato",
                   "timestampVarStato",
                   "tipoAvviso", "annoAvviso", "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi",
                   "sedeOrigine",
                   "flgSanzioni", "flgCessioneRuolo", "flgRateizzazione", "codEsattoriaAvviso", "codiceErrore",
                   "flgSanzioniAdr")
           .filter_by("codEsattoria", "=", ctx.cesa)
           .filter_by("statoAttivita", "=", "0G")
           .with_uncommitted_read()
           .compile_select()
       )
       rows_t01_cesa = self.engine.fetch(query_cesa, depth)
       tot_t01 = len(rows_t01_cesa)

       if tot_t01 == 0:
           BatchLogger.error("PARTITE-ESTRATTE-ADCFRT01", f"Nessuna partita estratta su ADCFRT01", depth=depth)
           ctx.indic_errore = "X"

       # Rif. COBOL: PERFORM UNTIL FINE-CURT01-SEDE
       for idx, raw_row in enumerate(rows_t01_cesa, start=1):
           row_t01_cesa = t01_map.normalize(raw_row)
           ctx.ws_ctr_t01 += 1 # ADD 1 TO WS-CTR-T01 (in FETCH-CURT01-CESA)

           BatchLogger.info(
               "PARTITE-ESTRATTE-ADCFRT01",
               f"[{idx}/{tot_t01}]",
               depth=depth + 1,
               is_last=(idx == tot_t01)
           )

           # Rif. COBOL: MOVE WS-ERRAV TO CODERR OF CDCFRT01
           #             MOVE CGES/CATT OF CDCFRT01 TO CGES/CATT OF CDCFRT10
           coderr = ctx.ws_erravv
           cges = str(row_t01_cesa.get("gestione") or "").strip()
           catt = str(row_t01_cesa.get("codiceAtto") or "").strip()

           self._aggiorna_stato_t01(ctx, row_t01_cesa, coderr, depth=depth + 2)
           self._aggiorna_stato_t10(ctx, row_t01_cesa, cges, catt, depth=depth + 2)

           if ctx.ws_ctr_t01 == 500:
                self.engine.commit(depth=depth)
                ctx.ws_ctr_t01 = 0
                ctx.ws_ctr_t03 = 0

                BatchLogger.info(
                    "COMMIT-IMP-ERRORE-CESA",
                    f"CGES = {cges} | CATT = {catt} | WS_ERRAVV = {coderr}",
                    depth=depth + 1)

       if 0 < ctx.ws_ctr_t01 < 500:
           self.engine.commit(depth=depth)
           ctx.ws_ctr_t01 = 0
           ctx.ws_ctr_t03 = 0
           BatchLogger.info(
               "COMMIT-IMP-ERRORE-CESA",
               f"COMMIT eseguito con successo",
               depth=depth + 1)

    def imp_errore_importo(self, ctx: PreparazionePostalizzazioneContext, depth: int = 4) -> None:
       """Imposta errore riferito all'importo del tributo
       quando è maggiore di 200000 euro o minore di 50 euro su ADCFRT01 e ADCFRT10"""

       BatchLogger.info("CURSORE-CURT01", "Estrazione delle partite su ADCFRT01", depth=1)
       t01_map = self.engine.get_table_map("ADCFRT01")

       # Equivalente di OPEN-CURT01 + FETCH-CURT01: CURSORE DI ESTRAZIONE DELLE PARTITE SU ADCFRT01 PER SEDE
       query = (
           self.engine.dataset("ADCFRT01")
           .select("gestione", "codiceAtto", "codiceFiscale", "sede", "zona",
                   "codCentro", "partitaIva", "dataInf", "dataNot", "codDipendente", "dataRifCon",
                   "codAzienda", "descrizioneAtto", "annoEmissione", "numEmissione", "numInail", "codSegnalazione",
                   "flgDecadenza", "meseInizioPeriodo", "meseFinePeriodo", "dataFallimento", "numSogg", "numRate",
                   "statoAttivita", "codEsattoria", "flgValFiscale", "annoRifRuolo", "numRuolo", "flgEuro",
                   "codEsattoriaDel",
                   "annoCarico", "numCarico", "numChkCarico", "dataTransizioneStato", "flgIscrizione", "flgCessione",
                   "codCausale",
                   "codFasAmm", "statoAzienda", "dataStatoAzienda", "descrizioneAttoBi", "timestampInsStato",
                   "timestampVarStato",
                   "tipoAvviso", "annoAvviso", "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi",
                   "sedeOrigine",
                   "flgSanzioni", "flgCessioneRuolo", "flgRateizzazione", "codEsattoriaAvviso", "codiceErrore",
                   "flgSanzioniAdr")
           .filter_by("codEsattoria", "=", ctx.cesa)
           .filter_by("annoCarico", "=", ctx.annoCartella)
           .filter_by("numCarico", "=", ctx.numeroCartella)
           .filter_by("numChkCarico", "=", ctx.chkCartella)
           .order_by("numEspAvviso")
           .with_uncommitted_read()
           .limit(1)  # da verificare che sia solo un record
           .compile_select()
       )
       rows_t01 = self.engine.fetch(query, depth=1)
       tot_t01 = len(rows_t01)

       if tot_t01 == 0:
           BatchLogger.error("PARTITE-ESTRATTE-ADCFRT01", f"Nessuna partita estratta su ADCFRT01", depth=depth)
           ctx.indic_errore = "X"

       # Rif. COBOL: PERFORM UNTIL FINE-CURT01
       for idx, raw_row in enumerate(rows_t01, start=1):
           row_t01 = t01_map.normalize(raw_row)

           BatchLogger.info(
               "PARTITE-ESTRATTE-ADCFRT01",
               f"[{idx}/{tot_t01}]",
               depth=depth + 1,
               is_last=(idx == tot_t01)
           )

           # Rif. COBOL: MOVE WS-ERRAV TO CODERR OF CDCFRT01
           #             MOVE CGES/CATT OF CDCFRT01 TO CGES/CATT OF CDCFRT10
           coderr = ctx.ws_erravv
           cges = str(row_t01.get("gestione") or "").strip()
           catt = str(row_t01.get("codiceAtto") or "").strip()

           if ctx.catt != ctx.idAvviso and ctx.ws_cges != "N":
                   self._aggiorna_stato_t01(ctx, row_t01, coderr, depth=depth + 2)
                   self._aggiorna_stato_t10(ctx, row_t01, cges, catt, depth=depth + 2)
           else:
                   # Se errore su avviso, si provvede a cancellazione fisica della partita creata per le spese di notifica
                   self._delete_t01(ctx, row_t01, cges, catt, depth=depth + 2)
                   self._delete_t10_t14(ctx, row_t01, cges, catt, depth=depth + 2)


