# Calibration Pipeline for ALCE Lite

This calibration layer converts the current deterministic risk engine into a data-aligned scoring system.

## Goal
Use historical shipment outcomes to map raw inputs into factor-level probabilities, learn optimal factor weights, and calibrate the final score to delay probability.

## Dataset schema
Required columns:
- shipment_id
- route_id
- timestamp
- precipitation
- wind_speed
- visibility
- traffic_index
- incident_flag
- fleet_utilization
- driver_fatigue
- driver_availability
- warehouse_dock_util
- warehouse_queue_time
- delay_minutes
- sla_breach (0/1)

## Training steps
1. Normalize raw inputs using percentile scaling (P5/P95).
2. Train lightweight factor models per risk domain.
3. Train a meta logistic regression on factor scores.
4. Calibrate the aggregate score to probability.
5. Export model coefficients and scaling parameters to `calibration/params.json`.

## Usage

```bash
python3 calibration/synthetic_data.py --n 10000 --scenario normal --output calibration/synthetic_logistics.csv
python3 calibration/train_calibration.py --data calibration/synthetic_logistics.csv --output calibration/params.json
```

## Backend integration
The Express backend loads `calibration/params.json` and applies:
- percentile-based scaling for raw inputs
- factor-level logistic models
- meta-model aggregation
- probability calibration

This preserves modular explainability while aligning the score with actual delay probability.
