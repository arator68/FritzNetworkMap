FRITZ!Box Network Map – MAC-Herstellerdatenbank

Enthaltene Dateien für custom_components/fritzbox_network_map:
- fritzbox_client.py (erweitert um lokale MAC-Präfix-Erkennung)
- sensor.py (fünf zusätzliche Gerätesensoren und zwei Datenbank-Diagnosesensoren)
- mac_vendor.py (lokaler Lookup, längster Präfix gewinnt)
- mac_vendors.csv (wird durch das Skript befüllt)
- build_mac_vendor_db.py (lädt öffentliche IEEE-MAC-Registrierungen)

WICHTIG: Die CSV enthält zunächst nur die Kopfzeile. Damit keine Herstellerdaten erfunden werden,
muss die Liste einmal auf dem Home-Assistant-System erzeugt werden.

Im Home-Assistant-Terminal ausführen:
  python3 /config/custom_components/fritzbox_network_map/build_mac_vendor_db.py

Das Skript benötigt für diesen einmaligen Download Internetzugriff. Danach läuft die Suche lokal.
Es lädt die öffentlichen IEEE-Registrierungen MA-L, MA-M und MA-S.

Danach Home Assistant neu starten. Die Sensoren zeigen:
- pro Gerät: Hersteller, MAC-Präfix, Hersteller-Registrierung, Hersteller-Erkennung,
  Gerätetyp-Erkennung
- separates Diagnosegerät: Herstellerdatenbank-Status und Herstellerdatenbank-Einträge

Wichtig zur Interpretation:
- Herstellerzuordnung beweist nicht, dass das Gerät ein Switch ist.
- lokal verwaltete/randomisierte MAC-Adressen werden nicht einem Hersteller zugeschrieben.
- Switch-Hinweise aus Namen/Modell werden als Hinweis markiert, nicht als sichere Erkennung.
- Bestehende Diagnose-Warnmeldungen wurden nicht entfernt.
