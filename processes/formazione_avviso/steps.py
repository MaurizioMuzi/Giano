# processes/formazione_avviso/steps.py
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import FormazioneAvvisoContext
from core.batch_logger import BatchLogger
from .step_tab14_cfis import AllineamentoAnagrafeStep as AllineamentoCfisStep
from .step_tab14_for import AllineamentoAnagrafeStep as AllineamentoForStep
from .step_aggiorna_tabelle import AggiornaTabelleStep


class BaseFormazioneStep(ABC):
    """Classe base astratta per tutti gli step della pipeline di formazione avvisi."""

    def __init__(self, engine):
        self.engine = engine

    @abstractmethod
    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        """Esegue l'elaborazione specifica dello step aggiornando il contesto condiviso."""
        pass


class StatoFormazioneStep(BaseFormazioneStep):
    """Paragrafi: CNTR-STATO-FORMAZIONE e UPD-STATO-INI-FORM (ADCFRT18)."""

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("INI-STATO-FOR", "STATO-FORMAZIONE (ADCFRT18)", depth=0)
        t18_map = self.engine.get_table_map("ADCFRT18")
        current_system_date = date.today()
        fixed_dfinfor_date = date(2026, 8, 24)

        query = (
            self.engine.dataset("ADCFRT18")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date)
            .filter_by("fstfor", "<>", "2")
            .with_uncommitted_read()
            .limit(1)
            .compile_select()
        )

        rows = self.engine.fetch(query, depth=1)
        if not rows:
            BatchLogger.error("INI-STATO-FOR", "Nessun record valido in ADCFRT18. Formazione non consentita.", depth=1, is_last=True)
            raise RuntimeError("[COBOL_EXCEPTION] FORMAZIONE NON CONSENTITA: Nessun record valido.")

        row = t18_map.normalize(rows[0])
        ctx.dcon = row.get("dcon")
        ctx.diniinf = row.get("diniinf")
        ctx.dfininf = row.get("dfininf")
        ctx.dinifor = row.get("dinifor")
        ctx.dfinfor = row.get("dfinfor")
        ctx.fstfor = row.get("fstfor")

        BatchLogger.info(
            "REC-FINESTRA",
            f"DCON={ctx.dcon} | Finestra Infasamento: {ctx.diniinf} -> {ctx.dfininf} | Stato={ctx.fstfor}",
            depth=1
        )

        upd = (
            self.engine.dataset("ADCFRT18")
            .filter_by("dcon", "=", ctx.dcon)
            .filter_by("diniinf", "=", ctx.diniinf)
            .compile_update({
                "fstfor": "1",
                "tmsini": datetime.now()
            })
        )
        righe_modificate = self.engine.execute_mutation(upd, depth=1)
        BatchLogger.info("UPD-STATO-T18", f"UPDATE ADCFRT18 SET FSTFOR='1' -> Record impattati: {righe_modificate}", depth=1, is_last=True)
        BatchLogger.separator(depth=0)


class GestioneRipartenzeStep(BaseFormazioneStep):
    """
    Reingegnerizzazione dei paragrafi:
      - GESTIONE-RIPARTENZE
      - CONTA-SEDI
      - CONTA-LAVORI
      - AGGIORNA-LAVORI
    """

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("CHK-RIPARTENZE", "GESTIONE-RIPARTENZE (ADCTET17)", depth=0)

        # CONTA-SEDI
        q_sedi = (
            self.engine.dataset("ADCTET17")
            .count()
            .with_uncommitted_read()
            .compile_select()
        )
        res_sedi = self.engine.fetch(q_sedi, depth=1)
        ctx.count_sedi = int(list(res_sedi[0].values())[0]) if res_sedi else 0

        # CONTA-LAVORI
        q_lavori = (
            self.engine.dataset("ADCTET17")
            .count()
            .filter_by("codServizio", "IN", ("IF", "AV"))
            .with_uncommitted_read()
            .compile_select()
        )
        res_lavori = self.engine.fetch(q_lavori, depth=1)
        ctx.count_lavori = int(list(res_lavori[0].values())[0]) if res_lavori else 0

        BatchLogger.info("CONTA-LAV-T17", f"Sedi censite: {ctx.count_sedi} | Lavori qualificati (IF/AV): {ctx.count_lavori}", depth=1)

        if ctx.count_lavori == ctx.count_sedi and ctx.count_sedi > 0:
            upd_reset = (
                self.engine.dataset("ADCTET17")
                .compile_update({
                    "codServizio": "AV",
                    "timestamp": datetime(1, 1, 1, 0, 0, 0)
                })
            )
            righe_aggiornate = self.engine.execute_mutation(upd_reset, depth=1)
            BatchLogger.info("RESET-LAV-T17", f"WS-COUNT = WS-COUNT-SED -> Reset massivo eseguito. Impattati: {righe_aggiornate}", depth=1, is_last=True)
        else:
            BatchLogger.info("CHECK-LAV-T17", "WS-COUNT <> WS-COUNT-SED -> Nessun riallineamento massivo necessario", depth=1, is_last=True)
        BatchLogger.separator(depth=0)


