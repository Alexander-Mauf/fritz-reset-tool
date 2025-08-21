import time
import requests
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from functools import wraps
import re
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

from browser_utils import Browser


FRITZ_DEFAULT_URL = "http://fritz.box"


class FirmwareManager:
    """Verwaltet Firmware-Dateien und deren Pfade für mehrstufige Updates."""

    def __init__(self):
        self.firmware_mapping = {
            "7590": {
                "bridge": "07.59",
                "final": "08.20",
                "bridge_file": "FRITZ.Box_7590-07.59.image",
                "final_file": "FRITZ.Box_7590-08.20.image"
            },
            "7590_AX": {
                "final": "08.02",
                "final_file": "FRITZ.Box_7590-AX-08.02.image"
            },
            "7530": {
                "final": "08.02",
                "final_file": "FRITZ.Box_7530-08.02.image"
            },
            "7490": {
                "final": "07.60",
                "final_file": "FRITZ.Box_7490-07.60.image"
            },
            "7582": {
                "final": "07.18",
                "final_file": "FRITZ.Box_7582-07.18.image"
            },
            "6660": {
                "final": "08.03",
                "final_file": "FRITZ.Box_6660_Cable-08.03.image"
            },
            "6890": {
                "final": "07.57",
                "final_file": "FRITZ.Box_6890_LTE-07.57.image"
            }
        }

    def _select_firmware_path_manually(self):
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Firmware Image", "*.image")]
        )
        root.destroy()
        return file_path

    def get_firmware_path(self, box_model: str, version_type: str = "final") -> str | None:
        """
        Sucht den Pfad für einen bestimmten Versionstyp ("bridge" or "final").
        """
        if not box_model or box_model not in self.firmware_mapping:
            print(f"⚠️ Kein Firmware-Eintrag für Modell '{box_model}' bekannt. Manuelle Auswahl.")
            return self._select_firmware_path_manually()

        model_files = self.firmware_mapping[box_model]
        file_key = f"{version_type}_file" # z.B. "bridge_file" oder "final_file"

        if file_key not in model_files:
            print(f"⚠️ Kein '{version_type}'-Update für Modell {box_model} definiert. Manuelle Auswahl.")
            return self._select_firmware_path_manually()

        firmware_filename = model_files[file_key]

        try:
            current_dir = Path(sys.argv[0]).parent
        except Exception:
            current_dir = Path.cwd()

        firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename
        print(f"ℹ️ Suche {version_type}-Firmware für {box_model} unter: {firmware_path_auto}")

        if firmware_path_auto.is_file():
            print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            return str(firmware_path_auto)
        else:
            print(f"❌ Firmware-Datei nicht gefunden. Bitte manuell auswählen.")
            return self._select_firmware_path_manually()


