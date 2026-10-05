# processes/formazione_ruoli/steps.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import FormazioneRuoliContext
from core.batch_logger import BatchLogger
from .step_tab14_cfis import AllineamentoAnagrafeStep as AllineamentoCfisStep
from .step_tab14_for import AllineamentoAnagrafeStep as AllineamentoForStep
from .step_aggiorna_tabelle import AggiornaTabelleStep


class ElaborazioneCurjoi2Step:
    """
    Reingegnerizzazione del paragrafo CICLO-CURJOI-2:
    Join tra ADCFRT01 e ADCFRT10 con gestione rottura e valorizzazione IMP-COMODI-KEY.
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_cfis = AllineamentoCfisStep(engine)
        self.step_for = AllineamentoForStep(engine)
        self.step_aggiorna_tabelle = AggiornaTabelleStep(engine)

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

        # Estrazione di tutti i crediti della sede e di tutti i moduli di credito relativi alla sede,
        # che siano già stati infasati
        query_curjoi2 = (
            self.engine.dataset("ADCFRT01")
            .join(t10_map, alias_self="A", alias_target="B")
            .on("gestione", "gestione")
            .on("codiceAtto", "codiceAtto")
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
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("codCentro", "=", ctx.current_cod_centro)
            .filter_by("dataInf", "<=",
                       getattr(ctx, "datainf", getattr(ctx, "ws_datainf", date.today())))  # NOT A.DINF > :CDCFRT01.DINF
            .filter_by("dataInf", "<>", date.today())  # A.DINF ^= CURRENT DATE
            .filter_by("dataInf", ">=", ctx.diniinf)  # A.DINF >= :CDCFRT18.DINIINF
            .filter_by("dataInf", "<=", ctx.dfininf)
            .filter_by("statoAttivita", "=", "0Q")
            .order_by("codEsattoria", "flgEuro")
            .order_by_joined("gestione", "codFasAmm", "numTotRate", "codTributoCnc", "codRata", "flgResiduo")
            .with_uncommitted_read()
            .compile_select()
        )

        record_art_totali = 0
        first_record = True
        avviso_interrotto_per_errore = False

        res = self.engine.fetch(query_curjoi2, depth=depth)
        if not res:
            ctx.indic_non_trov = "X"
            BatchLogger.info("CICLO-CURJOI-2", "Assenza di avvisi da elaborare)",
                             depth=depth)
            return 0
        else:
            # Estrazione del numero massimo del ruolo registrato per procedere alla conseguente
            # iscrizione del ruolo stesso in tabella.
            # In mancanza di numero ruolo presente in tabella viene assegnato in automatico il primo

            ws_annoruo_dec = str(ctx.dcon.year) if hasattr(ctx.dcon, "year") else str(ctx.dcon or "")[:4]
            t_ftr02_map = self.engine.get_table_map("ADCFRT02")

            query_max_t02 = (
                self.engine.dataset("ADCFRT02")
                .select(
                    "MAX:numRuolo"
                )
                .filter_by("codEsattoria", "=", ctx.current_sede)
                .filter_by("annoRif", "=", ws_annoruo_dec)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )

            rows = self.engine.fetch(query_max_t02, depth=1)
            max_nruo = rows.get("numRuolo")

            if max_nruo is None:
                ctx.ws_ctr_nruo = 1
            else:
                ctx.ws_ctr_nruo = max_nruo + 1

        # Ciclo di elaborazione con gestione di rottura chiave
        # Chiave:
        #   1) codEsattoria --> CESA
        #   2) flgEuro      --> FEUR
        #   3) gestione     --> CGES
        #   4) codFasAmm    --> CFASAMM
        #   5) numTotRate   --> NTOTRAT

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
                        ctx.ws_cesa == row_t01.get("codEsattoria") and
                        ctx.ws_feur == row_t01.get("flgEuro") and
                        ctx.ws_cges == row_t10.get("gestione") and
                        ctx.ws_cfasamm == row_t10.get("codFasAmm") and
                        ctx.ws_ntotrat == row_t10.get("numTotRate")
                    )

                    

                    if not stessa_chiave:
                        self._on_rottura_avviso(ctx, row_t01=row_t01, row_t10=row_t10, depth=depth)
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
            self._on_rottura_avviso(ctx, row_t01=None, row_t10=None, depth=depth, is_last=is_last_credit)

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
                    "gestione", "sede", "zona", "annoAvviso", "tipoAvviso", "progAvviso",
                    parent_table_map=t01_map, operator="<>"
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
        if ctx.ws_erravv.strip():
            return

        if (row_t01.get("numPartitaAvviso") or 0) != (ctx.ws_nparavv or 0):
            ctx.ws_erravv = "EXX381"
            BatchLogger.warn("VAL-CONGRUITA", f"Partita non conforme: {row_t01.get('numPartitaAvviso')} <> atteso {ctx.ws_nparavv} (ERR: EXX381)", depth=depth)
            return

        if str(row_t01.get("tipoAvviso") or "").strip() != str(getattr(ctx, "ws_tipoavv", "")).strip():
            ctx.ws_erravv = "EXX382"
            BatchLogger.warn("VAL-CONGRUITA", f"Tipo avviso non conforme: {row_t01.get('tipoAvviso')} <> atteso {getattr(ctx, 'ws_tipoavv', '')} (ERR: EXX382)", depth=depth)
            return

        if str(row_t01.get("codiceFiscale") or "").strip() != str(ctx.ws_cfis or "").strip():
            ctx.ws_erravv = "EXX383"
            BatchLogger.warn("VAL-CONGRUITA", f"Codice fiscale non conforme: {row_t01.get('codiceFiscale')} <> atteso {ctx.ws_cfis} (ERR: EXX383)", depth=depth)
            return

        if str(row_t01.get("sede") or "").strip() != str(ctx.ws_sede or "").strip():
            ctx.ws_erravv = "EXX384"
            BatchLogger.warn("VAL-CONGRUITA", f"Sede non conforme: {row_t01.get('sede')} <> atteso {ctx.ws_sede} (ERR: EXX384)", depth=depth)
            return

        if str(row_t01.get("zona") or "").strip() != str(ctx.ws_zona or "").strip():
            ctx.ws_erravv = "EXX385"
            BatchLogger.warn("VAL-CONGRUITA", f"Zona non conforme: {row_t01.get('zona')} <> atteso {ctx.ws_zona} (ERR: EXX385)", depth=depth)
            return

        cges = str(row_t01.get("gestione") or "").strip()
        if cges not in ("7", "8"):
            if str(row_t01.get("codAzienda") or "").strip() != str(getattr(ctx, "ws_cazi", "")).strip():
                ctx.ws_erravv = "EXX386"
                BatchLogger.warn("VAL-CONGRUITA", f"Codice azienda non conforme: {row_t01.get('codAzienda')} <> atteso {getattr(ctx, 'ws_cazi', '')} (ERR: EXX386)", depth=depth)
                return

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

        if str(row_t01.get("periodo") or "").strip() != str(getattr(ctx, "ws_periodo", "")).strip():
            ctx.ws_erravv = "EXX388"
            BatchLogger.warn("VAL-CONGRUITA", f"Periodo non conforme: {row_t01.get('periodo')} <> atteso {getattr(ctx, 'ws_periodo', '')} (ERR: EXX388)", depth=depth)
            return

        if str(row_t01.get("periodoBi") or "").strip() != str(getattr(ctx, "ws_periobi", "")).strip():
            ctx.ws_erravv = "EXX389"
            BatchLogger.warn("VAL-CONGRUITA", f"Periodo biennale non conforme: {row_t01.get('periodoBi')} <> atteso {getattr(ctx, 'ws_periobi', '')} (ERR: EXX389)", depth=depth)
            return

        if str(row_t01.get("flgRateizzazione") or "").strip() != str(getattr(ctx, "ws_frateiz", "")).strip():
            ctx.ws_erravv = "EXX390"
            BatchLogger.warn("VAL-CONGRUITA", f"Flag rateizzazione non conforme: {row_t01.get('flgRateizzazione')} <> atteso {getattr(ctx, 'ws_frateiz', '')} (ERR: EXX390)", depth=depth)
            return

        fvalfis = str(row_t01.get("flgValFiscale") or "").strip()
        f0 = str(getattr(ctx, "ws_forzatura0", "")).strip()
        f1 = str(getattr(ctx, "ws_forzatura1", "")).strip()

        if fvalfis != f0 and fvalfis != f1:
            ctx.ws_erravv = "EXX534"
            BatchLogger.warn("VAL-CONGRUITA", f"Flag validità fiscale non conforme: '{fvalfis}' non compreso tra [{f0}, {f1}] (ERR: EXX534)", depth=depth)
            return

    def _imp_errore(self, ctx: FormazioneAvvisoContext, row_t01: dict, depth: int = 4) -> None:
        ctx.indic_errore = "X"
        BatchLogger.error(
            "SCARTO-AVVISO",
            f"Avviso scartato [{ctx.ws_annoavv}/{ctx.ws_progavv}] CATT={row_t01.get('codiceAtto')} -> Errore bloccante: {ctx.ws_erravv}",
            depth=depth
        )

    def _on_rottura_avviso(self, ctx: FormazioneRuoliContext, row_t01: dict = None, row_t10: dict = None,
                           depth: int = 3, is_last: bool = False) -> None:
        t01 = row_t01 or {}
        t10 = row_t10 or {}

        BatchLogger.info("ROTTURA-CHIAVE", "**** ROTTURA CHIAVE **** [NUOVA CHIAVE AVVISO RILEVATA]", depth=depth)
        BatchLogger.debug(
            "ROTTURA-CHIAVE",
            f"CESA={t01.get('codEsattoria')} | FEUR={t01.get('flgEuro')} | "
            f"CGES={t10.get('gestione')} | CFASAMM={t10.get('codFasAmm')} | "
            f"NTOTRAT={t10.get('numTotRate')}",
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
            BatchLogger.warn(
                "CHIUSURA-AVV",
                f"Avviso {ctx.ws_annoavv}/{ctx.ws_progavv} SCARTATO ({ctx.ws_erravv}) -> Tot. Trib: 0.00 | Articoli: 0 | Salvataggio escluso",
                depth=depth,
                is_last=is_last
            )

        ctx.ws_itrbavv = Decimal("0")
        ctx.ws_iaggavv = Decimal("0")
        ctx.ws_nespart = 0
        ctx.ws_erravv = ""
        ctx.indic_errore = " "

    def _aggiorna_tabelle(self, ctx: FormazioneAvvisoContext, depth: int = 4) -> None:
        self.step_aggiorna_tabelle.execute(ctx, depth=depth)

    def _elabora_singolo_articolo(self, ctx: FormazioneAvvisoContext, row_t01: dict, row_t10: dict) -> None:
        itrb = self._parse_decimal(row_t10.get("impTributo"))
        iagg = self._parse_decimal(row_t10.get("impAggio"))
        ctx.ws_itrbavv += itrb
        ctx.ws_iaggavv += iagg
        ctx.ws_nespart += 1

    def execute(self, ctx: FormazioneAvvisoContext) -> None:
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

    def _aggiorna_tab17(self, ctx: FormazioneAvvisoContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCTET17 impostando il servizio a 'IN'."""
        upd_tab17 = (
            self.engine.dataset("ADCTET17")
            .filter_by("sede", "=", ctx.current_sede)
            .filter_by("zona", "=", ctx.current_zona)
            .filter_by("codCentro", "=", ctx.current_cod_centro)
            .compile_update({
                "codServizio": "IN",
                "timestamp": datetime(1, 1, 1, 0, 0, 0)
            })
        )
        righe_impattate = self.engine.execute_mutation(upd_tab17, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='IN' (Righe impattate: {righe_impattate})", depth=depth, is_last=is_last)

    def _aggiorna_tet17(self, ctx: FormazioneAvvisoContext, is_last: bool = False, depth: int = 1) -> None:
        """Aggiorna massivamente lo stato del record su ADCTET17 impostando il servizio a 'IF' a fine elaborazione."""
        upd_tet17 = (
            self.engine.dataset("ADCTET17")
            .compile_update({
                "codServizio": "IF",
                "timestamp": datetime.now()
            })
        )
        righe_impattate_if = self.engine.execute_mutation(upd_tet17, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T17", f"UPDATE ADCTET17 -> CDAS='IF' (Righe impattate: {righe_impattate_if})", depth=depth, is_last=is_last)