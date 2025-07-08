# main.py
from utils import run_workflow, dateipfad_auswählen
import time

def main():
    try:
        firmware_pfad = dateipfad_auswählen()
        if not firmware_pfad:
            print("❌ Keine Firmware-Datei ausgewählt.")
            return

        while True:
            password = input("🔑 FritzBox-Passwort eingeben: ").strip()
            result = run_workflow(password, firmware_pfad)

            if result == "restart":
                continue

            again = input("🔁 Nochmal ausführen? (j/n): ").strip().lower()
            if again != "j":
                print("🏁 Vorgang abgeschlossen.")
                break
    except Exception as e:
        print(e)
        time.sleep(5)


if __name__ == "__main__":
    main()
