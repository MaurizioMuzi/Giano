# processes/preparazione_postalizzazione/step_gestisci_pilota.py
from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext

# # Timestamp convenzionale = "non ancora valorizzato", non una data di business reale
# WS_TMS_DEFAULT = "0001-01-01-00.00.00.000000"

#progressivi di censimento (es. per la gestione 1 - aziende, per la gestione 2 - artigiani, ...)
CATEGORIE_GESTIONE = {
    1:  "Gestione Aziende con lavoratori dipendenti",
    2:  "Gestione Artigiani",
    3:  "Gestione Commercianti",
    4:  "Gestione Agricola - Datori di lavoro",
    5:  "Gestione Agricola - Lavoratori Autonomi ed Associati",
    6:  "Gestione Separata: Committenti/Associati",
    7:  "Gestione Separata: Liberi Professionisti",
    8:  "Gestione Pescatori Autonomi - Gestione Redec",
    9:  "Gestione Aziende con lavoratori dipendenti - DE",
    10:  "Gestione Artigiani - DE",
    11:  "Gestione Commercianti - DE",
    12:  "Gestione Agricola - Datori di lavoro - DE",
    13:  "Gestione Agricola - Lavoratori Autonomi ed Associati - DE",
    14:  "Gestione Separata: Committenti/Associati - DE",
    15:  "Gestione Separata: Liberi Professionisti - DE",
    16:  "Gestione Pescatori Autonomi - Gestione Redec - DE",
    17:  "Gestione Ex-Enpals Lavoratori dello spettacolo - Sportivi Professionisti",
    18:  "Gestione Ex-Enpals Lavoratori dello spettacolo - Sportivi Professionisti - DE",
    19:  "Gestione Dipendenti Pubblici",
    20:  "Gestione Dipendenti Pubblici - DE",
    21:  "Indebiti da Prestazioni a sostegno del Reddito - Indebiti da Pensioni",
    22:  "Indebiti da Prestazioni a sostegno del Reddito - Indebiti da Pensioni - DE",
    23:  "Gestione Lavoratori Domestici",
    24:  "Gestione Lavoratori Domestici - DE",
    25:  "Gestione Spese Legali",
    26:  "Gestione Spese Legali - DE",
    27:  "Gestione VMC",
    28:  "Gestione VMC - DE"
}

class GestiscePilota:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: PreparazionePostalizzazioneContext) -> None:
        BatchLogger.info("ACCEDI-PILOTA", "Verifica ultima elaborazione (ADCAVV11)", depth=1)
        tavv11_map = self.engine.get_table_map("ADCAVV11")

        # Equivalente di OPEN-CURT11 + FETCH-CURT11:
        # estrae il record con NUMELAB più alto (ultima elaborazione)
        query = (
            self.engine.dataset("ADCAVV11")
            .select("prgcens", "numelab", "dcon", "dinifor", "dfinfor", "cstacom", "cstaavv","tms_finform", "tms_finlot","tms_inveq")
            .order_by_desc("numelab")
            .limit(1)
            .compile_select()
        )
        rows = self.engine.fetch(query, depth=1)

        if not rows:
            # Rif. COBOL: IF PILOTA-KO -> TABELLA PILOTA VUOTA
            BatchLogger.error(
                "PILOTA-KO",
                "SEGNALAZIONE: POSTALIZZAZIONE NON CONSENTITA - TABELLA PILOTA VUOTA",
                depth=1, is_last=True
            )
            raise RuntimeError("[COBOL_EXCEPTION] POSTALIZZAZIONE NON CONSENTITA: TABELLA PILOTA VUOTA")

        row = tavv11_map.normalize(rows[0])
        numelab_estratto = row["numelab"]

        numelab_nuovo = numelab_estratto

        if ctx.fstfor == "3":
        # NUMELAB si incrementa solo se FSTFOR (pre-update) era '3' -> nuovo giro di elaborazione
        # se non è un nuovo giro ('3'), NUMELAB resta quello estratto
            numelab_nuovo += 1

            BatchLogger.info(
                "NUMELAB-CALCOLATO",
                f"NUMELAB estratto={numelab_estratto} | FSTFOR-precedente={ctx.fstfor} | NUMELAB-nuovo={numelab_nuovo}",
                depth=1
            )
            # inserimento di un record in ADCAVV11 per ognuno dei progressivi censimento
            BatchLogger.info(
                "INSERT-PILOTA",
                f"Avvio inserimento per {len(CATEGORIE_GESTIONE)} categorie | NUMELAB={numelab_nuovo}",
                depth=1
            )
            for prgcens in CATEGORIE_GESTIONE:
                self._insert_pilota(ctx, numelab_nuovo, prgcens)

            BatchLogger.info(
                "INSERT-PILOTA-COMPLETATO",
                f"Inserite {len(CATEGORIE_GESTIONE)} righe in ADCAVV11 (NUMELAB={numelab_nuovo})",
                depth=1
            )

    def _insert_pilota(self, ctx, numelab_nuovo: int, prgcens: int) -> None:
        """Rif. COBOL: INSERT-PILOTA-1 .. INSERT-PILOTA-30 (PRGCENS diverso).
        DCON/DINIFOR/DFINFOR provengono da CNTR-STATO-FORMAZIONE (già in ctx).
        CSTACOM/CSTAAVV = '0' e i tre timestamp = WS-TMS-DEFAULT sono valori fissi
        in tutti i paragrafi originali, non calcolati."""
        record_avv11 = {
            "prgcens": prgcens,
            "numelab": numelab_nuovo,
            "dcon": ctx.dcon,
            "dinifor": ctx.dinifor,
            "dfinfor": ctx.dfinfor,
            "cstacom": "0",
            "cstaavv": "0",
            "tms_finform": "0001-01-01-00.00.00.000000",
            "tms_finlot": "0001-01-01-00.00.00.000000",
            "tms_inveq": "0001-01-01-00.00.00.000000"
        }
        query = self.engine.dataset("ADCAVV11").compile_insert(record_avv11)


        try:
            self.engine.execute_mutation(query, depth=2)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-PILOTA-RIGA",
                f"Inserita riga PRGCENS={prgcens} ({CATEGORIE_GESTIONE[prgcens]}) NUMELAB={numelab_nuovo}",
                depth=2
            )
        except Exception as e:
            BatchLogger.error(
                "INSERT-PILOTA-ERRORE",
                f"Fallito inserimento PRGCENS={prgcens} ({CATEGORIE_GESTIONE[prgcens]}) NUMELAB={numelab_nuovo}: {e}",
                depth=2, is_last=True
            )
            raise
