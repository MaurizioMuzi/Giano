import sys
from datetime import date, datetime
from core.base_process import BaseProcessModel
from core.query_builder import CompiledQuery


class FormazioneAvvisoEngineProcessor(BaseProcessModel):
    """
    Reingegnerizzazione del programma COBOL PDCFOAVV
    Modulo applicativo Enterprise dedicato al ciclo per iscrizione crediti a ruolo.

    Vengono definiti tutti gli avvisi di addebito per i crediti infasati presenti
    sulla tabella db2 ADCFRT01

    Incapsula l'elaborazione dei paragrafi:
      - OPERAZIONI-INIZIALI
      - CNTR-STATO-FORMAZIONE
      - UPD-STATO-INI-FORM
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

    def _execute_business_logic(self):
        """Esecuzione sequenziale della logica di business derivata dal sorgente Host."""
        print(f"\n======================================================================")
        print(f"   AVVIO TASK: {self.process_name}")
        print(f"======================================================================")

        # Risoluzione della tabella logica 'stato_formazione' (ADCFRT18 / StatoFormazione)
        t18_map = self.get_table_map("stato_formazione")

        # ------------------------------------------------------------------
        # 1. PARAGRAFO: OPERAZIONI-INIZIALI & CURRENT DATE
        # ------------------------------------------------------------------
        current_system_date = date.today()
        formatted_curr_date = self.dialect.format_value(current_system_date)
        print(f"   >> [INIT] Data di sistema rilevata: {formatted_curr_date}")

        # ------------------------------------------------------------------
        # 2. PARAGRAFO: CNTR-STATO-FORMAZIONE
        # ------------------------------------------------------------------
        print("   >> Controllo finestre temporali e stato lavorazione...")

        fields = [
            getattr(t18_map, "dcon"),
            getattr(t18_map, "diniinf"),
            getattr(t18_map, "dfininf"),
            getattr(t18_map, "dinifor"),
            getattr(t18_map, "dfinfor"),
            getattr(t18_map, "fstfor"),
            getattr(t18_map, "tmsini"),
            getattr(t18_map, "tmsfin")
        ]
        fields_clause = ", ".join(fields)

        # Costruzione del predicato conforme al COBOL:
        # DINIFOR <= CURRENT DATE
        # DFINFOR >= CURRENT DATE
        # FSTFOR = '2'
        where_condition = (
            f"{t18_map.dinifor} <= ? AND {t18_map.dfinfor} >= ? "
            f"AND {t18_map.fstfor} <> ?"
        )

        sql_select = f"SELECT {fields_clause} FROM {t18_map.name} WHERE {where_condition}"
        if self.provider == "db2":
            sql_select += " WITH UR"

        query_params = (formatted_curr_date, formatted_curr_date, "2")
        compiled_select = CompiledQuery(sql=sql_select, params=query_params)

        raw_results = self.fetch(compiled_select)

        # Gestione del codice di ritorno SQL (SQLCODE <> 0 / SQL-KEY-NON-TROVATA)
        if not raw_results:
            print("\n   **********************************")
            print("   *          SEGNALAZIONE          *")
            print("   * ------------------------------ *")
            print("   *FORMAZIONE NON CONSENTITA       *")
            print("   **********************************\n")
            raise RuntimeError(
                "[COBOL_EXCEPTION] Condizione bloccante: nessun record valido in stato '2' "
                f"per la data contabile {formatted_curr_date}."
            )

        # Estrazione e normalizzazione del record recuperato
        normalized_row = t18_map.normalize(raw_results[0])
        self.ws_dcon = normalized_row.get("dcon")
        self.ws_diniinf = normalized_row.get("diniinf")
        self.ws_dfininf = normalized_row.get("dfininf")
        self.ws_dinifor = normalized_row.get("dinifor")
        self.ws_dfinfor = normalized_row.get("dfinfor")
        self.ws_fstfor = normalized_row.get("fstfor")

        print(f"   >> [CNTR-STATO-FORMAZIONE] Record intercettato con successo:")
        print(f"      - DCON    : {self.ws_dcon}")
        print(f"      - DINIINF : {self.ws_diniinf}")
        print(f"      - DINIFOR : {self.ws_dinifor}")
        print(f"      - DFINFOR : {self.ws_dfinfor}")
        print(f"      - FSTFOR  : {self.ws_fstfor}")

        # ------------------------------------------------------------------
        # 3. PARAGRAFO: UPD-STATO-INI-FORM -
        # AGGIORNA FSTFOR => '1' ( FORMAZIONE IN CORSO )
        # TMSINI => CURRENT TIMESTAMP DELLA TABELLA ADCFRT18
        # ------------------------------------------------------------------
        print("   >> Avanzamento stato a '1' e aggiornamento marcatura temporale...")

        current_timestamp = datetime.now()
        sql_update = (
            f"UPDATE {t18_map.name} "
            f"SET {t18_map.fstfor} = ?, {t18_map.tmsini} = ? "
            f"WHERE {t18_map.dcon} = ? AND {t18_map.diniinf} = ?"
        )

        update_params = (
            "1",
            current_timestamp,
            self.dialect.format_value(self.ws_dcon),
            self.dialect.format_value(self.ws_diniinf)
        )

        compiled_update = CompiledQuery(sql=sql_update, params=update_params)
        righe_modificate = self.execute_mutation(compiled_update)
        print(f"   >> Record aggiornati con successo: {righe_modificate}")

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
        # Qui verranno collocate le logiche dei blocchi COBOL successivi


if __name__ == "__main__":
    import os

    os.environ["EXTERNAL_DB_CONFIG_PATH"] = r"C:\Users\mmuzi\config\app_db_config.json"
    worker = FormazioneAvvisoEngineProcessor()
    worker.run()