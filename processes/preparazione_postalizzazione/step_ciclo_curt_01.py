# processes/preparazione_postalizzazione/step_ciclo_curt_01.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, rowt01, depth: int) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione intestatari dell'avviso pensioni", depth=0)

        self.step_valorizza_inserisci_t13.execute_dettaglio(ctx, rowt01, depth=depth+1)
        # OPEN-CURT10 + FETCH-CURT10: ESTRAZIONE DEGLI ARTICOLI SU ADCFRT10
        t10_map = self.engine.get_table_map("ADCFRT10")

        query_t10 = (
            self.engine.dataset("ADCFRT10")
            .select("gestione", "codiceAtto", "progArticolo", "numIdDecre", "codTributoCnc", "codCausale",
                    "codPeriodo", "codNaturaTrb", "numRata", "numAccreditamento", "codRata", "impTributo",
                    "flgResiduo", "codAggio", "impAggioAnt", "impAggioTot", "impArrotondamento", "codSsn",
                    "dataFineInf", "impInteressi", "tasso", "meseInizioPeriodo", "meseFinePeriodo", "annoConsolidamento",
                    "numTotRate", "descrizioneArticolo", "impTributoCalc", "dataFineCalc", "progCarico", "impTributoCarico",
                    "flgEuroCarico", "codPagamento", "flgEuroPag", "dataPagamento", "dataRegistrazionePag", "dataDecadenza",
                    "impTributoPagato", "impAggioPagato", "impAggioRimborso", "impAgcPagato", "impMoraPagata", "annoFlusso",
                    "numFlusso", "codEsattoria", "numQuietanza", "dataQuietanza", "dataRiversamento", "statoArticolo", "tipoAggio",
                    "codFasAmm", "statoGiudizio", "gradoGiudizio", "dataStatoGiudizio", "tipoRecupero", "impOrigModificato",
                    "codSituazione", "dataRifConsolidamento", "impCapitale", "dataPredoc", "descrizioneArticoloBi", "numRateDilazione",
                    "vetusta", "timestampIns", "timestampUpd", "impContributoDovuto", "impContributoVersato", "impAggio"
                    )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .with_uncommitted_read()
            .compile_select()
        )
        rows_t10 = []

        for chunk in self.engine.cursor_stream(query_t10, buffer_size=500, depth=depth):
            for raw_row in chunk:
                rows_t10.append(t10_map.normalize(raw_row))

        if not rows_t10:
            BatchLogger.error("SELECT-ADCFRT10",
                              f"Nessun articolo trovato su ADCFRT10 con CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                              depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

        tot_art = len(rows_t10)

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
                row=row_t10,
                depth=depth + 1,
                is_last_int=is_last_int)  # PERFORM CICLO-CURT10

        # UPDATE-T10
        self._aggiorna_t10(ctx, is_last_int, depth)

        # UPDATE-T21
        self._aggiorna_t21(ctx, depth)

        # UPDATE-T23
        self._aggiorna_t23(ctx, depth)

        # UPDATE-T24
        self._aggiorna_t24(ctx, depth)

        # UPDATE-AVV33
        self._aggiorna_avv33(ctx, depth)

    def _aggiorna_t10(self, ctx: PreparazionePostalizzazioneContext, is_last: bool = False, depth: int = 2) -> None:
        """Aggiorna lo stato del record su ADCFRT10 impostando lo stato a '0Q'."""
        upd_t10 = (
            self.engine.dataset("ADCFRT10")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "statoArticolo": "0Q",
                "timestampUpd": datetime.now()
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_t10, depth=depth + 1)
        BatchLogger.info("UPD-STATO-T10", f"UPDATE ADCFRT10 -> Stato Articolo='0Q' (Righe impattate: {righe_impattate})", depth=depth,
                     is_last=is_last)

    def _aggiorna_t21(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV21"""
        upd_t21 = (
            self.engine.dataset("ADCAVV21")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_t21, depth=depth + 1)
        BatchLogger.info("UPD-AVV21", f"UPDATE ADCAVV21 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _aggiorna_t23(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV23"""
        upd_t23 = (
            self.engine.dataset("ADCAVV23")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_t23, depth=depth + 1)
        BatchLogger.info("UPD-AVV23", f"UPDATE ADCAVV23 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _aggiorna_t24(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV24"""
        upd_t24 = (
            self.engine.dataset("ADCAVV24")
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .compile_update({
                "identificativoAvviso": ctx.idAvviso,
                "codiceAvviso": ctx.ws_codavv,
            })
        )

        righe_impattate = self.engine.execute_mutation(upd_t24, depth=depth + 1)
        BatchLogger.info("UPD-AVV24", f"UPDATE ADCAVV24 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

    def _aggiorna_avv33(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        """Aggiorna IDAVV e CODAVV di ADCAVV33"""
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

        righe_impattate = self.engine.execute_mutation(upd_t33, depth=depth + 1)
        BatchLogger.info("UPD-AVV33", f"UPDATE ADCAVV33 -> IDAVV = {ctx.idAvviso} e CODAVV = {ctx.ws_codavv} (Righe impattate: {righe_impattate})", depth=depth)

class ElaborazioneCicloCurt10Step:
    """CICLO ELABORAZIONE CURT10 PER ELABORAZIONE
    DEGLI ARTICOLI RELATIVI ALLE PARTITE CHE CONFLUISCONO IN UN AVVISO
    """

    def __init__(self, engine):
        self.engine = engine
        self.record_avv14={}

    def execute(self, ctx: PreparazionePostalizzazioneContext, row, depth: int = 1, is_last_int: bool = False) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione articoli", depth=0)
        self._valorizza_inserisci_t14(ctx, row, depth=depth+1)

    def _valorizza_inserisci_t14(self, ctx: PreparazionePostalizzazioneContext, row, is_last: bool = False,
                                 depth: int = 2) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV14", "Valorizzazione dati ADCAVV14 prima di procedere con l'inserimento", depth=depth)

        codiceTributo = self._select_avv09(ctx, depth)

        sart= str(row.get("descrizioneArticolo") or "")
        sartbi = str(row.get("descrizioneArticoloBi") or "")

        if ctx.ws_cges in ('E', 'F'):
            tipoCredito = ""
            tipoCreditoTds = ""
            periodoRif = ""
            periodoRifTds = ""

            sanatoria = row.get("impTributoPagato")
            codiceConto = row.get("codEsattoria")
            codiceCausale = row.get("numQuietanza")
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

            periodoRif = str(row.get("descrizioneArticolo"))[52:75]
            periodoRifTds = str(row.get("descrizioneArticoloBi"))[52:75]



        # Mappatura esclusiva sui nomi logici definiti in ADCAVV22.json
        self.record_avv14 = {
            "codiceAvviso": ctx.ws_codavv,
            "identificativoAvviso": ctx.idAvviso,
            "progPartita": ctx.nesp,
            "progArticolo" : row.get("progCarico"),
            "codiceTributo" : codiceTributo,
            "tipoCredito" : tipoCredito,
            "tipoCreditoTedesco" : tipoCreditoTds,
            "periodoRif" : periodoRif,
            "periodoRifTedesco" : periodoRifTds,
            "importoDovuto" : row.get("impContributoDovuto"),
            "importoVersato" : row.get("impContributoVersato"),
            "importoRichiesto" : row.get("impTributo"),
            "impAggio" : row.get("impAggio"),
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
            righe = self.engine.execute_mutation(ins_tavv14, depth=depth)
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

    def _select_avv09(self, ctx, depth):
        BatchLogger.info("SELECT-ADCAVV09", "Estrazione decodifica codice tributo su ADCAVV09", depth=depth+1)
        t09_map = self.engine.get_table_map("ADCAVV09")

        query = (
            self.engine.dataset("ADCAVV09")
            .select("codiceTributo", "descrizioneTributo", "descrizioneTributoTedesco")
            .filter_by("codiceTributo", "=", ctx.codiceTributo)
            .limit(1)
            .compile_select()
        )
        rows_t09 = self.engine.fetch(query, depth=1)

        if not rows_t09:
            BatchLogger.error("SELECT-ADCAVV09", f"Codice tributo non censito su ADCAVV09", depth=1, is_last=True)
            ctx.indic_errore = "X"
            return None

        return self.engine.get_table_map("ADCAVV09").normalize(rows_t09[0]).get("codiceTributo")



