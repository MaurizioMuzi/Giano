# database/manager.py
import os
import json
import threading
from pathlib import Path

from config.loader import ConfigurationError
from config.schema_mapper import SchemaMapper, TableMap

# Manteniamo vivi gli handle delle DLL registrate per la durata del processo su Windows
_DB2_DLL_HANDLES = []
_DB2_INITIALIZED = False


def _setup_db2_environment():
    """
    Configura le cartelle DLL del CLI Driver di IBM DB2 per sistemi Windows,
    garantendo che l'importazione di ibm_db vada a buon fine.
    """
    global _DB2_INITIALIZED
    if _DB2_INITIALIZED:
        return

    if os.name == "nt":
        # Calcola la radice del progetto: database/.. -> root del progetto
        project_root = Path(__file__).resolve().parent.parent
        clidriver_bin = (
            project_root
            / ".venv"
            / "Lib"
            / "site-packages"
            / "clidriver"
            / "bin"
        )
        vc12_dir = clidriver_bin / "amd64.VC12.CRT"

        # Aggiorna il PATH di processo
        os.environ["PATH"] = (
            str(vc12_dir)
            + os.pathsep
            + str(clidriver_bin)
            + os.pathsep
            + os.environ.get("PATH", "")
        )

        # Registrazione esplicita per Python 3.8+
        if vc12_dir.exists():
            _DB2_DLL_HANDLES.append(os.add_dll_directory(str(vc12_dir)))

        if clidriver_bin.exists():
            _DB2_DLL_HANDLES.append(os.add_dll_directory(str(clidriver_bin)))

    _DB2_INITIALIZED = True


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
                    # Configura le DLL prima dell'import
                    _setup_db2_environment()
                    import ibm_db

                    conn_str = (
                        f"DATABASE={db_config['database']};"
                        f"HOSTNAME={db_config['hostname']};"
                        f"PORT={db_config['port']};"
                        f"PROTOCOL=TCPIP;"
                        f"UID={db_config['username']};"
                        f"PWD={db_config['password']};"
                    )
                    self._conn = ibm_db.pconnect(conn_str, "", "")

                elif self._provider == "sqlserver":
                    import pyodbc
                    conn_str = (
                        f"DRIVER={{{db_config['driver']}}};"
                        f"SERVER={db_config['server']};"
                        f"DATABASE={db_config['database']};"
                        f"UID={db_config['username']};"
                        f"PWD={db_config['password']};"
                        f"Encrypt=yes;"
                        f"TrustServerCertificate=yes;"
                    )
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