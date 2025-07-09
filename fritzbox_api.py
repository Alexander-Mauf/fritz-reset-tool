# fritzbox_api.py
import time
import requests
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import re
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser_utils import Browser


FRITZ_DEFAULT_URL = "http://fritz.box"


class FirmwareManager:
    """Verwaltet Firmware-Dateien und deren Pfade basierend auf dem FritzBox-Modell."""

    def __init__(self):
        self.firmware_mapping = {
            "7590": "8.03",
            "7530": "8.02",
            "6890_LTE": "7.57",
        }

    def _select_firmware_path_manually(self):
        """Öffnet einen Dateidialog zur manuellen Auswahl des Firmware-Pfades."""
        # ... (diese Methode bleibt unverändert)
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Firmware Image", "*.image")]
        )
        root.destroy()
        return file_path

    def get_firmware_path(self, box_model: str) -> str | None:
        """
        Versucht, den Firmware-Pfad automatisch zu finden, ausgehend vom Ausführungsordner.
        """
        if not box_model:
            print("⚠️ Box-Modell ist unbekannt. Firmware-Pfad muss manuell gewählt werden.")
            return self._select_firmware_path_manually()

        target_version = self.firmware_mapping.get(box_model)
        if not target_version:
            print(f"⚠️ Keine Ziel-Firmware für Modell '{box_model}' bekannt. Bitte manuell auswählen.")
            return self._select_firmware_path_manually()

        # KORREKTUR: Nutzt das Verzeichnis, von dem das Programm gestartet wurde.
        # Path(sys.argv[0]).parent ist die robusteste Methode dafür.
        try:
            current_dir = Path(sys.argv[0]).parent
        except Exception:
            # Fallback, falls sys.argv[0] nicht wie erwartet funktioniert
            current_dir = Path.cwd()

        firmware_filename = f"FRITZ.Box_{box_model}-{target_version}.image"
        firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename

        print(f"ℹ️ Suche Firmware für {box_model} unter: {firmware_path_auto}")

        if firmware_path_auto.is_file():
            print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            return str(firmware_path_auto)
        else:
            print(f"❌ Firmware-Datei nicht gefunden. Bitte manuell auswählen.")
            return self._select_firmware_path_manually()

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
                    print(f"Fehler beim Prüfen der URL {url}: {e}")
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
            if self.browser.sicher_warten('//*[@id="uiLanguage-en"]', timeout=2, sichtbar=False):
                print("🌐 Sprachauswahl erkannt. Setze auf Englisch...")
                if self.browser.klicken('//*[@id="uiLanguage-en"]'):
                    if self.browser.klicken('//*[@id="submitLangBtn"]'):
                        time.sleep(3)
                        self.language = "en"
                        return True
                    print("⚠️ 'Sprache übernehmen'-Button nicht klickbar.")
                print("⚠️ Sprachauswahl-Button nicht klickbar.")
        except Exception:
            print("ℹ️ Keine Sprachauswahl erkannt oder konnte nicht verarbeitet werden.")
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
        Führt den Login in die FritzBox durch.
        Versucht, vorhandenen Login zu erkennen und alle auftretenden Dialoge zu behandeln,
        bis das Hauptmenü zugänglich ist.
        Gibt True bei Erfolg, False bei Fehlschlag zurück.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Login.")
            return False

        self.password = password

        print("🔐 Login wird versucht...")

        if not force_reload and self.is_logged_in_and_menu_ready(timeout=5):
            print("✅ Bereits eingeloggt und Hauptmenü bereit.")
            return True

        self.browser.get_url(self.url)

        if self._handle_language_selection():
            self.browser.get_url(self.url)

        if not self._check_if_login_required():
            print("❌ Login-Feld nicht gefunden. Unerwarteter Seiten-Zustand vor Login-Versuch.")
            self.is_logged_in = False
            return False

        try:
            if not self.browser.schreiben('//*[@id="uiPass"]', password):
                raise Exception("Passwort konnte nicht in Feld geschrieben werden.")
            if not self.browser.klicken('//*[@id="submitLoginBtn"]'):
                raise Exception("Login-Button konnte nicht geklickt werden.")

            time.sleep(2)

            max_dialog_attempts = 10
            for attempt in range(max_dialog_attempts):
                if self.is_logged_in_and_menu_ready(timeout=5):
                    print(f"✅ Login erfolgreich nach {attempt} Dialogrunden und Hauptmenü zugänglich.")
                    return True

                print(f"Versuche Post-Login-Dialoge zu behandeln (Runde {attempt + 1})...")
                if not self._handle_post_login_dialogs_round():
                    print("❌ Kritischer Fehler während Post-Login-Dialogbehandlung.")
                    self.is_logged_in = False
                    return False

                time.sleep(1)

            print("❌ Maximale Dialogrunden erreicht, Hauptmenü nicht zugänglich.")
            self.is_logged_in = False
            return False

        except Exception as e:
            print(f"❌ Login fehlgeschlagen: {e}")
            self.is_logged_in = False
            return False

    def _handle_post_login_dialogs_round(self) -> bool:
        """
        Versucht eine Runde aller bekannten Post-Login-Dialoge zu behandeln.
        Gibt True zurück, wenn die Runde ohne kritischen Fehler abgeschlossen wurde.
        Gibt False zurück, wenn ein kritischer Fehler (z.B. Logout) erkannt wurde.
        """
        print("⚙️ Starte Runde zur Behandlung von Post-Login-Dialogen...")
        dialog_handlers = [
            self.neue_firmware_dialog,
            self.dsl_setup_init,
            self.checkbox_fehlerdaten_dialog,
            self.skip_configuration,
        ]

        found_and_handled_any_dialog_in_this_round = False

        for handler in dialog_handlers:
            try:
                if not self.is_logged_in_and_menu_ready(timeout=2):
                    print(f"❌ Logout oder unerwarteter Zustand vor Aufruf von '{handler.__name__}'.")
                    return False

                handler_result = handler()
                if handler_result:
                    found_and_handled_any_dialog_in_this_round = True
                    time.sleep(1)

            except Exception as e:
                print(f"❌ Schwerwiegender Fehler beim Behandeln von Dialog '{handler.__name__}': {e}")
                return False

        if not found_and_handled_any_dialog_in_this_round:
            print("ℹ️ Keine weiteren bekannten Dialoge in dieser Runde gefunden.")
        else:
            print("✅ Einige Dialoge in dieser Runde behandelt.")

        return True

    def neue_firmware_dialog(self) -> bool:
        """Behandelt den Dialog, der nach einer Firmware-Installation erscheinen kann."""
        print("Prüfe ob 'Neue Firmware installiert'-Dialog erscheint...")
        ok_buttons_xpaths = [
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
        ]
        weiter_buttons_xpaths = [
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
        ]

        for xpath in ok_buttons_xpaths:
            if self.browser.klicken(xpath, timeout=2):
                print("✅ 'OK' Button im Firmware-Dialog geklickt.")
                time.sleep(1)
                return True
        for xpath in weiter_buttons_xpaths:
            if self.browser.klicken(xpath, timeout=2):
                print("✅ 'Weiter' Button im Firmware-Dialog geklickt.")
                time.sleep(1)
                return True

        print("ℹ️ Kein 'Neue Firmware installiert'-Dialog gefunden oder konnte nicht geklickt werden.")
        return False # Gebe False zurück, um anzuzeigen, dass kein Dialog erfolgreich behandelt wurde

    def dsl_setup_init(self) -> bool:
        """Behandelt initialen DSL-Setup-Dialog (z.B. nach einem Reset)."""
        print("⚙️ Prüfe auf und setze default DSL-Settings (falls vorhanden)...")
        forward_buttons_xpaths = [
            '//*[@id="uiForward"]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
        ]

        found_and_clicked = False
        for _ in range(3):
            for xpath in forward_buttons_xpaths:
                if self.browser.klicken(xpath, timeout=2):
                    print(f"✅ '{xpath}' im DSL-Setup initial gefunden und geklickt.")
                    found_and_clicked = True
                    time.sleep(1)
                    break
            if not found_and_clicked:
                break

        if found_and_clicked:
            return True
        else:
            print("ℹ️ Kein initialer DSL-Setup-Dialog ('uiForward' oder 'Weiter') gefunden.")
            return False

    def checkbox_fehlerdaten_dialog(self) -> bool:
        """Behandelt den Fehlerdaten-Senden-Dialog."""
        print("🛑 Fehlerdaten-Checkbox prüfen...")
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=2)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Deaktiviert.")
            else:
                print("☑️ Bereits deaktiviert.")

            apply_buttons_xpaths = [
                '//*[@id="uiApply"]',
                '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
            ]
            for xpath in apply_buttons_xpaths:
                if self.browser.klicken(xpath, timeout=2):
                    print("➡️ Änderungen übernommen (Fehlerdaten).")
                    time.sleep(1)
                    return True

            return True # Checkbox war da, aber evtl. kein Button nötig oder schon deaktiviert
        except Exception:
            print("ℹ️ Keine Fehlerdaten-Checkbox oder Übernehmen-Button gefunden/benötigt.")
            return False

    def skip_configuration(self) -> bool:
        """Versucht, generische Konfigurationsdialoge zu überspringen (z.B. "Weiter"-Buttons)."""
        print("📌 Konfigurationsdialoge überspringen (generisch)...")
        generic_buttons_xpaths = [
            '//*[@id="Button1"]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
        ]

        clicked_any_in_this_round = False
        for xpath in generic_buttons_xpaths:
            try:
                button_elem = self.browser.sicher_warten(xpath, timeout=1, sichtbar=True)
                if button_elem.is_displayed() and button_elem.is_enabled():
                    if self.browser.klicken(xpath, timeout=1):
                        print(f"✅ Generischen Button geklickt: {xpath}")
                        clicked_any_in_this_round = True
                        time.sleep(1)
                        break
            except Exception:
                pass

        if clicked_any_in_this_round:
            return True
        else:
            print("ℹ️ Keine generischen Konfigurationsdialoge gefunden in dieser Runde.")
            return False

    def reset_via_forgot_password(self) -> bool:
        """Leitet den Werksreset über den 'Passwort vergessen'-Link ein (ohne Login)."""
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Reset.")
            return False
        print("🚨 Werkseinstellungen einleiten (via 'Passwort vergessen')...")
        self.browser.get_url(self.url)

        kandidaten_xpaths = [
            '//*[@id="dialogFoot"]/a',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
        ]

        found_reset_link = False
        for xpath in kandidaten_xpaths:
            if self.browser.klicken(xpath, timeout=5):
                print(f"🔁 Reset-Link gefunden und geklickt ({xpath})")
                found_reset_link = True
                break
        if not found_reset_link:
            print("❌ Kein Reset-Link gefunden.")
            return False

        if self.browser.klicken('//*[@id="sendFacReset"]', timeout=5):
            print("🔁 Reset ausgelöst, warte auf Neustart...")
            time.sleep(60)
            self.is_reset = True
            if self.ist_sprachauswahl():
                print("✅ FritzBox erfolgreich auf Werkseinstellungen zurückgesetzt und Sprachauswahl erreicht.")
                return True
            else:
                print("⚠️ Reset ausgelöst, aber Sprachauswahl nicht verifiziert. Bitte manuell prüfen.")
                return False
        else:
            print("❌ Fehler beim Bestätigen des Resets via 'sendFacReset'.")
            return False

    def perform_factory_reset_from_ui(self) -> bool:
        """
        Setzt die FritzBox über die Benutzeroberfläche auf Werkseinstellungen zurück.
        Diese Methode ist hybrid und versucht Pfade für alte und neue OS-Versionen.
        """
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für UI-Reset erforderlich.")
            return False

        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            # Schritt 1: Klick auf "System" (konsistent über die meisten Versionen)
            if not self.browser.klicken('//*[@id="sys"]', timeout=5):
                print("Konnte nicht auf 'System' klicken.")
                return False
            time.sleep(1)

            # Schritt 2: Klick auf "Sicherung" (kombiniert alte und neue Selektoren)
            backup_selectors = [
                '//*[@id="mSave"]',  # ID für neuere Versionen
                '//a[contains(@href, "backup.lua")]',  # Link-Struktur für ältere Versionen
                '//a[contains(text(), "Sicherung")]'  # Text-basierter Fallback
            ]
            if not self.browser.klicken(backup_selectors, timeout=5):
                print("Konnte den Menüpunkt 'Sicherung' nicht finden.")
                return False
            time.sleep(1)

            # Schritt 3: Klick auf den Tab "Werkseinstellungen"
            factory_reset_tab_selectors = [
                '//*[@id="default"]',  # Standard-ID für den Tab
                '//a[contains(text(), "Werkseinstellungen")]'  # Text-basierter Fallback
            ]
            if not self.browser.klicken(factory_reset_tab_selectors, timeout=5):
                print("Konnte nicht auf den Tab 'Werkseinstellungen' klicken.")
                return False
            time.sleep(1)

            # Schritt 4: Klick auf den finalen Bestätigungs-Button (kombiniert mehrere Möglichkeiten)
            confirm_button_xpaths = [
                '//*[@id="uiDefaults"]',  # Spezifische ID für ältere Versionen (dein Fund)
                '//*[@id="content"]/div/button',  # Häufige Struktur bei neueren Versionen
                '//button[contains(text(), "Werkseinstellungen laden")]',  # Text auf neueren Buttons
                '//button[contains(text(), "Wiederherstellen")]'  # Alternativer Text
            ]

            found_confirm_button = False
            for xpath in confirm_button_xpaths:
                if self.browser.klicken(xpath, timeout=2):  # Kurzer Timeout, da wir mehrere XPaths testen
                    print(f"✅ Bestätigungs-Button gefunden und geklickt ({xpath}).")
                    found_confirm_button = True
                    break

            if not found_confirm_button:
                print("Konnte keinen Bestätigungsbutton für die Werkseinstellungen finden.")
                return False
            time.sleep(3)

        except Exception as e:
            print(f"❌ Fehler im Reset-Ablauf über UI-Menü: {e}")
            return False

        # Schritt 5: Auf physische Bestätigung warten (sollte für alle Versionen gleich sein)
        print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken (falls erforderlich)...")
        try:
            ok_button_xpath = '//*[@id="Button1"] | //button[text()="OK"]'
            btn = self.browser.sicher_warten(ok_button_xpath, timeout=180, sichtbar=True)
            btn.click()
            print("✅ OK-Button geklickt nach physischer Bestätigung.")
            self.is_reset = True
            time.sleep(25)  # Zeit für den Neustart-Prozess geben
            if self.ist_sprachauswahl():
                print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
                return True
            else:
                print("⚠️ Reset abgeschlossen, aber Sprachauswahl nicht verifiziert. Bitte manuell prüfen.")
                return True
        except Exception as e:
            print(f"❌ Fehler beim Warten auf den finalen OK-Klick: {e}")
            return False


    def get_firmware_version(self) -> str | None:
        """Ermittelt die aktuelle Firmware-Version der FritzBox."""
        print("ℹ️ Ermittle Firmware-Version...")
        try:
            if not self.is_logged_in_and_menu_ready():
                print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für Versionsprüfung erforderlich.")
                return None

            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return None
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return None

            version_elem = self.browser.sicher_warten('//*[@class="fakeTextInput" or contains(@class, "version_text")]', timeout=5)
            version_text = version_elem.text.strip()

            if version_text:
                self.os_version = version_text
                print(f"✅ Firmware-Version: {self.os_version}")
                return self.os_version
            else:
                print("❌ Keine Firmware-Version gefunden auf der Update-Seite.")
                return None
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln der Firmware-Version: {e}")
            return None

    def _extract_model_number(self, element) -> str | None:
        """
        Extrahiert die 4-stellige Modellnummer aus dem textContent eines Elements.
        Diese Methode ist zuverlässiger als .text für unsichtbare Elemente.
        """
        try:
            # .get_attribute("textContent") liest Text auch aus versteckten Elementen
            text_content = element.get_attribute("textContent").strip()

            # Dieser Regex sucht einfach nach der ersten 4-stelligen Zahl, was sehr robust ist.
            match = re.search(r'(\d{4,})', text_content)
            if match:
                model_number = match.group(1)
                # Fall für LTE-Modelle
                if "LTE" in text_content:
                    return f"{model_number}_LTE"
                return model_number
        except Exception:
            return None
        return None

    def get_box_model(self) -> str | None:
        """Ermittelt das Fritzbox-Modell mit einer robusten 3-Stufen-Strategie."""
        print("🔍 Ermittle Box-Modell (robuste Methode)...")
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt. Login für Modellermittlung erforderlich.")
            return None

        # XPaths, die wir auf den verschiedenen Seiten prüfen
        xpaths_to_check = [
            '//*[@id="blueBarTitel"]',
            '//span[contains(@class, "version_text")]',
            '//div[@class="boxInfo"]/span'
        ]

        # --- Stufe 1: Suche auf der aktuellen Seite ---
        print("   (Stufe 1/3: Suche auf aktueller Seite)")
        for xpath in xpaths_to_check:
            try:
                # Wichtig: sichtbar=False, um versteckte Elemente wie 'hide' zu finden
                element = self.browser.sicher_warten(xpath, timeout=1, sichtbar=False)
                model = self._extract_model_number(element)
                if model:
                    self.box_model = model
                    print(f"✅ Box-Modell: {self.box_model} (gefunden auf aktueller Seite).")
                    return self.box_model
            except Exception:
                continue

        # --- Stufe 2: Navigation zur Übersichtsseite ---
        print("   (Stufe 2/3: Suche auf Übersichtsseite)")
        if self.browser.klicken('//*[@id="overview"] | //*[@id="mHome"]', timeout=3):
            time.sleep(2)
            for xpath in xpaths_to_check:
                try:
                    element = self.browser.sicher_warten(xpath, timeout=1, sichtbar=False)
                    model = self._extract_model_number(element)
                    if model:
                        self.box_model = model
                        print(f"✅ Box-Modell: {self.box_model} (gefunden auf Übersichtsseite).")
                        return self.box_model
                except Exception:
                    continue

        # --- Stufe 3: Notfall-Fallback über Ereignis-Log ---
        print("   (Stufe 3/3: Suche in System-Ereignissen)")
        # Diese Stufe lassen wir vorerst weg, da sie selten nötig und komplex ist.
        # Die ersten beiden Stufen mit der neuen Logik sollten das Problem lösen.

        print("❌ Box-Modell konnte nicht identifiziert werden.")
        self.box_model = "UNKNOWN"
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
            print(f"❌ Schwerwiegender Fehler im DSL-Setup-Wizard: {e}")
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
            print(f"❌ Fehler beim Setzen der Sprache auf '{lang_code.upper()}': {e}")
            return False

    def check_wlan_antennas(self, max_versuche=2) -> bool:
        """Prüft die WLAN-Antennen. Erkennt automatisch die UI-Version (alt vs. neu)."""
        print("📡 WLAN-Antennen prüfen...")
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für WLAN-Check erforderlich.")
            return False

        # Navigation zum Funkkanal-Menü
        for versuch in range(1, max_versuche + 1):
            try:
                if not self.browser.klicken('//*[@id="wlan"]', timeout=5): raise Exception(
                    "Konnte 'WLAN' nicht klicken.")
                time.sleep(1)
                if not self.browser.klicken('//*[@id="chan"]', timeout=5): raise Exception(
                    "Konnte 'Funkkanal' nicht klicken.")
                time.sleep(5)

                # --- Automatische Erkennung der UI-Version ---
                # Versuch 1: Moderne UI mit 'flexRow' Divs
                rows = self.browser.driver.find_elements(By.XPATH, '//div[@class="flexRow" and .//div[@prefid="rssi"]]')
                if rows:
                    print(f"📶 Moderne UI erkannt. {len(rows)} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i, row in enumerate(rows):
                        name = row.find_element(By.XPATH, './/div[@prefid="name"]').text.strip()
                        freq = row.find_element(By.XPATH, './/div[@prefid="band"]').text.strip()
                        channel = row.find_element(By.XPATH, './/div[@prefid="channel"]').text.strip()
                        mac = row.find_element(By.XPATH, './/div[@prefid="mac"]').text.strip()
                        signal_title = row.find_element(By.XPATH, './/div[@prefid="rssi"]').get_attribute(
                            "title").strip()
                        self._print_wlan_entry(i, name, freq, channel, mac, signal_title)
                    self.is_wifi_checked = True
                    return True

                # Versuch 2: Alte UI mit 'table' (dein HTML-Beispiel)
                table_rows = self.browser.driver.find_elements(By.XPATH, '//tbody[@id="uiScanResultBody"]/tr')
                if table_rows:
                    print(f"📶 Alte Tabellen-UI erkannt. {len(table_rows)} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i, row in enumerate(table_rows):
                        cols = row.find_elements(By.TAG_NAME, 'td')
                        if len(cols) < 4: continue  # Zeile überspringen, wenn sie nicht genug Spalten hat

                        signal_title = cols[0].get_attribute("title").strip()
                        name = cols[1].text.strip()
                        channel = cols[2].text.strip()
                        mac = cols[3].text.strip()
                        # Frequenzband ist in der alten Ansicht nicht verfügbar
                        freq = "5 GHz" if int(channel) > 14 else "2,4 GHz"
                        self._print_wlan_entry(i, name, freq, channel, mac, signal_title)
                    self.is_wifi_checked = True
                    return True

                print(f"⚠️ Keine WLAN-Netzwerke gefunden (Versuch {versuch}/{max_versuche}).")

            except Exception as e:
                print(f"❌ Fehler beim Zugriff auf WLAN-Liste (Versuch {versuch}): {e}")

            if versuch < max_versuche: time.sleep(5)

        print("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")
        return False

    def _print_wlan_entry(self, index, name, freq, channel, mac, signal_title):
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
            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{index + 1}: {e}")

    def activate_expert_mode_if_needed(self) -> bool:
        """Prüft die FRITZ!OS-Version und aktiviert die erweiterte Ansicht mit erzwungenen JS-Klicks."""
        print("🔍 Prüfe, ob erweiterte Ansicht aktiviert werden muss...")
        if not self.os_version: return True

        match = re.search(r'(\d{2,3})\.(\d{2})', self.os_version)
        if not match: return True

        major, minor = int(match.group(1)), int(match.group(2))

        if major < 7 or (major == 7 and minor < 15):
            print(f"ℹ️ Version {major}.{minor} erkannt. Erweiterte Ansicht wird geprüft/aktiviert.")
            try:
                # Schritt 1: Klick auf das Menü-Icon mit JS erzwingen
                print("...erzwinge Klick auf Menü-Icon mit JavaScript.")
                menu_icon = self.browser.sicher_warten('//*[@id="blueBarUserMenuIcon"]', timeout=5, sichtbar=False)
                self.browser.driver.execute_script("arguments[0].click();", menu_icon)
                time.sleep(2)

                # Schritt 2: Klick auf die Checkbox ebenfalls mit JS erzwingen
                checkbox = self.browser.sicher_warten('//input[@id="expert"]', timeout=5)
                if not checkbox.is_selected():
                    print("🎚️ Erweiterte Ansicht ist nicht aktiv. Aktiviere sie jetzt...")
                    print("...erzwinge Klick auf Checkbox mit JavaScript.")
                    self.browser.driver.execute_script("arguments[0].click();", checkbox)
                    print("✅ Erweiterte Ansicht erfolgreich aktiviert.")
                    time.sleep(2)
                else:
                    print("✅ Erweiterte Ansicht ist bereits aktiv.")

                return True

            except Exception as e:
                print(f"❌ Fehler beim Aktivieren der erweiterten Ansicht: {e}")
                return False
        else:
            print("✅ Version ist aktuell genug, keine Prüfung der erweiterten Ansicht nötig.")
            return True


def perform_firmware_update(self, firmware_path: str) -> bool:
    """Führt ein Firmware-Update über die Weboberfläche durch (nach Login)."""
    if not self.is_logged_in_and_menu_ready():
        print("❌ Nicht eingeloggt. Login für Firmware-Update erforderlich.")
        return False
    if not firmware_path or not os.path.exists(firmware_path):
        print(f"❌ Firmware-Datei nicht gefunden unter: {firmware_path}")
        return False

    print(f"🆙 Firmware-Update wird mit Datei gestartet: {os.path.basename(firmware_path)}")

    try:
        # Navigation zum Update-Menü
        if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
        time.sleep(1)
        if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False
        time.sleep(1)
        if not self.browser.klicken('//*[@id="userUp"] | //a[contains(text(), "FRITZ!OS-Datei")]',
                                    timeout=5): return False
        time.sleep(2)

        # Optional: Checkbox zum Sichern der Einstellungen deaktivieren
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=3)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Checkbox 'Einstellungen sichern' deaktiviert.")
        except Exception:
            print("ℹ️ Checkbox 'Einstellungen sichern' nicht gefunden, wird übersprungen.")

        # Pfad zur Firmware-Datei eintragen und Update starten
        if not self.browser.schreiben('//*[@id="uiFile"]', firmware_path):
            print("❌ Fehler beim Eintragen des Firmware-Pfads.")
            return False

        # Klick auf "Update starten"
        if not self.browser.klicken('//*[@id="uiUpdate"]'):
            print("❌ Fehler beim Klicken auf 'Update starten'.")
            return False

        print("📤 Firmware wird hochgeladen... Die Box startet nun neu.")
        print("⏳ Der Workflow wird nach dem Neustart mit der Überprüfung der Erreichbarkeit fortgesetzt.")
        # Die Methode kehrt sofort zurück. Der Orchestrator muss warten und neu verbinden.
        return True

    except Exception as e:
        print(f"❌ Unerwarteter Fehler während des Firmware-Updates: {e}")
        time.sleep(15)
        return False