const express = require('express');
const cors = require('cors');
const fs = require('fs');

const path = require('path');
const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

const CALIBRATION_FILE = process.env.CALIBRATION_FILE
  ? path.resolve(__dirname, process.env.CALIBRATION_FILE)
  : path.join(__dirname, 'calibration', 'params.json');
let calibrationParams = null;

try {
  calibrationParams = JSON.parse(fs.readFileSync(CALIBRATION_FILE, 'utf8'));
  console.log(`Loaded calibration parameters from ${CALIBRATION_FILE}`);
} catch (error) {
  console.warn(`Calibration parameters not found or invalid at ${CALIBRATION_FILE}, using fallback defaults.`, error.message);
}

function clamp(value, min = 0, max = 100) {
  return Math.round(Math.min(max, Math.max(min, value)));
}

function normalizePayload(payload = {}) {
  return {
    precipitation: payload.precipitation,
    windSpeed: payload.windSpeed,
    visibility: payload.visibility,
    weather: payload.weather ?? payload.weatherRisk ?? 0,
    congestion: payload.congestion,
    incident: payload.incident,
    traffic: payload.traffic ?? payload.trafficSeverity ?? 0,
    utilization: payload.utilization,
    fleetAvailability: payload.fleetAvailability ?? payload.fleet ?? (payload.fleetUtilization != null ? 100 - Number(payload.fleetUtilization) : undefined),
    fleet: payload.fleet ?? payload.fleetAvailability,
    fatigue: payload.fatigue,
    availability: payload.availability ?? (payload.driverReadiness != null ? Number(payload.driverReadiness) / 100 : undefined),
    driverReadiness: payload.driverReadiness,
    dockUtilization: payload.dockUtilization,
    queueTime: payload.queueTime,
    warehouse: payload.warehouse ?? payload.load ?? 0,
    load: payload.load ?? payload.warehouse,
    distanceKm: payload.distanceKm ?? payload.distance,
    baseSpeedKmh: payload.baseSpeedKmh ?? payload.routeSpeed ?? payload.speed
  };
}

function percentileNormalize(value, p5, p95) {
  if (p95 === p5) return 0;
  return Math.min(1, Math.max(0, (value - p5) / (p95 - p5)));
}

function toProbability(logit) {
  return 1 / (1 + Math.exp(-logit));
}

function factorRawValue(factor, payload) {
  switch (factor) {
    case 'weather':
      return Number(payload.weather ?? 0);
    case 'traffic':
      return Number(payload.traffic ?? payload.trafficSeverity ?? 0);
    case 'fleet':
      return Number(payload.fleetAvailability ?? payload.fleet ?? 0);
    case 'driver':
      return Number(payload.driverReadiness ?? 0);
    case 'warehouse':
      return Number(payload.warehouse ?? payload.load ?? 0);
    default:
      return 0;
  }
}

function computeFactorScore(factor, payload) {
  const params = calibrationParams?.factorModels?.[factor];
  const scaling = calibrationParams?.scaling?.[factor];
  const rawValue = factorRawValue(factor, payload);
  const normalized = scaling
    ? percentileNormalize(rawValue, scaling.p5, scaling.p95)
    : Math.min(1, Math.max(0, rawValue / 100));

  if (params && typeof params.intercept === 'number' && typeof params.coef === 'number') {
    const logit = params.intercept + params.coef * normalized;
    return clamp(Math.round(toProbability(logit) * 100));
  }

  return clamp(Math.round(normalized * 100));
}

function computeMetaWeights() {
  const coeffs = calibrationParams?.metaModel?.coefficients;
  if (!coeffs) {
    return {
      weather: 0.25,
      traffic: 0.25,
      fleet: 0.2,
      driver: 0.15,
      warehouse: 0.15
    };
  }

  const absSum = Object.values(coeffs)
    .map(Math.abs)
    .reduce((sum, value) => sum + value, 0);
  if (absSum <= 0) {
    return {
      weather: 0.25,
      traffic: 0.25,
      fleet: 0.2,
      driver: 0.15,
      warehouse: 0.15
    };
  }

  return Object.fromEntries(
    Object.entries(coeffs).map(([factor, coef]) => [factor, Math.abs(coef) / absSum])
  );
}

function calibrateProbability(rawScore) {
  const calib = calibrationParams?.calibration;
  if (!calib || typeof calib.intercept !== 'number' || typeof calib.coef !== 'number') {
    return Math.min(1, Math.max(0, rawScore / 100));
  }
  return Math.min(1, Math.max(0, toProbability(calib.intercept + calib.coef * rawScore)));
}

function computeFactorScores(payload) {
  return {
    weather: computeFactorScore('weather', payload),
    traffic: computeFactorScore('traffic', payload),
    fleet: computeFactorScore('fleet', payload),
    driver: computeFactorScore('driver', payload),
    warehouse: computeFactorScore('warehouse', payload)
  };
}

