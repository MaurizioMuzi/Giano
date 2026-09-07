# database/manager.py
import threading
import os
import json
from config.loader import ConfigurationError
from config.schema_mapper import SchemaMapper, TableMap


class DefaultConnectionProvider:
    """Provider Centralizzato Pro per la gestione dello switch e dei metadati."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DefaultConnectionProvider, cls).__new__(cls)
                cls._instance._conn = None
                cls._instance._provider = None
        return cls._instance

    def _load_config(self) -> tuple:
        config_path = os.environ.get("EXTERNAL_DB_CONFIG_PATH")
        if not config_path or not os.path.exists(config_path):
            raise ConfigurationError("File di configurazione esterno non raggiungibile.")
        with open(config_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
            selected = payload.get("selected_connection")
            return payload["connections"][selected], selected

    def get_connection(self) -> tuple:
        with self._lock:
            if self._conn is not None:
                return self._conn, self._provider

            db_config, alias = self._load_config()
            self._provider = db_config.get("provider")

            try:
                if self._provider == "db2":
                    import ibm_db
                    conn_str = f"DATABASE={db_config['database']};HOSTNAME={db_config['hostname']};PORT={db_config['port']};PROTOCOL=TCPIP;UID={db_config['username']};PWD={db_config['password']};"
                    self._conn = ibm_db.pconnect(conn_str, "", "")
                elif self._provider == "sqlserver":
                    import pyodbc
                    conn_str = f"DRIVER={{{db_config['driver']}}};SERVER={db_config['server']};DATABASE={db_config['database']};UID={db_config['username']};PWD={db_config['password']};Encrypt=yes;TrustServerCertificate=yes;"
                    self._conn = pyodbc.connect(conn_str)
                return self._conn, self._provider
            except Exception as e:
                raise RuntimeError(f"Errore connessione runtime '{alias}': {e}")

    def get_table_map(self, logical_table_key: str) -> TableMap:
        """Centralizza l'esposizione dello SchemaMapper."""
        _, _ = self.get_connection()
        return SchemaMapper.get_map(logical_table_key, self._provider)

    def close(self):
        with self._lock:
            if self._conn is not None:
                if self._provider == "db2":
                    import ibm_db
                    ibm_db.close(self._conn)
                elif self._provider == "sqlserver":
                    self._conn.close()
                self._conn = None