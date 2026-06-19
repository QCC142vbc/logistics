import argparse
import numpy as np
import pandas as pd


def clamp(x, a, b):
    return np.minimum(np.maximum(x, a), b)


def sample_route_type(n):
    return np.random.choice(['urban', 'mixed', 'highway'], size=n, p=[0.4, 0.4, 0.2])


def sample_time_of_day(n):
    return np.random.choice(['night', 'offpeak', 'peak'], size=n, p=[0.2, 0.5, 0.3])


def route_time_base_traffic(route, tod):
    base_map = {
        ('urban', 'peak'): 0.8,
        ('urban', 'offpeak'): 0.5,
        ('urban', 'night'): 0.3,
        ('mixed', 'peak'): 0.6,
        ('mixed', 'offpeak'): 0.4,
        ('mixed', 'night'): 0.25,
        ('highway', 'peak'): 0.6,
        ('highway', 'offpeak'): 0.35,
        ('highway', 'night'): 0.2,
    }
    return np.array([base_map[(r, t)] for r, t in zip(route, tod)], dtype=float)


def sample_weather(n):
    precip = np.random.gamma(shape=2.0, scale=1.5, size=n)
    wind = clamp(np.random.normal(20, 10, size=n), 0, 120)
    vis = clamp(10 - 0.3 * precip - 0.02 * wind + np.random.normal(0, 0.5, size=n), 0.5, 10)
    return precip, wind, vis


def generate(n=10000, scenario='normal', seed=42):
    np.random.seed(seed)

    distance = np.random.uniform(20, 1200, size=n)
    route_type = sample_route_type(n)
    time_of_day = sample_time_of_day(n)

    precip, wind_speed, visibility = sample_weather(n)
    if scenario == 'extreme':
        precip = precip * 2

    base_traffic = route_time_base_traffic(route_type, time_of_day)

    traffic_index = clamp(
        base_traffic + 0.2 * (precip / 10) + 0.1 * (wind_speed / 100) + np.random.normal(0, 0.05, size=n),
        0,
        1,
    )

    if scenario == 'stressed':
        traffic_index = clamp(traffic_index + 0.2, 0, 1)
    elif scenario == 'extreme':
        traffic_index = clamp(traffic_index + 0.2, 0, 1)

    load = np.random.beta(2, 2, size=n)
    load = clamp(load + 0.2 * (time_of_day == 'peak'), 0, 1)

    fleet_utilization = clamp(load + np.random.normal(0, 0.05, size=n), 0, 1)
    driver_availability = clamp(1 - load + np.random.normal(0, 0.05, size=n), 0, 1)
    driver_fatigue = clamp(0.3 + 0.5 * (time_of_day == 'peak') + 0.2 * load + np.random.normal(0, 0.05, size=n), 0, 1)
    warehouse_dock_util = clamp(load + np.random.normal(0, 0.07, size=n), 0, 1)
    warehouse_queue_time = np.maximum(0, np.random.normal(20 + 80 * warehouse_dock_util, 10, size=n))

    traffic_index = traffic_index.copy()
    incident_prob = 0.05 + 0.25 * traffic_index + 0.1 * (precip / 10)

    if scenario == 'stressed':
        traffic_index = clamp(traffic_index + 0.2, 0, 1)
        fleet_utilization = clamp(fleet_utilization + 0.15, 0, 1)
        incident_prob = clamp(incident_prob + 0.05, 0, 1)
    elif scenario == 'extreme':
        precip = precip * 2
        traffic_index = clamp(traffic_index + 0.2, 0, 1)
        incident_prob = clamp(incident_prob * 1.5, 0, 1)

    incident_flag = np.random.rand(n) < incident_prob
    incident_flag = incident_flag.astype(int)

    speed_map = {
        'highway': 80,
        'mixed': 60,
        'urban': 40,
    }
    avg_speed = np.array([speed_map[r] for r in route_type], dtype=float)
    tbase = distance / avg_speed * 60.0

    dw = tbase * (0.05 * (precip / 10) + 0.03 * (wind_speed / 100) + 0.1 * (1 - visibility / 10))
    dt = tbase * (0.3 * traffic_index) + 20.0 * incident_flag
    df = 30.0 * np.maximum(0, fleet_utilization - 0.7)
    dd = 20.0 * driver_fatigue + 15.0 * (1 - driver_availability)
    dwh = 0.5 * warehouse_queue_time
    dint = 0.1 * dt * (precip / 10)
    eps = np.random.normal(0, 10, size=n)

    delay_minutes = np.maximum(0.0, dw + dt + df + dd + dwh + dint + eps)
    sla_threshold = 0.15 * tbase
    sla_breach = (delay_minutes > sla_threshold).astype(int)

    return pd.DataFrame(
        {
            'distance_km': distance,
            'route_type': route_type,
            'time_of_day': time_of_day,
            'precipitation': precip,
            'wind_speed': wind_speed,
            'visibility': visibility,
            'traffic_index': traffic_index,
            'incident_flag': incident_flag,
            'fleet_utilization': fleet_utilization,
            'driver_fatigue': driver_fatigue,
            'driver_availability': driver_availability,
            'warehouse_dock_util': warehouse_dock_util,
            'warehouse_queue_time': warehouse_queue_time,
            'delay_minutes': delay_minutes,
            'sla_breach': sla_breach,
        }
    )


def main():
    parser = argparse.ArgumentParser(description='Generate synthetic logistics dataset for ALCE calibration.')
    parser.add_argument('--n', type=int, default=10000, help='Number of samples to generate.')
    parser.add_argument('--scenario', choices=['normal', 'stressed', 'extreme'], default='normal', help='Scenario mode for the generator.')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for reproducibility.')
    parser.add_argument('--output', default='calibration/synthetic_logistics.csv', help='Output CSV path.')
    args = parser.parse_args()

    df = generate(n=args.n, scenario=args.scenario, seed=args.seed)
    df.to_csv(args.output, index=False)
    print(f'Generated {len(df)} rows to {args.output} ({args.scenario} scenario).')


if __name__ == '__main__':
    main()