function computeRiskScore(payload) {
  if (calibrationParams) {
    const factors = computeFactorScores(payload);
    const weights = computeMetaWeights();
    const rawScore =
      factors.weather * weights.weather +
      factors.traffic * weights.traffic +
      factors.fleet * weights.fleet +
      factors.driver * weights.driver +
      factors.warehouse * weights.warehouse;

    const delayProbability = calibrateProbability(rawScore);
    const riskScore = clamp(Math.round(delayProbability * 100));

    return {
      risk_score: riskScore,
      delay_probability: parseFloat(delayProbability.toFixed(3)),
      factors,
      weights,
      rawScore: Math.round(rawScore),
      calibrated: true
    };
  }

  const factors = {
    weather: computeWeatherRisk(payload),
    traffic: computeTrafficRisk(payload),
    fleet: computeFleetRisk(payload),
    driver: computeDriverRisk(payload),
    warehouse: computeWarehouseRisk(payload)
  };

  const weights = {
    weather: 0.25,
    traffic: 0.25,
    fleet: 0.2,
    driver: 0.15,
    warehouse: 0.15
  };

  const baseScore =
    factors.weather * weights.weather +
    factors.traffic * weights.traffic +
    factors.fleet * weights.fleet +
    factors.driver * weights.driver +
    factors.warehouse * weights.warehouse;

  const interaction = 0.1 * (factors.traffic * factors.weather / 100);
  const totalRisk = clamp(baseScore + interaction);

  return {
    risk_score: totalRisk,
    delay_probability: parseFloat((Math.min(1, Math.max(0, totalRisk / 100))).toFixed(3)),
    factors,
    weights,
    interaction: Math.round(interaction),
    rawScore: Math.round(baseScore),
    calibrated: false
  };
}

function computeTrafficRisk({ congestion, incident, traffic }) {
  if (congestion != null || incident != null) {
    const c = Number(congestion ?? 0);
    const i = Number(incident ?? 0);
    return clamp(c * 80 + i * 20);
  }
  return clamp(Number(traffic ?? 0));
}

function computeFleetRisk({ utilization, fleetAvailability }) {
  const u = utilization != null ? Number(utilization) : fleetAvailability != null ? 1 - Number(fleetAvailability) / 100 : 0;
  const clamped = Math.min(1, Math.max(0, u));
  if (clamped < 0.7) {
    return clamp(clamped * 50);
  }
  return clamp(50 + (clamped - 0.7) * 166);
}

function computeDriverRisk({ fatigue, availability, driverReadiness }) {
  const avail = availability != null ? Number(availability) : driverReadiness != null ? Number(driverReadiness) / 100 : 1;
  const fat = fatigue != null ? Number(fatigue) : 1 - avail;
  return clamp(fat * 70 + (1 - avail) * 30);
}

function computeWarehouseRisk({ dockUtilization, queueTime, warehouse }) {
  const dock = dockUtilization != null ? Number(dockUtilization) : warehouse != null ? Number(warehouse) / 100 : 0;
  const queue = queueTime != null ? Number(queueTime) : 0;
  return clamp(dock * 60 + Math.min(40, queue / 2));
}

function riskLevel(score) {
  if (score >= 81) return 'Critical';
  if (score >= 61) return 'High';
  if (score >= 31) return 'Moderate';
  return 'Low';
}

function topContributors(factors) {
  return Object.entries(factors)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key]) => key);
}

function computeEta({ distanceKm, baseSpeedKmh, weather, traffic }) {
  const travelHours = distanceKm / Math.max(baseSpeedKmh, 1);
  const weatherDelay = 1 + Math.min(0.35, weather / 200);
  const trafficDelay = 1 + Math.min(0.4, traffic / 150);
  const etaHours = travelHours * weatherDelay * trafficDelay;
  return parseFloat(etaHours.toFixed(2));
}

function computeRecommendation({ riskScore, weather, traffic, fleet, load }) {
  const actions = [];
  if (riskScore >= 75) {
    actions.push('Reroute high-risk shipments away from weather and congestion corridors.');
  }
  if (riskScore >= 50 && riskScore < 75) {
    actions.push('Delay dispatch for non-critical loads and hold contingency capacity.');
  }
  if (fleet < 65) {
    actions.push('Increase capacity with spare assets or third-party carriers.');
  }
  if (weather > 60) {
    actions.push('Use inland alternate routes to avoid severe weather.');
  }
  if (traffic > 55) {
    actions.push('Adjust departure windows to avoid peak urban congestion.');
  }
  if (actions.length === 0) {
    actions.push('Maintain current plan; network is stable under current inputs.');
  }
  return actions;
}

app.post('/estimate', (req, res) => {
  const payload = normalizePayload(req.body);
  const eta = computeEta(payload);
  res.json({ etaHours: eta, formula: 'base distance / speed * weather factor * traffic factor' });
});

app.post('/risk-score', (req, res) => {
  const payload = normalizePayload(req.body);
  const result = computeRiskScore(payload);
  res.json({
    total_risk: result.total_risk,
    level: riskLevel(result.total_risk),
    factors: result.factors,
    interaction: result.interaction,
    top_contributors: topContributors(result.factors)
  });
});

app.post('/recommendation', (req, res) => {
  const payload = normalizePayload(req.body);
  const result = computeRiskScore(payload);
  const actions = computeRecommendation({ riskScore: result.total_risk, ...payload });
  res.json({
    total_risk: result.total_risk,
    level: riskLevel(result.total_risk),
    factors: result.factors,
    interaction: result.interaction,
    top_contributors: topContributors(result.factors),
    actions
  });
});

app.post('/simulate', (req, res) => {
  const payload = normalizePayload(req.body);
  const eta = computeEta(payload);
  const result = computeRiskScore(payload);
  const actions = computeRecommendation({ riskScore: result.total_risk, ...payload });
  res.json({
    etaHours: eta,
    total_risk: result.total_risk,
    level: riskLevel(result.total_risk),
    factors: result.factors,
    interaction: result.interaction,
    top_contributors: topContributors(result.factors),
    actions
  });
});

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`ALCE backend running on http://localhost:${port}`);
});
