# config/schema_mapper.py
import os
import json
from datetime import datetime, date


class TableMap:
    """Rappresentazione dinamica, intelligente e tipizzata di una tabella fisica (Versione PRO)."""

    def __init__(self, provider: str, table_config: dict):
        self.provider = provider
        self.name = table_config["table"][provider]

        # Estrazione della mappatura dei nomi fisici delle colonne
        self._columns = {k: v[provider] for k, v in table_config["columns"].items()}
        self._reverse_columns = {v[provider]: k for k, v in table_config["columns"].items()}

        # Conservazione dell'intero schema dei metadati per la gestione dei tipi
        self._meta = table_config["columns"]

    def __getattr__(self, logical_column_name: str) -> str:
        if logical_column_name in self._columns:
            return self._columns[logical_column_name]
        raise AttributeError(f"[MAPPER ERROR] La colonna logica '{logical_column_name}' non esiste.")

    def normalize(self, physical_row_dict: dict) -> dict:
        """Riceve i dati grezzi dal DB e li restituisce tipizzati e standardizzati in Python."""
        if not physical_row_dict:
            return physical_row_dict

        normalized_row = {}
        for physical_key, raw_value in physical_row_dict.items():
            logical_key = self._reverse_columns.get(physical_key, physical_key)

            # Se la colonna fa parte dei metadati censiti, applichiamo le regole di tipo
            if logical_key in self._meta:
                col_meta = self._meta[logical_key]
                logical_type = col_meta.get("logical_type", "string")

                # Gestione della rimozione degli spazi (Padding tipico del COBOL)
                if col_meta.get("padding") and isinstance(raw_value, str):
                    raw_value = raw_value.strip()

                # Casting dinamico centralizzato
                normalized_row[logical_key] = self._cast_value(raw_value, logical_type)
            else:
                normalized_row[logical_key] = raw_value

        return normalized_row

    def _cast_value(self, value, logical_type: str):
        """Effettua il casting sicuro del dato isolando i comportamenti anomali dei driver."""
        if value is None:
            return None

        try:
            if logical_type == "int":
                return int(value)
            elif logical_type == "float":
                return float(value)
            elif logical_type == "date":
                if isinstance(value, (date, datetime)):
                    return value if isinstance(value, date) else value.date()
                # Se DB2 o COBOL restituiscono stringhe contratte tipo YYYYMMDD o YYYY-MM-DD
                clean_str = str(value).replace("-", "").strip()
                if len(clean_str) == 8:
                    return datetime.strptime(clean_str, "%Y%m%d").date()
                return datetime.fromisoformat(str(value)).date()
            elif logical_type == "datetime":
                if isinstance(value, datetime):
                    return value
                return datetime.fromisoformat(str(value).strip())
            elif logical_type == "string":
                return str(value)
            return value
        except Exception as e:
            print(f"[WARN] Impossibile effettuare il casting del valore '{value}' nel tipo '{logical_type}': {e}")
            return value


class SchemaMapper:
    """Motore di caricamento dinamico on-demand per le mappature dei database (Invariato)."""
    _cache = {}
    _MAPPINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings")

    @classmethod
    def get_map(cls, logical_table_key: str, provider: str) -> TableMap:
        cache_key = f"{logical_table_key}_{provider}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        json_file_path = os.path.join(cls._MAPPINGS_DIR, f"{logical_table_key}.json")
        if not os.path.exists(json_file_path):
            raise FileNotFoundError(f"[MAPPER ERROR] File di mappatura non trovato per l'asset: '{logical_table_key}'.")

        try:
            with open(json_file_path, 'r', encoding='utf-8') as file:
                table_config = json.load(file)

            table_map_instance = TableMap(provider, table_config)
            cls._cache[cache_key] = table_map_instance
            return table_map_instance
        except Exception as error:
            raise RuntimeError(f"[MAPPER CRITICAL] Fallimento nel parsing del file JSON {json_file_path}: {error}")