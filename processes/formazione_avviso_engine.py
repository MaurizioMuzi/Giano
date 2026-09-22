# processes/formazione_avviso_engine.py
import sys
import os
from datetime import date, datetime
from core.base_process import BaseProcessModel


class FormazioneAvvisoEngineProcessor(BaseProcessModel):
    """
    Reingegnerizzazione del programma COBOL PDCFOAVV.
    Modulo applicativo Enterprise dedicato al ciclo per iscrizione crediti a ruolo.

    Incapsula l'elaborazione dei paragrafi:
      - OPERAZIONI-INIZIALI
            - CNTR-STATO-FORMAZIONE
            - UPD-STATO-INI-FORM
      - GESTIONE-RIPARTENZE
            - CONTA-SEDI
            - CONTA-LAVORI
            - AGGIORNA-LAVORI
      - ELABORAZIONE (Apertura e scorrimento CURJOI-1 fino a prima di CICLO-CURJOI-2A)
      - ACCEDI-PILOTA (predisposizione strutturale)
    """

    def __init__(self):
        super().__init__(process_name="Formazione_Avviso_Engine")
        # Registri di memoria dedicati (Working-Storage COBOL)
        self.ws_dcon = None
        self.ws_diniinf = None
        self.ws_dfininf = None
        self.ws_dinifor = None
        self.ws_dfinfor = None
        self.ws_fstfor = None
        self.ws_count_sed = 0
        self.ws_count = 0

        # Registri cursore CURJOI-1 (ADCTET17)
        self.current_sede = None
        self.current_zona = None
        self.current_cod_centro = None
        self.current_cod_servizio = None

    def _execute_business_logic(self):
        """Esecuzione sequenziale della logica di business derivata dal sorgente Host."""
        print("======================================================================")
        print(f"   AVVIO TASK: {self.process_name}")
        print(f"   Provider Rete Attivo: {self.provider.upper()}")
        print("======================================================================")

        t18_map = self.get_table_map("ADCFRT18")

        # ------------------------------------------------------------------
        # 1. PARAGRAFO: OPERAZIONI-INIZIALI & CURRENT DATE
        # Nel codice COBOL: EXEC SQL SET :WS-DATA-SQL = CURRENT DATE END-EXEC
        # ------------------------------------------------------------------
        current_system_date = date.today()
        print(f"   >> [INIT] Data di sistema rilevata: {current_system_date.isoformat()}")

        # ------------------------------------------------------------------
        # 2. PARAGRAFO: CNTR-STATO-FORMAZIONE
        # Condizioni COBOL:
        #   DINIFOR <= :WS-DATA-SQL AND DFINFOR >= '2026-08-24' AND FSTFOR <> '2'
        # ------------------------------------------------------------------
        print("   >> [CNTR-STATO-FORMAZIONE] Controllo finestre temporali e stato lavorazione...")

        fixed_dfinfor_date = date(2026, 8, 24)

        query_builder = (
            self.dataset("ADCFRT18")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", fixed_dfinfor_date)
            .filter_by("fstfor", "<>", "2")
            .with_uncommitted_read()
            .limit(1)
        )

        raw_results = self.fetch(query_builder.compile_select())

        # Gestione del codice di ritorno SQL (SQLCODE <> 0 / SQL-KEY-NON-TROVATA)
        if not raw_results:
            print("\n   **********************************")
            print("   *          SEGNALAZIONE          *")
            print("   * ------------------------------ *")
            print("   *FORMAZIONE NON CONSENTITA       *")
            print("   **********************************\n")
            raise RuntimeError(
                f"[COBOL_EXCEPTION] Condizione bloccante: nessun record valido in lavorazione "
                f"per la data contabile {current_system_date.isoformat()}."
            )

        # Normalizzazione e assegnazione dei valori ai registri interni
        normalized_row = t18_map.normalize(raw_results[0])
        self.ws_dcon = normalized_row.get("dcon")
        self.ws_diniinf = normalized_row.get("diniinf")
        self.ws_dfininf = normalized_row.get("dfininf")
        self.ws_dinifor = normalized_row.get("dinifor")
        self.ws_dfinfor = normalized_row.get("dfinfor")
        self.ws_fstfor = normalized_row.get("fstfor")

        print(f"   >> [CNTR-STATO-FORMAZIONE] Record intercettato con successo:")
        print(f"      - Data Consolidamento (DCON)    : {self.ws_dcon}")
        print(f"      - Inizio Infasamento (DINIINF)  : {self.ws_diniinf}")
        print(f"      - Inizio Formazione (DINIFOR)   : {self.ws_dinifor}")
        print(f"      - Fine Formazione (DFINFOR)     : {self.ws_dfinfor}")
        print(f"      - Stato Rilevato (FSTFOR)       : {self.ws_fstfor}")

        # ------------------------------------------------------------------
        # 3. PARAGRAFO: UPD-STATO-INI-FORM
        # Aggiorna FSTFOR = '1' (Formazione in corso) e TMSINI = CURRENT TIMESTAMP
        # ------------------------------------------------------------------
        print("   >> [UPD-STATO-INI-FORM] Avanzamento stato a '1' e marcatura timestamp avvio...")

        current_timestamp = datetime.now()
        update_query = (
            self.dataset("ADCFRT18")
            .filter_by("dcon", "=", self.ws_dcon)
            .filter_by("diniinf", "=", self.ws_diniinf)
            .compile_update({
                "fstfor": "1",
                "tmsini": current_timestamp
            })
        )

        righe_modificate = self.execute_mutation(update_query)
        print(f"   >> [UPD-STATO-INI-FORM] Record aggiornati con successo: {righe_modificate}")

        # ------------------------------------------------------------------
        # 4. PARAGRAFO: GESTIONE-RIPARTENZE
        # ------------------------------------------------------------------
        self._gestione_ripartenze()

        # ------------------------------------------------------------------
        # 5. PARAGRAFO: ELABORAZIONE (CURJOI-1)
        # ------------------------------------------------------------------
        self._elaborazione()

        # ------------------------------------------------------------------
        # 6. PARAGRAFO: ACCEDI-PILOTA
        # ------------------------------------------------------------------
        self._accedi_pilota()

    def _gestione_ripartenze(self):
        """
        Reingegnerizzazione dei paragrafi:
          - GESTIONE-RIPARTENZE
          - CONTA-SEDI
          - CONTA-LAVORI
          - AGGIORNA-LAVORI
        Opera sulla tabella ADCTET17 (ADCTET17).
        """
        print("\n   ------------------------------------------------------------------")
        print("   >> [GESTIONE-RIPARTENZE] Inizio verifica allineamento sedi/lavori...")
        print("   ------------------------------------------------------------------")

        # --- PARAGRAFO CONTA-SEDI ---
        # SELECT COUNT(*) FROM ADCTET17 WITH UR
        query_count_sedi = (
            self.dataset("ADCTET17")
            .count()
            .with_uncommitted_read()
            .compile_select()
        )
        res_sedi = self.fetch(query_count_sedi)
        self.ws_count_sed = int(list(res_sedi[0].values())[0]) if res_sedi else 0
        print(f"   >> [CONTA-SEDI] Totale sedi censite (WS-COUNT-SED): {self.ws_count_sed}")

        # --- PARAGRAFO CONTA-LAVORI ---
        # SELECT COUNT(*) FROM ADCTET17 WHERE CDAS IN ('IF', 'AV') WITH UR
        query_count_lavori = (
            self.dataset("ADCTET17")
            .count()
            .filter_by("codServizio", "IN", ("IF", "AV"))
            .with_uncommitted_read()
            .compile_select()
        )
        res_lavori = self.fetch(query_count_lavori)
        self.ws_count = int(list(res_lavori[0].values())[0]) if res_lavori else 0
        print(f"   >> [CONTA-LAVORI] Totale lavori qualificati (WS-COUNT): {self.ws_count}")

        # --- CONTROLLO ED EVENTUALE AGGIORNA-LAVORI ---
        if self.ws_count == self.ws_count_sed and self.ws_count_sed > 0:
            print("   >> [GESTIONE-RIPARTENZE] Condizione verificata (WS-COUNT = WS-COUNT-SED). Esecuzione AGGIORNA-LAVORI...")
            self._aggiorna_lavori()
        else:
            print("   >> [GESTIONE-RIPARTENZE] LAVORI NON AGGIORNATI (WS-COUNT <> WS-COUNT-SED)")

    def _aggiorna_lavori(self):
        """
        Reingegnerizzazione del paragrafo AGGIORNA-LAVORI:
        UPDATE ADCTET17 SET CDAS = 'AV', HTMSLAV = '0001-01-01-00.00.00.000000'
        """
        # Timestamp COBOL di azzeramento convenzionale '0001-01-01-00.00.00.000000'
        reset_timestamp = datetime(1, 1, 1, 0, 0, 0)

        update_lavori_query = (
            self.dataset("ADCTET17")
            .compile_update({
                "codServizio": "AV",
                "timestamp": reset_timestamp
            })
        )

        righe_aggiornate = self.execute_mutation(update_lavori_query)
        print(f"   >> [AGGIORNA-LAVORI] Aggiornamento massivo completato. Righe impattate: {righe_aggiornate}")

    def _elaborazione(self):
        """
        Reingegnerizzazione del paragrafo ELABORAZIONE e scorrimento cursore CURJOI-1:
        DECLARE CURJOI-1 CURSOR FOR
          SELECT DISTINCT CSED, CZON, CCOP, CDAS
            FROM ADCTET17
           WHERE CDAS = 'AV'
             AND HTMSLAV = :WS-TMS-DEFAULT
             AND DPRE <= CURRENT DATE
           ORDER BY CSED, CZON, CCOP
          WITH UR FOR FETCH ONLY
        """
        print("\n   ------------------------------------------------------------------")
        print("   >> [ELABORAZIONE] Apertura cursore CURJOI-1 ed elaborazione sedi...")
        print("   ------------------------------------------------------------------")

        t17_map = self.get_table_map("ADCTET17")
        ws_tms_default = datetime(1, 1, 1, 0, 0, 0)
        current_system_date = date.today()

        query_curjoi_1 = (
            self.dataset("ADCTET17")
            .distinct()
            .select("sede", "zona", "codCentro", "codServizio")
            .filter_by("codServizio", "=", "AV")
            .filter_by("timestamp", "=", ws_tms_default)
            .filter_by("dataPre", "<=", current_system_date)
            .order_by("sede", "zona", "codCentro")
            .with_uncommitted_read()
            .compile_select()
        )

        record_totali = 0

        # Scansione sequenziale bufferizzata del cursore CURJOI-1
        for chunk in self.cursor_stream(query_curjoi_1, buffer_size=500):
            for raw_row in chunk:
                record_totali += 1
                row = t17_map.normalize(raw_row)

                # MOVE CSED/CZON/CCOP OF CDCTET17 TO CDCFRT01
                self.current_sede = row.get("sede")
                self.current_zona = row.get("zona")
                self.current_cod_centro = row.get("codCentro")
                self.current_cod_servizio = row.get("codServizio")

                print(
                    f"   >> [CURJOI-1] Sede in elaborazione: "
                    f"SEDE={self.current_sede}, ZONA={self.current_zona}, CENTRO={self.current_cod_centro}"
                )

                # ==================================================================
                # PUNTO DI ARRESTO: Qui subentrerà il ciclo sul secondo cursore
                # PERFORM UNTIL FINE-CURJOI-2A OR ERRORE
                #   PERFORM CICLO-CURJOI-2A THRU CICLO-CURJOI-2A-EX
                # ==================================================================

        if record_totali == 0:
            print("   >> [CURJOI-1] Nessun record trovato in ADCTET17 conforme ai criteri di lavorazione.")

    def _accedi_pilota(self):
        """
        Gancio logico per l'elaborazione della tabella pilota.
        Riceve in input la chiave di consolidamento (DCON) estratta dalla tabella T18.
        """
        print(f"\n   >> [ACCEDI-PILOTA] Inizializzazione controllo tabella pilota per DCON={self.ws_dcon}...")


if __name__ == "__main__":
    os.environ["EXTERNAL_DB_CONFIG_PATH"] = r"C:\Users\maurizio.muzi\config\app_db_config.json"
    worker = FormazioneAvvisoEngineProcessor()
    worker.run()