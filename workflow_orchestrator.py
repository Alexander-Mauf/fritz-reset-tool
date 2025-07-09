# workflow_orchestrator.py
from fritzbox_api import FritzBox, FirmwareManager
from browser_utils import setup_browser, Browser
import time
import win32gui
import win32con
import ctypes

class WorkflowOrchestrator:
    """
    Steuert den gesamten Workflow zur Verwaltung einer FritzBox.
    Koordiniert die Schritte, handhabt Retries und Benutzerinteraktion.
    """
    def __init__(self):
        self.browser_driver = None
        self.browser = None
        self.fritzbox = None
        self.firmware_manager = FirmwareManager() # FirmwareManager hier instanziieren

    def _fenster_in_vordergrund_holen(self):
        """Bringt das CMD-Fenster in den Vordergrund."""
        try:
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            win32gui.ShowWindow(console_hwnd, win32con.SW_SHOWNORMAL)
            win32gui.SetForegroundWindow(console_hwnd)
            print("🪟 CMD-Fenster wurde in den Vordergrund gebracht.")
        except Exception as e:
            print(f"⚠️ Fenster-Fokus fehlgeschlagen: {e}")

    def _run_step_with_retry(self, description: str, func, *args, **kwargs) -> bool:
        """
        Führt einen einzelnen Schritt aus und bietet Optionen zur Wiederholung/Überspringen bei Fehlern.
        Gibt True zurück, wenn der Schritt erfolgreich war oder übersprungen wurde, False bei Abbruch.
        """
        print(f"\n➡️ {description}...")

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                result = func(*args, **kwargs)

                # Eine explizite Rückgabe von False durch die Funktion signalisiert einen kontrollierten Fehlschlag.
                if result is False:
                    print(
                        f"⚠️ Funktion '{description}' meldete expliziten Fehlschlag (Versuch {attempt + 1}/{max_attempts}).")
                    if attempt < max_attempts - 1:
                        print("🔁 Versuche es erneut...")
                        time.sleep(2)
                        continue
                    else:
                        # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                        # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                        break

                # Wenn die Funktion True zurückgab (oder None, was wir als Erfolg interpretieren,
                # da die Funktion keine explizite False-Rückgabe hatte), ist der Schritt erfolgreich.
                print("✅ Schritt erfolgreich.")
                return True

            except Exception as e:
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    print("🔁 Versuche es erneut...")
                    time.sleep(2)
                else:
                    # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                    # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                    break

        # Wenn die Schleife beendet ist (nach max_attempts oder explizitem False),
        # fragen wir den Benutzer, was zu tun ist.
        while True:
            auswahl = input(
                "🔁 (W)iederholen, (Ü)berspringen, (B)eenden, (N)eue FritzBox? "
            ).strip().lower()

            if auswahl == "b":
                print("⛔ Vorgang abgebrochen.")
                return False
            elif auswahl == "w":
                # Rekursiver Aufruf für Wiederholung mit Retry-Logik
                return self._run_step_with_retry(description, func, *args, **kwargs)
            elif auswahl == "ü":
                print("⏭️ Schritt übersprungen.")
                return True
            elif auswahl == "n":
                raise RuntimeError("RESTART_NEW_BOX")
            else:
                print("❓ Ungültige Eingabe. Bitte wähle w/ü/b/n.")

    def run_full_workflow(self, password: str) -> str | None:
        """
        Führt den gesamten FritzBox-Verwaltungs-Workflow aus.
        Gibt "restart" zurück, wenn eine neue Box gewünscht wird, sonst None.
        """
        self.browser_driver = setup_browser()
        self.browser = Browser(self.browser_driver)
        self.fritzbox = FritzBox(self.browser)
        self._fenster_in_vordergrund_holen()

        try:
            if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen", self.fritzbox.warte_auf_erreichbarkeit):
                return None
            if not self._run_step_with_retry("Login durchführen", self.fritzbox.login, password):
                return None
            if not self._run_step_with_retry("Box-Modell ermitteln", self.fritzbox.get_box_model):
                return None
            if not self._run_step_with_retry("Firmware-Version ermitteln", self.fritzbox.get_firmware_version):
                return None

            # NEUER SCHRITT: Erweiterte Ansicht bei alten Versionen aktivieren
            if not self._run_step_with_retry("Erweiterte Ansicht prüfen/aktivieren",
                                             self.fritzbox.activate_expert_mode_if_needed):
                return None

            firmware_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model)
            if not firmware_path:
                print("❌ Firmware-Pfad konnte nicht ermittelt werden. Update wird übersprungen.")
                if input("Möchten Sie trotzdem fortfahren (ohne Update)? (j/n): ").lower() != 'j':
                    return None

            # Logik für Entscheidung: Update oder Reset
            perform_update = False
            perform_reset = False

            if self.fritzbox.box_model != "UNKNOWN" and firmware_path:
                target_version = self.firmware_manager.firmware_mapping.get(self.fritzbox.box_model)
                if self.fritzbox.os_version == "8.03":  # Annahme, dies ist TIM-spezifisch
                    print("🔁 Version 8.03 erkannt – Reset statt Update wird empfohlen.")
                    if input("Möchten Sie stattdessen einen Reset durchführen? (j/n): ").lower() == 'j':
                        perform_reset = True
                elif target_version and target_version not in self.fritzbox.os_version:
                    print(
                        f"ℹ️ Update empfohlen: Aktuell ist '{self.fritzbox.os_version}', Ziel ist '{target_version}'.")
                    if input("Möchten Sie das Firmware-Update durchführen? (j/n): ").lower() == 'j':
                        perform_update = True
                else:
                    print(f"✅ Firmware ist aktuell ({self.fritzbox.os_version}).")

            if not perform_update and not perform_reset:
                if input("Möchten Sie die Box trotzdem auf Werkseinstellungen zurücksetzen? (j/n): ").lower() == 'j':
                    perform_reset = True

            if perform_update and firmware_path:
                if self._run_step_with_retry("Firmware-Update durchführen", self.fritzbox.perform_firmware_update,
                                             firmware_path):
                    print("⏳ Warte 180 Sekunden auf den Neustart der Box nach dem Update...")
                    time.sleep(180)
                    if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Update)",
                                                     self.fritzbox.warte_auf_erreichbarkeit, versuche=30, delay=10):
                        return None
                    if not self._run_step_with_retry("Erneuter Login nach Update", self.fritzbox.login, password,
                                                     force_reload=True):
                        return None
                    self._run_step_with_retry("Firmware-Version erneut ermitteln", self.fritzbox.get_firmware_version)
                else:
                    return None  # Abbruch, wenn Update fehlschlägt

            if perform_reset:
                if self.fritzbox.is_logged_in:
                    if not self._run_step_with_retry("Werkseinstellungen über UI",
                                                     self.fritzbox.perform_factory_reset_from_ui):
                        return None
                else:  # Fallback, falls nicht eingeloggt
                    if not self._run_step_with_retry("Werkseinstellungen via 'Passwort vergessen'",
                                                     self.fritzbox.reset_via_forgot_password):
                        return None

                print("⏳ Warte 120 Sekunden auf den Neustart der Box nach dem Reset...")
                time.sleep(120)
                if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Reset)",
                                                 self.fritzbox.warte_auf_erreichbarkeit, versuche=30, delay=10):
                    return None
                if self.fritzbox.ist_sprachauswahl():
                    self.fritzbox.set_language("en")  # Sprache auf Englisch setzen
                if not self._run_step_with_retry("Erneuter Login nach Reset", self.fritzbox.login, password,
                                                 force_reload=True):
                    return None

            if not self._run_step_with_retry("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas):
                return None

            print("\n🎉 Workflow erfolgreich abgeschlossen!")

            # Frage nach der nächsten Aktion
            while True:
                auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
                if auswahl == 'n':
                    return "restart"
                elif auswahl == 'b':
                    return None
                else:
                    print("❓ Ungültige Eingabe.")


        except RuntimeError as e:
            if str(e) == "RESTART_NEW_BOX":
                print("🆕 Benutzer wünscht neue FritzBox. Starte Workflow neu.")
                return "restart"
            else:
                print(f"❌ Unerwarteter Laufzeitfehler: {e}")
                return None
        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow: {e}")
            return None
        finally:
            if self.browser:
                self.browser.quit()