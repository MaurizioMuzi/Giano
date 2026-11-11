# processes/formazione_ruoli/__init__.py
"""
Package dedicato alla reingegnerizzazione del programma COBOL batch PDCFORUO.
"""

from .processor import FormazioneRuoliEngineProcessor

__all__ = ["FormazioneRuoliEngineProcessor"]