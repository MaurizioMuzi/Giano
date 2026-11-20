# processes/preparazione_postalizzazione/step_ciclo_curt_01.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Any

from .context import PreparazionePostalizzazioneContext
from .step_valorizza_inserisci_t13 import DettaglioValorizzaT13
from core.batch_logger import BatchLogger

class DettaglioCicloCurt01:
    """
    Reingegnerizzazione del paragrafo CICLO-CURT01:
    CICLO DI ELABORAZIONE CURSORE SU ADCFRT01 PER L'ELABORAZIONE DELLE PARTITE CHE CONFLUISCONO IN UN AVVISO
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_valorizza_inserisci_t13 = DettaglioValorizzaT13(engine)
        self.step_ciclo_curt10 = ElaborazioneCicloCurt10Step(engine)

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1, is_last: bool = False) -> None:
        BatchLogger.info("ELABORAZIONE", "Ciclo di elaborazione (su ADCFRT01) delle partite che confluiscono in un avviso", depth=depth)

        t10_map = self.engine.get_table_map("ADCFRT10")
        try:
            self.step_valorizza_inserisci_t13.execute_dettaglio(ctx, depth=depth+1)

            raw_rows = self._db_fetch_curt10(ctx, depth=depth + 1)
            rows_t10 = [t10_map.normalize(r) for r in raw_rows]

            tot_art = len(rows_t10)

            if tot_art == 0:
                BatchLogger.error("SELECT-ADCFRT10",
                                  f"Nessun articolo trovato su ADCFRT10 con CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                                  depth=depth+1, is_last=True)

            ctx.indic_errore = " "

            # PERFORM UNTIL FINE-CURT10
            for idx, row_t10 in enumerate(rows_t10, start=1):
                is_last_int = (idx == tot_art)

                ctx.codiceTributo = row_t10["codiceTributo"]

                BatchLogger.info(
                    "ARTICOLI",
                    f"[{idx}/{tot_art}]",
                    depth=depth+1,
                    is_last=False
                )

                self.step_ciclo_curt10.execute(
                    ctx=ctx,
                    rowt10=row_t10,
                    depth=depth + 1,
                    is_last_int=is_last_int)  # PERFORM CICLO-CURT10

            # UPDATE-T10
            self._aggiorna_t10(ctx, depth=depth)

            # UPDATE-T21
            self._aggiorna_t21(ctx, depth=depth)

            # UPDATE-T23
            self._aggiorna_t23(ctx, depth=depth)

            # UPDATE-T24
            self._aggiorna_t24(ctx, depth=depth)

            # UPDATE-AVV33
            self._aggiorna_avv33(ctx, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "CICLO-T01-ERR",
                f"Errore critico durante elaborazione su ADCFRT01: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise


    # =========================================================================
    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_curt10(self, ctx:PreparazionePostalizzazioneContext, depth: int) -> List[Any]:
        """Accesso atomico DB: apertura cursore su ADCFRT10 """
        # OPEN-CURT10 + FETCH-CURT10: ESTRAZIONE DEGLI ARTICOLI DI RUOLO SU ADCFRT10
        query_t10 = (
            self.engine.dataset("ADCFRT10")
            .select("gestione", "codiceAtto", "progArticolo", "numIdDecre", "codTributoCnc", "codCausale",
                    "codPeriodo", "codNaturaTrb", "numRata", "numAccreditamento", "codRata", "impTributo",
                    "flgResiduo", "codAggio", "impAggioAnt", "impAggioTot", "impArrotondamento", "codSsn",
                    "dataFineInf", "impInteressi", "tasso", "meseInizioPeriodo", "meseFinePeriodo",
                    "annoConsolidamento", "numTotRate", "descrizioneArticolo", "impTributoCalc", "dataFineCalc",
                    "progCarico", "impTributoCarico", "flgEuroCarico", "codPagamento", "flgEuroPag", "dataPagamento",
                    "dataRegistrazionePag", "dataDecadenza", "impTributoPagato", "impAggioPagato", "impAggioRimborso",
                    "impAgcPagato", "impMoraPagata", "annoFlusso", "numFlusso", "codEsattoria", "numQuietanza",
                    "dataQuietanza", "dataRiversamento", "statoArticolo", "tipoAggio", "codFasAmm", "statoGiudizio",
                    "gradoGiudizio", "dataStatoGiudizio", "tipoRecupero", "impOrigModificato", "codSituazione",
                    "dataRifConsolidamento", "impCapitale", "dataPredoc", "descrizioneArticoloBi", "numRateDilazione",
                    "vetusta", "timestampIns", "timestampUpd", "impContributoDovuto", "impContributoVersato", "impAggio"
                    )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .with_uncommitted_read()
            .compile_select()
        )
        try:
            return [raw for chunk in self.engine.cursor_stream(query_t10, buffer_size=500, depth=depth)
                    for raw in chunk]

        except Exception as err:
            BatchLogger.error("DB-FETCH-CURT10-ERR",
                              f"Errore DB durante apertura cursore su ADCFRT10: {err}", depth=depth)
            raise

    def _aggiorna_t10(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCFRT10 impostando lo stato a '0Q'."""
        righe_impattate = self._db_update_t10(ctx, depth=depth)
        BatchLogger.info("UPD-STATO-T10", f"UPDATE ADCFRT10 -> Stato Articolo='0Q' (Righe impattate: {righe_impattate})", depth=depth,
                     is_last=is_last)


    def _db_update_t10(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento massivo di fine ciclo a StatoArticolo='0Q'."""
        upd_t10 = (
            self.engine.dataset("ADCFRT10")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "statoArticolo": "0Q",
                "timestampUpd": datetime.now()
            })
        )
        try:
            return self.engine.execute_mutation(upd_t10, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T10-FINE-ERR",
            f"Errore DB durante UPDATE ADCFRT10 a '0Q' "
                 f"[CGES={ctx.ws_cges} | CATT={ctx.catt} ]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

    def _aggiorna_t21(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV21"""
        righe_impattate = self._db_update_t21(ctx, depth=depth)
        BatchLogger.info("UPD-AVV21", f"UPDATE ADCAVV21 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} "
                                      f"(Righe impattate: {righe_impattate})", depth=depth)

    def _db_update_t21(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento codice avviso e idAvviso."""
        upd_t21 = (
            self.engine.dataset("ADCAVV21")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )
        try:
            return self.engine.execute_mutation(upd_t21, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T21-FINE-ERR",
            f"Errore DB durante UPDATE ADCAVV21"
                 f"[CGES={ctx.ws_cges} | CATT={ctx.catt} ]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

    def _aggiorna_t23(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV23"""
        righe_impattate = self._db_update_t23(ctx, depth=depth)
        BatchLogger.info("UPD-AVV23", f"UPDATE ADCAVV23 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _db_update_t23(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento codice avviso e idAvviso."""
        upd_t23 = (
            self.engine.dataset("ADCAVV23")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )
        try:
            return self.engine.execute_mutation(upd_t23, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T23-FINE-ERR",
            f"Errore DB durante UPDATE ADCAVV23"
                 f"[CGES={ctx.ws_cges} | CATT={ctx.catt} ]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

    def _aggiorna_t24(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV24"""
        righe_impattate = self._db_update_t24(ctx, depth=depth)
        BatchLogger.info("UPD-AVV24", f"UPDATE ADCAVV24 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _db_update_t24(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento codice avviso e idAvviso."""
        upd_t24 = (
            self.engine.dataset("ADCAVV24")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )
        try:
            return self.engine.execute_mutation(upd_t24, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T24-FINE-ERR",
            f"Errore DB durante UPDATE ADCAVV24"
                 f"[CGES={ctx.ws_cges} | CATT={ctx.catt} ]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise

    def _aggiorna_avv33(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV33"""
        righe_impattate = self._db_update_t33(ctx, depth=depth)
        BatchLogger.info("UPD-AVV33", f"UPDATE ADCAVV33 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _db_update_t33(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> int:
        """Accesso atomico DB: aggiornamento codice avviso e idAvviso."""
        if ctx.ws_cges == "D":
            codTrib = ctx.dfal.strftime("%Y%m%d") if ctx.dfal else ""

        upd_t33 = (
            self.engine.dataset("ADCAVV33")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
                "codiceTribunale": codTrib
            })
        )
        try:
            return self.engine.execute_mutation(upd_t33, depth=depth)
        except Exception as err:
            BatchLogger.error(
            "DB-UPD-T33-FINE-ERR",
            f"Errore DB durante UPDATE ADCAVV33"
                 f"[CGES={ctx.ws_cges} | CATT={ctx.catt} ]: {err}",
                 depth=depth, is_last=True)
            ctx.indic_errore = "X"
            raise


class ElaborazioneCicloCurt10Step:
    """CICLO ELABORAZIONE CURT10 PER ELABORAZIONE
    DEGLI ARTICOLI RELATIVI ALLE PARTITE CHE CONFLUISCONO IN UN AVVISO
    """

    def __init__(self, engine):
        self.engine = engine
        self.record_avv14={}

    def execute(self, ctx: PreparazionePostalizzazioneContext, rowt10, depth: int = 1, is_last_int: bool = False) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione articoli su ADCFRT10", depth=depth)
        try:
            self._valorizza_inserisci_t14(ctx, rowt10, depth=depth+1)
        except Exception as err:
            BatchLogger.error(
                "CICLO-T10-ERR",
                f"Errore critico durante elaborazione su ADCFRT10: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise

    def _valorizza_inserisci_t14(self, ctx: PreparazionePostalizzazioneContext, rowt10, is_last: bool = False,
                                 depth: int = 2) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV14", "Valorizzazione dati ADCAVV14", depth=depth)
        try:
            codiceTributo = self._select_avv09(ctx, depth=depth+1)

            sart= str(rowt10.get("descrizioneArticolo") or "")
            sartbi = str(rowt10.get("descrizioneArticoloBi") or "")

            if ctx.ws_cges in ('E', 'F'):
                tipoCredito = ""
                tipoCreditoTds = ""
                periodoRif = ""
                periodoRifTds = ""

                sanatoria = rowt10.get("impTributoPagato")
                codiceConto = rowt10.get("codEsattoria")
                codiceCausale = rowt10.get("numQuietanza")
                descrizioneArt = sart
                descrizioneArtTds = sartbi
            else:
                tipoCredito = sart[:52]

                sanatoria = 0
                codiceConto = 0
                codiceCausale = 0
                descrizioneArt = ""
                descrizioneArtTds = ""

                if ctx.ws_cges != 'D':
                    tipoCreditoTds = sartbi[:52]
                else:
                    tipoCreditoTds = (sartbi[0:35].ljust(35) + "vom" + sartbi[39:52])

                periodoRif = str(rowt10.get("descrizioneArticolo"))[52:75]
                periodoRifTds = str(rowt10.get("descrizioneArticoloBi"))[52:75]

            # Mappatura esclusiva sui nomi logici definiti in ADCAVV22.json
            self.record_avv14 = {
                "codiceAvviso": ctx.ws_codavv,
                "identificativoAvviso": ctx.idAvviso,
                "progPartita": ctx.nesp,
                "progArticolo" : rowt10.get("progCarico"),
                "codiceTributo" : codiceTributo,
                "tipoCredito" : tipoCredito,
                "tipoCreditoTedesco" : tipoCreditoTds,
                "periodoRif" : periodoRif,
                "periodoRifTedesco" : periodoRifTds,
                "importoDovuto" : rowt10.get("impContributoDovuto"),
                "importoVersato" : rowt10.get("impContributoVersato"),
                "importoRichiesto" : rowt10.get("impTributo"),
                "impAggio" : rowt10.get("impAggio"),
                "sanatoria" : sanatoria ,
                "codiceConto" : codiceConto,
                "codiceCausale" : codiceCausale,
                "descrizioneArt" : descrizioneArt,
                "descrizioneArtTedesco" : descrizioneArtTds
            }

            BatchLogger.info(
                "INSERT-T14",
                f"Inserimento articolo in ADCAVV14 (Codice avviso: {ctx.ws_codavv})",
                depth=depth
            )

            ins_tavv14 = self.engine.dataset("ADCAVV14").compile_insert(self.record_avv14)

            try:
                righe = self.engine.execute_mutation(ins_tavv14, depth=depth+1)
                BatchLogger.debug(
                    "INSERISCI-ADCAVV14",
                    f"Articolo inserito per avviso {ctx.ws_codavv} (Righe: {righe})",
                    depth=depth
                )
            except:
                ctx.indic_errore = "X"
                BatchLogger.error(
                    "INSERT-ADCAVV14",
                    f"Fallito inserimento articolo in ADCAVV14 (Codice avviso: {ctx.ws_codavv})",
                    depth=2, is_last=True
                )
                raise
        except Exception as err:
            BatchLogger.error(
                "AVV14-ERR",
                f"Errore critico su ADCAVV14: {err}",
                depth=depth+1
            )
            ctx.indic_errore = "X"
            raise

    def _select_avv09(self, ctx, depth) -> str:
        BatchLogger.info("SELECT-ADCAVV09", "Estrazione decodifica codice tributo su ADCAVV09", depth=depth+1)
        t09_map = self.engine.get_table_map("ADCAVV09")

        query = (
            self.engine.dataset("ADCAVV09")
            .select("codiceTributo", "descrizioneTributo", "descrizioneTributoTedesco")
            .filter_by("codiceTributo", "=", ctx.codiceTributo)
            .limit(1)
            .compile_select()
        )
        try:
            rows_t09 = self.engine.fetch(query, depth=depth)

            if not rows_t09:
                BatchLogger.error("SELECT-ADCAVV09", f"Codice tributo non censito su ADCAVV09", depth=depth, is_last=True)
                ctx.indic_errore = "X"
                raise

            return self.engine.get_table_map("ADCAVV09").normalize(rows_t09[0]).get("codiceTributo")

        except Exception as err:
            BatchLogger.error(
                "SELECT-AVV09-ERR",
                f"Errore DB durante la SELECT su ADCAVV09.: {err}",
                depth=depth
            )
            raise




