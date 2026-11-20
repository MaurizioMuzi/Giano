# processes/invio_ruoli_AdER/context.py
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict, Any
from decimal import Decimal

from core.file_writer import FileWriter


@dataclass
class InvioRuoliAdREContext:
    """
    Working-Storage Section specifica per il processo PDCINCRE / PDCFORUO.
    Mantiene lo stato condiviso, i parametri di input, i registri runtime e lo stream di output.
    """
    # Parametri CLI / Batch
    sk_data_invio: Optional[date] = None
    sk_data_firma: Optional[date] = None
    data_elaborazione: Optional[date] = None
    data_limite_formazione: Optional[date] = None
    sede_filter: Optional[str] = None
    size_commit: int = 1000

    # Gestione Writer Flussi Posizionali (R3A, R5A, R7A, R3Z, ecc.)
    writer: Optional[FileWriter] = None
    current_output_file: Optional[str] = None

    # Campi specifici testata/coda flusso R3
    ws_ente_impos: int = 0
    ws_id_file: str = ""
    ws_data_creazione: int = 0
    ws_data_consegna: int = 0

    # Dizionari riga corrente tabelle collegate
    row_t01: Dict[str, Any] = field(default_factory=dict)
    row_t09: Dict[str, Any] = field(default_factory=dict)
    row_t10: Dict[str, Any] = field(default_factory=dict)
    row_t02: Dict[str, Any] = field(default_factory=dict)
    row_tv12: Dict[str, Any] = field(default_factory=dict)

    # Registri contabili da ADCFRT18
    dcon: Optional[date] = None
    diniinf: Optional[date] = None
    dfininf: Optional[date] = None
    dinifor: Optional[date] = None
    dfinfor: Optional[date] = None

    ws_dinv: Optional[date] = None
    ws_dcon: Optional[date] = None
    ws_dataFineCalc: Optional[date] = None

    ws_dt_x: int = 0
    ws_dt_fincal: int = 0
    ws_dtvisto: int = 0

    fstfor: Optional[str] = None

    # Registri contabili da TRATTAS
    ws_tasSanz_2: Decimal = field(default_factory=lambda: Decimal("0"))
    dataDec: Optional[date] = None

    # Registri contatori da ADCTET17
    count_sedi: int = 0
    count_ruoli: int = 0
    count_lavori: int = 0
    count_lavori_if: int = 0
    count_lavori_in: int = 0
    ws_ctr_nfil: int = 0
    ws_tot_r3z_r5a: int = 0
    ws_prg_file: int = 0

    # Registri contatori da ADCAVV11
    ws_cstacom: Optional[str] = None
    dinifor_vv11: Optional[date] = None
    dcon_vv11: Optional[date] = None

    # Registri campi da ADCFRT03
    ws_acar: int = 0
    ws_ncar: int = 0
    ws_nchkcar: int = 0
    ws_prov: int = 0
    ws_idavv: str = ""
    ws_ver_ok: int = 0
    ws_ver_er: int = 0
    timestampInsStato: Optional[datetime] = None
    ws_cstacar: Optional[str] = None

    # Registri campi da ADCAVV12
    ws_codConcessione: Optional[str] = None
    ws_codErr: Optional[str] = None
    ws_codRav: Optional[Any] = None
    ws_nrav_cid: Optional[str] = None
    ws_dlett: Optional[date] = None
    ws_cstalet: Optional[str] = None
    ws_itotdeb: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_snom_dir: Optional[str] = None
    ws_scogn_dir: Optional[str] = None
    ws_sindpec: Optional[str] = None

    cesa_nrav: int = 0
    prog_nrav: int = 0
    cabi_nrav: int = 0
    ciderav_min: int = 0
    ciderav_max: int = 0

    ws_identificativoAvviso: Optional[str] = None

    # Dati correnti cursore CURJOI-1
    current_sede: Optional[str] = None
    current_zona: Optional[str] = None
    current_cod_centro: Optional[str] = None
    current_cod_servizio: Optional[str] = None
    totale_record_curjoi1: int = 0

    # Indicatori e contatori del ciclo di elaborazione (COBOL Flags)
    righe_elaborate_sede: int = 0
    indic_errore: Optional[str] = None
    indic_prima_volta_T02: Optional[str] = None
    indic_primo_ciclo_T02: Optional[str] = None
    indic_prima_volta_R5A: Optional[str] = None
    indic_fine_file_T02: Optional[str] = None

    indic_prima_volta_T09: Optional[str] = None
    indic_guarda: Optional[str] = None
    indic_bloccata: Optional[str] = None
    indic_nessun_dato: Optional[str] = None

    indic_aggiorna: bool = False
    indic_non_trov: str = " "

    # =========================================================================
    # REGISTRI CONTATORI E DIAGNOSTICA SPECIFICI PDCFORUO
    # =========================================================================
    ws_ctr_nruo: int = 0
    ws_ctr_righe: int = 0
    ws_nart: int = 0
    ws_nome_tab: str = ""

    ws_indici: Dict[str, int] = field(default_factory=lambda: {
        "ind_tab": 0,
        "ind_riga": 0,
        "ind_art": 0
    })

    # WS-SOMME (Totalizzatori contabili specifici di PDCFORUO)
    ws_t02_itrbcal: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_itrb_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_isan_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iint_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_ialt_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iaggant: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iaggant_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iaggtot: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iaggtot_t: Decimal = field(default_factory=lambda: Decimal("0"))

    ws_t10_itrb: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_itrb_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iaggant: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iaggant_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iaggtot: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iaggtot_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iarr: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t10_iarr_t: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iarr: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_t02_iarr_t: Decimal = field(default_factory=lambda: Decimal("0"))

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
    ws_idavv12: Optional[str] = None

    ws_tipoavv: Optional[str] = None
    ws_annoavv: Optional[int] = None
    ws_progavv: Optional[int] = None
    ws_nparavv: Optional[int] = None
    ws_sedeavv: Optional[str] = None
    ws_sede: Optional[str] = None
    ws_zona: Optional[str] = None
    ws_centro: Optional[str] = None
    ws_cruo: Optional[int] = None
    ws_cfis: Optional[str] = None
    ws_cazi: Optional[str] = None
    ws_periodo: Optional[int] = None
    ws_periobi: Optional[int] = None
    ws_frateiz: Optional[str] = None

    # Forzature fiscali (FVALFIS)
    ws_forzatura0: Optional[str] = None
    ws_forzatura1: Optional[str] = None

    ws_cesa: Optional[int] = None
    ws_cesaavv: Optional[int] = None
    ws_feur: Optional[str] = None
    ws_cesa_t02: Optional[int] = None
    ws_cesa_t02_2: Optional[int] = None
    ws_feur_t02: Optional[str] = None
    ws_arifruo_t02: Optional[int] = 0
    ws_nruo_t02: Optional[int] = None
    ws_arifruo_t09: Optional[int] = None
    ws_cesa_t09: Optional[int] = None
    ws_nruo_t09: Optional[int] = None
    ws_fres_t09: Optional[str] = None
    ws_ctrbcnc_t09: Optional[str] = None
    ws_arifcon_t09: Optional[int] = None
    ws_nrat_t09: Optional[int] = None
    ws_crat_t09: Optional[str] = None
    ws_itrb_t09: Optional[int] = None
    ws_nart_t09: Optional[int] = None
    ws_iaggant_t09: Optional[int] = None
    ws_iaggtot_t09: Optional[int] = None
    ws_iarr_t09: Optional[int] = None
    ws_icrc_t09: Optional[int] = None

    ws_ctrbcnc: Optional[str] = None
    ws_crat: Optional[str] = None
    ws_ntotrat: Optional[int] = None
    ws_fres: Optional[str] = None
    ws_cfasamm: Optional[str] = None

    ws_key_ctrbcnc: Optional[str] = None
    ws_key_crat: Optional[str] = None
    ws_key_ntotrat: Optional[int] = None
    ws_key_fres: Optional[str] = None
    ws_key_cfasamm: Optional[str] = None
    ws_key_cesa: Optional[int] = None

    ws_key_catt: Optional[str] = None
    ws_key_cges: Optional[str] = None
    ws_key_nprgart: Optional[int] = None

    # Totalizzatori e contatori azzerati a rottura avviso
    ws_itrb: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_isan: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iint: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_ialt: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iaggant: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iaggtot: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iarr: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_iiva: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_icrc: Decimal = field(default_factory=lambda: Decimal("0"))

    ws_iaggavv: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_nespavv: int = 0
    ws_nespart: int = 0
    ws_ntotpar: int = 0
    record_art_totali: int = 0

    # Indicatori di scarto e switch
    indic_scarto_t01: str = " "
    indic_scarto_t10: str = " "
    indic_scarto_t14: str = " "
    ws_erravv: str = " "
    sw_keyavv: int = 0
    sw_errore: int = 0

    @property
    def dinf_cdcfrt01(self) -> date:
        if self.sk_data_firma is None:
            return date(9999, 12, 31)
        return self.sk_data_firma

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
        self.ws_nart = 0
        self.ws_nome_tab = ""
        self.ws_tot_r3z_r5a = 0
        self.ws_prg_file = 0

        # Reset WS-INDICI
        self.ws_indici = {
            "ind_tab": 0,
            "ind_riga": 0,
            "ind_art": 0
        }

        # Reset WS-SOMME
        self.ws_t02_itrbcal = Decimal("0")
        self.ws_t02_itrb_t = Decimal("0")
        self.ws_t02_isan_t = Decimal("0")
        self.ws_t02_iint_t = Decimal("0")
        self.ws_t02_ialt_t = Decimal("0")
        self.ws_t02_iaggant = Decimal("0")
        self.ws_t02_iaggant_t = Decimal("0")
        self.ws_t02_iaggtot = Decimal("0")
        self.ws_t02_iaggtot_t = Decimal("0")
        self.ws_t10_itrb = Decimal("0")
        self.ws_t10_itrb_t = Decimal("0")
        self.ws_t10_iaggant = Decimal("0")
        self.ws_t10_iaggant_t = Decimal("0")
        self.ws_t10_iaggtot = Decimal("0")
        self.ws_t10_iaggtot_t = Decimal("0")
        self.ws_t10_iarr = Decimal("0")
        self.ws_t10_iarr_t = Decimal("0")
        self.ws_t02_iarr = Decimal("0")
        self.ws_t02_iarr_t = Decimal("0")

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
        self.ws_idavv = ""
        self.ws_idavv12 = None
        self.ws_tipoavv = None
        self.ws_annoavv = None
        self.ws_progavv = None
        self.ws_nparavv = None
        self.ws_sedeavv = None
        self.ws_sede = None
        self.ws_zona = None
        self.ws_centro = None
        self.ws_cruo = None
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
        self.ws_cesa_t02 = None
        self.ws_cesa_t02_2 = None
        self.ws_feur_t02 = None
        self.ws_arifruo_t02 = 0
        self.ws_nruo_t02 = None
        self.ws_arifruo_t09 = None
        self.ws_cesa_t09 = None
        self.ws_nruo_t09 = None
        self.ws_fres_t09 = None

        self.ws_ctrbcnc_t09 = None
        self.ws_arifcon_t09 = None
        self.ws_nrat_t09 = None
        self.ws_crat_t09 = None
        self.ws_itrb_t09 = None
        self.ws_nart_t09 = None
        self.ws_iaggant_t09 = None
        self.ws_iaggtot_t09 = None
        self.ws_iarr_t09 = None
        self.ws_icrc_t09 = None

        # Reset campi ADCAVV12
        self.row_tv12 = {}
        self.ws_dlett = None
        self.ws_cstalet = None
        self.ws_itotdeb = Decimal("0")
        self.ws_snom_dir = None
        self.ws_scogn_dir = None
        self.ws_sindpec = None
        self.ws_codRav = None
        self.ws_identificativoAvviso = None

        self.ws_ctrbcnc = None
        self.ws_crat = None
        self.ws_ntotrat = None
        self.ws_fres = None
        self.ws_cfasamm = None
        self.ws_key_catt = None
        self.ws_key_cges = None
        self.ws_key_nprgart = None

        self.ws_key_ctrbcnc = None
        self.ws_key_crat = None
        self.ws_key_ntotrat = None
        self.ws_key_fres = None
        self.ws_key_cfasamm = None
        self.ws_key_cesa = None

        # Reset accumulatori avviso
        self.ws_itrb = Decimal("0")
        self.ws_isan = Decimal("0")
        self.ws_iint = Decimal("0")
        self.ws_ialt = Decimal("0")
        self.ws_iaggant = Decimal("0")
        self.ws_iaggtot = Decimal("0")
        self.ws_iarr = Decimal("0")
        self.ws_iiva = Decimal("0")
        self.ws_icrc = Decimal("0")

        self.ws_nespavv = 0
        self.ws_nespart = 0
        self.ws_ntotpar = 0

        # Reset flag ed errori
        self.indic_errore = " "
        self.indic_prima_volta_T02 = " "
        self.indic_primo_ciclo_T02 = " "
        self.indic_prima_volta_R5A = " "
        self.indic_fine_file_T02 = " "
        self.indic_guarda = " "
        self.indic_bloccata = " "
        self.indic_nessun_dato = " "

        self.indic_aggiorna = False
        self.indic_non_trov = " "
        self.indic_scarto_t01 = " "
        self.indic_scarto_t10 = " "
        self.indic_scarto_t14 = " "
        self.ws_erravv = " "
        self.sw_keyavv = 0
        self.sw_errore = 0

    def imp_comodi_key(
        self,
        row_t02: dict,
        row_t01: Optional[dict] = None,
        row_t10: Optional[dict] = None,
        row_t09: Optional[dict] = None
    ) -> None:
        """
        Reingegnerizzazione del paragrafo COBOL IMP-COMODI-KEY.
        Inizializza registri di rottura, calcola le forzature fiscali e resetta i flag.
        """
        row_t01 = row_t01 or self.row_t01 or {}
        row_t09 = row_t09 or self.row_t10 or {}
        row_t10 = row_t10 or self.row_t10 or {}

        # CDCFRT01 -> Working Fields
        cesa_val = row_t02.get("codEsattoria")
        self.ws_cesa = cesa_val
        self.ws_cesa_t02 = cesa_val
        self.ws_cesa_t02_2 = cesa_val

        self.ws_catt = ""
        self.n_catt = ""
        self.n_nprgart = row_t10.get("progArticolo")

        # campi row_t01
        self.ws_tipoavv = row_t01.get("tipoAvviso")
        self.ws_annoavv = row_t01.get("annoAvviso")
        self.ws_progavv = row_t01.get("progAvviso")
        self.ws_nparavv = row_t01.get("numPartitaAvviso")
        self.ws_sedeavv = row_t01.get("sedeOrigine")
        self.ws_sede = row_t01.get("sede")
        self.ws_zona = row_t01.get("zona")
        self.ws_centro = row_t01.get("codCentro")
        self.ws_cruo = row_t01.get("codRuoloCoa")
        self.ws_cfis = row_t01.get("codiceFiscale")
        self.ws_cazi = row_t01.get("codAzienda")
        self.ws_periodo = row_t01.get("periodo")
        self.ws_periobi = row_t01.get("periodoBi")
        self.ws_frateiz = row_t01.get("flgRateizzazione")

        # campi row_t09
        self.ws_progavv = row_t09.get("progAvviso")
        self.ws_nparavv = row_t09.get("numPartitaAvviso")

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

        # ADCFRT02 -> Working Fields
        self.ws_cesa = row_t02.get("codEsattoria")
        self.ws_feur = row_t02.get("flgEuro")
        self.ws_arifruo_t02 = row_t02.get("annoRif")
        self.ws_nruo_t02 = row_t02.get("numRuolo")

        # ADCFRT09 -> Working Fields
        self.ws_arifruo_t09 = row_t09.get("annoRif")
        self.ws_cesa_t09 = row_t09.get("codEsattoria")
        self.ws_nruo_t09 = row_t09.get("numRuolo")
        self.ws_fres_t09 = row_t09.get("flgResiduo")
        self.ws_ctrbcnc_t09 = row_t09.get("codTributoCnc")
        self.ws_arifcon_t09 = row_t09.get("annoRifCont")
        self.ws_nrat_t09 = row_t09.get("numRate")
        self.ws_crat_t09 = row_t09.get("codRata")
        self.ws_itrb_t09 = row_t09.get("impTributo")
        self.ws_nart_t09 = row_t09.get("numArticoli")
        self.ws_iaggant_t09 = row_t09.get("impAggioAnt")
        self.ws_iaggtot_t09 = row_t09.get("impAggioTot")
        self.ws_iarr_t09 = row_t09.get("impArrotondamento")
        self.ws_icrc_t09 = row_t09.get("impCarico")

        self.ws_cesa_t02 = row_t02.get("codEsattoria")
        self.ws_cesa_t02_2 = row_t02.get("codEsattoria")
        self.ws_feur_t02 = row_t02.get("flgEuro")
        self.ws_arifruo_t02 = row_t02.get("annoRif")
        self.ws_nruo_t02 = row_t02.get("numRuolo")

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
        self.ws_t02_itrbcal = Decimal("0")
        self.ws_t02_iaggant = Decimal("0")
        self.ws_t02_iaggant_t = Decimal("0")
        self.ws_t02_iaggtot = Decimal("0")
        self.ws_t02_iaggtot_t = Decimal("0")
        self.ws_itrb = Decimal("0")
        self.ws_isan = Decimal("0")
        self.ws_iint = Decimal("0")
        self.ws_ialt = Decimal("0")
        self.ws_iaggant = Decimal("0")
        self.ws_iaggtot = Decimal("0")
        self.ws_iarr = Decimal("0")
        self.ws_iiva = Decimal("0")
        self.ws_icrc = Decimal("0")

        self.ws_nespavv = 0
        self.ws_nespart = 0
        self.ws_ntotpar = 0
        self.indic_scarto_t01 = " "
        self.indic_scarto_t10 = " "
        self.indic_scarto_t14 = " "
        self.ws_erravv = " "
        self.sw_keyavv = 0
        self.sw_errore = 0