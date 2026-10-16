# core/models/ad_commarea.py
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional


# =========================================================================
# ENUM / LIVELLI 88 COBOL
# =========================================================================

class codVersPagPaginazione(IntEnum):
    """Corrisponde ai livelli 88 su CAMPO5 PIC 9(01)."""
    NO_PAGINA = 0
    PAGINA_AVANTI = 1
    PAGINA_INDIETRO = 2
    PAGINA_PRIMA = 3
    PAGINA_ULTIMA = 4


class codOperazAzione(str, Enum):
    """Corrisponde ai livelli 88 su CAMPO20 PIC X(01)."""
    INSERIRE = "C"
    VARIARE = "U"
    CANCELLARE = "D"


# =========================================================================
# LIVELLI DI DETTAGLIO E SOTTO-STRUTTURE
# =========================================================================

@dataclass
class AdcampiKeyFiltri:
    """15 campiKey (Filtri per intervalli di selezione)."""
    codEsattoria_da: int = 0
    codEsattoria_a: int = 0
    annoRif_da: int = 0
    annoRif_a: int = 0
    numRuolo_da: int = 0
    numRuolo_a: int = 0
    filler: str = ""


@dataclass
class AdInput:
    """10 AD-INPUT."""
    numTab: str = ""
    lunRiga: int = 0
    numRighe: int = 0
    flgMod: int = 0
    codVersPag: int = codVersPagPaginazione.NO_PAGINA.value
    campiKey: AdcampiKeyFiltri = field(default_factory=AdcampiKeyFiltri)


@dataclass
class AdOutput:
    """10 AD-OUTPUT."""
    codMessaggio: str = ""
    numCelTot: int = 0
    flgMre: str = ""


@dataclass
class RigaTabella:
    """Elemento ripetuto 15 RIGA-TAB OCCURS 40."""
    codEsattoria: int = 0
    annoRif: int = 0
    numRuolo: int = 0
    codTributoCnc: str = ""
    annoRifCont: int = 0
    numRate: int = 0
    codRata: str = ""
    flgResiduo: str = ""
    impTributo: int = 0
    numArticoli: int = 0
    impAggioAnt: int = 0
    impAggioTot: int = 0
    impArrotondamento: int = 0
    impCarico: int = 0
    codOperaz: str = codOperazAzione.INSERIRE.value


@dataclass
class AdTabella:
    """10 AD-TABELLA."""
    righe: List[RigaTabella] = field(default_factory=list)


# =========================================================================
# STRUTTURA RADICE DELLA COMMAREA
# =========================================================================

@dataclass
class AdCommarea:
    """05 AD (Radice della struttura di comunicazione)."""
    ad_input: AdInput = field(default_factory=AdInput)
    ad_output: AdOutput = field(default_factory=AdOutput)
    ad_tabella: AdTabella = field(default_factory=AdTabella)

    # Esito chiamata (standard di ritorno di livello applicativo)
    rc_esito: int = 0
    msg_errore: str = ""