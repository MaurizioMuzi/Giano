# main.py
import os
import sys
import json
import argparse
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.manager import DefaultConnectionProvider
from processes.formazione_avviso.processor import FormazioneAvvisoEngineProcessor
from processes.formazione_avviso.context import FormazioneAvvisoContext
from config.loader import ConfigurationError
from core.batch_logger import BatchLogger

ELABORAZIONI_VALIDE = [
    "gestione_avvisi",
    "formazione_avviso",
    "postalizzazione",
    "formazione_ruoli",
    "firma_ruoli",
    "invio_ruoli_AdER"
]


def parse_date_param(date_str):
    """Parsa la data accettando i formati standard YYYY-MM-DD, DD.MM.YYYY e DD/MM/YYYY."""
    if not date_str or not str(date_str).strip():
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"Formato data non valido: '{date_str}'. Formati accettati: YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY"
    )


def load_config_parameters(config_path: str) -> dict:
    """Estrae i parametri operativi, di logging e di soglia commit dal file JSON configurato."""
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        batch_params = cfg.get("batch_parameters", {})
        logging_params = cfg.get("logging", {})

        # Risoluzione soglia commit (cerca nel root o dentro batch_parameters, fallback a 1000)
        size_commit = cfg.get("size_commit") or batch_params.get("size_commit") or 1000

        # Risoluzione data_formazione_avviso
        raw_data = cfg.get("data_formazione_avviso") or batch_params.get("data_formazione_avviso")
        parsed_data = parse_date_param(raw_data) if raw_data else None

        tipo_elab = cfg.get("tipo_elaborazione") or batch_params.get("tipo_elaborazione")
        if tipo_elab:
            tipo_elab = str(tipo_elab).strip()

        return {
            "data_formazione_avviso": parsed_data,
            "tipo_elaborazione": tipo_elab,
            "size_commit": int(size_commit),
            "log_dir": logging_params.get("log_dir"),
            "log_console": logging_params.get("log_console"),
            "log_file": logging_params.get("log_file")
        }
    except Exception as err:
        print(f"[WARN] Impossibile recuperare i parametri dal file JSON: {err}", file=sys.stderr)
        return {}


def resolve_log_level(level_name=None, default: int = logging.INFO) -> int:
    """Mappa la stringa del livello di log al relativo intero del modulo logging."""
    if not level_name:
        return default
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR
    }
    return mapping.get(str(level_name).strip().upper(), default)


def parse_args():
    parser = argparse.ArgumentParser(description="Runtime Industrial Processor - Engine COBOL Batch Mainframe")

    parser.add_argument(
        "sk_data_elab",
        type=parse_date_param,
        nargs="?",
        default=None,
        help="Data contabile SK-DATA-ELAB (es. 2026-08-31 o 31.08.2026). Se omessa, legge dal JSON o assegna default 9999-12-31"
    )

    parser.add_argument(
        "--tipo-elaborazione",
        type=str,
        default=None,
        choices=ELABORAZIONI_VALIDE,
        help="Target elaborazione batch (se omesso viene letto dal file JSON)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Se specificato, esegue il batch in sola simulazione"
    )

    parser.add_argument(
        "--config-path",
        type=str,
        default=r"C:\Users\maurizio.muzi\config\app_db_config.json",
        help="Percorso al file JSON di configurazione DB"
    )

    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="Cartella di destinazione per i file di log .txt (default: letta da JSON o 'logs')"
    )

    parser.add_argument(
        "--log-console",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        help="Livello minimo di tracciamento su console (default: letto da JSON o INFO)"
    )

    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        help="Livello minimo di tracciamento su file .txt (default: letto da JSON o DEBUG)"
    )

    return parser.parse_args()


