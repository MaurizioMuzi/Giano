# processes/formazione_avviso/__init__.py
"""
Package dedicato alla reingegnerizzazione del programma COBOL batch PDCFOAVV.
"""

from .processor import FormazioneAvvisoEngineProcessor

__all__ = ["FormazioneAvvisoEngineProcessor"]