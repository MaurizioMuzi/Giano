# processes/preparazione_postalizzazione/step_valorizza_inserisci_t13.py
from typing import List, Any

from .context import PreparazionePostalizzazioneContext
import descrizioni_config as C
from .step_descrizioni_partite import Descrizioni, crea_lingue
from core.batch_logger import BatchLogger

class DettaglioValorizzaT13:

    def __init__(self, engine):
        self.engine = engine
        self.descrizioni = Descrizioni(engine)
        self.record_avv13 = {}


    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 1) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV13",
                             "Valorizzazione dati per l'inserimento nella tabella dettaglio addebiti (ADCAVV13)",
                             depth=depth)
        try:
            if ((ctx.ws_cges == "1" and ctx.tipoavv == "V")
                    or (ctx.ws_cges == "D")):
                # estrazione valori per le descrizioni SPAR1 e SPAR2
                self._cerca_spar_vig(ctx, depth=depth+1)

            ctx.it.reset(); ctx.tds.reset()

            if (ctx.catt == ctx.idAvviso
                and ctx.ws_cges == "N"):
            # Rif COBOL: PERFORM VALO-DESPAR-SPS-TDS E VALO-DESPAR-SPS-IT

                if ctx.cesa == 21:
                    # VALO-DESPAR-SPS-TDS / VALO-DESPAR-SPS-IT: spese di notifica
                    if int(ctx.cesa or 0) == 21:
                        ctx.tds.s1.move(C.K1_SPSTD)
                        ctx.tds.s2.move(ctx.sattbi)
                        ctx.tds.chiudi()
                    ctx.it.s1.move(C.K1_SPSIT)
                    ctx.it.s2.move(ctx.satt)
                    ctx.it.chiudi()
            else:
                self.descrizioni.valorizza(ctx, depth+1)

            if (ctx.tipoavv == "L"
                and ctx.cseg == "51" and ctx.ws_cges == " 1"):

                ctx.sreg_sanz = " "
                ctx.sreg_sanz_tds = " "
            else:
                self._select_adcavv05(ctx,depth+1)

            # Mappatura esclusiva sui nomi logici definiti in ADCAVV13.json
            self.record_avv13 = {
                    "codiceAvviso": ctx.ws_codavv,
                    "identificativoAvviso": ctx.idAvviso,
                    "progPartita": ctx.nesp,
                    "descrizione1": ctx.it.out1,
                    "descrizione2": ctx.it.out2,
                    "descrizioneTedesco1": ctx.tds.out1,
                    "descrizioneTedesco2": ctx.tds.out2,
                    "descrizioneSanzioni": ctx.sreg_sanz,
                    "descrizioneSanzioniTedesco": ctx.sreg_sanz_tds,
                }

            BatchLogger.info(
                    "INSERT-T13",
                    f"Inserimento record in ADCAVV13 (Codice avviso: {ctx.ws_codavv} e Progressivo partita: {ctx.nesp})",
                    depth=depth
                )

            ins_tavv13 = self.engine.dataset("ADCAVV13").compile_insert(self.record_avv13)

            try:
                righe = self.engine.execute_mutation(ins_tavv13, depth=depth+1)
                BatchLogger.debug(
                        "INSERISCI-ADCAVV13",
                        f"Inserito record per avviso {ctx.ws_codavv} (Righe: {righe})",
                        depth=depth+1
                )
            except:
                ctx.indic_errore = "X"
                BatchLogger.error(
                        "INSERT-ADCAVV13",
                        f"Fallito inserimento record in ADCAVV13 (Codice avviso: {ctx.ws_codavv})",
                        depth=depth+1, is_last=True
                )
                raise
        except:
            BatchLogger.error(
                "VALORIZZAZIONE-ADCAVV13",
                f"Errore critico durante valorizzazione di ADCAVV13)",
                depth=depth, is_last=True
            )
            raise

    def _cerca_spar_vig(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        BatchLogger.info("SELECT-ADCAVV33", "Estrazione delle descrizioni partite su ADCAVV33", depth=depth)
        t33_map = self.engine.get_table_map("ADCAVV33")

        try:
            rows_t33 = self._db_fetch_t33(ctx, depth=depth)

            if not rows_t33:
                BatchLogger.error("SELECT-ADCAVV33", f"Descrizioni partite assenti.", depth=depth, is_last=True)

            row_t33 = t33_map.normalize(rows_t33[0])

            # ITALIANO
            ctx.desc_partita_1 = row_t33.get("descrizionePartita1")
            ctx.desc_partita_2 = row_t33.get("descrizionePartita2")

            # TEDESCO
            ctx.desc_partita_3 = row_t33.get("descrizionePartita3")
            ctx.desc_partita_4 = row_t33.get("descrizionePartita4")

        except Exception as err:
            BatchLogger.error(
                "SELECT-AVV33-ERR",
                f"Errore durante l'estrazione delle descrizioni.': {err}",
                depth=depth
            )
            raise


    def _select_adcavv05(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        # Estrazione decodifica regime sanzionatorio da ADCAVV05
        BatchLogger.info("SELECT-ADCAVV05", "Estrazione decodifica regime sanzionatorio su ADCAVV05", depth=depth)
        t05_map = self.engine.get_table_map("ADCAVV05")
        try:

            rows_t05 = self._db_fetch_t05(ctx, depth=depth)

            if not rows_t05:
                BatchLogger.error("SELECT-ADCAVV05", f"Regime sanzionatorio assente", depth=depth, is_last=True)

            row_t05 = t05_map.normalize(rows_t05[0])
            ctx.sreg_sanz = row_t05.get("regimeSanz")
            ctx.sreg_sanz_tds = row_t05.get("regimeSanz_Tds")

        except Exception as err:
            BatchLogger.error(
                "SELECT-ADCAVV05-ERR",
                f"Errore durante decodifica regime sanzionatorio.': {err}",
                depth=depth
            )
            raise


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_t33(self, ctx:PreparazionePostalizzazioneContext, depth: int) -> List[Any]:
        """Accesso atomico DB: recupera le descrizioni da ADCAVV33"""
        query_t33 = (
                self.engine.dataset("ADCAVV33")
                .select("codiceTribunale", "descrizionePartita1", "descrizionePartita2",
                        "descrizionePartita3", "descrizionePartita4")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.catt)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
        try:
            return self.engine.fetch(query_t33, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-T33-ERR",
                f"Errore DB durante la SELECT su ADCAVV33 [CGES={ctx.ws_cges}, CATT={ctx.catt}]: {err}",
                depth=depth
            )
            raise

    def _db_fetch_t05(self, ctx:PreparazionePostalizzazioneContext, depth: int) -> List[Any]:
        """Accesso atomico DB: decodifica regime sanzionario"""
        query_t05 = (
            self.engine.dataset("ADCAVV05")
            .select("flgSanzioni", "regimeSanz", "regimeSanz_Tds")
            .filter_by("flgSanzioni", "=", ctx.flagSanzioni)
            .limit(1)
            .compile_select()
        )
        try:
            return self.engine.fetch(query_t05, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-T05-ERR",
                f"Errore DB durante la SELECT su ADCAVV05.: {err}",
                depth=depth
            )
            raise