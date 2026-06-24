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
  console.warn(
    `Calibration parameters not found or invalid, using fallback.`,
    error.message
  );
}

// -------------------- utils --------------------

function clamp(value, min = 0, max = 100) {
  if (isNaN(value)) return min;
  return Math.round(Math.min(max, Math.max(min, value)));
}

function toProbability(logit) {
  return 1 / (1 + Math.exp(-logit));
}

function percentileNormalize(value, p5, p95) {
  if (p95 === p5) return 0;
  return Math.min(1, Math.max(0, (value - p5) / (p95 - p5)));
}

// -------------------- payload normalization --------------------

function normalizePayload(payload = {}) {
  const n = (v, d = 0) => (v == null || isNaN(v) ? d : Number(v));

  return {
    weather: n(payload.weather ?? payload.weatherRisk),
    traffic: n(payload.traffic ?? payload.trafficSeverity),
    fleet: n(payload.fleetAvailability ?? payload.fleet),
    driver: n(payload.driverReadiness),
    warehouse: n(payload.warehouse ?? payload.load),

    utilization: n(payload.utilization),
    fatigue: n(payload.fatigue),

    congestion: n(payload.congestion),
    incident: n(payload.incident),

    distanceKm: n(payload.distanceKm ?? payload.distance),
    baseSpeedKmh: n(payload.baseSpeedKmh ?? payload.routeSpeed ?? payload.speed, 50),

    dockUtilization: n(payload.dockUtilization),
    queueTime: n(payload.queueTime)
  };
}

// -------------------- factor extraction --------------------

function factorRawValue(factor, p) {
  switch (factor) {
    case 'weather': return p.weather;
    case 'traffic': return p.traffic;
    case 'fleet': return p.fleet;
    case 'driver': return p.driver;
    case 'warehouse': return p.warehouse;
    default: return 0;
  }
}

function computeFactorScore(factor, payload) {
  const raw = factorRawValue(factor, payload);

  const scaling = calibrationParams?.scaling?.[factor];
  const model = calibrationParams?.factorModels?.[factor];

  const normalized = scaling
    ? percentileNormalize(raw, scaling.p5, scaling.p95)
    : Math.min(1, Math.max(0, raw / 100));

  if (model?.intercept != null && model?.coef != null) {
    const logit = model.intercept + model.coef * normalized;
    return clamp(toProbability(logit) * 100);
  }

  return clamp(normalized * 100);
}

function computeFactorScores(p) {
  return {
    weather: computeFactorScore('weather', p),
    traffic: computeFactorScore('traffic', p),
    fleet: computeFactorScore('fleet', p),
    driver: computeFactorScore('driver', p),
    warehouse: computeFactorScore('warehouse', p)
  };
}

// -------------------- weights --------------------

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

  const sum = Object.values(coeffs).reduce((a, b) => a + Math.abs(b), 0);

  if (sum === 0) return computeMetaWeights();

  return Object.fromEntries(
    Object.entries(coeffs).map(([k, v]) => [k, Math.abs(v) / sum])
  );
}

// -------------------- risk model --------------------

function calibrateProbability(score) {
  const c = calibrationParams?.calibration;
  if (!c) return Math.min(1, Math.max(0, score / 100));

  return Math.min(
    1,
    Math.max(0, toProbability(c.intercept + c.coef * score))
  );
}

function computeRiskScore(payload) {
  const factors = computeFactorScores(payload);
  const weights = computeMetaWeights();

  const rawScore =
    factors.weather * weights.weather +
    factors.traffic * weights.traffic +
    factors.fleet * weights.fleet +
    factors.driver * weights.driver +
    factors.warehouse * weights.warehouse;

  const delayProb = calibrateProbability(rawScore);
  const riskScore = clamp(delayProb * 100);

  return {
    risk_score: riskScore,
    delay_probability: Number(delayProb.toFixed(3)),
    factors,
    weights,
    rawScore: Math.round(rawScore),
    calibrated: Boolean(calibrationParams)
  };
}

// -------------------- helper analytics --------------------

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
    .map(([k]) => k);
}

// -------------------- ETA --------------------

function computeEta(p) {
  const base = p.distanceKm / Math.max(p.baseSpeedKmh, 1);

  const weatherFactor = 1 + Math.min(0.4, p.weather / 200);
  const trafficFactor = 1 + Math.min(0.5, p.traffic / 150);

  const interaction = weatherFactor * trafficFactor;

  return Number((base * interaction).toFixed(2));
}

// -------------------- recommendation --------------------

function computeRecommendation({ risk_score, weather, traffic, fleet }) {
  const actions = [];

  if (risk_score >= 75) {
    actions.push('Reroute high-risk shipments away from disruption zones.');
  }
  if (risk_score >= 50) {
    actions.push('Delay non-critical dispatches and preserve capacity.');
  }
  if (fleet < 65) {
    actions.push('Increase fleet capacity or use third-party carriers.');
  }
  if (weather > 60) {
    actions.push('Avoid weather-affected corridors.');
  }
  if (traffic > 55) {
    actions.push('Shift departure windows to off-peak hours.');
  }

  if (actions.length === 0) {
    actions.push('Network stable under current conditions.');
  }

  return actions;
}

// -------------------- API --------------------

app.post('/estimate', (req, res) => {
  const p = normalizePayload(req.body);
  res.json({ etaHours: computeEta(p) });
});

app.post('/risk-score', (req, res) => {
  const p = normalizePayload(req.body);
  const r = computeRiskScore(p);

  res.json({
    risk_score: r.risk_score,
    level: riskLevel(r.risk_score),
    factors: r.factors,
    top_contributors: topContributors(r.factors)
  });
});

app.post('/recommendation', (req, res) => {
  const p = normalizePayload(req.body);
  const r = computeRiskScore(p);

  res.json({
    risk_score: r.risk_score,
    level: riskLevel(r.risk_score),
    factors: r.factors,
    top_contributors: topContributors(r.factors),
    actions: computeRecommendation({
      risk_score: r.risk_score,
      ...p
    })
  });
});

app.post('/simulate', (req, res) => {
  const p = normalizePayload(req.body);
  const r = computeRiskScore(p);

  res.json({
    etaHours: computeEta(p),
    risk_score: r.risk_score,
    level: riskLevel(r.risk_score),
    factors: r.factors,
    top_contributors: topContributors(r.factors),
    actions: computeRecommendation({
      risk_score: r.risk_score,
      ...p
    })
  });
});

// -------------------- start --------------------

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`ALCE backend running on http://localhost:${port}`);
});