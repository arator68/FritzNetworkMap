# FRITZ!Box Network Map — Entwicklungsstand 0.1.2

## Testziel
- Der bisherige Geräteabruf über `/api/v0/generic/landevice` bleibt erhalten.
- Zusätzlich wird optional TR-064 `Hosts:1` abgefragt (`GetHostNumberOfEntries` / `GetGenericHostEntry`).
- Die Attribute unter `devices` sollen pro Gerät zusätzlich enthalten:
  - `connection_type`: `LAN`, `WLAN` oder `unknown`
  - `interface_type`: Rohwert der FRITZ!Box
  - `active`: Status, sofern geliefert
- Ist TR-064 nicht verfügbar, bleibt die bisherige Geräteliste bestehen; die neuen Werte können dann `unknown` bleiben.

## Aktualisierung
1. Sicherungskopie des vorhandenen Ordners `custom_components/fritzbox_network_map` anlegen.
2. Ordner aus diesem ZIP nach `/config/custom_components/fritzbox_network_map` kopieren und vorhandene Dateien überschreiben.
3. Home Assistant neu starten.
4. Entwicklerwerkzeuge → Zustände → `sensor.fritz_box_netzwerkgeraete` öffnen.
5. Unter `devices` die Werte `connection_type` und `interface_type` prüfen.

## Grenzen
- Noch nicht gegen die konkrete FRITZ!Box getestet; TR-064-Verfügbarkeit und Antwortformat hängen von FRITZ!OS und Berechtigungen ab.
- Frequenzband, Datenrate, Signalstärke und Mesh-Repeater-Pfad sind noch nicht implementiert.
- Fehler der optionalen TR-064-Abfrage werden abgefangen, damit der bestehende Geräteabruf erhalten bleibt.