def require_login(func):
    """
    Decorator, der sicherstellt, dass vor der Ausführung der Funktion ein Login besteht.
    Versucht bei Bedarf automatisch einen erneuten Login.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # 'self' ist hier die Instanz der FritzBox-Klasse
        print(f"🕵️  Login-Prüfung für die Funktion '{func.__name__}'...")

        if not self.is_logged_in_and_menu_ready(timeout=2):
            print("⚠️ Session abgelaufen oder nicht eingeloggt. Versuche automatischen Re-Login...")

            # Die login() Methode verwendet das gespeicherte Passwort (self.password)
            if self.login(self.password):
                print("✅ Re-Login war erfolgreich.")
            else:
                print(f"❌ Der automatische Re-Login ist fehlgeschlagen. Breche '{func.__name__}' ab.")
                return False  # Signalisiert den Fehlschlag an den WorkflowOrchestrator

        # Wenn der Login besteht (oder der Re-Login erfolgreich war), führe die eigentliche Funktion aus
        return func(self, *args, **kwargs)

    return wrapper




class FritzBox:
    """Repräsentiert eine FritzBox und kapselt ihre Interaktionen."""

    def __init__(self, browser: Browser):
        if not isinstance(browser, Browser):
            raise TypeError("Der übergebene Browser muss eine Instanz der Browser-Klasse sein.")
        self.browser = browser
        self.url = FRITZ_DEFAULT_URL
        self.os_version = None
        self.is_reset = False
        self.language = None
        self.is_logged_in = False
        self.password = None
        self.box_model = None
        self.is_wifi_checked = False
        self.wlan_scan_results = []
        self.firmware_manager = FirmwareManager()

    def warte_auf_erreichbarkeit(self, versuche=20, delay=5) -> bool:
        """Wartet, bis die FritzBox unter einer bekannten IP erreichbar ist."""
        ip_list = [
            "http://fritz.box",
            "http://192.168.178.1",
            "http://169.254.139.1",
            "http://169.254.1.1",
        ]

        print("🔍 Suche erreichbare FritzBox...")

        for _ in range(versuche):
            for url in ip_list:
                try:
                    r = requests.get(url, timeout=3, verify=False, allow_redirects=False)
                    if r.status_code == 200:
                        self.url = url
                        print(f"✅ FritzBox erreichbar unter {url}")
                        return True
                except requests.exceptions.ConnectionError:
                    pass
                except Exception as e:
                    print(f"Fehler beim Prüfen der URL {url}:")
            time.sleep(delay)

        print("❌ FritzBox nicht erreichbar.")
        return False

    def _check_if_login_required(self) -> bool:
        """Interne Methode: Prüft, ob das Passwortfeld auf der aktuellen Seite vorhanden ist."""
        try:
            return bool(self.browser.sicher_warten('//*[@id="uiPass" or @type="password"]', timeout=1, sichtbar=False))
        except Exception:
            return False

    def _handle_language_selection(self) -> bool:
        """Interne Methode: Behandelt die Sprachauswahl, falls sie erscheint."""
        try:
            # Hier keinen get_url aufruf! wird vor dem aufruf im login gemacht
            # Prüfe, ob Sprachauswahl-Elemente da sind
            if self.browser.sicher_warten('//*[@id="uiLanguage-de"]', timeout=2, sichtbar=False):
                print("🌐 Sprachauswahl erkannt. Setze auf Deutsch...")
                if self.browser.klicken('//*[@id="uiLanguage-de"]'):
                    if self.browser.klicken('//*[@id="submitLangBtn"]'):
                        time.sleep(3)
                        self.language = "de"
                        return True
                    print("⚠️ 'Sprache übernehmen'-Button nicht klickbar.")
                print("⚠️ Sprachauswahl-Button nicht klickbar.")
            else:
                print("ℹ️ Keine Sprachauswahl erkannt.")
        except Exception:
            print("⚠️ Sprachauswahl konnte nicht verarbeitet werden.")
        return False

    def is_main_menu_loaded_and_ready(self, timeout=5) -> bool:
        """
        Prüft, ob die Hauptmenüstruktur der FritzBox geladen und interaktiv ist.
        Sucht nach Schlüssel-Menüpunkten wie WLAN, System etc.
        """
        menu_xpaths = [
            '//*[@id="wlan"]',
            '//*[@id="sys"]',
            '//*[@id="internet"]',
            '//*[@id="home"]',
        ]
        # print(f"🔍 Prüfe auf geladenes und klickbares Hauptmenü (Timeout: {timeout}s)...")
        for xpath in menu_xpaths:
            try:
                element = self.browser.sicher_warten(xpath, timeout=timeout/len(menu_xpaths) if menu_xpaths else timeout, sichtbar=True)
                if element and element.is_displayed() and element.is_enabled():
                    # print(f"✅ Hauptmenü-Element '{xpath}' gefunden und bereit.")
                    return True
            except Exception:
                pass
        # print("❌ Hauptmenü nicht gefunden oder nicht bereit.")
        return False

    def is_logged_in_and_menu_ready(self, timeout=5) -> bool:
        """
        Prüft, ob der Browser auf einer FritzBox-Seite ist, auf der man eingeloggt ist
        und das Hauptmenü sichtbar und interaktiv ist.
        Aktualisiert self.is_logged_in.
        """
        # print(f"🔍 Prüfe Login-Status und Menübereitschaft (Timeout: {timeout}s)...")
        if self._check_if_login_required():
            # print("ℹ️ Login-Feld gefunden. Nicht eingeloggt oder ausgeloggt.")
            self.is_logged_in = False
            return False

        if self.is_main_menu_loaded_and_ready(timeout=timeout):
            # print("✅ Eingeloggt und Hauptmenü bereit.")
            self.is_logged_in = True
            return True
        else:
            # print("❌ Weder Login-Feld noch Hauptmenü erkannt. Unerwarteter Zustand.")
            self.is_logged_in = False
            return False

    def login(self, password: str, force_reload=False) -> bool:
        """
        Führt den Login durch und arbeitet alle nachfolgenden Dialoge in einer
        robusten Schleife ab, bis das Hauptmenü erreichbar ist.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Login.")
            return False
        if password is not None and password != "":
            self.password = password
        if self.browser.driver is None:
            print("⚠️ Browser-Instanz fehlt – starte neue WebDriver-Instanz...")
            try:
                from browser_utils import setup_browser, Browser
                new_driver = setup_browser()
                self.browser = Browser(new_driver)
                print("✅ Neuer Browser gestartet.")
            except Exception as e:
                print(f"❌ Konnte keine neue Browser-Instanz erstellen: {e}")
                return False
        print("Reload der startseite")
        self.browser.reload(self.url)
        print("🔐 Login wird versucht...")


        if not force_reload and self.is_logged_in_and_menu_ready(timeout=3):
            print("✅ Bereits eingeloggt und Hauptmenü bereit.")
            return True

        # gelegentlich gibt es boxen, die keine PW nach reset haben, sondern mal muss es selbst vergeben
        # zuerst kommt Bitte drücken Sie kurz eine beliebige Taste an Ihrer FRITZ!Box, um sich anzumelden.
        # --- NEU: Prüfen auf "Bitte Taste drücken"-Dialog ---
        try:
            text_xpath = '//div[@class="dialog_content"]//p[contains(text(),"Bitte drücken Sie kurz eine beliebige Taste")]'
            self.browser.sicher_warten(text_xpath, timeout=5)
            print("⚠️ℹ️⚠️ FritzBox verlangt physischen Tastendruck zur Anmeldung.")
            print("👉 Bitte jetzt Taste an der Box drücken...")
            tries = 0

        except Exception:
            print("Kein physischer Tastendruck-Dialog gefunden. Fahre normal fort...")

        try:
            self.browser.sicher_warten('//*[@id="uiPass-input"]')
            self.browser.schreiben('//*[@id="uiPass-input"]', self.password)
            self.browser.klicken('//button[contains(text(),"OK")]')
            self.browser.klicken('//*[@id="uiApply"]')
            print("✅ 'OK'-Button gefunden und geklickt. Prozess wird fortgesetzt.")
            print(f"Es wurde ein Passwort gesetzt: {self.password}")
            self.browser.reload(self.url)
        except:
            print("Box hat ein existentes Passwort.")

        while True:
            self.browser.get_url(self.url)
            self._handle_language_selection()
            try:
                self.browser.sicher_warten('//*[@id="uiPass"]')
                break
            except Exception:
                print("Password Feld nicht gefunden. Rufe Seite erneut auf.")

        if self._check_if_login_required():
            try:
                self.browser.schreiben('//*[@id="uiPass"]', self.password)
                self.browser.klicken('//*[@id="submitLoginBtn"]')
            except Exception as e:
                print(f"❌ Fehler bei der initialen Login-Eingabe:")
                return False
        else:
            print("ℹ️ Kein Login-Feld gefunden. Gehe davon aus, dass ein initialer Dialog aktiv ist.")

        # --- FINALE DIALOG-SCHLEIFE (HYBRID-MODELL) ---
        max_dialog_attempts = 15
        print("...starte Abarbeitung aller möglichen Dialoge...")
        dialog_handlers = [
            self.continue_setup,
            self.dsl_setup_init,
            self.handle_registration_dialog,
            self.neue_firmware_dialog,
            self.checkbox_fehlerdaten_dialog,
            self.skip_configuration,
        ]

        for attempt in range(max_dialog_attempts):
            print(f"   (Dialog-Runde {attempt + 1}/{max_dialog_attempts})")

            if self.is_logged_in_and_menu_ready(timeout=2):
                print("✅ Login erfolgreich und Hauptmenü zugänglich.")
                self.is_logged_in = True
                return True

            if self._check_if_login_required():
                print("❌ Zurück auf der Login-Seite. Der Login ist fehlgeschlagen.")
                self.is_logged_in = False
                return False

            # Versuche, einen der spezifischen Dialoge zu behandeln
            action_taken = False
            for handler in dialog_handlers:
                if handler():
                    action_taken = True
                    break

            if not action_taken:
                print("   ...kein spezifischer Dialog gefunden, versuche generischen Fallback.")
                self._handle_any_dialog_button()


        print("❌ Login-Vorgang abgebrochen: Nach mehreren Versuchen konnte das Hauptmenü nicht erreicht werden.")
        self.is_logged_in = False
        return False


    def continue_setup(self) -> bool:
        """prüft am Anfang, ob ein 'einrichtung fortsetzen' dialog aufgeht und beendet diesen"""
        try:
            btn = self.browser.sicher_warten('//button[contains(translate(text(), "Einrichtung jetzt beenden", "einrichtung jetzt beenden"), "einrichtung jetzt beenden")]')
            btn.click()
            print("Clicking the Einrichtung jetzt beenden Button.")
        except:
            return False

        try:
            btn = self.browser.sicher_warten('//button[contains(translate(text(), "Einrichtung abschließen", "einrichtung abschließen"), "einrichtung abschließen")]')
            btn.click()
            print("Clicking the Einrichtung abschließen Button.")
        except:
            return False

        return True


    def _handle_any_dialog_button(self) -> bool:
        """
        Sucht nach einer Liste von generischen "positiven" Buttons (OK, Weiter, etc.)
        und klickt den ersten, den er findet. Gibt True zurück, wenn ein Klick erfolgte.
        """
        # Priorisierte Liste von Buttons. Spezifische IDs und Namen zuerst.
        positive_buttons_xpaths = [
            '//*[@id="uiApply"]',
            '//button[@name="apply"]',  # <--- NEU basierend auf deinem Feedback
            '//*[@id="uiForward"]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "fortschritt anzeigen")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "fortschritt anzeigen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ", "abcdefghijklmnopqrstuvwxyzäöü"), "schritt überspringen")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ", "abcdefghijklmnopqrstuvwxyzäöü"), "schritt überspringen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "schritt abschließen")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "schritt abschließen")]',
            '//button[contains(translate(text(), "OK", "ok"), "ok")]',
            '//a[contains(translate(text(), "OK", "ok"), "ok")]',
            '//button[contains(translate(text(), "ÜBERNEHMEN", "übernehmen"), "übernehmen")]',
            '//button[contains(translate(text(), "FERTIGSTELLEN", "fertigstellen"), "fertigstellen")]',
            '//*[@id="submit_button"]',
            '//*[@id="Button1"]'
        ]

        for xpath in positive_buttons_xpaths:
            # Wir nutzen einen sehr kurzen Timeout, da wir nur prüfen, ob der Button gerade da ist.
            if self.browser.klicken(xpath, timeout=0.5, versuche=1, verbose=False):
                print(f"✅ Generischen Dialog-Button geklickt: {xpath}")
                return True
        return False

    def neue_firmware_dialog(self) -> bool:
        """Behandelt den Dialog 'Neue Firmware wurde installiert'."""
        try:
            # Suchen nach einem eindeutigen Text oder Button dieses Dialogs
            if self.browser.sicher_warten('//h1[contains(text(), "FRITZ!OS wurde aktualisiert")]', timeout=1, sichtbar=False):
                print("...behandle 'Firmware aktualisiert'-Dialog.")
                # Klickt auf OK oder Weiter
                self.browser.klicken('//button[contains(text(), "OK")] | //a[contains(text(), "Weiter")]', timeout=3, versuche=1)
                return True
        except Exception:
            pass # Element nicht gefunden, also war dieser Dialog nicht da.
        return False

    def dsl_setup_init(self) -> bool:
        """Behandelt den initialen DSL-Einrichtungs-Assistenten."""
        try:
             # Dieser Assistent wird oft durch den "Weiter"-Button mit der ID 'uiForward' eingeleitet
            if self.browser.sicher_warten('//*[@id="uiForward"]', timeout=1, sichtbar=False):
                print("...behandle initialen DSL-Setup-Dialog.")
                try:
                    print("Versuche den Schritt zu überspringen.")
                    self.browser.klicken('//*[@id="uiSkip"]', timeout=3, versuche=1)
                    # es kann auch das element //*[@id="Button1"] sein nur wenn beides fehlschlägt sollte der workflow in der exception getriggert werden
                except Exception:
                    print("skip hat nicht funktioniert, versuche nun generischen anbieter auszuwählen")
                    try:
                        # Dropdown-Element auswählen
                        dropdown = Select(self.browser.find_element_by_xpath('//*[@id="uiSuperprovider"]'))
                        # Wert auf "more" setzen
                        dropdown.select_by_value("more")
                        print("Generischen Anbieter ausgewählt.")
                    except Exception as e:
                        print(f"Fehler beim Auswählen des Anbieters: {e}")

                self.browser.klicken('//*[@id="uiForward"]', timeout=3, versuche=1)
                return True
        except Exception:
            pass
        return False

    def checkbox_fehlerdaten_dialog(self) -> bool:
        """Behandelt den Dialog zum Senden von Fehlerdiagnosedaten."""
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=1)
            print("...behandle Fehlerdaten-Dialog.")
            if checkbox.is_selected():
                checkbox.click()
            # Klickt danach auf "Übernehmen"
            self.browser.klicken('//*[@id="uiApply"]')
            return True
        except Exception:
            pass
        return False

    def _close_any_overlay(self) -> bool:
        """
        Sucht nach einem generischen "Schließen"-Button und klickt ihn, falls vorhanden.
        Diese Version ist "crash-sicher" und verursacht keinen Fehler, wenn nichts gefunden wird.
        """
        try:
            # Wir verwenden find_elements (plural), was eine leere Liste zurückgibt statt einen Fehler zu werfen.
            close_buttons = self.browser.driver.find_elements(By.XPATH,
                                                              '//button[.//div[text()="Schließen"] or text()="Schließen"]')

            # Nur wenn die Liste nicht leer ist, also ein Button gefunden wurde:
            if close_buttons:
                print("...generisches Overlay gefunden, versuche es zu schließen.")
                # Klicke den ersten gefundenen Button mit einem sicheren JS-Klick
                self.browser.driver.execute_script("arguments[0].click();", close_buttons[0])
                print("✅ Generisches Overlay geschlossen.")
                time.sleep(1)
                return True
        except Exception as e:
            # Fängt alle anderen möglichen Fehler ab, um Abstürze zu vermeiden.
            print(f"⚠️ Kleiner Fehler beim Versuch, ein Overlay zu schließen (wird ignoriert):")
            pass
        return False

    def handle_registration_dialog(self) -> bool:
        """Behandelt den "Informiert bleiben"-Dialog."""
        try:
            # Eindeutiger Text dieses Dialogs
            if self.browser.sicher_warten('//h1[contains(text(), "Informiert bleiben")]', timeout=1, sichtbar=False):
                print("...behandle 'Informiert bleiben'-Dialog.")
                # Klickt auf OK
                self.browser.klicken('//*[@id="content"]/div[2]/button[1]', timeout=3, versuche=1)
                return True
        except Exception:
            pass  # Dialog war nicht da.
        return False

    def skip_configuration(self) -> bool:
        """Behandelt generische Konfigurations-Dialoge mit einem "Schließen" oder "OK" Button."""
        try:
             # Dieser Dialog hat oft einen allgemeinen Button mit ID "Button1"
            if self.browser.sicher_warten('//*[@id="Button1"]', timeout=1, sichtbar=False):
                print("...überspringe generischen Konfigurations-Dialog.")
                btn = self.browser.sicher_warten('//*[@id="Button1"]', timeout=1, sichtbar=False)
                try:
                    btn.click()
                except Exception:
                    try:
                        self.browser.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        self.browser.driver.execute_script("arguments[0].click();", btn)
                        print("✅ OK-Button via JavaScript-Klick gedrückt.")
                    except Exception as e:
                        print(f"❌ OK-Button konnte auch via JS nicht gedrückt werden: {e}")
                        return False
                return True
        except Exception:
            pass
        return False

    def reset_via_forgot_password(self):
        """
        Führt einen Werksreset über den 'Passwort vergessen' / 'Kennwort vergessen'-Flow aus.
        Gibt False zurück, wenn der Ablauf nicht durchgeführt werden konnte.
        Beendet NICHT mehr das Programm, falls der Button nicht verfügbar ist.
        """
        print("🚨 Werkseinstellungen einleiten (via 'Passwort vergessen')...")

        kandidaten_xpaths = [
            '//*[@id="dialogFoot"]/a',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "kennwort vergessen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "kennwort vergessen")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "kennwort vergessen")]',
        ]

        # Schritt 1: Link/Button finden und klicken
        found_reset_link = False
        for xpath in kandidaten_xpaths:
            try:
                if self.browser.klicken(xpath, timeout=5, versuche=1):
                    print(f"🔁 Reset-Link gefunden und geklickt ({xpath})")
                    found_reset_link = True
                    break
            except Exception:
                continue

        if not found_reset_link:
            print("❌ Kein Reset-Link gefunden – Werksreset via Passwort vergessen nicht möglich.")
            return False

        # Schritt 2: Auf sendFacReset warten und klicken
        max_versuche = 3
        for attempt in range(1, max_versuche + 1):
            try:
                btn = self.browser.sicher_warten('//*[@id="sendFacReset"]', timeout=8, sichtbar=True)

                # Versuche normalen Klick
                try:
                    btn.click()
                except Exception:
                    # Fallback: Scroll + JS-Klick
                    try:
                        self.browser.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        self.browser.driver.execute_script("arguments[0].click();", btn)
                        print("✅ sendFacReset via JavaScript-Klick ausgelöst.")
                    except Exception as e:
                        print(f"❌ Klick auf sendFacReset fehlgeschlagen: {e}")
                        continue

                print("🔁 Reset ausgelöst, warte auf Neustart...")
                time.sleep(50)
                return True

            except Exception:
                print(f"⚠️ Element //*[@id='sendFacReset'] nicht gefunden (Versuch {attempt}/{max_versuche})")
                # Falls Seite hängen geblieben ist, versuche sanftes Reload ohne Cookies zu löschen
                self.browser.reload(self.url, clear_cookies=False)

        # Schritt 3: Falls der Button gar nicht kommt → nur Info, kein Exit
        print("⚠️ Reset konnte nicht ausgelöst werden – Button 'sendFacReset' nicht verfügbar. "
              "Möglicherweise war die Box zu lange an oder ist schon neu gestartet.")
        return None # damit der Workflow nicht hart abbricht, falls nicht gefunden

    @require_login
    def activate_expert_mode_if_needed(self) -> bool:
        """
        Prüft, ob der "FRITZ!OS-Datei"-Reiter klickbar ist. Wenn nicht, wird die
        erweiterte Ansicht aktiviert. Dies ist die zuverlässigste Methode.
        """
        print("🔍 Prüfe, ob erweiterte Ansicht aktiv ist (via Update-Reiter-Status)...")
        if not self.os_version: return True

        # Extrahiert die Versionsnummer, um zu entscheiden, ob die Prüfung nötig ist
        match = re.search(r'(\d{1,2})\.(\d{2})', self.os_version)
        if not match: return True
        major, minor = int(match.group(1)), int(match.group(2))

        # Bei alten Versionen ist die erweiterte Ansicht oft nicht standardmäßig aktiv
        if major < 7 or (major == 7 and minor < 15):
            try:
                print("...navigiere zur Update-Seite, um den Status zu prüfen.")
                # VERSUCH 1: Klicke direkt auf "Update", falls Menü schon offen ist
                if not self.browser.klicken('//*[@id="mUp"]', timeout=2, versuche=1):
                    # VERSUCH 2: Wenn das fehlschlägt, klicke erst auf "System" und dann auf "Update"
                    print("...'Update'-Menü nicht direkt sichtbar, öffne 'System'-Menü.")
                    if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
                    time.sleep(1)
                    if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False

                time.sleep(2)  # Warten, bis die Seite und ihre Elemente geladen sind

                # Prüfe den Zustand des "FRITZ!OS-Datei"-Reiters
                try:
                    update_tab = self.browser.sicher_warten('//*[@id="userUp"]', timeout=5)
                    print("✅ Erweiterte Ansicht ist bereits aktiv.")
                except:
                    print("...'FRITZ!OS-Datei' ist deaktiviert. Aktiviere erweiterte Ansicht.")
                    # Menü (Burger-Icon) öffnen
                    menu_icon = self.browser.sicher_warten('//*[@id="blueBarUserMenuIcon"]', timeout=5)
                    self.browser.driver.execute_script("arguments[0].click();", menu_icon)
                    WebDriverWait(self.browser.driver, 5).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//*[@id="blueBarUserMenuIcon" and @aria-expanded="true"]'))
                    )
                    # Link für erweiterte Ansicht klicken
                    expert_link = self.browser.sicher_warten('//a[@id="expert"]', timeout=5)
                    self.browser.driver.execute_script("arguments[0].click();", expert_link)
                    print("✅ 'Erweiterte Ansicht' erfolgreich umgeschaltet.")
                    time.sleep(3)

                # Zurück zur Hauptseite für einen sauberen Zustand
                self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
                return True

            except Exception as e:
                print(f"❌ Fehler beim Prüfen/Umschalten der erweiterten Ansicht:")
                return False
        else:
            print("✅ Version ist aktuell genug, keine Prüfung der erweiterten Ansicht nötig.")
            return True

    @require_login
    def perform_factory_reset_from_ui(self) -> bool:
        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            # -------------------------
            # ALT: Klassischer Workflow
            # -------------------------
            print("➡️ Versuche klassischen Workflow...")
            if self._factory_reset_classic():
                return True
            print("❌ Klassischer Workflow fehlgeschlagen – versuche neuen JS3-Workflow...")

            # -------------------------
            # NEU: JS3 Workflow
            # -------------------------
            if self._factory_reset_js3():
                return True
            else:
                print("❌ Auch der JS3-Workflow ist fehlgeschlagen.")
                return False

        except Exception as e:
            print(f"❌ Unerwarteter Fehler: {e}")
            return False

    def _factory_reset_classic(self) -> bool:
        """Alter Workflow mit erstem OK-Dialog"""
        try:
            if not self.browser.klicken('//*[@id="mSave"]', timeout=2, versuche=1):
                if not self.browser.klicken('//*[@id="sys"]', timeout=5):
                    return False
                time.sleep(1)
                if not self.browser.klicken('//*[@id="mSave"]', timeout=5):
                    return False
            time.sleep(1)

            self.browser.klicken('//*[@id="default"]')
            time.sleep(1)

            if not (self.browser.klicken('//*[@id="uiDefaults"]', timeout=3, versuche=1) or
                    self.browser.klicken('//*[@id="content"]/div/button', timeout=3, versuche=1) or
                    self.browser.klicken('//a[contains(text(),"Werkseinstellungen laden")]', timeout=3, versuche=1)):
                return False
            time.sleep(2)

            if not self.browser.klicken('//*[@id="Button1"]', timeout=5):
                return False
            print("✅ Klassischer Workflow: Erster OK-Dialog bestätigt.")

            return self._wait_for_physical_button()
        except Exception:
            return False

    def _factory_reset_js3(self) -> bool:
        """Neuer Workflow mit Tile + Dialog (robust für Shadow DOM / JS3)."""
        try:
            # --- Schritt 1: Tile klicken ---
            clicked = False
            tile_selectors = [
                '#js3ContentBox js3-view article div:nth-child(2) js3-tile a',  # Shadow DOM Pfad
                '//a[contains(text(),"Werkseinstellungen laden")]'  # Fallback XPath
            ]
            for sel in tile_selectors:
                try:
                    # Versuche erst JS-Clique über querySelector
                    if sel.startswith('#'):
                        self.browser.driver.execute_script(
                            f"document.querySelector('{sel}').click()"
                        )
                        clicked = True
                        print(f"✅ JS3 Workflow: Tile geklickt via querySelector: {sel}")
                        break
                    else:
                        # Klassischer XPath-Fallback
                        clicked = self.browser.klicken(sel, timeout=5, versuche=1)
                        if clicked:
                            print(f"✅ JS3 Workflow: Tile geklickt via XPath: {sel}")
                            break
                except Exception:
                    continue
            if not clicked:
                print("❌ JS3 Workflow: Konnte Tile nicht finden.")
                return False
            time.sleep(1)

            # --- Schritt 2: Dialog-Knopf klicken ---
            clicked = False
            dialog_selectors = [
                '#js3ContentBox js3-dialog js3-button:nth-child(1) button',  # Shadow DOM Pfad
                '//button[contains(text(),"Werkseinstellungen laden")]',  # Fallback XPath
            ]
            for sel in dialog_selectors:
                try:
                    if sel.startswith('#'):
                        self.browser.driver.execute_script(
                            f"document.querySelector('{sel}').click()"
                        )
                        clicked = True
                        print(f"✅ JS3 Workflow: Dialog-Knopf geklickt via querySelector: {sel}")
                        break
                    else:
                        clicked = self.browser.klicken(sel, timeout=5, versuche=1)
                        if clicked:
                            print(f"✅ JS3 Workflow: Dialog-Knopf geklickt via XPath: {sel}")
                            break
                except Exception:
                    continue
            if not clicked:
                print("❌ JS3 Workflow: Dialog-Knopf nicht gefunden.")
                return False

            # --- Schritt 3: Warten auf physischen Knopf ---
            return self._wait_for_physical_button()

        except Exception as e:
            print(f"❌ JS3 Workflow fehlgeschlagen: {e}")
            return False

    def _wait_for_physical_button(self) -> bool:
        """Gemeinsamer Schritt: physischen Knopf drücken und finalen OK bestätigen"""
        print("⚠️ Bitte jetzt physischen Knopf an der Box drücken...")

        ok_xpath = '//button[contains(text(),"OK")]'
        retry_xpath = '//button[contains(text(),"Wiederholen") or contains(text(),"Retry")]'

        tries = 0
        while True:
            try:
                btn = self.browser.sicher_warten(ok_xpath, timeout=180, sichtbar=True)
                time.sleep(2)
                btn.click()
                print("✅ 'OK'-Button gefunden und geklickt. Prozess wird fortgesetzt.")
                break
            except Exception:
                print("⏳ 'OK'-Button nicht im Zeitfenster gefunden. Suche nach Fallback...")
                try:
                    retry_btn = self.browser.sicher_warten(retry_xpath, timeout=5, sichtbar=True)
                    retry_btn.click()
                    print("🔁 'Wiederholen/Retry' geklickt. Starte neuen Suchlauf für 'OK'.")
                except Exception:
                    print("❌ Kein interaktives Element gefunden. Warte 10s und versuche es erneut.")
                    time.sleep(10)
            tries += 1
            if tries > 8:
                print("❌ 'OK' nach physischem Knopf nicht auffindbar – breche Reset ab.")
                return False

        print("...warte auf Neustart der Box (kann einige Minuten dauern).")
        time.sleep(45)  # Grundwartezeit
        if self.warte_auf_erreichbarkeit(versuche=40, delay=10):
            print("✅ Box ist nach dem Reset wieder erreichbar.")
            if self.ist_sprachauswahl():
                print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt (Sprachauswahl erkannt).")
                return True
            else:
                print("✅ Reset-Vorgang abgeschlossen (Standard-Login erkannt).")
                return True
        else:
            print("❌ Box ist nach dem Reset nicht wieder erreichbar.")
            return False

    @require_login
    def get_firmware_version(self) -> str | bool:
        """Ermittelt die aktuelle Firmware-Version der FritzBox, inkl. JS3-Input für 08.20+."""
        print("ℹ️ Ermittle Firmware-Version...")
        self._close_any_overlay()
        try:
            if not self.is_logged_in_and_menu_ready():
                print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für Versionsprüfung erforderlich.")
                return False

            # Zur Sicherheit zur Hauptseite, dann ins Menü
            self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
            time.sleep(1)
            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False

            version_text = ""

            # --- Neuer JS3-Input Ansatz (z.B. 08.20) ---
            try:
                # Warte, bis das Input-Feld sichtbar ist
                input_elem = self.browser.sicher_warten('//input[@name="fritzOsVersion"]', timeout=5, verbose=True)
                # DAS HIER MUSS ALTERNATIV MIT JS VERSUCHT WERDEN!
                # Wert aus dem 'value'-Attribut auslesen
                version_text = input_elem.get_attribute("value")

                if version_text:
                    print(f"✅ Firmware-Version gefunden: {version_text}")
            except Exception:
                try:
                    # --- JS-Fallback: direktes Abfragen des value im DOM ---
                    js_code = """
                        let input = document.querySelector('input[name="fritzOsVersion"]');
                        return input ? input.value : '';
                        """
                    version_text = self.browser.driver.execute_script(js_code)
                    if version_text:
                        print(f"✅ Firmware-Version gefunden (JS-Fallback): {version_text}")
                    else:
                        print("❌ JS-Fallback konnte keine Firmware-Version finden.")
                except Exception as e:
                    print(f"❌ JS-Fallback Fehler: {e}")

            # --- Klassische Fallbacks ---
            if not version_text:
                try:
                    primary_selector = '//*[@class="fakeTextInput" or contains(@class, "version_text")]'
                    version_elem = self.browser.sicher_warten(primary_selector, timeout=3)
                    version_text = version_elem.text.strip()
                except Exception:
                    try:
                        fallback_selector = '//*[@id="content"]/div[1]/div[div[contains(text(), "FRITZ!OS")]]'
                        version_elem = self.browser.sicher_warten(fallback_selector, timeout=5)
                        full_text = version_elem.text.strip()
                        match = re.search(r'(\d{1,2}\.\d{1,2})', full_text)
                        if match:
                            version_text = match.group(1)
                    except Exception:
                        pass

            if version_text:
                self.os_version = version_text
                print(f"✅ Firmware-Version: {self.os_version}")
                return self.os_version
            else:
                print("❌ Keine Firmware-Version gefunden auf der Update-Seite.")
                return False

        except Exception as e:
            print(f"❌ Fehler beim Ermitteln der Firmware-Version: {e}")
            return False

    @require_login
    def get_box_model(self) -> str | bool:
        """
        Ermittelt das Fritzbox-Modell mit einer robusten 3-Stufen-Strategie.
        Gibt bei Fehlschlag False zurück, um den Workflow korrekt zu steuern.
        """
        print("🔍 Ermittle Box-Modell (robuste Methode)...")
        self._close_any_overlay()

        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt. Login für Modellermittlung erforderlich.")
            return False

        # --- Stufe 1: Suche auf der aktuellen Seite ---
        print("   (Stufe 1/3: Suche auf aktueller Seite)")
        xpaths_to_check = [
            '//*[@id="blueBarTitel"]',
            '//span[contains(@class, "version_text")]',
            '//div[@class="boxInfo"]/span',
            '//*[@id="uiVersion"]/div/div'
        ]
        for xpath in xpaths_to_check:
            try:
                element = self.browser.sicher_warten(xpath, timeout=3, sichtbar=False)
                model = self._extract_model_number(element)
                if model:
                    self.box_model = model
                    print(f"✅ Box-Modell: {self.box_model} (gefunden auf aktueller Seite).")
                    return self.box_model
            except Exception:
                continue

        print("   (Stufe 2/3: Suche auf Übersichtsseite)")
        if self.browser.klicken('//*[@id="overview"] | //*[@id="mHome"]', timeout=3):
            time.sleep(2)
            for xpath in xpaths_to_check:
                try:
                    element = self.browser.sicher_warten(xpath, timeout=3, sichtbar=False)
                    model = self._extract_model_number(element)
                    if model:
                        self.box_model = model
                        print(f"✅ Box-Modell: {self.box_model} (gefunden auf Übersichtsseite).")
                        return self.box_model
                except Exception:
                    continue


        print("❌ Box-Modell konnte nicht identifiziert werden.")
        self.box_model = "UNKNOWN"
        return False  # KORREKTUR: Bei Fehlschlag False zurückgeben, nicht None.

    def _extract_model_number(self, element) -> str | None:
        """
        Extrahiert die 4-stellige Modellnummer aus dem textContent eines Elements.
        Diese Methode ist zuverlässiger als .text für unsichtbare Elemente.
        """
        try:
            # .get_attribute("textContent") liest Text auch aus versteckten Elementen
            text_content = element.get_attribute("textContent").strip()

            # Dieser Regex sucht einfach nach der ersten 4-stelligen Zahl.
            match = re.search(r'(\d{4,})', text_content)
            if match:
                model_number = match.group(1)
                # Fall für LTE-Modelle
                if int(model_number) == 6890:
                    return f"{model_number}_LTE"
                if "LTE" in text_content:
                    return f"{model_number}_LTE"
                self.model = model_number
                return model_number
        except Exception:
            return None
        return None

    def dsl_setup_wizard(self) -> bool:
        """Durchläuft den DSL-Setup-Wizard (falls er nach einem Reset/Update erscheint)."""
        print("⚙️ Prüfe auf und durchlaufe Setup-Wizard (DSL)...")
        # Hier auch prüfen, ob eingeloggt, falls der Wizard nach einem Login erscheint, aber nicht direkt nach Reset.
        # Wenn der Wizard direkt nach Reset kommt, ist kein Login möglich, daher ist diese Prüfung optional.
        # if not self.is_logged_in_and_menu_ready():
        #    print("❌ Nicht eingeloggt. Wizard kann ggf. nicht behandelt werden.")
        #    return False

        try:
            # Versuche zuerst, den Direktlink zum Überspringen zu finden/klicken
            if self.browser.klicken('//*[@id="dlg_welcome"]/p[3]/a', timeout=5):
                print("✅ Direktlink zum Überspringen des Wizards gefunden und geklickt.")
                time.sleep(2)
                return True
            else:
                print("⚠️ Kein Direktlink zum Überspringen – versuche manuellen Ablauf des Wizards.")
                wizard_xpaths = [
                    '//*[@id="uiForward"]',
                    '//*[@id="uiSkip"]',
                    '//*[@id="uiWizFooterBtns"]/button',
                    '//*[@id="uiFinish"]',
                    '//*[@id="Button1"]'
                ]
                found_and_clicked_any = False
                for xpath in wizard_xpaths:
                    try:
                        if self.browser.klicken(xpath, timeout=3):
                            print(f"➡️ Wizard-Schritt mit {xpath} geklickt.")
                            found_and_clicked_any = True
                            time.sleep(2)
                    except Exception:
                        pass # Element nicht gefunden oder Klick fehlgeschlagen, Wizard ist wohl durch

                if found_and_clicked_any:
                    return True
                else:
                    print("ℹ️ DSL-Wizard-Schritte nicht gefunden oder bereits abgeschlossen.")
                    return False

        except Exception as e:
            print(f"❌ Schwerwiegender Fehler im DSL-Setup-Wizard:")
            return False

    def ist_sprachauswahl(self) -> bool:
        """
        Prüft, ob die Sprachauswahl-Seite angezeigt wird,
        indem es nach den spezifischen Sprachauswahl-Elementen sucht.
        """
        try:
            self.browser.sicher_warten('//*[@id="uiLanguage-de"] | //*[@id="uiLanguage-en"]', timeout=3, sichtbar=False)
            print("🌐 Sprachauswahlseite erkannt.")
            return True
        except Exception:
            # print("ℹ️ Keine Sprachauswahlseite erkannt.")
            return False

    def set_language(self, lang_code: str = "en") -> bool:
        """
        Setzt die Sprache der FritzBox-Oberfläche.
        lang_code: 'de' für Deutsch, 'en' für Englisch.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar, Sprache kann nicht gesetzt werden.")
            return False

        print(f"🌐 Versuche Sprache auf '{lang_code.upper()}' zu setzen...")
        try:
            self.browser.get_url(self.url)
            if self.ist_sprachauswahl():
                xpath_lang_button = f'//*[@id="uiLanguage-{lang_code}"]'
                if self.browser.klicken(xpath_lang_button, timeout=5):
                    print(f"✅ Sprache '{lang_code.upper()}' ausgewählt.")
                    if self.browser.klicken('//*[@id="submitLangBtn"]', timeout=5):
                        print("✅ Sprachauswahl bestätigt.")
                        time.sleep(5)
                        self.language = lang_code
                        return True
                    print("❌ Sprachauswahl-Bestätigungsbutton nicht gefunden.")
                    return False
                print(f"❌ Sprachauswahlbutton für '{lang_code.upper()}' nicht gefunden.")
                return False
            else:
                print("ℹ️ Sprachauswahlseite nicht aktiv. Sprache kann nicht geändert werden.")
                return False
        except Exception as e:
            print(f"❌ Fehler beim Setzen der Sprache auf '{lang_code.upper()}'")
            return False

    @require_login
    def check_wlan_antennas(self, max_versuche=2) -> bool:
        """
        Prüft WLAN-Antennen; erkennt automatisch die UI-Version (modern vs. alt)
        und ist gegen StaleElement-Fehler in beiden Fällen abgesichert.
        """
        print("📡 WLAN-Antennen prüfen...")
        self._close_any_overlay()
        self.wlan_scan_results = []  # Liste vor jedem neuen Scan leeren

        for versuch in range(1, max_versuche + 1):
            try:
                if not self.browser.klicken('//*[@id="wlan"]', timeout=5): raise Exception(
                    "Konnte 'WLAN' nicht klicken.")
                time.sleep(1)
                if not self.browser.klicken('//*[@id="chan"]', timeout=5): raise Exception(
                    "Konnte 'Funkkanal' nicht klicken.")
                time.sleep(15)


                try:
                    self.browser.klicken('//button[contains(text(),"WLAN einschalten")]', timeout=5, versuche=1)
                except Exception as e:
                    print(e)
                    pass
                try:
                    self.browser.klicken('//a[contains(text(),"WLAN einschalten")]', timeout=5, versuche=1)
                except Exception as e:
                    print(e)
                    pass

                # --- Logik für MODERNE UI (div-basiert) ---

                modern_row_xpath = '//div[@class="flexRow" and .//div[@prefid="rssi"]]'
                num_modern_rows = len(self.browser.driver.find_elements(By.XPATH, modern_row_xpath))

                if num_modern_rows > 0:
                    print(f"📶 Moderne UI erkannt. {num_modern_rows} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i in range(num_modern_rows):
                        try:
                            row = self.browser.driver.find_element(By.XPATH, f"({modern_row_xpath})[{i + 1}]")
                            name = row.find_element(By.XPATH, './/div[@prefid="name"]').text.strip()
                            freq = row.find_element(By.XPATH, './/div[@prefid="band"]').text.strip()
                            channel = row.find_element(By.XPATH, './/div[@prefid="channel"]').text.strip()
                            mac = row.find_element(By.XPATH, './/div[@prefid="mac"]').text.strip()
                            signal_title = row.find_element(By.XPATH, './/div[@prefid="rssi"]').get_attribute(
                                "title").strip()
                            self.print_wlan_entry(i, name, freq, channel, mac, signal_title)
                            self.wlan_scan_results.append({
                                "name": name,
                                "frequency": freq,
                                "channel": channel,
                                "mac": mac,
                                "signal": signal_title
                            })
                        except Exception as e:
                            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{i + 1}")
                    self.is_wifi_checked = True
                    return True

                # --- Fallback-Logik für ALTE UI (Tabellen-basiert) ---
                old_table_row_xpath = '//tbody[@id="uiScanResultBody"]/tr'
                num_table_rows = len(self.browser.driver.find_elements(By.XPATH, old_table_row_xpath))

                if num_table_rows > 0:
                    print(f"📶 Alte Tabellen-UI erkannt. {num_table_rows} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i in range(num_table_rows):
                        try:
                            row = self.browser.driver.find_element(By.XPATH, f"({old_table_row_xpath})[{i + 1}]")
                            cols = row.find_elements(By.TAG_NAME, 'td')
                            if len(cols) < 4: continue

                            signal_title = cols[0].get_attribute("title").strip()
                            name = cols[1].text.strip()
                            freq = cols[2].text.strip() # this is apparently freq in the old Version
                            mac = cols[3].text.strip()
                            channel = cols[4].text.strip() # fragwürdig
                            self.print_wlan_entry(i, name, freq, channel, mac, signal_title)
                            self.wlan_scan_results.append({
                                "name": name,
                                "frequency": freq,
                                "channel": channel,
                                "mac": mac,
                                "signal": signal_title
                            })
                        except Exception as e:
                            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{i + 1}")
                    self.is_wifi_checked = True
                    return True

                # Wenn keine der beiden Suchen erfolgreich war
                print(f"⚠️ Keine WLAN-Netzwerke gefunden (Versuch {versuch}/{max_versuche}).")

            except Exception as e:
                print(f"❌ Fehler beim Zugriff auf WLAN-Liste (Versuch {versuch}) ")

            if versuch < max_versuche: time.sleep(5)

        print("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")
        return False

    def print_wlan_entry(self, index, name, freq, channel, mac, signal_title):
        """Hilfsfunktion zur formatierten Ausgabe eines WLAN-Eintrags."""
        try:
            signal_val = signal_title.replace('%', '').replace('<', '')
            signal_strength = int(signal_val or 0)

            if signal_strength <= 30:
                emoji = "📶🔴"
            elif signal_strength <= 60:
                emoji = "📶🟡"
            else:
                emoji = "📶🟢"

            print(f"{index + 1}. {name} | {freq} | Kanal {channel} | MAC: {mac} | Signal: {signal_title} {emoji}")
        except Exception as e:
            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{index + 1}:")

    @require_login
    def perform_firmware_update(self, firmware_path: str) -> bool:
        """Führt ein Firmware-Update durch und stellt vorher einen sauberen UI-Zustand her."""
        if not firmware_path or not os.path.exists(firmware_path):
            print(f"❌ Firmware-Datei nicht gefunden unter: {firmware_path}")
            return False

        print(f"🆙 Firmware-Update wird mit Datei gestartet: {os.path.basename(firmware_path)}")

        try:
            print("...navigiere zur Hauptseite für einen sauberen Start.")
            self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
            time.sleep(1)

            # Schritt 1: Navigation zum Update-Menü
            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
            time.sleep(1)
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False
            time.sleep(1)
            if not self.browser.klicken('//*[@id="userUp"] | //a[contains(text(), "FRITZ!OS-Datei")]',
                                        timeout=5): return False
            time.sleep(1)

            print("...warte auf die Seite für das Date-Update.")
            try:
                checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=10)
            except Exception as e:
                print(f"❌ Die Seite für das Firmware-Update konnte nicht geladen werden (Checkbox nicht gefunden):")
                return False

            if checkbox.is_selected():
                print("...deaktiviere die Checkbox 'Einstellungen sichern'.")
                checkbox.click()
                time.sleep(1)

            print("...warte auf das Datei-Eingabefeld.")
            try:
                file_input = self.browser.sicher_warten('//*[@id="uiFile"]', timeout=10)
            except Exception as e:
                print(f"❌ Das Datei-Eingabefeld ist nicht erschienen:")
                return False

            file_input.send_keys(firmware_path)
            print("✅ Firmware-Pfad erfolgreich eingetragen.")

            if not self.browser.klicken('//*[@id="uiUpdate"]'):
                print("❌ Fehler beim Klicken auf 'Update starten'.")
                return False

            print("📤 Firmware wird hochgeladen... Die Box startet nun neu.")
            # --- NEU: Aktiv auf die Box warten ---
            # Wir geben ihr großzügig Zeit (40 Versuche * 10s = 400s)
            time.sleep(60)
            if self.warte_auf_erreichbarkeit(versuche=40, delay=10):
                # this needs login check for
                print("✅ Box ist nach dem Update wieder erreichbar.")
                return True
            else:
                print("❌ Box ist nach dem Update nicht wieder erreichbar.")
                return False

        except Exception as e:
            print(f"❌ Unerwarteter Fehler während des Firmware-Updates")
            return False

    def _prepare_version_info(self) -> bool:
        """Bereitet Versions- und Modellinformationen vor."""
        current_version_str = self.os_version or "0.0"
        match = re.search(r'(\d{1,2}\.\d{2})', current_version_str)
        self._clean_current_version = match.group(1) if match else ""
        self._major_version = int(self._clean_current_version.split('.')[0]) if self._clean_current_version else 0
        self._model_info = self.firmware_manager.firmware_mapping.get(self.box_model)
        return True

    @require_login
    def update_firmware(self) -> bool:
        """Entscheidet und führt das passende Firmware-Update durch."""
        self._prepare_version_info()
        if self._major_version < 7 and self._model_info and "bridge" in self._model_info:
            print("ℹ️ Mehrstufiges Update erforderlich (alt -> bridge -> final).")
            return self._perform_bridge_update()

        if self._model_info:
            target_version = self._model_info.get("final", "")
            if self._clean_current_version and target_version and \
                    self._clean_current_version.replace("0", "") == target_version.replace("0", ""):
                print(f"✅ Firmware ist bereits auf Zielversion ({self._clean_current_version}).")
                return True
            print(f"ℹ️ Update von {self._clean_current_version} auf {target_version} wird durchgeführt.")
            final_path = self.firmware_manager.get_firmware_path(self.box_model, "final")
            return self.perform_firmware_update(final_path) if final_path else False

        print("Keine Update-Regel für dieses Modell gefunden.")
        return True

    def _perform_bridge_update(self) -> bool:
        """Mehrstufiges Update: erst Bridge, dann Final."""
        bridge_path = self.firmware_manager.get_firmware_path(self.box_model, "bridge")
        if bridge_path and not self.perform_firmware_update(bridge_path):
            return False
        final_path = self.firmware_manager.get_firmware_path(self.box_model, "final")
        return self.perform_firmware_update(final_path) if final_path else False

    def show_wlan_summary(self) -> bool:
        """Zeigt gespeicherte WLAN-Scan-Ergebnisse an."""
        if not self.wlan_scan_results:
            return True
        print("\n\n📡📋 Zusammenfassung des WLAN-Scans 📡📋")
        for i, network_data in enumerate(self.wlan_scan_results):
            self.print_wlan_entry(
                index=i,
                name=network_data.get("name"),
                freq=network_data.get("frequency"),
                channel=network_data.get("channel"),
                mac=network_data.get("mac"),
                signal_title=network_data.get("signal")
            )
        print("--------------------------------------------------")
        return True