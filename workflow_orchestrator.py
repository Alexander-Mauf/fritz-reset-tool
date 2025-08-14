# workflow_orchestrator.py
from fritzbox_api import FritzBox, FirmwareManager
from browser_utils import setup_browser, Browser
import time
import win32gui
import win32con
import ctypes
import re

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

    def ensure_browser(self):
        if self.browser is None or not self.browser_still_alive():
            self.browser_driver = setup_browser()
            self.browser = Browser(self.browser_driver)
            if not self.fritzbox:
                self.fritzbox = FritzBox(self.browser)
            else:
                self.fritzbox.browser = self.browser

    def browser_still_alive(self):
        try:
            # Ping: kleine Abfrage an den Browser
            self.browser.driver.title
            return True
        except Exception:
            return False

    def _fenster_in_vordergrund_holen(self):
        """Bringt das CMD-Fenster in den Vordergrund."""
        try:
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            win32gui.ShowWindow(console_hwnd, win32con.SW_SHOWNORMAL)
            win32gui.SetForegroundWindow(console_hwnd)
            print("🪟 CMD-Fenster wurde in den Vordergrund gebracht.")
        except Exception as e:
            print(f"⚠️ Fenster-Fokus fehlgeschlagen")

    def _run_step_with_retry(self, description: str, func, *args, **kwargs) -> bool:
        """
        Führt einen einzelnen Schritt aus und bietet Optionen zur Wiederholung/Überspringen bei Fehlern.
        Gibt True zurück, wenn der Schritt erfolgreich war oder übersprungen wurde, False bei Abbruch.
        """
        print(f"\n➡️ {description}...")

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                self.ensure_browser()

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

                print("✅ Schritt erfolgreich.")
                return True

            except Exception as e:
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt + 1}/{max_attempts}) Error:{e}")
                if attempt < max_attempts - 1:
                    print("🔁 Versuche es erneut...")
                    time.sleep(2)
                else:
                    # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                    # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                    break

        # Wenn der fehlgeschlagene Schritt der Login war:
        if description == "Login durchführen":
            print("\nLogin ist fehlgeschlagen. Starte Korrektur...")
            letztes_passwort = self.fritzbox.password  # Das zuletzt versuchte Passwort holen

            while True:
                neues_passwort = input(
                    "🔑 Passwort möglicherweise falsch. Bitte erneut eingeben.").strip()

                if neues_passwort == letztes_passwort:
                    print("⚠️ Das eingegebene Passwort ist identisch zum letzten Versuch.")
                    print("🚨 Starte Werksreset über 'Passwort vergessen'...")
                    return self.fritzbox.reset_via_forgot_password()
                else:
                    # Der Benutzer hat ein neues Passwort eingegeben, wir versuchen es damit erneut.
                    print("🔁 Versuche Login mit dem neuen Passwort...")
                    # Wir rufen die Login-Funktion direkt mit dem neuen Passwort auf
                    if self.fritzbox.login(neues_passwort):
                        print("✅ Login mit neuem Passwort war erfolgreich!")
                        return True
                    else:
                        letztes_passwort = neues_passwort


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
        """Führt den gesamten FritzBox-Verwaltungs-Workflow anhand einer flexiblen Schritt-Liste aus."""

        try:
            workflow_steps = [
                ("FritzBox Erreichbarkeit prüfen", self.fritzbox.warte_auf_erreichbarkeit),
                ("Login durchführen", self.fritzbox.login, password),
                ("Box-Modell ermitteln", self.fritzbox.get_box_model),
                ("Firmware-Version ermitteln", self.fritzbox.get_firmware_version),
                ("Erweiterte Ansicht prüfen/aktivieren", self.fritzbox.activate_expert_mode_if_needed),
                ("Firmware Update Routine", self.fritzbox.update_firmware),
                ("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas),
                ("Werkseinstellungen über UI", self.fritzbox.perform_factory_reset_from_ui),
                ("WLAN-Scan Zusammenfassung", self.fritzbox.show_wlan_summary),
            ]

            for step_name, func, *args in workflow_steps:
                try:
                    if not self._run_step_with_retry(step_name, func, *args):
                        return None
                    self._fenster_in_vordergrund_holen()
                except RuntimeError as e:
                    if str(e) == "RESTART_NEW_BOX":
                        return "restart"
                    else:
                        raise
                except Exception:
                    raise Exception


            print("\n🎉 Workflow für diese FritzBox erfolgreich abgeschlossen!")
            auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
            return None if auswahl == 'b' else "restart"

        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow: {e}")
            time.sleep(10)
            raise Exception

        finally:
            if self.browser:
                self.browser.quit()