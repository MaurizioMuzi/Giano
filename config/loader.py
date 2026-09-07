# config/loader.py
import os
import json


class ConfigurationError(Exception):
    """Eccezione sollevata in caso di anomalie critiche nella configurazione esterna."""
    pass


class ConfigLoader:
    """
    Componente specializzato nell'estrazione e validazione dei parametri
    di configurazione memorizzati nel placeholder esterno al progetto.
    """

    @staticmethod
    def get_database_payload() -> dict:
        """Legge la variabile d'ambiente ed estrae i dati di connessione attivi."""
        config_path = os.environ.get("EXTERNAL_DB_CONFIG_PATH")
        if not config_path:
            raise ConfigurationError(
                "La variabile d'ambiente 'EXTERNAL_DB_CONFIG_PATH' non è definita nel sistema."
            )

        if not os.path.exists(config_path):
            raise ConfigurationError(
                f"Il file di configurazione esterno non esiste nel percorso: {config_path}"
            )

        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                full_payload = json.load(file)
                selected = full_payload.get("selected_connection")
                db_config = full_payload.get("connections", {}).get(selected)

                if not db_config:
                    raise KeyError(f"La chiave di connessione '{selected}' non è presente nel file JSON.")

                return db_config
        except Exception as error:
            raise ConfigurationError(
                f"Errore fatale durante il parsing del file di configurazione: {error}"
            )