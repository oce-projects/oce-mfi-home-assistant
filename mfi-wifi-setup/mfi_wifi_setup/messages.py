"""Messages of mfi_wifi_setup in Italian and English, and the language choice.

Standard library only, no tkinter: the tests import this module without a display.
"""
from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "it": {
        "title": "mFi Wi-Fi Setup",
        "step1_title": "Collega questo PC alla rete Wi-Fi del dispositivo:",
        "network_name": "rete aperta 'mFi {mac6}', senza password",
        "status_checking": "Controllo del dispositivo...",
        "status_found": "Stato: dispositivo trovato - {model}, {firmware}",
        "not_on_network": "Questo PC non è sulla rete Wi-Fi del dispositivo: collegalo alla rete 'mFi' e riprova.",
        "not_answering": "Il dispositivo non risponde. Attendi un momento e controlla che sia acceso.",
        "step2_button": "Apri la pagina del dispositivo",
        "step3_title": "Nella pagina: scegli la rete Wi-Fi di casa, scrivi la sua password e questo indirizzo del controller:",
        "copy_button": "Copia",
        "close_button": "Chiudi",
        "page_ready": "La pagina del dispositivo è aperta nel browser. Completa la configurazione lì.",
        "how_to_stop": "Per fermare il programma chiudi questa finestra.",
    },
    "en": {
        "title": "mFi Wi-Fi Setup",
        "step1_title": "Join this PC to the Wi-Fi of the device:",
        "network_name": "open network 'mFi {mac6}', no password",
        "status_checking": "Checking the device...",
        "status_found": "Status: device found - {model}, {firmware}",
        "not_on_network": "This PC is not on the Wi-Fi of the device: join the network 'mFi' and try again.",
        "not_answering": "The device does not answer. Wait a moment and check that it is switched on.",
        "step2_button": "Open the device page",
        "step3_title": "In the page: choose your home Wi-Fi, type its password and this controller address:",
        "copy_button": "Copy",
        "close_button": "Close",
        "page_ready": "The device page is open in the browser. Complete the setup there.",
        "how_to_stop": "To stop the program, close this window.",
    },
}


def choose_language(lang_code: str | None) -> str:
    """'it' for any Italian code (it, it_IT, it-CH), 'en' for every other code or None."""
    return "it" if (lang_code or "").lower().startswith("it") else "en"


def windows_language() -> str | None:
    """Windows UI language as a locale name such as 'it_IT'; None when it cannot be read."""
    try:
        import ctypes
        import locale

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lang_id)
    except Exception:
        # Not Windows, or the API is missing: the caller falls back to English.
        return None


def tr(lang: str) -> dict[str, str]:
    """Messages of one language; any unknown language gets English."""
    return MESSAGES.get(lang, MESSAGES["en"])