class ElaborazioneCurjoi2Step(BaseFormazioneStep):
    """
    Reingegnerizzazione del paragrafo CICLO-CURJOI-2:
    Join tra ADCFRT01 e ADCFRT10 con gestione rottura e valorizzazione IMP-COMODI-KEY.
    """

    def __init__(self, engine):
        super().__init__(engine)
        self.step_cfis = AllineamentoCfisStep(engine)
        self.step_for = AllineamentoForStep(engine)
        self.step_aggiorna_tabelle = AggiornaTabelleStep(engine)

    def execute_record(self, ctx: FormazioneAvvisoContext, cges: str, anno_avv: int, prog_avv: int, depth: int = 3, is_last_credit: bool = False) -> None:
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

        query_curjoi2 = (
            self.engine.dataset("ADCFRT01")
            .join(t10_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
            .on("statoAttivita", "statoArticolo")
            .select(
                "codEsattoria", "gestione", "codiceAtto", "statoAttivita", "codiceFiscale",
                "flgEuro", "dataRifCon", "codAzienda", "dataFallimento", "sede", "zona",
                "codCentro", "flgCessione", "flgDecadenza", "tipoAvviso", "annoAvviso",
                "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi",
                "codEsattoriaAvviso", "sedeOrigine", "flgRateizzazione", "flgValFiscale"
            )
            .select_joined(
                "codTributoCnc", "codRata", "numTotRate", "flgResiduo", "impTributo",
                "impInteressi", "codNaturaTrb", "impTributoCalc", "impAggioTot", "impAggioAnt",
                "impArrotondamento", "progArticolo", "numIdDecre", "tasso", "impCapitale",
                "dataFineCalc", "codFasAmm", "impAggio", "statoArticolo"
            )
            .filter_by("gestione", "=", cges)
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("annoAvviso", "=", anno_avv)
            .filter_by("progAvviso", "=", prog_avv)
            .filter_by("statoAttivita", "=", "0I")
            .order_by("gestione", "annoAvviso", "progAvviso", "numEspAvviso")
            .order_by_joined("progArticolo")
            .with_uncommitted_read()
            .compile_select()
        )

        record_art_totali = 0
        first_record = True
        avviso_interrotto_per_errore = False

        for chunk in self.engine.cursor_stream(query_curjoi2, buffer_size=500, depth=depth):
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
                        ctx.ws_cges == row_t01.get("gestione") and
                        ctx.ws_sede == row_t01.get("sede") and
                        ctx.ws_zona == row_t01.get("zona") and
                        ctx.ws_annoavv == row_t01.get("annoAvviso") and
                        ctx.ws_progavv == row_t01.get("progAvviso")
                    )

                    if not stessa_chiave:
                        self._on_rottura_avviso(ctx, row_t01=row_t01, depth=depth)
                        ctx.imp_comodi_key(row_t01, row_t10)
                        ctx.sw_keyavv = 0

                # CONTROLLI DI CONGRUITA' ONE-OFF SULL'AVVISO (depth=depth+1 -> 4)
                if ctx.sw_keyavv == 0:
                    ctx.sw_keyavv = 1

                    # 1. CNTR-KEY-AVV
                    ws_count_avv = self._cntr_key_avv(ctx, depth=depth + 1)
                    if ws_count_avv != (ctx.ws_nparavv or 0):
                        ctx.ws_erravv = "EXX381"
                        BatchLogger.warn(
                            "CNTR-KEY-AVV",
                            f"Partite disallineate: trovate {ws_count_avv} su ADCFRT01, attese {ctx.ws_nparavv} da NPARAVV (ERR: EXX381)",
                            depth=depth + 1
                        )
                    else:
                        BatchLogger.info("CNTR-KEY-AVV", f"Verifica partite: trovate {ws_count_avv} / attese {ctx.ws_nparavv} [OK]", depth=depth + 1)

                    # 2. CNTR-MAX-ART
                    if not ctx.ws_erravv.strip():
                        ws_count_dif = self._cntr_max_art(ctx, depth=depth + 1)
                        if ws_count_dif > 0:
                            ctx.ws_erravv = "EXX638"
                            BatchLogger.warn("CNTR-MAX-ART", "Sequenzialità progressivi articolo non integra (ERR: EXX638)", depth=depth + 1)
                        else:
                            BatchLogger.info("CNTR-MAX-ART", "Verifica sequenzialità: MAX(NPRGART)=COUNT(*) [OK]", depth=depth + 1)

                    # 3. CNTR-KEY-ART
                    if not ctx.ws_erravv.strip():
                        ws_count_art = self._cntr_key_art(ctx, depth=depth + 1)
                        if ws_count_art > 999:
                            ctx.ws_erravv = "EXX637"
                            BatchLogger.warn("CNTR-KEY-ART", f"Massimo numero di articoli superato: {ws_count_art} (ERR: EXX637)", depth=depth + 1)
                        else:
                            BatchLogger.info("CNTR-KEY-ART", f"Controllo massimo 999 articoli: {ws_count_art} [OK]", depth=depth + 1)

                    # 4. CNTRL-CF-BLK
                    esito_blocco = self._cntrl_cf_blk(ctx, depth=depth + 1)

                    # 5. CNTRL-TAB14-CFIS - Gestione doppio ciclo per codici fiscali non bloccati
                    if esito_blocco == 0 and not ctx.ws_erravv.strip():
                        if str(getattr(ctx, "ws_forzatura0", "")).strip() in ("0", "1"):
                            ws_count_cf = self._cntrl_tab14_cfis(ctx, depth=depth + 1)
                            if ws_count_cf > 0:
                                self.step_cfis.execute_allineamento(ctx, depth=depth + 1)
                            else:
                                BatchLogger.info("ALLINEA-CFIS", "WS-COUNT-CF = 0: nessun allineamento anagrafico richiesto", depth=depth + 1)

                    # 6. CNTRL-TAB14-FOR - Gestione doppio ciclo per codici fiscali bloccati
                    elif esito_blocco == 1 and not ctx.ws_erravv.strip():
                        if str(getattr(ctx, "ws_forzatura0", "")).strip() in ("2", "3"):
                            self.step_for.execute_allineamento_for(ctx, depth=depth + 1)

                # VALIDAZIONE CONGRUITA' RECORD CDCFRT01 (EXX381 .. EXX534)
                self._valida_congruita_riga_t01(ctx, row_t01, depth=depth + 1)

                # GESTIONE CONTABILE E RILEVAZIONE SCARTO AVVISO
                if not ctx.ws_erravv.strip():
                    self._elabora_singolo_articolo(ctx, row_t01, row_t10)
                else:
                    self._imp_errore(ctx, row_t01, depth=depth + 1)
                    avviso_interrotto_per_errore = True
                    break

            if avviso_interrotto_per_errore:
                break

        if record_art_totali == 0:
            BatchLogger.warn("ESITO-DETT-T10", "0 articoli correlati su ADCFRT10 per l'avviso", depth=depth, is_last=is_last_credit)
        else:
            self._on_rottura_avviso(ctx, row_t01=None, depth=depth, is_last=is_last_credit)

    # -----------------------------------------------------------------------------
    # STEP 1: CONTROLLO CONGRUITÀ NUMERO PARTITE INFASATE
    # -----------------------------------------------------------------------------
    def _cntr_key_avv(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> int:
        try:
            query = (
                self.engine.dataset("ADCFRT01")
                .count()
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("sede", "=", ctx.ws_sede)
                .filter_by("zona", "=", ctx.ws_zona)
                .filter_by("annoAvviso", "=", ctx.ws_annoavv)
                .filter_by("progAvviso", "=", ctx.ws_progavv)
                .filter_by("statoAttivita", "=", "0I")
                .with_uncommitted_read()
                .compile_select()
            )
            res = self.engine.fetch(query, depth=depth)
            return int(list(res[0].values())[0]) if res else 0

        except Exception as err:
            BatchLogger.error("CNTR-KEY-AVV", f"Errore DB in conteggio partite: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1

    # -----------------------------------------------------------------------------
    # STEP 2: CONTROLLO CONTINUITÀ NUMERAZIONE ARTICOLI PER AVVISO
    # -----------------------------------------------------------------------------
    def _cntr_max_art(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> int:
        t10_map = self.engine.get_table_map("ADCFRT10")
        col_prg_b = f"B.{t10_map.progArticolo}"

        try:
            query = (
                self.engine.dataset("ADCFRT01")
                .join(t10_map, alias_self="A", alias_target="B")
                .on("gestione", "gestione")
                .on("codiceAtto", "codiceAtto")
                .select("codiceAtto")
                .select_raw(f"MAX({col_prg_b}) AS MAXPRG")
                .select_raw("COUNT(*) AS COUNT10")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("sede", "=", ctx.ws_sede)
                .filter_by("zona", "=", ctx.ws_zona)
                .filter_by("annoAvviso", "=", ctx.ws_annoavv)
                .filter_by("progAvviso", "=", ctx.ws_progavv)
                .filter_by("statoAttivita", "=", "0I")
                .group_by("codiceAtto")
                .having_raw(f"MAX({col_prg_b}) <> COUNT(*)")
                .count_subquery(alias="TAB1")
                .with_uncommitted_read()
                .compile_select()
            )
            res = self.engine.fetch(query, depth=depth)
            return int(list(res[0].values())[0]) if res else 0

        except Exception as err:
            BatchLogger.error("CNTR-MAX-ART", f"Errore DB in conteggio numerazione sequenziale: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1

    # -----------------------------------------------------------------------------
    # STEP 3: CONTROLLO SOGLIA MASSIMA ARTICOLI INFASATI PER AVVISO
    # -----------------------------------------------------------------------------
    def _cntr_key_art(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> int:
        t10_map = self.engine.get_table_map("ADCFRT10")

        try:
            query = (
                self.engine.dataset("ADCFRT01")
                .join(t10_map, alias_self="A", alias_target="B")
                .on("gestione", "gestione")
                .on("codiceAtto", "codiceAtto")
                .count()
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("sede", "=", ctx.ws_sede)
                .filter_by("zona", "=", ctx.ws_zona)
                .filter_by("annoAvviso", "=", ctx.ws_annoavv)
                .filter_by("progAvviso", "=", ctx.ws_progavv)
                .filter_by("statoAttivita", "=", "0I")
                .with_uncommitted_read()
                .compile_select()
            )
            res = self.engine.fetch(query, depth=depth)
            return int(list(res[0].values())[0]) if res else 0

        except Exception as err:
            BatchLogger.error("CNTR-KEY-ART", f"Errore DB in conteggio limite max 999: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1

    # -----------------------------------------------------------------------------
    # STEP 4: VERIFICA STATO BLOCCO CODICE FISCALE
    # -----------------------------------------------------------------------------
    def _cntrl_cf_blk(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> int:
        t62_map = self.engine.get_table_map("ADCFRT62")

        try:
            query = (
                self.engine.dataset("ADCFRT62")
                .select("flagBlocco", "timestampInsInfo", "timestampVarInfo", "date:timestampVarInfo")
                .filter_by("codiceFiscale", "=", ctx.ws_cfis)
                .order_by_desc("timestampInsInfo")
                .with_uncommitted_read()
                .compile_select()
            )
            res = self.engine.fetch(query, depth=depth)

            if not res:
                ctx.ws_flgblk = "0"
                BatchLogger.info("CNTR-BLOCCO-CF", "Record CDCFRT62 assente -> CF non bloccato (WS-FLGBLK='0')", depth=depth)
                return 0

            row = t62_map.normalize(res[0])
            flgblk = str(row.get("flagBlocco", "")).strip()
            dt_upd = row.get("timestampVarInfo")

            in_finestra = bool(dt_upd and ctx.diniinf and ctx.dfininf and ctx.diniinf <= dt_upd <= ctx.dfininf)
            ctx.ws_flgblk = "1" if (flgblk != "0" or in_finestra) else "0"

            dettaglio = f"FLGBLK='{flgblk}'" + (
                f" (DataUpd={dt_upd} in finestra [{ctx.diniinf}..{ctx.dfininf}])" if in_finestra else ""
            )
            BatchLogger.info("CNTR-BLOCCO-CF", f"{dettaglio} -> WS-FLGBLK='{ctx.ws_flgblk}'", depth=depth)

            return int(ctx.ws_flgblk)

        except Exception as err:
            BatchLogger.error("CNTR-BLOCCO-CF", f"Errore DB in verifica codice fiscale bloccato: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1

    # -----------------------------------------------------------------------------
    # STEP 5: ALLINEAMENTO INDIRIZZO ANAGRAFE TRIBUTARIA PER CF NON BLOCCATO
    # -----------------------------------------------------------------------------
    def _cntrl_tab14_cfis(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> int:
        t01_dataset = self.engine.dataset("ADCFRT01")
        t01_map = self.engine.get_table_map("ADCFRT01")

        try:
            sub_exists = (
                t01_dataset.exists(t01_map, alias="B")
                .correlate("codiceFiscale", "codiceFiscale", t01_map)
                .filter_by("dataInf", ">=", ctx.diniinf)
                .filter_by("dataInf", "<=", ctx.dfininf)
                .correlate_mismatch(
                    "gestione",
                    "sede",
                    "zona",
                    "annoAvviso",
                    "tipoAvviso",
                    "progAvviso",
                    parent_table_map=t01_map,
                    operator="<>"
                )
                .filter_by("statoAttivita", "=", "0I")
            )

            query = (
                t01_dataset
                .count()
                .filter_by("codiceFiscale", "=", ctx.ws_cfis)
                .filter_by("statoAttivita", "=", "0I")
                .where_exists(sub_exists)
                .with_uncommitted_read()
                .compile_select()
            )

            res = self.engine.fetch(query, depth=depth)
            count_val = int(list(res[0].values())[0]) if res else 0

            BatchLogger.info("CNTRL-T14-CFIS", f"WS-COUNT-CF calcolato: {count_val}", depth=depth)
            return count_val

        except Exception as err:
            BatchLogger.error("CNTRL-T14-CFIS", f"Errore DB in verifica codice fiscale con più avvisi: {err}", depth=depth)
            ctx.indic_errore = "X"
            return -1

    def _parse_decimal(self, value) -> Decimal:
        """Esegue il cast sicuro a Decimal con gestione fallback a 0 in caso di valori None o non validi."""
        if value is None:
            return Decimal("0")
        val_str = str(value).strip()
        if not val_str:
            return Decimal("0")
        try:
            return Decimal(val_str)
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _valida_congruita_riga_t01(self, ctx: FormazioneAvvisoContext, row_t01: dict, depth: int = 4) -> None:
        """
        Verifica sequenziale di congruenza della singola riga CDCFRT01 rispetto ai dati consolidati dell'avviso.
        Reingegnerizza la catena di controlli COBOL da EXX381 a EXX534 con logica fail-fast.
        """
        if ctx.ws_erravv.strip():
            return

        # 1. EXX381 - Controllo Numero Partita Avviso (NPARAVV)
        if (row_t01.get("numPartitaAvviso") or 0) != (ctx.ws_nparavv or 0):
            ctx.ws_erravv = "EXX381"
            BatchLogger.warn("VAL-CONGRUITA", f"Partita non conforme: {row_t01.get('numPartitaAvviso')} <> atteso {ctx.ws_nparavv} (ERR: EXX381)", depth=depth)
            return

        # 2. EXX382 - Controllo Tipo Avviso (TIPOAVV)
        if str(row_t01.get("tipoAvviso") or "").strip() != str(getattr(ctx, "ws_tipoavv", "")).strip():
            ctx.ws_erravv = "EXX382"
            BatchLogger.warn("VAL-CONGRUITA", f"Tipo avviso non conforme: {row_t01.get('tipoAvviso')} <> atteso {getattr(ctx, 'ws_tipoavv', '')} (ERR: EXX382)", depth=depth)
            return

        # 3. EXX383 - Controllo Codice Fiscale (CFIS)
        if str(row_t01.get("codiceFiscale") or "").strip() != str(ctx.ws_cfis or "").strip():
            ctx.ws_erravv = "EXX383"
            BatchLogger.warn("VAL-CONGRUITA", f"Codice fiscale non conforme: {row_t01.get('codiceFiscale')} <> atteso {ctx.ws_cfis} (ERR: EXX383)", depth=depth)
            return

        # 4. EXX384 - Controllo Sede (CSED)
        if str(row_t01.get("sede") or "").strip() != str(ctx.ws_sede or "").strip():
            ctx.ws_erravv = "EXX384"
            BatchLogger.warn("VAL-CONGRUITA", f"Sede non conforme: {row_t01.get('sede')} <> atteso {ctx.ws_sede} (ERR: EXX384)", depth=depth)
            return

        # 5. EXX385 - Controllo Zona (CZON)
        if str(row_t01.get("zona") or "").strip() != str(ctx.ws_zona or "").strip():
            ctx.ws_erravv = "EXX385"
            BatchLogger.warn("VAL-CONGRUITA", f"Zona non conforme: {row_t01.get('zona')} <> atteso {ctx.ws_zona} (ERR: EXX385)", depth=depth)
            return

        # 6. EXX386 - Controllo Codice Azienda (CAZI) - solo se Gestione != 7 e != 8
        cges = str(row_t01.get("gestione") or "").strip()
        if cges not in ("7", "8"):
            if str(row_t01.get("codAzienda") or "").strip() != str(getattr(ctx, "ws_cazi", "")).strip():
                ctx.ws_erravv = "EXX386"
                BatchLogger.warn("VAL-CONGRUITA", f"Codice azienda non conforme: {row_t01.get('codAzienda')} <> atteso {getattr(ctx, 'ws_cazi', '')} (ERR: EXX386)", depth=depth)
                return

        # 7. EXX387 - Controllo Codice Atto (CATT) e Sequenzialità Esposizione Partita (NESPAVV)
        catt_corrente = str(row_t01.get("codiceAtto") or "").strip()
        nesp_corrente = int(row_t01.get("numEspAvviso") or 0)
        ws_catt = str(getattr(ctx, "ws_catt", "")).strip()

        if catt_corrente != ws_catt:
            ctx.ws_catt = catt_corrente
            atteso_nesp = int(getattr(ctx, "ws_nespavv", 0) or 0) + 1
            if nesp_corrente != atteso_nesp:
                ctx.ws_erravv = "EXX387"
                BatchLogger.warn("VAL-CONGRUITA", f"Discontinuità esposizione atto {catt_corrente}: {nesp_corrente} <> atteso {atteso_nesp} (ERR: EXX387)", depth=depth)
                return
            else:
                ctx.ws_nespavv = nesp_corrente
                ctx.ws_ntotpar = getattr(ctx, "ws_ntotpar", 0) + 1
        else:
            ctx.ws_nespavv = nesp_corrente

        # 8. EXX388 - Controllo Periodo (PERIODO)
        if str(row_t01.get("periodo") or "").strip() != str(getattr(ctx, "ws_periodo", "")).strip():
            ctx.ws_erravv = "EXX388"
            BatchLogger.warn("VAL-CONGRUITA", f"Periodo non conforme: {row_t01.get('periodo')} <> atteso {getattr(ctx, 'ws_periodo', '')} (ERR: EXX388)", depth=depth)
            return

        # 9. EXX389 - Controllo Periodo Biennale (PERIOBI)
        if str(row_t01.get("periodoBi") or "").strip() != str(getattr(ctx, "ws_periobi", "")).strip():
            ctx.ws_erravv = "EXX389"
            BatchLogger.warn("VAL-CONGRUITA", f"Periodo biennale non conforme: {row_t01.get('periodoBi')} <> atteso {getattr(ctx, 'ws_periobi', '')} (ERR: EXX389)", depth=depth)
            return

        # 10. EXX390 - Controllo Flag Rateizzazione (FRATEIZZ)
        if str(row_t01.get("flgRateizzazione") or "").strip() != str(getattr(ctx, "ws_frateiz", "")).strip():
            ctx.ws_erravv = "EXX390"
            BatchLogger.warn("VAL-CONGRUITA", f"Flag rateizzazione non conforme: {row_t01.get('flgRateizzazione')} <> atteso {getattr(ctx, 'ws_frateiz', '')} (ERR: EXX390)", depth=depth)
            return

        # 11. EXX534 - Controllo Flag Validità Fiscale (FVALFIS con forzature)
        fvalfis = str(row_t01.get("flgValFiscale") or "").strip()
        f0 = str(getattr(ctx, "ws_forzatura0", "")).strip()
        f1 = str(getattr(ctx, "ws_forzatura1", "")).strip()

        if fvalfis != f0 and fvalfis != f1:
            ctx.ws_erravv = "EXX534"
            BatchLogger.warn("VAL-CONGRUITA", f"Flag validità fiscale non conforme: '{fvalfis}' non compreso tra [{f0}, {f1}] (ERR: EXX534)", depth=depth)
            return

    def _imp_errore(self, ctx: FormazioneAvvisoContext, row_t01: dict, depth: int = 4) -> None:
        """
        Reingegnerizza il paragrafo IMP-ERRORE THRU IMP-ERRORE-EX.
        Imposta il flag generale di errore su 'X', scrive nel log lo scarto dell'avviso
        e predispone le variabili per la chiusura anticipata dell'elaborazione corrente.
        """
        ctx.indic_errore = "X"
        BatchLogger.error(
            "SCARTO-AVVISO",
            f"Avviso scartato [{ctx.ws_annoavv}/{ctx.ws_progavv}] CATT={row_t01.get('codiceAtto')} -> Errore bloccante: {ctx.ws_erravv}",
            depth=depth
        )

    def _on_rottura_avviso(self, ctx: FormazioneAvvisoContext, row_t01: dict = None, depth: int = 3, is_last: bool = False) -> None:
        """
        Reingegnerizza il blocco COBOL di rottura chiave avviso (ELSE di controllo chiave).
        Se SW-ERRORE = 0 (nessun errore bloccante), esegue il paragrafo AGGIORNA-TABELLE,
        quindi predispone il contesto per il nuovo avviso azzerando i contatori finanziari.
        """
        if row_t01:
            BatchLogger.info("ROTTURA-CHIAVE", "**** ROTTURA CHIAVE **** [NUOVA CHIAVE AVVISO RILEVATA]", depth=depth)
            BatchLogger.debug(
                "ROTTURA-CHIAVE",
                f"CGES={row_t01.get('gestione')} | CSED={row_t01.get('sede')} | "
                f"CZON={row_t01.get('zona')} | ANNOAVV={row_t01.get('annoAvviso')} | "
                f"PROGAVV={row_t01.get('progAvviso')}",
                depth=depth + 1
            )

        sw_errore = 1 if (ctx.indic_errore == "X" or ctx.ws_erravv.strip()) else 0

        if sw_errore == 0:
            BatchLogger.info(
                "CHIUSURA-AVV",
                f"Avviso {ctx.ws_annoavv}/{ctx.ws_progavv} REGOLARE -> Tot. Tributi: {ctx.ws_itrbavv} | Articoli: {ctx.ws_nespart} | Avvio consolidamento",
                depth=depth
            )
            self._aggiorna_tabelle(ctx, depth=depth + 1)
        else:
            # Singola emissione pulita a livello 3 senza doppioni o sotto-alberi anomali
            BatchLogger.warn(
                "CHIUSURA-AVV",
                f"Avviso {ctx.ws_annoavv}/{ctx.ws_progavv} SCARTATO ({ctx.ws_erravv}) -> Tot. Trib: 0.00 | Articoli: 0 | Salvataggio escluso",
                depth=depth,
                is_last=is_last
            )

        # Reset variabili locali dell'avviso per garantire isolamento al credito successivo
        ctx.ws_itrbavv = Decimal("0")
        ctx.ws_iaggavv = Decimal("0")
        ctx.ws_nespart = 0
        ctx.ws_erravv = ""
        ctx.indic_errore = " "

    def _aggiorna_tabelle(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> None:
        """
        Reingegnerizza il paragrafo AGGIORNA-TABELLE THRU AGGIORNA-TABELLE-EX
        delegando l'intera pipeline di consolidamento alla classe dedicata.
        """
        self.step_aggiorna_tabelle.execute(ctx, depth=depth)

    def _elabora_singolo_articolo(self, ctx: FormazioneAvvisoContext, row_t01: dict, row_t10: dict) -> None:
        """Aggiorna i totalizzatori finanziari progressivi dell'avviso (tributo, aggio, numero articoli)."""
        itrb = self._parse_decimal(row_t10.get("impTributo"))
        iagg = self._parse_decimal(row_t10.get("impAggio"))
        ctx.ws_itrbavv += itrb
        ctx.ws_iaggavv += iagg
        ctx.ws_nespart += 1

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        """Metodo astratto di interfaccia."""
        pass


class ElaborazioneCurjoi12AStep(BaseFormazioneStep):
    """Estrazione dei crediti distinti da ADCFRT01 (CURJOI-2A)."""

    def __init__(self, engine):
        super().__init__(engine)
        self.step_curjoi2 = ElaborazioneCurjoi2Step(engine)

    def execute(self, ctx: FormazioneAvvisoContext, depth: int = 2) -> None:
        t01_map = self.engine.get_table_map("ADCFRT01")

        query = (
            self.engine.dataset("ADCFRT01")
            .distinct()
            .select("gestione", "sede", "zona", "annoAvviso", "progAvviso")
            .filter_by("statoAttivita", "=", "0I")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("codCentro", "=", ctx.current_cod_centro)
            .with_uncommitted_read()
            .compile_select()
        )

        dettagli_record = []
        for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=depth):
            for raw_row in chunk:
                row = t01_map.normalize(raw_row)
                dettagli_record.append({
                    "cges": row.get("gestione"),
                    "csed": row.get("sede"),
                    "czon": row.get("zona"),
                    "annoavv": row.get("annoAvviso"),
                    "progavv": row.get("progAvviso")
                })

        tot_crediti = len(dettagli_record)
        ctx.righe_elaborate_sede = tot_crediti

        if tot_crediti == 0:
            BatchLogger.info("SCAN-ATTI-T01", "Crediti infasati rilevati (stato 0I): 0", depth=depth)
            return

        BatchLogger.info("SCAN-ATTI-T01", f"Crediti infasati rilevati (stato 0I): {tot_crediti}", depth=depth)

        tbl_sep = "+--------+------+------+------+---------+------------+"
        header = f"| {'PROG':<6} | {'CGES':<4} | {'CSED':<4} | {'CZON':<4} | {'ANNOAVV':<7} | {'PROGAVV':<10} |"

        BatchLogger.info("ELENCO-CREDITI", tbl_sep, depth=depth)
        BatchLogger.info("ELENCO-CREDITI", header, depth=depth)
        BatchLogger.info("ELENCO-CREDITI", tbl_sep, depth=depth)
        for idx, r in enumerate(dettagli_record, start=1):
            row_str = f"| {idx:<6} | {str(r['cges']):<4} | {str(r['csed']):<4} | {str(r['czon']):<4} | {str(r['annoavv']):<7} | {str(r['progavv']):<10} |"
            BatchLogger.info("ELENCO-CREDITI", row_str, depth=depth)
        BatchLogger.info("ELENCO-CREDITI", tbl_sep, depth=depth)

        for idx, r in enumerate(dettagli_record, start=1):
            is_last_credit = (idx == tot_crediti)
            BatchLogger.info(
                "CREDITO-ATTIVO",
                f"[{idx}/{tot_crediti}] CGES={r['cges']} | ANNO={r['annoavv']} | PROG={r['progavv']}",
                depth=depth + 1,
                is_last=False
            )
            self.step_curjoi2.execute_record(
                ctx=ctx,
                cges=r["cges"],
                anno_avv=r["annoavv"],
                prog_avv=r["progavv"],
                depth=depth + 1,
                is_last_credit=is_last_credit
            )


class ElaborazioneCurjoi1Step(BaseFormazioneStep):
    """Scansione delle sedi di recapito (CURJOI-1 su ADCTET17)."""

    def __init__(self, engine):
        super().__init__(engine)
        self.step_curjoi_2a = ElaborazioneCurjoi12AStep(engine)

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
        BatchLogger.info("SCAN-SEDI-T17", "Avvio scansione sedi operative (CURJOI-1 su ADCTET17)", depth=0)
        t17_map = self.engine.get_table_map("ADCTET17")

        query = (
            self.engine.dataset("ADCTET17")
            .distinct()
            .select("sede", "zona", "codCentro", "codServizio")
            .filter_by("codServizio", "=", "AV")
            .filter_by("dataPre", "<=", date.today())
            .order_by("sede", "zona", "codCentro")
            .with_uncommitted_read()
            .compile_select()
        )

        rows = []
        for chunk in self.engine.cursor_stream(query, buffer_size=500, depth=1):
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
            ctx.current_cod_servizio = row.get("codServizio")
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
                stato_aggiornamento = "IN (AGGIORNATO)"
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

    def _aggiorna_tab17(self, ctx: FormazioneAvvisoContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCTET17 impostando il servizio a 'IN'."""
        upd_tab17 = (
            self.engine.dataset("ADCTET17")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("codCentro", "=", ctx.current_cod_centro)
            .compile_update({
                "codServizio": "IN",
                "timestamp": datetime.now()
            })
        )
        righe_impattate = self.engine.execute_mutation(upd_tab17, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='IN' (Righe impattate: {righe_impattate})", depth=depth, is_last=is_last)