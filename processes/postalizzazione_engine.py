# processes/postalizzazione_engine.py
import sys
import os
from datetime import date, datetime
from core.base_process import BaseProcessModel


class PostalizzazioneEngineProcessor(BaseProcessModel):
    """
    Reingegnerizzazione del programma COBOL PDCPOAVV.
    Modulo applicativo Enterprise dedicato al ciclo di controllo e avanzamento stato
    per la formazione e postalizzazione.

    Vengono elaborati tutti gli avvisi di addebito formati con conseguente
    scrittura sulle tabelle condivise con il gruppo di postalizzazione.

    Incapsula l'elaborazione dei paragrafi:
      - OPERAZIONI-INIZIALI
      - CNTR-STATO-FORMAZIONE
      - UPD-STATO-INI-FORM
      - ACCEDI-PILOTA (predisposizione strutturale)
    """

    def __init__(self):
        super().__init__(process_name="Postalizzazione_Formazione_Engine")
        # Registri di memoria dedicati (Working-Storage COBOL)
        self.ws_dcon = None
        self.ws_diniinf = None
        self.ws_dfininf = None
        self.ws_dinifor = None
        self.ws_dfinfor = None
        self.ws_fstfor = None

    def _execute_business_logic(self):
        """Esecuzione sequenziale della logica di business derivata dal sorgente Host."""
        print("======================================================================")
        print(f"   AVVIO TASK: {self.process_name}")
        print(f"   Provider Rete Attivo: {self.provider.upper()}")
        print("======================================================================")

        t18_map = self.get_table_map("stato_formazione")

        # ------------------------------------------------------------------
        # 1. PARAGRAFO: OPERAZIONI-INIZIALI & CURRENT DATE
        # Nel codice COBOL: EXEC SQL SET :WS-DATA-SQL = CURRENT DATE END-EXEC
        # ------------------------------------------------------------------
        current_system_date = date.today()
        print(f"   >> [INIT] Data di sistema rilevata: {current_system_date.isoformat()}")

        # ------------------------------------------------------------------
        # 2. PARAGRAFO: CNTR-STATO-FORMAZIONE
        # Condizioni COBOL:
        #   DINIFOR <= :WS-DATA-SQL AND DFINFOR >= :WS-DATA-SQL AND (FSTFOR = '3' OR FSTFOR = '9')
        # ------------------------------------------------------------------
        print("   >> [CNTR-STATO-FORMAZIONE] Controllo finestre temporali e stato lavorazione...")

        query_builder = (
            self.dataset("stato_formazione")
            .select("dcon", "diniinf", "dfininf", "dinifor", "dfinfor", "fstfor", "tmsini", "tmsfin")
            .filter_by("dinifor", "<=", current_system_date)
            .filter_by("dfinfor", ">=", current_system_date)
            .filter_by("fstfor", "IN", ("3", "9"))
            .with_uncommitted_read()
            .limit(1)
        )

        raw_results = self.fetch(query_builder.compile_select())

        # Gestione del codice di ritorno SQL (SQLCODE <> 0 / SQL-KEY-NON-TROVATA)
        if not raw_results:
            print("\n   **********************************")
            print("   *          SEGNALAZIONE          *")
            print("   * ------------------------------ *")
            print("   *POSTALIZZAZIONE NON CONSENTITA  *")
            print("   **********************************\n")
            raise RuntimeError(
                f"[COBOL_EXCEPTION] Condizione bloccante: nessun record valido in stato '3' o '9' "
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
        # Aggiorna FSTFOR = '9' e TMSFIN = CURRENT TIMESTAMP
        # ------------------------------------------------------------------
        print("   >> [UPD-STATO-INI-FORM] Avanzamento stato a '9' e marcatura timestamp chiusura...")

        current_timestamp = datetime.now()
        update_query = (
            self.dataset("stato_formazione")
            .filter_by("dcon", "=", self.ws_dcon)
            .filter_by("diniinf", "=", self.ws_diniinf)
            .compile_update({
                "fstfor": "9",
                "tmsfin": current_timestamp
            })
        )

        righe_modificate = self.execute_mutation(update_query)
        print(f"   >> [UPD-STATO-INI-FORM] Record aggiornati con successo: {righe_modificate}")

        # ------------------------------------------------------------------
        # 4. PARAGRAFO: ACCEDI-PILOTA
        # ------------------------------------------------------------------
        self._accedi_pilota()

    def _accedi_pilota(self):
        """
        Gancio logico per l'elaborazione della tabella pilota.
        Riceve in input la chiave di consolidamento (DCON) estratta dalla tabella T18.
        """
        print(f"   >> [ACCEDI-PILOTA] Inizializzazione controllo tabella pilota per DCON={self.ws_dcon}...")
        # Predisposto per l'inserimento/verifica della tabella pilota


if __name__ == "__main__":
    os.environ["EXTERNAL_DB_CONFIG_PATH"] = r"C:\Users\mmuzi\config\app_db_config.json"
    worker = PostalizzazioneEngineProcessor()
    worker.run()