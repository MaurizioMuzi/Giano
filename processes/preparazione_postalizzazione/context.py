# processes/pdcpoavv_preparazione_postalizzazione/context.py
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict, Any
from decimal import Decimal


@dataclass
class PreparazionePostalizzazioneContext:
    """
    Working-Storage Section specifica per il processo PDCPOAVV.
    Mantiene lo stato condiviso, i parametri di input e i registri runtime.
    """
    # Parametri CLI / Batch
    sk_data_elab: Optional[date] = None
    data_elaborazione: Optional[date] = None
    data_limite_formazione: Optional[date] = None
    sede_filter: Optional[str] = None
    size_commit = 1000

    # Registri contabili da ADCFRT18
    dcon: Optional[date] = None
    diniinf: Optional[date] = None
    dfininf: Optional[date] = None
    dinifor: Optional[date] = None
    dfinfor: Optional[date] = None
    fstfor: Optional[str] = None

    # Registri contatori da ADCTET17
    count_sedi: int = 0
    count_lavori: int = 0

    # Dati correnti ADCAVV11
    ws_num_elab: Optional[int] = None

    # Dati correnti cursore CURT-17
    current_sede: Optional[str] = None
    current_zona: Optional[str] = None
    current_cod_centro: Optional[str] = None
    current_cod_servizio: Optional[str] = None
    totale_record_curt17: int = 0

    # Indicatori e contatori del ciclo di elaborazione (COBOL Flags)
    righe_elaborate_sede: int = 0
    indic_errore: bool = False
    indic_aggiorna: bool = False
    indic_imp_avv: bool = False
    indic_rav_presente: str = " "

    # Dati correnti cursore CURT-03
    cesa: int = 0
    annoCartella: int = 0
    numeroCartella: int = 0
    chkCartella: int = 0
    idAvviso:  Optional[str] = None
    impAvvisoRav: int = 0
    impCaricoCartella: int = 0
    impAggio: int = 0

    # CONTATORI
    ws_ctr_t03 : int = 0
    ws_nespcf: int = 0

    # Indicatori da VSEDI_ADDEBITI
    sszz: Optional[str] = None
    nomedir: Optional[str]  = " "
    cogndir: Optional[str]  = " "
    sede: Optional[str]  = " "
    pr: Optional[str]  = " "
    indir_sedi: Optional[str]  = " "
    cap_sedi: Optional[str] = " "
    nomedir_prov: Optional[str] = None
    cogndir_prov: Optional[str] = None
    comune_sedi: Optional[str] = " "

    # Indicatori di scarto (o riciclo)
    indic_sede_nonval: bool = False
    ws_cstatt: Optional[str] = " "
    ws_cstaart: Optional[str] = " "
    ws_cstacar: Optional[str] = " "
    ws_erravv: str = " "


    # Totalizzatori e contatori
    ws_itrbcar_50: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_itrbcar_12: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_nespavv: int = 0
    ws_nespart: int = 0
    ws_ntotpar: int = 0

    # Dati correnti cursore CURV-03
    ws_cabi: int = 0
    ws_ciderav: int = 0
    ws_ciderav_max: int = 0
    ws_ciderav_new: int = 0
    ws_delta_rav: int = 0
    ws_flag_attr: Optional[str] = None

    # Dati Calcolo CIN e RAV
    ws_cin1: int = 0
    ws_cin2: int = 0

    # Dati correnti ADCFRT01
    ws_cges: Optional[str] = None
    cseg: Optional[str] = None
    catt: Optional[str] = None
    nesp: int = 0
    tipoavv: Optional[str] = None
    sattbi: Optional[str] = None
    satt: Optional[str] = None
    sedorig: Optional[str] = None

    # =========================================================================
    # CAMPI DI LAVORO (WORKING-STORAGE: VALORIZZA-T12)
    # =========================================================================


    prgcens: Decimal = field(default_factory=lambda: Decimal("0"))
    ws_cesaavv: Optional[int] = None
    ws_annoavv: Optional[int] = None
    ws_numavv: Optional[int] = None
    ws_nck: Optional[str] = None
    ws_sol: Optional[str] = None
    ws_frateiz: Optional[str] = None


    totale_record_curt14: int = 0

    ws_sede: Optional[str] = None
    ws_cazi: Optional[str] = None
    ws_periodo: Optional[int] = None
    ws_periobi: Optional[int] = None


    ws_forzatura0: Optional[str] = None
    ws_forzatura1: Optional[str] = None

    ws_cesa: Optional[int] = None
    ws_feur: Optional[str] = None
    ws_ctrbcnc: Optional[str] = None
    ws_crat: Optional[str] = None
    ws_ntotrat: Optional[int] = None
    ws_fres: Optional[str] = None
    ws_cfasamm: Optional[str] = None

    ws_key_catt: Optional[str] = None
    ws_key_cges: Optional[str] = None
    ws_key_nprgart: Optional[int] = None

    # Indicatori di scarto e switch
    # indic_scarto_t01: str = " "
    # indic_scarto_t10: str = " "
    # indic_scarto_t14: str = " "
    # ws_erravv: str = " "
    # sw_keyavv: int = 0
    # sw_errore: int = 0

    # Dati correnti ADCAVV13
    ws_spar1: Optional[str] = None
    ws_spar2: Optional[str] = None
    ws_spar1_tds: Optional[str] = None
    ws_spar2_tds: Optional[str] = None

    ws_appo_inad: Optional[int] = 0
    ws_anno_catt: Optional[int] = 0
    ws_appo_catt: Optional[int] = 0

    @property
    def dinf_cdcfrt01(self) -> date:
        if self.sk_data_elab is None:
            return date(9999, 12, 31)
        return self.sk_data_elab

    @property
    def ws_codavv(self) -> str:
        return (
            f"{int(self.ws_cesaavv or 0) % 10**3:03d}"
            f"{int(self.ws_annoavv or 0) % 10**4:04d}"
            f"{int(self.ws_numavv or 0) % 10**8:08d}"
            f"{(self.ws_nck or '')[:2]:<2}"
            f"{(self.ws_sol or '')[:3]:<3}"
        )

    @property
    def rav_17(self) -> str:
        return (
            f"{int(self.ws_cabi or 0) % 10**5:05d}"
            f"{int(self.ws_ciderav or 0) % 10**9:09d}"
            f"{int(self.ws_cin1 or 0) % 10**1:01d}"
            f"{int(self.ws_cin2 or 0) % 10**2:02d}"
        )

    # def imp_comodi_key(self, row_t01: dict, row_t10: dict) -> None:
    #     """
    #     Reingegnerizzazione fedele del paragrafo COBOL IMP-COMODI-KEY.
    #     Inizializza registri di rottura, calcola le forzature fiscali e resetta i flag.
    #     """
    #     # CDCFRT01 -> Working Fields
    #     cges_val = row_t01.get("gestione")
    #     self.ws_cges = cges_val
    #     self.ws_cgesavv = cges_val
    #     self.n_cges = cges_val
    #
    #     self.ws_catt = ""
    #     self.n_catt = ""
    #     self.n_nprgart = row_t10.get("progArticolo")
    #
    #     self.ws_tipoavv = row_t01.get("tipoAvviso")
    #     self.ws_annoavv = row_t01.get("annoAvviso")
    #     self.ws_progavv = row_t01.get("progAvviso")
    #     self.ws_nparavv = row_t01.get("numPartitaAvviso")
    #     self.ws_sedeavv = row_t01.get("sedeOrigine")
    #     self.ws_sede = row_t01.get("sede")
    #     self.ws_zona = row_t01.get("zona")
    #     self.ws_cfis = row_t01.get("codiceFiscale")
    #     self.ws_cazi = row_t01.get("codAzienda")
    #     self.ws_periodo = row_t01.get("periodo")
    #     self.ws_periobi = row_t01.get("periodoBi")
    #     self.ws_frateiz = row_t01.get("flgRateizzazione")
    #
    #     # Gestione Forzature Fiscali (FVALFIS)
    #     fvalfis = str(row_t01.get("flgValFiscale") or "").strip()
    #     self.ws_forzatura0 = fvalfis
    #     if fvalfis == "0":
    #         self.ws_forzatura1 = "1"
    #     elif fvalfis == "1":
    #         self.ws_forzatura1 = "0"
    #     elif fvalfis == "2":
    #         self.ws_forzatura1 = "3"
    #     elif fvalfis == "3":
    #         self.ws_forzatura1 = "2"
    #     else:
    #         self.ws_forzatura1 = None
    #
    #     self.ws_cesa = row_t01.get("codEsattoria")
    #     self.ws_cesaavv = row_t01.get("codEsattoriaAvviso")
    #     self.ws_feur = row_t01.get("flgEuro")
    #
    #     # CDCFRT10 -> Working Fields
    #     self.ws_ctrbcnc = row_t10.get("codTributoCnc")
    #     self.ws_crat = row_t10.get("codRata")
    #     self.ws_ntotrat = row_t10.get("numTotRate")
    #     self.ws_fres = row_t10.get("flgResiduo")
    #     self.ws_cfasamm = row_t10.get("codFasAmm")
    #
    #     self.ws_key_catt = row_t10.get("codiceAtto")
    #     self.ws_key_cges = row_t10.get("gestione")
    #     self.ws_key_nprgart = row_t10.get("progArticolo")
    #
    #     # Reset accumulatori e indicatori per il nuovo avviso
    #     self.ws_itrbavv = Decimal("0")
    #     self.ws_iaggavv = Decimal("0")
    #     self.ws_nespavv = 0
    #     self.ws_nespart = 0
    #     self.ws_ntotpar = 0
    #     self.indic_scarto_t01 = " "
    #     self.indic_scarto_t10 = " "
    #     self.indic_scarto_t14 = " "
    #     self.ws_erravv = " "
    #     self.sw_keyavv = 0
    #     self.sw_errore = 0