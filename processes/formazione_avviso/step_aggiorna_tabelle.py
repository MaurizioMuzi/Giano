# processes/formazione_avviso/step_aggiorna_tabelle.py
from datetime import datetime, date
from decimal import Decimal
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class AggiornaTabelleStep:
    """
    Reingegnerizzazione del paragrafo AGGIORNA-TABELLE THRU AGGIORNA-TABELLE-EX.
    Coordina la sequenza transazionale di consolidamento dell'avviso:
      1) CNTRL-TAB14
      2) CALCOLA-IDENT
      3) Cicla sul cursore CURT01
      4) AGGIORNA-TAB01
      5) AGGIORNA-TAB10
      6) INSERISCI-SPESE
      7) INSERISCI-TAB03
    """

    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> None:
        BatchLogger.info(
            "AGGIORNA-TABELLE",
            f"Avvio consolidamento avviso {ctx.ws_annoavv}/{ctx.ws_progavv} (CGES={ctx.ws_cges})",
            depth=depth
        )

        try:
            # 1) CNTRL-TAB14: Controllo di coerenza o recupero anagrafico finale
            self._cntrl_tab14(ctx, depth=depth + 1)

            # 2) CALCOLA-IDENT: Determinazione dell'identificativo avviso (es. codice a barre / IUV / progressivo)
            identificativo = self._calcola_ident(ctx, depth=depth + 1)

            # 3, 4, 5) Ciclo CURT01 con aggiornamento a cascata di ADCFRT01 e ADCFRT10
            self._elabora_cursore_curt01(ctx, identificativo, depth=depth + 1)

            # 6) INSERISCI-SPESE: Calcolo e registrazione diritti/spese di notifica
            self._inserisci_spese(ctx, identificativo, depth=depth + 1)

            # 7) INSERISCI-TAB03: Scrittura della testata dell'avviso formato su ADCFRT03
            self._inserisci_tab03(ctx, identificativo, depth=depth + 1)

            BatchLogger.info(
                "AGGIORNA-TABELLE",
                f"Consolidamento completato con successo per avviso {ctx.ws_annoavv}/{ctx.ws_progavv}",
                depth=depth
            )

        except Exception as err:
            BatchLogger.error(
                "AGGIORNA-TABELLE",
                f"Errore durante il consolidamento dell'avviso {ctx.ws_annoavv}/{ctx.ws_progavv}: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            ctx.ws_erravv = "ERR-UPD"
            raise err

    # -------------------------------------------------------------------------
    # STEP 1: CNTRL-TAB14
    # -------------------------------------------------------------------------
    def _cntrl_tab14(self, ctx: FormazioneAvvisoContext, depth: int) -> None:
        BatchLogger.info("STEP-1/7", f"Esecuzione CNTRL-TAB14 a doppio cursore per CF: {ctx.ws_cfis}", depth=depth)
        t01_map = self.engine.get_table_map("ADCFRT01")
        t14_map = self.engine.get_table_map("ADCFRT14")

        # CURSORE 1: Recupero record Master cronologicamente più recente
        query_cur_master = (
            self.engine.dataset("ADCFRT01")
            .join(t14_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
            .select_joined(
                "cognome", "nome", "indAnagrafeTrib",
                "siglaProvAnagrafeTrib", "comuneAnagrafeTrib", "capAnagrafeTrib", "locAnagrafeTrib"
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

        rows_master = self.engine.fetch(query_cur_master, depth=depth + 1)
        if not rows_master:
            BatchLogger.warn("CNTRL-TAB14", "Nessun record master individuato su CDCFRT14", depth=depth + 1)
            return

        raw_master = rows_master[0]
        master_t14 = t14_map.normalize(raw_master)
        master_t01 = t01_map.normalize(raw_master)
        master_row = {**master_t14, **master_t01}

        ws_cognome = str(master_row.get("cognome") or "").strip()
        ws_nome = str(master_row.get("nome") or "").strip()
        ws_indirizzo = str(master_row.get("indAnagrafeTrib") or "").strip()
        ws_provincia = str(master_row.get("siglaProvAnagrafeTrib") or "").strip()
        ws_codcomune = str(master_row.get("comuneAnagrafeTrib") or "").strip()
        ws_cap = str(master_row.get("capAnagrafeTrib") or "").strip()
        ws_localita = str(master_row.get("locAnagrafeTrib") or "").strip()

        ctx.ws_codcomune = ws_codcomune

        BatchLogger.info(
            "MASTER-T14",
            f"Master individuato: CATT={master_row.get('codiceAtto')} | "
            f"Nominativo: {ws_cognome} {ws_nome} | Indirizzo: {ws_indirizzo} | Belfiore: {ws_codcomune}",
            depth=depth + 1
        )

        # CURSORE 2: Scansione di dettaglio di tutti i record per allineamento
        query_cur_dett = (
            self.engine.dataset("ADCFRT01")
            .join(t14_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
            .select("gestione", "codiceAtto")
            .select_joined(
                "cognome", "nome", "indAnagrafeTrib",
                "siglaProvAnagrafeTrib", "comuneAnagrafeTrib", "capAnagrafeTrib", "locAnagrafeTrib"
            )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .filter_by("statoAttivita", "=", "0I")
            .filter_by_joined("codiceAnag", "=", "I")
            .order_by("timestampInsStato")
            .with_uncommitted_read()
            .compile_select()
        )

        records_aggiornati = 0

        for chunk in self.engine.cursor_stream(query_cur_dett, buffer_size=500, depth=depth + 1):
            for raw_row in chunk:
                if getattr(ctx, "scarto_t14", False):
                    BatchLogger.warn("UNTIL-T14", "Interruzione ciclo: condizione SCARTO-T14 attiva", depth=depth + 2)
                    return

                row_t14 = t14_map.normalize(raw_row)
                row_t01 = t01_map.normalize(raw_row)

                scog = str(row_t14.get("cognome") or "").strip()
                snom = str(row_t14.get("nome") or "").strip()
                sindatr = str(row_t14.get("indAnagrafeTrib") or "").strip()
                cproatr = str(row_t14.get("siglaProvAnagrafeTrib") or "").strip()
                ccomatr = str(row_t14.get("comuneAnagrafeTrib") or "").strip()
                ccapatr = str(row_t14.get("capAnagrafeTrib") or "").strip()
                slocatr = str(row_t14.get("locAnagrafeTrib") or "").strip()

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
                    continue

                self._aggiorna_t14(
                    cges=row_t01.get("gestione"),
                    catt=row_t01.get("codiceAtto"),
                    scog=ws_cognome,
                    snom=ws_nome,
                    sindatr=ws_indirizzo,
                    cproatr=ws_provincia,
                    ccomatr=ws_codcomune,
                    ccapatr=ws_cap,
                    slocatr=ws_localita,
                    depth=depth + 2
                )
                records_aggiornati += 1

        BatchLogger.info(
            "ESITO-T14",
            f"CNTRL-TAB14 completato. Record CDCFRT14 riallineati: {records_aggiornati}",
            depth=depth + 1
        )

    def _aggiorna_t14(self, cges: str, catt: str, scog: str, snom: str, sindatr: str,
                      cproatr: str, ccomatr: str, ccapatr: str, slocatr: str, depth: int) -> None:
        """Paragrafo AGGIORNA-T14 THRU AGGIORNA-T14-EX su CDCFRT14."""
        upd = (
            self.engine.dataset("ADCFRT14")
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .filter_by("codiceAnag", "=", "I")
            .compile_update({
                "cognome": scog,
                "nome": snom,
                "indAnagrafeTrib": sindatr,
                "siglaProvAnagrafeTrib": cproatr,
                "comuneAnagrafeTrib": ccomatr,
                "capAnagrafeTrib": ccapatr,
                "locAnagrafeTrib": slocatr
            })
        )
        righe = self.engine.execute_mutation(upd, depth=depth)
        BatchLogger.debug("AGGIORNA-T14", f"UPDATE CDCFRT14 CATT={catt} -> Righe impattate: {righe}", depth=depth)

    # -------------------------------------------------------------------------
    # STEP 2: CALCOLA-IDENT
    # -------------------------------------------------------------------------
    def _calcola_ident(self, ctx: FormazioneAvvisoContext, depth: int) -> str:
        BatchLogger.info("STEP-2/7", "Calcolo identificativo univoco avviso (CALCOLA-IDENT)", depth=depth)

        cod_comune = getattr(ctx, "ws_codcomune", "")
        t02_map = self.engine.get_table_map("ADCAVV02")

        query_cesa = (
            self.engine.dataset("ADCAVV02")
            .select("codConcessione")
            .filter_by("codBelfiore", "=", cod_comune)
            .filter_by("flgValidita", "=", "0")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query_cesa, depth=depth)

        if rows:
            row_t02 = t02_map.normalize(rows[0])
            ws_cesanew = str(row_t02.get("codConcessione") or "").strip()
        else:
            ws_cesanew = ""

        cesa_base = int(ws_cesanew) if str(ws_cesanew).strip().isdigit() else 0
        cesa_avviso = cesa_base + 300

        ctx.ws_cesa = str(cesa_base)
        ctx.ws_cesaavv = str(cesa_avviso)

        upd_t01 = (
            self.engine.dataset("ADCFRT01")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .compile_update({
                "codEsattoria": str(ctx.ws_cesa),
                "codEsattoriaAvviso": str(ctx.ws_cesaavv)
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_t01, depth=depth)
        BatchLogger.info(
            "UPD-T01",
            f"Aggiornamento CESA/CESAAVV su ADCFRT01 per avviso {ctx.ws_annoavv}/{ctx.ws_progavv} -> Righe impattate: {righe_impattate}",
            depth=depth
        )

        ws_annoruo_dec = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
        t_avv01_map = self.engine.get_table_map("ADCAVV01")

        query_v01 = (
            self.engine.dataset("ADCAVV01")
            .select("progAvviso")
            .filter_by("codConcessione", "=", str(ctx.ws_cesaavv))
            .filter_by("annoAvviso", "=", str(ws_annoruo_dec))
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        try:
            rows = self.engine.fetch(query_v01, depth=depth)

            if not rows:
                BatchLogger.info(
                    "CALCOLA-IDENT",
                    f"Record ADCAVV01 assente per CESAAVV={ctx.ws_cesaavv}, ANNO={ws_annoruo_dec}. Inserimento nuovo progressivo.",
                    depth=depth
                )
                self._inserisci_avv01(ctx, ws_annoruo_dec, depth=depth + 1)
                ctx.ws_nprgruo_dec = 0
            else:
                row_avv01 = t_avv01_map.normalize(rows[0])
                ctx.ws_nprgruo_dec = int(row_avv01.get("progAvviso") or 0)
                BatchLogger.debug(
                    "CALCOLA-IDENT",
                    f"Progressivo recuperato da ADCAVV01: {ctx.ws_nprgruo_dec}",
                    depth=depth
                )

            ctx.ws_nprgruo_dec += 1
            ctx.ws_nprgruo = str(ctx.ws_nprgruo_dec).zfill(8)

            ctx.ws_cesaruo = str(ctx.ws_cesaavv).zfill(3)
            ctx.ws_annoruo = str(ws_annoruo_dec).zfill(4)

            pri15ruo_str = f"{ctx.ws_cesaruo}{ctx.ws_annoruo}{ctx.ws_nprgruo}"
            pri15ruo_val = int(pri15ruo_str) if pri15ruo_str.isdigit() else 0

            ws_risultato, ws_resto = divmod(pri15ruo_val, 93)

            ctx.ws_nchkruo = str(ws_resto).zfill(2)
            ctx.ws_soggruo = "000"

            self._aggiorna_avv01(ctx, ws_annoruo_dec, depth=depth + 1)

            identificativo_completo = f"{pri15ruo_str}{ctx.ws_nchkruo}{ctx.ws_soggruo}"
            ctx.ws_idavvruo = identificativo_completo[:20]

            BatchLogger.info(
                "CALCOLA-IDENT",
                f"Identificativo generato: {ctx.ws_idavvruo} (Resto Modulo 93: {ctx.ws_nchkruo})",
                depth=depth
            )
            return ctx.ws_idavvruo

        except Exception as err:
            BatchLogger.error(
                "SEGNALA-LOG-001",
                f"Errore SQL durante elaborazione ADCAVV01 (CESAAVV={ctx.ws_cesaavv}, ANNO={ws_annoruo_dec}): {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            ctx.ws_erravv = "EXX001"
            raise err

    def _inserisci_avv01(self, ctx: FormazioneAvvisoContext, anno_avviso: str, depth: int) -> None:
        ins_avv01 = self.engine.dataset("ADCAVV01").compile_insert({
            "codConcessione": str(ctx.ws_cesaavv),
            "annoAvviso": str(anno_avviso),
            "progAvviso": 0,
            "timestampUpd": datetime.now()
        })
        righe = self.engine.execute_mutation(ins_avv01, depth=depth)
        BatchLogger.info(
            "INSERISCI-AVV01",
            f"Nuovo progressivo censito su ADCAVV01 (CESAAVV={ctx.ws_cesaavv}, ANNO={anno_avviso}, PROG=0, righe: {righe})",
            depth=depth
        )

    def _aggiorna_avv01(self, ctx: FormazioneAvvisoContext, anno_avviso: str, depth: int) -> None:
        agg_avv01 = (
            self.engine.dataset("ADCAVV01")
            .filter_by("codConcessione", "=", str(ctx.ws_cesaavv))
            .filter_by("annoAvviso", "=", str(anno_avviso))
            .compile_update({
                "progAvviso": ctx.ws_nprgruo_dec,
                "timestampUpd": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(agg_avv01, depth=depth)
        BatchLogger.info(
            "UPD-AVV01",
            f"UPDATE ADCAVV01 eseguito per CESAAVV={ctx.ws_cesaavv} ANNO={anno_avviso} -> Nuovo PROG={ctx.ws_nprgruo_dec} (Righe: {righe_modificate})",
            depth=depth
        )

    # -------------------------------------------------------------------------
    # STEP 3, 4, 5: Cursore CURT01, AGGIORNA-TAB01, AGGIORNA-TAB10
    # -------------------------------------------------------------------------
    def _elabora_cursore_curt01(self, ctx: FormazioneAvvisoContext, identificativo: str, depth: int) -> None:
        BatchLogger.info("STEP-3/7", "Apertura cursore CURT01 per aggiornamento partite/articoli", depth=depth)
        t01_map = self.engine.get_table_map("ADCFRT01")

        query_curt01 = (
            self.engine.dataset("ADCFRT01")
            .select("gestione", "codiceAtto", "statoAttivita", "codEsattoria")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("sede", "=", ctx.ws_sede)
            .filter_by("zona", "=", ctx.ws_zona)
            .filter_by("annoAvviso", "=", ctx.ws_annoavv)
            .filter_by("progAvviso", "=", ctx.ws_progavv)
            .filter_by("statoAttivita", "=", "0I")
            .order_by("gestione", "annoAvviso", "progAvviso", "numEspAvviso")
            .with_uncommitted_read()
            .compile_select()
        )

        stream = self.engine.cursor_stream(query_curt01, buffer_size=500, depth=depth)
        record_iterator = (row for chunk in stream for row in chunk)

        try:
            first_raw_row = next(record_iterator)
        except StopIteration:
            ctx.indic_scarto_t01 = "X"
            ctx.indic_errore = "X"
            BatchLogger.error("CURT01", "*** NON TROVATA T01 PER AGG. TABELLE ***", depth=depth)
            return

        self._elabora_singola_partita_curt01(ctx, t01_map.normalize(first_raw_row), identificativo, depth=depth + 1)

        for raw_row in record_iterator:
            if getattr(ctx, "indic_scarto_t01", " ") == "X" or ctx.indic_errore == "X":
                BatchLogger.warn("CURT01", "Interruzione ciclo: condizione SCARTO-T01 rilevata", depth=depth + 1)
                break
            self._elabora_singola_partita_curt01(ctx, t01_map.normalize(raw_row), identificativo, depth=depth + 1)

    def _elabora_singola_partita_curt01(self, ctx: FormazioneAvvisoContext, row_t01: dict, identificativo: str,
                                        depth: int) -> None:
        cges = row_t01.get("gestione")
        catt = row_t01.get("codiceAtto")
        cesa = row_t01.get("codEsattoria")

        ctx.n_cges = cges
        ctx.n_catt = catt

        BatchLogger.debug(
            "CURT01",
            f"Elaborazione partita: CESA={cesa} | CGES={cges} | CATT={catt}",
            depth=depth
        )

        # 4) STEP-4/7: AGGIORNA-TAB01 (Aggiornamento stato partita testata a '0G')
        BatchLogger.info("STEP-4/7", f"Aggiornamento testata partita su ADCFRT01 (AGGIORNA-TAB01) per CATT={catt}",
                         depth=depth)
        self._aggiorna_tab01(ctx, cges, catt, identificativo, depth=depth + 1)

        # 5) STEP-5/7: AGGIORNA-TAB10 (Aggiornamento articoli correlati a '0G' e numerazione carico)
        if ctx.indic_errore != "X":
            BatchLogger.info("STEP-5/7",
                             f"Aggiornamento articoli su ADCFRT10 (AGGIORNA-TAB10) per CGES={cges} CATT={catt}",
                             depth=depth)
            self._aggiorna_tab10(ctx, cges, catt, depth=depth + 1)

    def _aggiorna_tab01(self, ctx: FormazioneAvvisoContext, cges: str, catt: str, identificativo: str, depth: int) -> None:
        upd_t01 = (
            self.engine.dataset("ADCFRT01")
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .compile_update({
                "annoCarico": getattr(ctx, "ws_annoruo", ""),
                "numCarico": getattr(ctx, "ws_nprgruo", ""),
                "numChkCarico": getattr(ctx, "ws_nchkruo", ""),
                "statoAttivita": "0G",
                "timestampVarStato": datetime.now()
            })
        )
        righe = self.engine.execute_mutation(upd_t01, depth=depth)
        BatchLogger.debug("AGGIORNA-TAB01", f"CATT={catt} -> Partita aggiornata a '0G' (righe: {righe})", depth=depth)

    def _aggiorna_tab10(self, ctx: FormazioneAvvisoContext, cges: str, catt: str, depth: int) -> None:
        BatchLogger.info("AGGIORNA-TAB10", f"Apertura cursore articoli per CGES={cges} CATT={catt}", depth=depth)
        t10_map = self.engine.get_table_map("ADCFRT10")

        query_curt10 = (
            self.engine.dataset("ADCFRT10")
            .select("gestione", "codiceAtto", "progArticolo", "impTributo", "impTributoCalc")
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .filter_by("statoArticolo", "=", "0I")
            .order_by("gestione", "codiceAtto", "progArticolo")
            .with_uncommitted_read()
            .compile_select()
        )

        righe_aggiornate = 0
        ctx.ws_itrbavv = Decimal("0")

        for chunk in self.engine.cursor_stream(query_curt10, buffer_size=500, depth=depth):
            for raw_row in chunk:
                row_t10 = t10_map.normalize(raw_row)
                nprgart = row_t10.get("progArticolo")

                ctx.n_nprgart = nprgart
                ctx.ws_nespart = getattr(ctx, "ws_nespart", 0) + 1

                itrb_val = Decimal(str(row_t10.get("impTributo") or 0))
                ctx.ws_itrbavv += itrb_val

                itrb_carico = row_t10.get("impTributoCalc") or itrb_val

                upd_t10 = (
                    self.engine.dataset("ADCFRT10")
                    .filter_by("gestione", "=", cges)
                    .filter_by("codiceAtto", "=", catt)
                    .filter_by("progArticolo", "=", nprgart)
                    .compile_update({
                        "statoArticolo": "0G",
                        "timestampUpd": datetime.now(),
                        "progCarico": ctx.ws_nespart,
                        "impTributoCarico": itrb_carico,
                        "flgEuroCarico": "1",
                    })
                )

                self.engine.execute_mutation(upd_t10, depth=depth)
                righe_aggiornate += 1

        BatchLogger.debug(
            "AGGIORNA-TAB10",
            f"CATT={catt} -> Articoli aggiornati: {righe_aggiornate} (Ultimo progressivo: {ctx.ws_nespart})",
            depth=depth
        )

    # -------------------------------------------------------------------------
    # STEP 6: INSERISCI-SPESE (Orchestratore T01, T10, T14)
    # -------------------------------------------------------------------------
    def _inserisci_spese(self, ctx: FormazioneAvvisoContext, identificativo: str, depth: int) -> None:
        cges = getattr(ctx, "n_cges", ctx.ws_cges)
        catt = getattr(ctx, "n_catt", "")
        id_avviso = getattr(ctx, "ws_idavvruo", identificativo)

        BatchLogger.info(
            "STEP-6/7",
            f"Creazione e inserimento diritti/spese di notifica (INSERISCI-SPESE) per CATT={catt} -> Nuovo ID={id_avviso}",
            depth=depth
        )

        if not catt:
            BatchLogger.warn("INSERISCI-SPESE", "Nessun codice atto (N-CATT) valido per inserimento spese", depth=depth)
            return

        try:
            # 1. Inserimento testata partita su ADCFRT01
            record_t01 = self._inserisci_spese_t01(ctx, cges, catt, id_avviso, depth=depth + 1)
            if not record_t01:
                return

            # 2. Inserimento articolo spese su ADCFRT10
            self._inserisci_spese_t10(ctx, cges, catt, id_avviso, depth=depth + 1)

            # 3. Inserimento anagrafica recapito su ADCFRT14
            self._inserisci_spese_t14(ctx, cges, catt, id_avviso, depth=depth + 1)

            BatchLogger.info(
                "INSERISCI-SPESE",
                f"Terna spese completata con successo (ADCFRT01, ADCFRT10, ADCFRT14) per CATT={id_avviso}",
                depth=depth
            )

        except Exception as err:
            BatchLogger.error(
                "INSERISCI-SPESE",
                f"Errore durante l'inserimento spese per CATT={id_avviso}: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise err

    def _inserisci_spese_t01(self, ctx: FormazioneAvvisoContext, cges: str, catt: str, id_avviso: str, depth: int) -> dict:
        t01_map = self.engine.get_table_map("ADCFRT01")

        query_t01_sel = (
            self.engine.dataset("ADCFRT01")
            .select(
                "gestione", "codiceAtto", "codiceFiscale", "sede", "zona", "codCentro", "partitaIva",
                "dataInf", "dataNot", "codDipendente", "dataRifCon", "codAzienda", "descrizioneAtto",
                "annoEmissione", "numEmissione", "numInail", "codSegnalazione", "flgDecadenza",
                "meseInizioPeriodo", "meseFinePeriodo", "dataFallimento", "numSogg", "numRate",
                "statoAttivita", "codEsattoria", "flgValFiscale", "annoRifRuolo", "numRuolo", "flgEuro",
                "codEsattoriaDel", "annoCarico", "numCarico", "numChkCarico", "dataTransizioneStato",
                "flgIscrizione", "flgCessione", "codCausale", "codFasAmm", "statoAzienda", "dataStatoAzienda",
                "descrizioneAttoBi", "timestampInsStato", "timestampVarStato", "tipoAvviso", "annoAvviso",
                "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi", "sedeOrigine",
                "flgSanzioni", "flgCessioneRuolo", "flgRateizzazione", "codEsattoriaAvviso", "codiceErrore",
                "flgSanzioniAdr"
            )
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query_t01_sel, depth=depth)
        if not rows:
            BatchLogger.warn("INSERISCI-SPESE-T01", f"Record master ADCFRT01 non trovato per CGES={cges} CATT={catt}", depth=depth)
            return {}

        record_t01 = t01_map.normalize(rows[0])

        d_zero = "0001-01-01"
        d_not = record_t01.get("dataNot")
        d_fal = record_t01.get("dataFallimento")

        record_t01.update({
            "gestione": "N",
            "codiceAtto": str(id_avviso)[:20],
            "codDipendente": "PDCFOAVV",
            "descrizioneAtto": "",
            "descrizioneAttoBi": "",
            "annoEmissione": 0,
            "numEmissione": 0,
            "numInail": "",
            "codSegnalazione": "",
            "meseInizioPeriodo": 0,
            "meseFinePeriodo": 0,
            "numRate": 0,
            "flgCessione": "O",
            "codCausale": "",
            "codFasAmm": "F",
            "statoAzienda": "",
            "dataStatoAzienda": d_zero,
            "dataNot": d_not if d_not and d_not != "0001-01-01" else d_zero,
            "dataFallimento": d_fal if d_fal and d_fal != "0001-01-01" else d_zero,
            "flgSanzioni": "N",
            "flgCessioneRuolo": "",
            "flgRateizzazione": "1",
            "flgSanzioniAdr": "",
            "codiceErrore": "",
            "statoAttivita": "0G",
            "codAzienda": "",
            "periodo": "",
            "periodoBi": "",
            "timestampVarStato": "0001-01-01-00.00.00.000000",
        })

        cesa_raw = getattr(ctx, "ws_cesa", record_t01.get("codEsattoria", 0))
        record_t01["codEsattoria"] = int(str(cesa_raw).strip() or 0)

        cesaavv_raw = getattr(ctx, "ws_cesaruo", ctx.ws_cesaavv)
        record_t01["codEsattoriaAvviso"] = int(str(cesaavv_raw).strip() or 0)

        acar_raw = getattr(ctx, "ws_annoruo", 0)
        record_t01["annoCarico"] = int(str(acar_raw).strip() or 0)

        ncar_raw = getattr(ctx, "ws_nprgruo", 0)
        record_t01["numCarico"] = int(str(ncar_raw).strip() or 0)

        nchk_raw = getattr(ctx, "ws_nchkruo", 0)
        record_t01["numChkCarico"] = int(str(nchk_raw).strip() or 0)

        record_t01["numSogg"] = "00"

        num_partita = int(record_t01.get("numPartitaAvviso") or 0)
        record_t01["numEspAvviso"] = num_partita + 1

        record_t01.pop("idAvvisoRuolo", None)

        ins_t01 = self.engine.dataset("ADCFRT01").compile_insert(record_t01)
        righe = self.engine.execute_mutation(ins_t01, depth=depth)
        BatchLogger.debug("INSERISCI-SPESE-T01", f"ADCFRT01 inserito con CATT={id_avviso} (Righe: {righe})", depth=depth)
        return record_t01

    def _inserisci_spese_t10(self, ctx: FormazioneAvvisoContext, cges: str, catt: str, id_avviso: str, depth: int) -> None:
        t10_map = self.engine.get_table_map("ADCFRT10")
        n_nprgart = getattr(ctx, "n_nprgart", 1)

        query_t10_sel = (
            self.engine.dataset("ADCFRT10")
            .select(
                "gestione", "codiceAtto", "progArticolo", "numIdDecre", "codTributoCnc", "codCausale",
                "codPeriodo", "codNaturaTrb", "numRata", "numAccreditamento", "codRata", "impTributo",
                "flgResiduo", "codAggio", "impAggioAnt", "impAggioTot", "impArrotondamento", "codSsn",
                "dataFineInf", "impInteressi", "tasso", "meseInizioPeriodo", "meseFinePeriodo",
                "annoConsolidamento", "numTotRate", "descrizioneArticolo", "impTributoCalc", "dataFineCalc",
                "progCarico", "impTributoCarico", "flgEuroCarico", "codPagamento", "flgEuroPag",
                "dataPagamento", "dataRegistrazionePag", "dataDecadenza", "impTributoPagato", "impAggioPagato",
                "impAggioRimborso", "impAgcPagato", "impMoraPagata", "annoFlusso", "numFlusso",
                "codEsattoria", "numQuietanza", "dataQuietanza", "dataRiversamento", "statoArticolo",
                "tipoAggio", "codFasAmm", "statoGiudizio", "gradoGiudizio", "dataStatoGiudizio",
                "tipoRecupero", "impOrigModificato", "codSituazione", "dataRifConsolidamento", "impCapitale",
                "dataPredoc", "descrizioneArticoloBi", "numRateDilazione", "vetusta", "timestampIns",
                "timestampUpd", "impContributoDovuto", "impContributoVersato", "impAggio"
            )
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .filter_by("progArticolo", "=", n_nprgart)
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query_t10_sel, depth=depth)
        if not rows:
            BatchLogger.warn(
                "INSERISCI-SPESE-T10",
                f"Articolo ADCFRT10 non trovato per CGES={cges}, CATT={catt}, NPRGART={n_nprgart}",
                depth=depth
            )
            return

        record_t10 = t10_map.normalize(rows[0])

        ctx.ws_nespart = getattr(ctx, "ws_nespart", 0) + 1
        ws_annoruo_dec = int(str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4])

        record_t10.update({
            "gestione": "N",
            "codiceAtto": str(id_avviso)[:20],
            "progArticolo": 1,
            "numIdDecre": 0,
            "codTributoCnc": "8340",
            "codCausale": "",
            "codPeriodo": "00",
            "codNaturaTrb": "N",
            "numRata": 0,
            "numAccreditamento": "",
            "codRata": "",
            "impTributo": Decimal("690"),
            "flgResiduo": "",
            "codAggio": "",
            "impAggioAnt": Decimal("0"),
            "impAggioTot": Decimal("0"),
            "impArrotondamento": Decimal("0"),
            "codSsn": 0,
            "dataFineInf": "0001-01-01",
            "impInteressi": Decimal("0"),
            "tasso": Decimal("0"),
            "meseInizioPeriodo": ws_annoruo_dec,
            "meseFinePeriodo": 0,
            "annoConsolidamento": 0,
            "numTotRate": 0,
            "descrizioneArticolo": "",
            "impTributoCalc": Decimal("0"),
            "dataFineCalc": "0001-01-01",
            "progCarico": ctx.ws_nespart,
            "impTributoCarico": Decimal("690"),
            "flgEuroCarico": "1",
            "codPagamento": "",
            "flgEuroPag": "1",
            "dataPagamento": "0001-01-01",
            "dataRegistrazionePag": "0001-01-01",
            "dataDecadenza": "0001-01-01",
            "impTributoPagato": Decimal("0"),
            "impAggioPagato": Decimal("0"),
            "impAggioRimborso": Decimal("0"),
            "impAgcPagato": Decimal("0"),
            "impMoraPagata": Decimal("0"),
            "annoFlusso": 0,
            "numFlusso": "",
            "codEsattoria": 0,
            "numQuietanza": 0,
            "dataQuietanza": "0001-01-01",
            "dataRiversamento": "0001-01-01",
            "statoArticolo": "0G",
            "tipoAggio": "",
            "codFasAmm": "F",
            "statoGiudizio": "",
            "gradoGiudizio": "",
            "dataStatoGiudizio": "0001-01-01",
            "tipoRecupero": "",
            "impOrigModificato": Decimal("0"),
            "codSituazione": 0,
            "dataRifConsolidamento": 0,
            "impCapitale": Decimal("0"),
            "dataPredoc": "0001-01-01",
            "descrizioneArticoloBi": "",
            "numRateDilazione": 0,
            "vetusta": ws_annoruo_dec,
            "timestampUpd": "0001-01-01-00.00.00.000000",
            "impContributoDovuto": Decimal("0"),
            "impContributoVersato": Decimal("0"),
            "impAggio": Decimal("0"),
        })

        itrb_val = Decimal(str(record_t10.get("impTributo") or 0))
        ctx.ws_itrbavv = getattr(ctx, "ws_itrbavv", Decimal("0")) + itrb_val

        ins_t10 = self.engine.dataset("ADCFRT10").compile_insert(record_t10)
        righe = self.engine.execute_mutation(ins_t10, depth=depth)
        BatchLogger.debug(
            "INSERISCI-SPESE-T10",
            f"ADCFRT10 spese inserito su CATT={id_avviso} (NPRGCAR={ctx.ws_nespart}, Righe: {righe})",
            depth=depth
        )

    def _inserisci_spese_t14(self, ctx: FormazioneAvvisoContext, cges: str, catt: str, id_avviso: str, depth: int) -> None:
        t14_map = self.engine.get_table_map("ADCFRT14")

        query_t14_sel = (
            self.engine.dataset("ADCFRT14")
            .select(
                "gestione", "codiceAtto", "codiceAnag", "partitaIva", "codiceFiscale", "cognome", "nome",
                "sesso", "dataNascita", "comuneNascita", "provinciaNascita", "indirizzo", "numeroCivico",
                "letteraCivico", "numeroChilometro", "cap", "localita", "siglaProvincia", "comuneDomicilio",
                "indAnagrafeTrib", "capAnagrafeTrib", "siglaProvAnagrafeTrib", "locAnagrafeTrib", "comuneAnagrafeTrib",
                "dataValidDoc", "pec"
            )
            .filter_by("gestione", "=", cges)
            .filter_by("codiceAtto", "=", catt)
            .filter_by("codiceAnag", "=", "I")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query_t14_sel, depth=depth)
        if not rows:
            BatchLogger.warn("INSERISCI-SPESE-T14", f"Anagrafica ADCFRT14 non trovata per CGES={cges}, CATT={catt}", depth=depth)
            return

        record_t14 = t14_map.normalize(rows[0])
        record_t14["gestione"] = "N"
        record_t14["codiceAtto"] = str(id_avviso)[:20]

        if "impTributoAvviso" in record_t14:
            record_t14["impTributoAvviso"] = ctx.ws_itrbavv
        elif "totaleTributi" in record_t14:
            record_t14["totaleTributi"] = ctx.ws_itrbavv

        # Normalizzazione preventiva del campo chilometrico per preservare il tipo intero
        if "numeroChilometro" in record_t14:
            raw_nkim = str(record_t14.get("numeroChilometro") or "").strip().replace(",", ".")
            try:
                record_t14["numeroChilometro"] = int(float(raw_nkim)) if raw_nkim else 0
            except (ValueError, TypeError):
                record_t14["numeroChilometro"] = 0

        ins_t14 = (self.engine.dataset("ADCFRT14")
                   .compile_insert(record_t14))
        righe = self.engine.execute_mutation(ins_t14, depth=depth)
        BatchLogger.debug(
            "INSERISCI-SPESE-T14",
            f"ADCFRT14 duplicato su CATT={id_avviso} con Tot. Tributi={ctx.ws_itrbavv} (Righe: {righe})",
            depth=depth
        )

    # -------------------------------------------------------------------------
    # STEP 7: INSERISCI-TAB03 (DDL: DTPT03.ADCFRT03 via ADCFRT03.json)
    # -------------------------------------------------------------------------
    def _inserisci_tab03(self, ctx: FormazioneAvvisoContext, identificativo: str, depth: int) -> None:
        """
        Inserisce il record riepilogativo di testata dell'avviso formato in ADCFRT03
        utilizzando i campi logici esatti definiti nel mapper JSON di ADCFRT03.
        """
        BatchLogger.info(
            "STEP-7/7",
            f"Inserimento testata avviso in ADCFRT03 (Tot. Trib: {ctx.ws_itrbavv}, Aggio: {ctx.ws_iaggavv})",
            depth=depth
        )

        ws_annoruo_dec = int(str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4])
        now_dt = datetime.now()
        ws_timestamp = now_dt.strftime("%Y-%m-%d-%H.%M.%S.%f")
        ws_ckey = f"AVAD{ws_timestamp}"[:30]

        val_idges = [
            str(getattr(ctx, "ws_cgesavv", ctx.ws_cges) or "").strip(),
            str(getattr(ctx, "ws_sedeavv", ctx.ws_sede) or "").strip(),
            str(ctx.ws_annoavv or "").strip(),
            str(ctx.ws_progavv or "").strip()
        ]
        ws_idavvges = "".join(val_idges)[:19]

        ws_itrbavv = getattr(ctx, "ws_itrbavv", Decimal("0"))
        ws_iaggavv = getattr(ctx, "ws_iaggavv", Decimal("0"))
        id_avviso_completo = getattr(ctx, "ws_idavvruo", identificativo)[:20]

        ncar_val = int(str(getattr(ctx, "ws_nprgruo", 0)).strip() or 0)
        nchk_val = int(str(getattr(ctx, "ws_nchkruo", 0)).strip() or 0)
        cesaavv_val = int(str(ctx.ws_cesaavv).strip() or 0)
        d_con = ctx.dcon if isinstance(ctx.dcon, (date, datetime)) else date(2026, 8, 25)

        # Mappatura esclusiva sui nomi logici definiti in ADCFRT03.json
        record_t03 = {
            "codConcessione": cesaavv_val,
            "annoCartella": ws_annoruo_dec,
            "numCartella": ncar_val,
            "chkCartella": nchk_val,
            "codiceFiscale": str(ctx.ws_cfis).strip()[:16],
            "statoCartella": "G",
            "dataCartella": date.today(),
            "impCaricoCartella": int(ws_itrbavv),
            "divisa": "1",
            "dataNotifica": "0001-01-01",
            "dataRegNotifica": "0001-01-01",
            "ambitoDelegato": 0,
            "dataProvvDelega": "0001-01-01",
            "dataRegDelega": "0001-01-01",
            "annoRifFormazione": 0,
            "numProgrAnnoForm": 0,
            "annoRifNotifica": 0,
            "numProgrAnnoNotif": 0,
            "annoRifDelega": 0,
            "numProgrAnnoDelega": 0,
            "keyTabEventi": ws_ckey,
            "soggetto": "000",
            "timestampInsStato": now_dt,
            "timestampUpdStato": now_dt,
            "codEsattoriaAvviso": cesaavv_val,
            "idAvvisoGest": ws_idavvges,
            "tipoAvviso": str(ctx.ws_tipoavv).strip()[:1],
            "impAvvisoRav": int(ws_itrbavv + ws_iaggavv),
            "impAggio": int(ws_iaggavv),
            "numPartiteAvviso": int(ctx.ws_nparavv or 1),
            "codRav": 0,
            "esitoNotifica": " ",
            "motivoNotifica": " ",
            "annoSpedNotifca": 0,
            "numProgrAnnoSped": 0,
            "statoSped": "  ",
            "dataConsegna": d_con,
            "sede": str(ctx.ws_sede).strip()[:2],
            "zona": str(ctx.ws_zona).strip()[:2],
            "identificativoAvviso": id_avviso_completo,
            "cinesi": "  ",
            "codErroreEsito": " " * 189
        }

        ins_t03 = self.engine.dataset("ADCFRT03").compile_insert(record_t03)
        righe = self.engine.execute_mutation(ins_t03, depth=depth)
        BatchLogger.debug(
            "INSERISCI-TAB03",
            f"Testata ADCFRT03 inserita per avviso {ctx.ws_annoavv}/{ctx.ws_progavv} (Righe: {righe})",
            depth=depth
        )