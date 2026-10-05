# processes/formazione_ruoli/context.py
import decimal
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal


@dataclass
class FormazioneRuoliContext:
    """
    Working-Storage Section specifica per il processo PDCFORUO.
    Mantiene lo stato condiviso, i parametri di input e i registri runtime.
    """
    # Parametri CLI / Batch
    sk_data_elab: Optional[date] = None
    data_elaborazione: Optional[date] = None
    data_limite_formazione: Optional[date] = None
    sede_filter: Optional[str] = None
    size_commit: int = 1000

    # Registri contabili da ADCFRT18
    dcon: Optional[date] = None
    diniinf: Optional[date] = None
    dfininf: Optional[date] = None
    dinifor: Optional[date] = None
    dfinfor: Optional[date] = None
    fstfor: Optional[str] = None

    # Registri contabili da TRATTAS
    ws_tasSanz_2: Decimal = field(default_factory=lambda: Decimal("0"))
    dataDec: Optional[date] = None

    # Registri contatori da ADCTET17
    count_sedi: int = 0
    count_lavori: int = 0
    count_lavori_if: int = 0
    count_lavori_in: int = 0

    # Registri contatori da ADCAVV11
    ws_cstacom: Optional[str] = None
    dinifor_vv11: Optional[date] = None
    dcon_vv11: Optional[date] = None

    # Registri campi da ADCFRT03
    ws_acar: int = 0
    ws_ncar: int = 0
    ws_nchkcar: int = 0
    ws_prov: int = 0

    # Dati correnti cursore CURJOI-1
    current_sede: Optional[str] = None
    current_zona: Optional[str] = None
    current_cod_centro: Optional[str] = None
    current_cod_servizio: Optional[str] = None
    totale_record_curjoi1: int = 0

    # Indicatori e contatori del ciclo di elaborazione (COBOL Flags)
    righe_elaborate_sede: int = 0
    indic_errore: bool = False
    indic_aggiorna: bool = False
    indic_non_trov: str = " "

    # =========================================================================
    # REGISTRI CONTATORI E DIAGNOSTICA SPECIFICI PDCFORUO
    # =========================================================================
    # WS-CTR-NRUO e WS-CTR-RIGHE
    ws_ctr_nruo: int = 0
    ws_ctr_righe: int = 0

    # WS-NOME-TAB (Diagnostica / SQL Error Logging)
    ws_nome_tab: str = ""

    # WS-INDICI (Puntatori / Indici di scorrimento tabelle ed elenchi)
    ws_indici: Dict[str, int] = field(default_factory=lambda: {
        "ind_tab": 0,
        "ind_riga": 0,
        "ind_art": 0
    })

    # WS-SOMME (Totalizzatori contabili specifici di PDCFORUO)
    ws_somma_tributi: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_somma_diritti: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_somma_spese: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_somma_totale_ruolo: Decimal = field(default_factory=lambda: Decimal("0"))

    # =========================================================================
    # CAMPI DI LAVORO (WORKING-STORAGE: WS-COMODI / IMP-COMODI-KEY)
    # =========================================================================
    ws_cges: Optional[str] = None
    ws_cgesavv: Optional[str] = None
    n_cges: Optional[str] = None
    ws_catt: str = ""
    n_catt: str = ""
    n_nprgart: Optional[int] = None

    ws_tipoavv: Optional[str] = None
    ws_annoavv: Optional[int] = None
    ws_progavv: Optional[int] = None
    ws_nparavv: Optional[int] = None
    ws_sedeavv: Optional[str] = None
    ws_sede: Optional[str] = None
    ws_zona: Optional[str] = None
    ws_cfis: Optional[str] = None
    ws_cazi: Optional[str] = None
    ws_periodo: Optional[int] = None
    ws_periobi: Optional[int] = None
    ws_frateiz: Optional[str] = None

    ws_forzatura0: Optional[str] = None
    ws_forzatura1: Optional[str] = None

    ws_cesa: Optional[int] = None
    ws_cesaavv: Optional[int] = None
    ws_feur: Optional[str] = None
    ws_ctrbcnc: Optional[str] = None
    ws_crat: Optional[str] = None
    ws_ntotrat: Optional[int] = None
    ws_fres: Optional[str] = None
    ws_cfasamm: Optional[str] = None

    ws_key_catt: Optional[str] = None
    ws_key_cges: Optional[str] = None
    ws_key_nprgart: Optional[int] = None

    # Totalizzatori e contatori azzerati a rottura avviso
    ws_itrbavv: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iaggavv: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_nespavv: int = 0
    ws_nespart: int = 0
    ws_ntotpar: int = 0

    # Indicatori di scarto e switch
    indic_scarto_t01: str = " "
    indic_scarto_t10: str = " "
    indic_scarto_t14: str = " "
    ws_erravv: str = " "
    sw_keyavv: int = 0
    sw_errore: int = 0

    @property
    def dinf_cdcfrt01(self) -> date:
        if self.sk_data_elab is None:
            return date(9999, 12, 31)
        return self.sk_data_elab

    def initialize_working_storage(self) -> None:
        """
        Reingegnerizzazione fedele dell'INITIALIZE COBOL per:
          - WS-INDICI
          - WS-NOME-TAB
          - WS-COMODI
          - WS-SOMME
          - WS-CTR-NRUO
          - WS-CTR-RIGHE
        """
        # Reset contatori numerici
        self.ws_ctr_nruo = 0
        self.ws_ctr_righe = 0
        self.ws_nome_tab = ""

        # Reset WS-INDICI
        self.ws_indici = {
            "ind_tab": 0,
            "ind_riga": 0,
            "ind_art": 0
        }

        # Reset WS-SOMME
        self.ws_somma_tributi = Decimal("0")
        self.ws_somma_diritti = Decimal("0")
        self.ws_somma_spese = Decimal("0")
        self.ws_somma_totale_ruolo = Decimal("0")

        # Reset WS-COMODI
        self.ws_cges = None
        self.ws_cgesavv = None
        self.n_cges = None
        self.ws_catt = ""
        self.n_catt = ""
        self.n_nprgart = None
        self.ws_tipoavv = None
        self.ws_annoavv = None
        self.ws_progavv = None
        self.ws_nparavv = None
        self.ws_sedeavv = None
        self.ws_sede = None
        self.ws_zona = None
        self.ws_cfis = None
        self.ws_cazi = None
        self.ws_periodo = None
        self.ws_periobi = None
        self.ws_frateiz = None
        self.ws_forzatura0 = None
        self.ws_forzatura1 = None
        self.ws_cesa = None
        self.ws_cesaavv = None
        self.ws_feur = None
        self.ws_ctrbcnc = None
        self.ws_crat = None
        self.ws_ntotrat = None
        self.ws_fres = None
        self.ws_cfasamm = None
        self.ws_key_catt = None
        self.ws_key_cges = None
        self.ws_key_nprgart = None

        # Reset accumulatori avviso
        self.ws_itrbavv = Decimal("0")
        self.ws_iaggavv = Decimal("0")
        self.ws_nespavv = 0
        self.ws_nespart = 0
        self.ws_ntotpar = 0

        # Reset flag ed errori
        self.indic_errore = False
        self.indic_aggiorna = False
        self.indic_non_trov = " "
        self.indic_scarto_t01 = " "
        self.indic_scarto_t10 = " "
        self.indic_scarto_t14 = " "
        self.ws_erravv = " "
        self.sw_keyavv = 0
        self.sw_errore = 0

    def imp_comodi_key(self, row_t01: dict, row_t10: dict) -> None:
        """
        Reingegnerizzazione del paragrafo COBOL IMP-COMODI-KEY.
        Inizializza registri di rottura, calcola le forzature fiscali e resetta i flag.
        """
        # CDCFRT01 -> Working Fields
        cges_val = row_t01.get("gestione")
        self.ws_cges = cges_val
        self.ws_cgesavv = cges_val
        self.n_cges = cges_val

        self.ws_catt = ""
        self.n_catt = ""
        self.n_nprgart = row_t10.get("progArticolo")

        self.ws_tipoavv = row_t01.get("tipoAvviso")
        self.ws_annoavv = row_t01.get("annoAvviso")
        self.ws_progavv = row_t01.get("progAvviso")
        self.ws_nparavv = row_t01.get("numPartitaAvviso")
        self.ws_sedeavv = row_t01.get("sedeOrigine")
        self.ws_sede = row_t01.get("sede")
        self.ws_zona = row_t01.get("zona")
        self.ws_cfis = row_t01.get("codiceFiscale")
        self.ws_cazi = row_t01.get("codAzienda")
        self.ws_periodo = row_t01.get("periodo")
        self.ws_periobi = row_t01.get("periodoBi")
        self.ws_frateiz = row_t01.get("flgRateizzazione")

        # Gestione Forzature Fiscali (FVALFIS)
        fvalfis = str(row_t01.get("flgValFiscale") or "").strip()
        self.ws_forzatura0 = fvalfis
        if fvalfis == "0":
            self.ws_forzatura1 = "1"
        elif fvalfis == "1":
            self.ws_forzatura1 = "0"
        elif fvalfis == "2":
            self.ws_forzatura1 = "3"
        elif fvalfis == "3":
            self.ws_forzatura1 = "2"
        else:
            self.ws_forzatura1 = None

        self.ws_cesa = row_t01.get("codEsattoria")
        self.ws_cesaavv = row_t01.get("codEsattoriaAvviso")
        self.ws_feur = row_t01.get("flgEuro")

        # CDCFRT10 -> Working Fields
        self.ws_ctrbcnc = row_t10.get("codTributoCnc")
        self.ws_crat = row_t10.get("codRata")
        self.ws_ntotrat = row_t10.get("numTotRate")
        self.ws_fres = row_t10.get("flgResiduo")
        self.ws_cfasamm = row_t10.get("codFasAmm")

        self.ws_key_catt = row_t10.get("codiceAtto")
        self.ws_key_cges = row_t10.get("gestione")
        self.ws_key_nprgart = row_t10.get("progArticolo")

        # Reset accumulatori e indicatori per il nuovo avviso
        self.ws_itrbavv = Decimal("0")
        self.ws_iaggavv = Decimal("0")
        self.ws_nespavv = 0
        self.ws_nespart = 0
        self.ws_ntotpar = 0
        self.indic_scarto_t01 = " "
        self.indic_scarto_t10 = " "
        self.indic_scarto_t14 = " "
        self.ws_erravv = " "
        self.sw_keyavv = 0
        self.sw_errore = 0