# Zigbee range test — SLZB-06MU / SNZB-02D

Status: pending hardware and physical testing. No routers added.

Record coordinator location, firmware, antenna orientation, Zigbee channel, date/time, sensor ID, and battery before starting. Keep coordinator in a fixed position. At each point, allow several actual fresh reports (record timestamps and observation duration); do not use retained MQTT state. Use Zigbee2MQTT LQI 0–255 and report missing data separately, not as LQI 0. LQI is not a distance measurement or a guaranteed reliability score.

| Test ID | Location / floor | Distance m | Obstruction | Observation time | Fresh reports | LQI min / max | Last seen | Result / notes |
|---|---|---|---|---|---|---|---|---|
| RF-01 | Same floor, line of sight | | None | | | | | Pending |
| RF-02 | Same floor, progressively farther | | None | | | | | Pending |
| RF-03 | Behind production partition | | Wall | | | | | Pending |
| RF-04 | Curtain negative-pressure room | | Curtain | | | | | Pending |
| RF-05 | Behind storage racks | | Racks | | | | | Pending |
| RF-06 | One floor above | | Floor slab | | | | | Pending |
| RF-07 | One floor below | | Floor slab | | | | | Pending |
| RF-08 | Two floors away | | Floor slabs | | | | | Pending |

Repeat until maximum reliable distance and floor reach are measured. List all dead zones separately. Compare actual report cadence with configured timeout; decide whether routers are needed only after reviewing results.
