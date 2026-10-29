# processes/preparazione_postalizzazione/step_curt_14.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .context import PreparazionePostalizzazioneContext
from core.batch_logger import BatchLogger

class DettaglioCurt14:
    """
    Reingegnerizzazione del paragrafo OPEN-CURT14, CICLO-CURT14:
    CICLO DI ELABORAZIONE CURSORE SU ADCFRT14 PER L'ESTRAZIONE
    DELLE OCCORRENZE CON CANA = 'IP' + INSERIMENTO SU ADCAVV22
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_ciclo_curt14 = ElaborazioneCicloCurt14Step(engine)

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, rowt01, depth: int) -> None:

        ctx.ws_nespcf = 0

        # OPEN-CURT14 + FETCH-CURT14: ESTRAZIONE DEGLI INTESTATARI SU ADCFRT14
        t14ip_map = self.engine.get_table_map("ADCFRT14")

        query_t14_ip = (
            self.engine.dataset("ADCFRT14")
            .select("gestione", "codiceAtto", "partitaIva", "codiceFiscale", "cognome",
                    "nome", "sesso", "dataNascita", "comuneNascita", "provinciaNascita", "indirizzo",
                    "numeroCivico", "letteraCivico", "numeroChilometro", "cap","localita", "siglaProvincia",
                    "comuneDomicilio", "indAnagrafeTrib", "capAnagrafeTrib", "siglaProvAnagrafeTrib", "locAnagrafeTrib"
                    "comuneAnagrafeTrib", "dataValidDoc", "pec"
                    )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .filter_by("codiceAnag", "=", "IP")
            .compile_select()
        )
        rows_t14ip = []

        for chunk in self.engine.cursor_stream(query_t14_ip, buffer_size=500, depth=depth):
            for raw_row in chunk:
                rows_t14ip.append(t14ip_map.normalize(raw_row))

        if not rows_t14ip:
            BatchLogger.error("SELECT-ADCFRT14",
                              f"Nessun intestatario trovato su ADCFRT14 con CANA = 'IP' e CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                              depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

        tot_int_ip = len(rows_t14ip)
        ctx.totale_record_curt14 = tot_int_ip

        # PERFORM UNTIL FINE-CURT14
        for idx, row_ip in enumerate(rows_t14ip, start=1):
            is_last_int = (idx == tot_int_ip)

            BatchLogger.info(
                "INTESTATARI-IP",
                f"[{idx}/{tot_int_ip}]",
                depth=depth+1,
                is_last=False
            )

            self.step_ciclo_curt14.execute(
                ctx=ctx,
                row=row_ip,
                depth=depth + 1,
                is_last_int=is_last_int)  # PERFORM CICLO-CURT14

class ElaborazioneCicloCurt14Step:
    """CICLO ELABORAZIONE CURT14 PER ELABORAZIONE INTESTATARI DELL'AVVISO PENSIONI"""

    def __init__(self, engine):
        self.engine = engine
        self.record_avv22={}

    def execute(self, ctx: PreparazionePostalizzazioneContext, row, depth: int = 1, is_last_int: bool = False) -> None:
        BatchLogger.info("ELABORAZIONE", "Avvio elaborazione intestatari dell'avviso pensioni", depth=0)
        self._valorizza_inserisci_t22(ctx, row, depth=depth+1)

    def _valorizza_inserisci_t22(self, ctx: PreparazionePostalizzazioneContext, row, is_last: bool = False,
                                 depth: int = 2) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV22", "Valorizzazione dati ADCAVV22 prima di procedere con l'inserimento", depth=depth)
        current_system_date = date.today()

        # Mappatura esclusiva sui nomi logici definiti in ADCAVV22.json
        self.record_avv22 = {
            "gestione": ctx.ws_cges,
            "codiceAtti" : ctx.catt,
            "progEsposizioneCF" : ctx.ws_nespcf,
            "cognome" : row.get("cognome"),
            "nome" : row.get("nome"),
            "codiceFiscale" : row.get("codiceFiscale"),
            "identificativoAvviso" : ctx.idAvviso,
            "codiceAvviso": ctx.ws_codavv,
            "timestampInserimento" : current_system_date
        }

        BatchLogger.info(
            "INSERT-T22",
            f"Inserimento intestatario in ADCAVV22 (Codice avviso: {ctx.ws_codavv} e Codice Fiscale: {row.get('codiceFiscale')})",
            depth=depth
        )

        ins_tavv22 = self.engine.dataset("ADCAVV22").compile_insert(self.record_avv22)

        try:
            righe = self.engine.execute_mutation(ins_tavv22, depth=depth)
            BatchLogger.debug(
                "INSERISCI-ADCAVV22",
                f"Codice fiscale (CF: {row.get('codiceFiscale')}) inserito per avviso {ctx.ws_codavv} (Righe: {righe})",
                depth=depth
            )
        except:
            ctx.indic_errore = "X"
            BatchLogger.error(
                "INSERT-ADCAVV22",
                f"Fallito inserimento intestatario in ADCAVV22 (Codice avviso: {ctx.ws_codavv})",
                depth=2, is_last=True
            )
            raise