def esegui_formazione_avviso(args, effective_sk_date, config_params):
    """Inizializza ed esegue il processore di formazione avviso passando la soglia di commit."""
    context = FormazioneAvvisoContext(sk_data_elab=effective_sk_date)
    context.size_commit = config_params.get("size_commit", 1000)  # Salvato nel contesto

    BatchLogger.info("ORCHESTRATORE", f"SK-DATA-ELAB operativo: {context.sk_data_elab}")
    BatchLogger.info("ORCHESTRATORE", f"Soglia COMMIT parziale configurata: {context.size_commit} record")

    worker = FormazioneAvvisoEngineProcessor(
        context=context,
        dry_run=args.dry_run
    )
    # Passiamo la soglia anche all'engine/processore se necessario
    worker.size_commit = context.size_commit
    worker.run()


def main():
    args = parse_args()
    os.environ["EXTERNAL_DB_CONFIG_PATH"] = args.config_path

    # 1. Caricamento parametri dal file JSON di configurazione
    config_params = load_config_parameters(args.config_path)

    # 2. Risoluzione preliminare del tipo elaborazione per denominare il file di log
    effective_tipo_elab = args.tipo_elaborazione or config_params.get("tipo_elaborazione") or "formazione_avviso"

    # 3. Risoluzione cartella e livelli di logging (CLI > JSON > Default)
    effective_log_dir = args.log_dir or config_params.get("log_dir") or "logs"
    effective_log_console = args.log_console or config_params.get("log_console") or "INFO"
    effective_log_file = args.log_file or config_params.get("log_file") or "DEBUG"

    console_lvl = resolve_log_level(effective_log_console, logging.INFO)
    file_lvl = resolve_log_level(effective_log_file, logging.DEBUG)

    # 4. Inizializzazione unificata del Logger con prefisso dinamico da effective_tipo_elab
    BatchLogger.setup_logger(
        log_dir=effective_log_dir,
        console_level=console_lvl,
        file_level=file_lvl,
        log_prefix=effective_tipo_elab
    )

    # Risoluzione data contabile
    effective_sk_date = args.sk_data_elab or config_params.get("data_formazione_avviso")

    if effective_tipo_elab not in ELABORAZIONI_VALIDE:
        BatchLogger.error(
            "ORCHESTRATORE",
            f"Tipo elaborazione '{effective_tipo_elab}' non valido. Ammessi: {', '.join(ELABORAZIONI_VALIDE)}"
        )
        sys.exit(1)

    BatchLogger.info("ORCHESTRATORE", f"Target di Elaborazione Selezionato: [{effective_tipo_elab.upper()}]")
    BatchLogger.info("LOG-CONFIG", f"Livello Console: [{effective_log_console.upper()}] | Livello File: [{effective_log_file.upper()}]")

    exit_code = 0
    try:
        if effective_tipo_elab == "formazione_avviso":
            esegui_formazione_avviso(args, effective_sk_date, config_params)

        elif effective_tipo_elab == "postalizzazione":
            BatchLogger.info("STEP-POSTALIZZAZIONE", "Avvio fase di Postalizzazione...")

        elif effective_tipo_elab == "formazione_ruoli":
            BatchLogger.info("STEP-FORMAZIONE-RUOLI", "Avvio fase di Formazione Ruoli...")

        elif effective_tipo_elab == "firma_ruoli":
            BatchLogger.info("STEP-FIRMA-RUOLI", "Avvio fase di Firma Ruoli...")

        elif effective_tipo_elab == "invio_ruoli_AdER":
            BatchLogger.info("STEP-INVIO-ADER", "Avvio fase di Invio Ruoli ad Agenzia delle Entrate-Riscossione...")

        elif effective_tipo_elab == "gestione_avvisi":
            BatchLogger.info("WORKFLOW-COMPLETO", "Esecuzione sequenziale di tutte le fasi batch...")

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [1/5] Formazione Avviso")
            esegui_formazione_avviso(args, effective_sk_date, config_params)

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [2/5] Postalizzazione")

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [3/5] Formazione Ruoli")

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [4/5] Firma Ruoli")

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [5/5] Invio Ruoli AdER")

    except ConfigurationError as env_error:
        BatchLogger.error("ERR_ENVIRONMENT", str(env_error))
        exit_code = 2
    except Exception as general_error:
        BatchLogger.error("ERR_SYSTEM", str(general_error))
        exit_code = 1
    finally:
        DefaultConnectionProvider().close()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()