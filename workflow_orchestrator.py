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

        max_attempts = 2 # Maximal zwei automatische Versuche
        for attempt in range(max_attempts):
            try:
                # Führe die Funktion aus. Ihre Rückgabe ist entscheidend.
                # Es wird erwartet, dass die Funktion True bei Erfolg, False bei bestimmten Fehlern zurückgibt.
                # Oder eine Exception wirft, die hier gefangen wird.
                result = func(*args, **kwargs)
                if result is None: # Wenn die Funktion nichts zurückgibt, nehmen wir Erfolg an.
                    print("✅ Schritt erfolgreich (Funktion gab keine explizite Rückgabe).")
                    return True
                elif result is True:
                    print("✅ Schritt erfolgreich.")
                    return True
                else: # Wenn die Funktion explizit False zurückgibt (z.B. Login fehlgeschlagen)
                    raise Exception("Funktion meldete Fehlschlag.")

            except Exception as e:
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    print("🔁 Versuche es erneut...")
                    time.sleep(2) # Kurze Pause vor dem nächsten Versuch
                else:
                    break # Alle automatischen Versuche aufgebraucht

        # Wenn alle automatischen Versuche fehlgeschlagen sind, frage den Benutzer
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
                raise RuntimeError("RESTART_NEW_BOX") # Spezielles Signal für Main-Loop
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
            # 1. FritzBox Erreichbarkeit prüfen
            if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen", self.fritzbox.warte_auf_erreichbarkeit):
                return None

            # 2. Login durchführen
            # Das Passwort wird nun direkt an die Login-Methode übergeben
            if not self._run_step_with_retry("Login durchführen", self.fritzbox.login, password):
                return None # Abbruch, wenn Login fehlschlägt

            # 3. Box-Modell ermitteln
            # get_box_model setzt self.fritzbox.box_model
            if not self._run_step_with_retry("Box-Modell ermitteln", self.fritzbox.get_box_model):
                return None

            # 4. Firmware-Version ermitteln
            # get_firmware_version setzt self.fritzbox.os_version
            if not self._run_step_with_retry("Firmware-Version ermitteln", self.fritzbox.get_firmware_version):
                return None

            # 5. Firmware-Pfad ermitteln (automatisch oder manuell)
            firmware_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model)
            if not firmware_path:
                print("❌ Firmware-Pfad konnte nicht ermittelt werden. Abbruch des Updates.")
                # Hier könnten wir den Benutzer fragen, ob er trotzdem fortfahren möchte (ohne Update)
                if not self._run_step_with_retry("Trotzdem fortfahren? (Update überspringen)", lambda: True): # Trick: immer True, aber Abfrage
                    return None
            else:
                # 6. Firmware-Update oder Reset basierend auf Version und Modell
                # Hier die Logik zur Entscheidung, ob Update oder Reset oder beides
                target_version = self.firmware_manager.firmware_mapping.get(self.fritzbox.box_model)

                perform_update = False
                perform_reset = False

                if self.fritzbox.box_model == "UNKNOWN":
                    print("⚠️ Box-Modell unbekannt. Keine spezifische Firmware-Logik anwendbar.")
                    # Hier könnte man den Benutzer fragen, ob er ein generisches Update/Reset möchte
                    if input("Möchten Sie trotzdem ein Update/Reset versuchen? (j/n): ").lower() == 'j':
                         # Wenn der Benutzer 'j' sagt, versuchen wir, das Update mit dem ermittelten Pfad zu machen
                         # oder einen Reset, wenn es 8.03 ist.
                        if self.fritzbox.os_version == "8.03":
                            perform_reset = True
                        elif firmware_path: # nur wenn ein Pfad vorhanden ist
                            perform_update = True
                elif target_version and self.fritzbox.os_version != target_version:
                    print(f"Firmware {self.fritzbox.box_model} sollte auf {target_version} sein. Aktuell: {self.fritzbox.os_version}")
                    perform_update = True
                elif self.fritzbox.os_version == "8.03": # TIM-spezifische Reset-Logik
                    print("🔁 Version 8.03 erkannt – Reset statt Update (TIM-Spezifisch).")
                    perform_reset = True
                else:
                    print(f"ℹ️ Firmware ist aktuell ({self.fritzbox.os_version}) für {self.fritzbox.box_model} oder kein spezifisches Update nötig.")
                    # Optional: Wenn kein Update nötig, fragen, ob Reset gewünscht ist
                    if input("Möchten Sie die Box trotzdem auf Werkseinstellungen zurücksetzen? (j/n): ").lower() == 'j':
                        perform_reset = True

                if perform_update and firmware_path:
                    if not self._run_step_with_retry("Firmware-Update durchführen", self.fritzbox.perform_firmware_update, firmware_path):
                        return None
                    # Nach dem Update ist die Box oft im Sprachauswahl-Modus oder braucht einen erneuten Login
                    # Warte auf erneute Erreichbarkeit und Login nach Update
                    if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Update)", self.fritzbox.warte_auf_erreichbarkeit):
                        return None
                    if not self._run_step_with_retry("Erneuter Login nach Update", self.fritzbox.login, password):
                        return None
                    # Version und Modell nach Update erneut prüfen, da sie sich geändert haben könnten
                    self._run_step_with_retry("Box-Modell erneut ermitteln (nach Update)", self.fritzbox.get_box_model)
                    self._run_step_with_retry("Firmware-Version erneut ermitteln (nach Update)", self.fritzbox.get_firmware_version)

                if perform_reset:
                    # Entscheide, welche Reset-Methode verwendet werden soll
                    # Hier könntest du eine Logik einbauen, z.B. wenn kein Login möglich ist, den "Passwort vergessen"-Reset nutzen
                    if self.fritzbox.is_logged_in:
                        if not self._run_step_with_retry("Werkseinstellungen über UI", self.fritzbox.perform_factory_reset_from_ui):
                            return None
                    else:
                        if not self._run_step_with_retry("Werkseinstellungen via 'Passwort vergessen'", self.fritzbox.reset_via_forgot_password):
                            return None

                    # Nach dem Reset ist die Box definitiv ausgeloggt und im Sprachauswahl-Modus
                    # Warte auf erneute Erreichbarkeit und setze Sprache
                    if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen (nach Reset)", self.fritzbox.warte_auf_erreichbarkeit):
                        return None
                    # Sprache auf Englisch setzen
                    if not self._run_step_with_retry("Sprache auf Englisch setzen", self.fritzbox.set_language, "en"):
                         return None
                    # Nach Reset ist Login erforderlich
                    if not self._run_step_with_retry("Erneuter Login nach Reset", self.fritzbox.login, password):
                        return None

            # 7. WLAN-Antennen prüfen
            if not self._run_step_with_retry("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas):
                return None

            print("\n🎉 Workflow erfolgreich abgeschlossen!")
            return None # Kein Restart notwendig

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