import argparse
import json
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

SCHEMA = [
    'shipment_id',
    'route_id',
    'timestamp',
    'precipitation',
    'wind_speed',
    'visibility',
    'traffic_index',
    'incident_flag',
    'fleet_utilization',
    'driver_fatigue',
    'driver_availability',
    'warehouse_dock_util',
    'warehouse_queue_time',
    'delay_minutes',
    'sla_breach'
]

FACTOR_DEFS = {
    'weather': ['precipitation', 'wind_speed', 'visibility'],
    'traffic': ['traffic_index', 'incident_flag'],
    'fleet': ['fleet_utilization'],
    'driver': ['driver_fatigue', 'driver_availability'],
    'warehouse': ['warehouse_dock_util', 'warehouse_queue_time']
}

TARGET = 'sla_breach'

PERCENTILE_COLS = {
    'weather': ['precipitation', 'wind_speed', 'visibility'],
    'traffic': ['traffic_index', 'incident_flag'],
    'fleet': ['fleet_utilization'],
    'driver': ['driver_fatigue', 'driver_availability'],
    'warehouse': ['warehouse_dock_util', 'warehouse_queue_time']
}

CALIBRATION_PATH = 'calibration/params.json'


def percentile_scale(series):
    p5 = series.quantile(0.05)
    p95 = series.quantile(0.95)
    scaled = (series - p5) / (p95 - p5)
    return scaled.clip(0, 1), float(p5), float(p95)


def build_feature_matrix(df, columns):
    return df[columns].fillna(0).astype(float)


def train_factor_models(df):
    models = {}
    scalers = {}

    for factor, columns in FACTOR_DEFS.items():
        X = build_feature_matrix(df, columns)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = LogisticRegression(solver='liblinear', max_iter=1000)
        model.fit(X_scaled, df[TARGET])

        models[factor] = {
            'intercept': float(model.intercept_[0]),
            'coef': [float(c) for c in model.coef_[0]],
            'columns': columns
        }
        scalers[factor] = scaler

    return models, scalers


def predict_factor_scores(df, models, scalers):
    scores = pd.DataFrame(index=df.index)
    for factor, meta in models.items():
        X = build_feature_matrix(df, meta['columns'])
        scaler = scalers[factor]
        X_scaled = scaler.transform(X)
        logits = X_scaled.dot(meta['coef']) + meta['intercept']
        scores[factor] = 1 / (1 + np.exp(-logits))
    return scores


def train_meta_model(score_df, target):
    model = LogisticRegression(solver='liblinear', max_iter=1000)
    model.fit(score_df, target)
    return model


def calibrate_score(raw_scores, target):
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(raw_scores, target)
    return iso


def export_params(params, path=CALIBRATION_PATH):
    with open(path, 'w') as f:
        json.dump(params, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Train calibration models for ALCE risk scoring')
    parser.add_argument('--data', required=True, help='Path to historical shipment CSV')
    parser.add_argument('--output', default=CALIBRATION_PATH, help='Output JSON file for calibrated parameters')
    parser.add_argument('--distort-factor', choices=list(FACTOR_DEFS.keys()), help='Deliberately distort one factor during training')
    parser.add_argument('--distort-scale', type=float, default=1.0, help='Scale applied to the distorted factor raw signal')
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    df = df.dropna(subset=[TARGET])

    train_df, test_df = train_test_split(df, test_size=0.3, random_state=42, stratify=df[TARGET])
    val_df, test_df = train_test_split(test_df, test_size=0.5, random_state=42, stratify=test_df[TARGET])

    factor_models = {}
    scaling = {}

    for factor, cols in PERCENTILE_COLS.items():
        combined = train_df[cols].fillna(0).astype(float)
        flattened = combined.mean(axis=1)
        scaled, p5, p95 = percentile_scale(flattened)
        scaling[factor] = {'p5': p5, 'p95': p95}

    # NOTE: This example code trains lightweight logistic factors with standard scaling, but it is intended as a template.
    # For production use, replace the feature engineering sections with your actual factor definition and the P5/P95 scaler.

    # Use each factor as a single proxy feature for the first pass
    factor_scores_train = pd.DataFrame(index=train_df.index)
    for factor, cols in FACTOR_DEFS.items():
        raw = train_df[cols].fillna(0).astype(float).mean(axis=1)
        if args.distort_factor == factor:
            print(f'Distorting factor {factor} by scale {args.distort_scale}')
            raw = raw * args.distort_scale
        scaled = (raw - scaling[factor]['p5']) / (scaling[factor]['p95'] - scaling[factor]['p5'])
        factor_scores_train[factor] = scaled.clip(0, 1)

    meta_model = LogisticRegression(solver='liblinear', max_iter=1000)
    meta_model.fit(factor_scores_train, train_df[TARGET])

    params = {
        'scaling': scaling,
        'factorModels': {
            factor: {'intercept': 0.0, 'coef': 1.0}
            for factor in FACTOR_DEFS
        },
        'metaModel': {
            'intercept': float(meta_model.intercept_[0]),
            'coefficients': {factor: float(coef) for factor, coef in zip(factor_scores_train.columns, meta_model.coef_[0])}
        },
        'interactions': {},
        'calibration': {
            'intercept': 0.0,
            'coef': 1.0
        },
        'distortion': {
            'factor': args.distort_factor,
            'scale': args.distort_scale
        }
    }

    export_params(params, args.output)
    print(f'Calibration parameters exported to {args.output}')

if __name__ == '__main__':
    import numpy as np
    main()
