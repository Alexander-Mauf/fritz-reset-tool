
from fritz_steps import (
    erstelle_standard_steps
)


def run_step(driver, description, func):
    print(f"\n➡️ {description}...")
    try:
        return func(driver)
    except Exception as e:
        print(f"⚠️ Fehler bei {description}: {e}")
        choice = input("🔁 (W)iederholen, (Ü)berspringen, (B)eenden? ").strip().lower()
        if choice == "w":
            return func(driver)
        elif choice == "ü":
            return
        else:
            raise SystemExit("Abbruch durch Benutzer")

def run_workflow(driver, password, firmware_pfad):
    steps = erstelle_standard_steps(password, firmware_pfad)
    for beschreibung, funktion in steps:
        run_step(driver, beschreibung, funktion)
