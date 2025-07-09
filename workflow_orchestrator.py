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
        Führt den gesamten FritzBox-Verwaltungs-Workflow in einer logisch korrekten Reihenfolge aus.
        Gibt "restart" zurück, wenn eine neue Box gewünscht wird, sonst None.
        """
        self.browser_driver = setup_browser()
        self.browser = Browser(self.browser_driver)
        self.fritzbox = FritzBox(self.browser)
        self._fenster_in_vordergrund_holen()

        try:
            # Schritt 1 & 2: Erreichbarkeit prüfen und Login (inkl. Dialog-Handling)
            if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen", self.fritzbox.warte_auf_erreichbarkeit):
                return None
            if not self._run_step_with_retry("Login durchführen", self.fritzbox.login, password):
                return None

            # Schritt 3 & 4: Versionen und Modell ermitteln
            if not self._run_step_with_retry("Firmware-Version ermitteln", self.fritzbox.get_firmware_version):
                return None
            if not self._run_step_with_retry("Box-Modell ermitteln", self.fritzbox.get_box_model):
                return None

            # Schritt 5: WLAN-Antennen prüfen (vor potenziellen Änderungen)
            if not self._run_step_with_retry("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas):
                return None

            # --- Ab hier optionale, vom Benutzer gesteuerte Aktionen ---

            # Schritt 6: Update vorbereiten (Erweiterte Ansicht prüfen und Firmware-Pfad holen)
            if not self._run_step_with_retry("Erweiterte Ansicht prüfen/aktivieren",
                                             self.fritzbox.activate_expert_mode_if_needed):
                return None
            firmware_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model)

            # Schritt 7 & 8: Entscheidung und Durchführung von Update oder Reset
            perform_update = False
            perform_reset = False

            # Update anbieten, wenn sinnvoll
            if firmware_path:
                target_version = self.firmware_manager.firmware_mapping.get(self.fritzbox.box_model)
                if target_version and target_version not in self.fritzbox.os_version:
                    print(
                        f"ℹ️ Update empfohlen: Aktuell ist '{self.fritzbox.os_version}', Ziel ist '{target_version}'.")
                    if input("Möchten Sie das Firmware-Update durchführen? (j/n): ").lower() == 'j':
                        perform_update = True
                else:
                    print(f"✅ Firmware ist aktuell ({self.fritzbox.os_version}).")
            else:
                print("⚠️ Firmware-Datei nicht gefunden, Update nicht möglich.")

            # Reset anbieten (immer als Option, falls kein Update gemacht wird)
            if not perform_update:
                if input("Möchten Sie die Box auf Werkseinstellungen zurücksetzen? (j/n): ").lower() == 'j':
                    perform_reset = True

            # Durchführung
            if perform_update:
                # KORREKTUR: Der Aufruf wird in eine Lambda-Funktion gekapselt.
                # Das stellt sicher, dass das 'firmware_path'-Argument korrekt übergeben wird.
                update_step = lambda: self.fritzbox.perform_firmware_update(firmware_path)

                if self._run_step_with_retry("Firmware-Update durchführen", update_step):
                    print("⏳ Warte 180 Sekunden auf den Neustart der Box nach dem Update...")
                    time.sleep(180)
                    # Nach dem Update ist eine komplette Neuanmeldung nötig
                    if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Update)",
                                                     self.fritzbox.warte_auf_erreichbarkeit, versuche=30,
                                                     delay=10): return None
                    if not self._run_step_with_retry("Erneuter Login nach Update", self.fritzbox.login, password,
                                                     force_reload=True): return None
                    self._run_step_with_retry("Firmware-Version erneut ermitteln", self.fritzbox.get_firmware_version)
                else:
                    return None

            if perform_reset:
                if self.fritzbox.perform_factory_reset_from_ui():
                    print("⏳ Warte 120 Sekunden auf den Neustart der Box nach dem Reset...")
                    time.sleep(120)
                    # Nach Reset ist ebenfalls eine Neuanmeldung nötig
                    if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Reset)",
                                                     self.fritzbox.warte_auf_erreichbarkeit, versuche=30,
                                                     delay=10): return None
                    if self.fritzbox.ist_sprachauswahl(): self.fritzbox.set_language("en")
                    if not self._run_step_with_retry("Erneuter Login nach Reset", self.fritzbox.login, password,
                                                     force_reload=True): return None
                else:
                    return None

            print("\n🎉 Workflow für diese FritzBox erfolgreich abgeschlossen!")

            # Frage nach der nächsten Aktion
            while True:
                auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
                if auswahl == 'n':
                    return "restart"
                elif auswahl == 'b':
                    return None

        except RuntimeError as e:
            if str(e) == "RESTART_NEW_BOX":
                print("🆕 Benutzer wünscht neue FritzBox. Starte Workflow neu.")
                return "restart"
            raise e
        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow: {e}")
            return None
        finally:
            if self.browser:
                self.browser.quit()