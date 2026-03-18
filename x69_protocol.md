# X69 Drone (ProFlight PFBD302) Communication Protocol Documentation

This document identifies the communication protocols for the X69 drone, as derived from the App Store and the ProFlight PFBD302 manual.

## WiFi Specifications

- **SSID Pattern**: `X69-XXXXXX`, `WiFi-XXXXXX`, or `GPS-XXXXXX`.
- **Frequency**:
  - **Remote Controller**: 2.4GHz (proprietary RF link, FHSS).
  - **WiFi FPV**: 2.4GHz or 5GHz (802.11ac), depending on hardware revision.
- **Default IP**: `192.168.1.1` or `192.168.0.1`.
- **Control Protocol**: UDP (User Datagram Protocol).
- **Control Ports**:
  - **Flight Control**: UDP 8888 or 50000.
  - **Video Streaming**: UDP 8080.
- **Range**:
  - **WiFi FPV**: Approximately 200 meters.
  - **Remote Controller**: Approximately 400 meters.

## Bluetooth Specifications

- **Result**: No Bluetooth or BLE hardware identified.
- **Connection Method**: The drone and app connect exclusively via the drone's WiFi hotspot. The remote controller pairs with the drone using a proprietary 2.4GHz RF link.

## Control Commands (Common WiFi Drones)

*Note: These are representative of the UDP-based commands identified for similar WiFi drones.*

| Command | Action |
| --- | --- |
| `TAKEOFF` | Drone initiates takeoff. |
| `LAND` | Drone initiates landing. |
| `UP` | Drone moves upward. |
| `DOWN` | Drone moves downward. |
| `LEFT` | Drone moves left. |
| `RIGHT` | Drone moves right. |
| `FORWARD` | Drone moves forward. |
| `BACKWARD` | Drone moves backward. |
| `FLIP` | Drone performs a 360-degree flip. |
| `HEADLESS_MODE` | Toggle orientation-independent flight. |
| `EMERGENCY_STOP` | Immediate cut of all motors. |
