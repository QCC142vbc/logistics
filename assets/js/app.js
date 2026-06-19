const shipments = [
	{ id: 'SHP-1001', status: 'In transit', eta: '14:30 UTC', location: 'Hamburg', carrier: 'OceanBridge' },
	{ id: 'SHP-1002', status: 'Delayed', eta: '20:15 UTC', location: 'Frankfurt', carrier: 'SwiftLine' },
	{ id: 'SHP-1003', status: 'At warehouse', eta: '08:00 UTC', location: 'Rotterdam', carrier: 'GreenFleet' },
	{ id: 'SHP-1004', status: 'Departed', eta: '12:45 UTC', location: 'Munich', carrier: 'NorthStar' },
	{ id: 'SHP-1005', status: 'In transit', eta: '18:20 UTC', location: 'Leipzig', carrier: 'AirWave' }
];

const warehouses = [
	{ name: 'Rotterdam DC', occupancy: 82, throughput: 'High' },
	{ name: 'Hamburg Hub', occupancy: 66, throughput: 'Moderate' },
	{ name: 'Berlin Crossdock', occupancy: 91, throughput: 'Critical' }
];

const inventoryLevels = [
	{ sku: 'Pallet A', value: 76 },
	{ sku: 'Pallet B', value: 45 },
	{ sku: 'Pallet C', value: 58 },
	{ sku: 'Pallet D', value: 92 }
];

const auditEntries = [
	{ message: 'System initialized for tenant: Global Logistics Corp', timestamp: '2026-06-19 08:03:21' },
	{ message: 'ALCE command engine loaded with predictive risk profile', timestamp: '2026-06-19 08:04:00' }
];

const scenarioLibrary = {
  peakSeason: {
    title: 'Peak season surge',
    note: 'High freight volume and inventory pressure during holiday peak season.',
    preset: { weather: 30, traffic: 42, warehouse: 76, fleet: 84, driver: 88 }
  },
  stormFront: {
    title: 'North Sea storm front',
    note: 'Severe weather and port disruptions across northwestern Europe.',
    preset: { weather: 82, traffic: 58, warehouse: 68, fleet: 64, driver: 78 }
  },
  portCongestion: {
    title: 'Port congestion alert',
    note: 'Terminal delays, berth queues, and container dwell time risks.',
    preset: { weather: 22, traffic: 67, warehouse: 84, fleet: 70, driver: 90 }
  },
  fleetShortage: {
    title: 'Fleet availability pressure',
    note: 'Reduced tractor availability and higher utilization across key lanes.',
    preset: { weather: 18, traffic: 38, warehouse: 64, fleet: 52, driver: 79 }
  }
};

function setText(id, text) {
	const node = document.getElementById(id);
	node.textContent = text;
	node.classList.remove('flash');
	void node.offsetWidth;
	node.classList.add('flash');
}

function setHtml(id, html) {
	const node = document.getElementById(id);
	node.innerHTML = html.replace(/\n/g, '<br>');
}

function calculateTransportCost() {
	const distance = parseFloat(document.getElementById('distance').value) || 0;
	const ratePerKm = parseFloat(document.getElementById('ratePerKm').value) || 0;
	const fuelCost = parseFloat(document.getElementById('fuelCost').value) || 0;
	const driverCost = parseFloat(document.getElementById('driverCost').value) || 0;
	const otherCost = parseFloat(document.getElementById('otherCost').value) || 0;
	const routeCost = distance * ratePerKm;
	const total = routeCost + fuelCost + driverCost + otherCost;
	setText(
		'transportResult',
		`Estimated transport cost: ${formatCurrency(total)} (route ${formatCurrency(routeCost)} + fuel ${formatCurrency(fuelCost)} + driver ${formatCurrency(driverCost)} + additional ${formatCurrency(otherCost)})`
	);
}

function calculateDeliveryTime() {
	const distance = parseFloat(document.getElementById('distanceTime').value) || 0;
	const speed = parseFloat(document.getElementById('speed').value) || 1;
	const loadingTime = parseFloat(document.getElementById('loadingTime').value) || 0;
	const unloadingTime = parseFloat(document.getElementById('unloadingTime').value) || 0;
	const delayFactor = parseFloat(document.getElementById('delayFactor').value) || 1;
	const travelHours = distance / speed;
	const totalHours = (travelHours + loadingTime + unloadingTime) * delayFactor;
	setText(
		'timeResult',
		`Estimated delivery time: ${totalHours.toFixed(2)} h (${travelHours.toFixed(2)}h travel + ${loadingTime.toFixed(2)}h loading + ${unloadingTime.toFixed(2)}h unloading, factor ${delayFactor.toFixed(2)})`
	);
}

function calculateFuelConsumption() {
	const distance = parseFloat(document.getElementById('fuelDistance').value) || 0;
	const efficiency = parseFloat(document.getElementById('efficiency').value) || 1;
	const fuelPrice = parseFloat(document.getElementById('fuelPrice').value) || 0;
	const liters = distance / efficiency;
	const cost = liters * fuelPrice;
	setText(
		'fuelResult',
		`Fuel usage: ${liters.toFixed(2)} L, total fuel cost: ${formatCurrency(cost)} at ${fuelPrice.toFixed(2)} $/L.`
	);
}

function calculateLoadDensity() {
	const weight = parseFloat(document.getElementById('weight').value) || 0;
	const volume = parseFloat(document.getElementById('volume').value) || 0;
	if (volume <= 0) {
		setText('densityResult', 'Enter a volume greater than zero to compute density.');
		return;
	}
	const density = weight / volume;
	setText('densityResult', `Load density: ${density.toFixed(2)} kg/m³.`);
}

function calculateReorderPoint() {
	const dailyDemand = parseFloat(document.getElementById('dailyDemand').value) || 0;
	const leadTime = parseFloat(document.getElementById('leadTime').value) || 0;
	const safetyStock = parseFloat(document.getElementById('safetyStock').value) || 0;
	const reorderPoint = dailyDemand * leadTime + safetyStock;
	setText('reorderResult', `Reorder point: ${reorderPoint.toFixed(0)} units.`);
}

window.addEventListener('DOMContentLoaded', () => {
	const transportForm = document.getElementById('transportForm');
	if (transportForm) transportForm.addEventListener('submit', function (event) {
		event.preventDefault();
		calculateTransportCost();
	});

	const timeForm = document.getElementById('timeForm');
	if (timeForm) timeForm.addEventListener('submit', function (event) {
		event.preventDefault();
		calculateDeliveryTime();
	});

	const fuelForm = document.getElementById('fuelForm');
	if (fuelForm) fuelForm.addEventListener('submit', function (event) {
		event.preventDefault();
		calculateFuelConsumption();
	});

	const densityForm = document.getElementById('densityForm');
	if (densityForm) densityForm.addEventListener('submit', function (event) {
		event.preventDefault();
		calculateLoadDensity();
	});

	const reorderForm = document.getElementById('reorderForm');
	if (reorderForm) reorderForm.addEventListener('submit', function (event) {
		event.preventDefault();
		calculateReorderPoint();
	});

	const runBtn = document.getElementById('runAlce');
	if (runBtn) runBtn.addEventListener('click', runAlceScan);

	const loadScenario = document.getElementById('loadScenario');
	if (loadScenario) loadScenario.addEventListener('click', applyScenarioPreset);

	renderDashboard();
});

async function runAlceScan() {
	const weatherRisk = parseInt(document.getElementById('weatherRisk').value, 10);
	const trafficSeverity = parseInt(document.getElementById('trafficSeverity').value, 10);
	const warehouseLoad = parseInt(document.getElementById('warehouseLoad').value, 10);
	const fleetAvailability = parseInt(document.getElementById('fleetAvailabilityInput').value, 10);
	const driverReadiness = parseInt(document.getElementById('driverReadiness').value, 10);
	const routeDistance = parseFloat(document.getElementById('routeDistance').value) || 0;
	const routeSpeed = parseFloat(document.getElementById('routeSpeed').value) || 60;

	const payload = {
		weather: weatherRisk,
		traffic: trafficSeverity,
		fleet: fleetAvailability,
		load: warehouseLoad,
		distanceKm: routeDistance,
		baseSpeedKmh: routeSpeed
	};

	setText('commandResult', 'Running ALCE simulation...');
	try {
		const response = await fetch('/simulate', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (!response.ok) throw new Error('Backend returned an error');

		const result = await response.json();
		setHtml(
			'commandResult',
			`<strong>Risk level:</strong> ${result.level}<br><strong>Score:</strong> ${result.total_risk}/100<br><strong>ETA:</strong> ${result.etaHours} h`
		);

		setHtml(
			'recommendationPanel',
			`<strong>Recommended actions</strong><br>${result.actions.map((item) => `- ${item}`).join('<br>')}`
		);

		renderRiskBreakdown(result.factors || {}, result.top_contributors || [], result.interaction);
		logAudit(`ALCE simulation executed — score ${result.total_risk}, ETA ${result.etaHours}h`);
	} catch (error) {
		console.error(error);
		setText('commandResult', 'ALCE scan failed. Check backend or refresh the page.');
	}
}

function applyScenarioPreset() {
	const scenarioSelect = document.getElementById('scenarioSelect');
	if (!scenarioSelect) return;
	const scenario = scenarioSelect.value;
	const preset = scenarioLibrary?.[scenario]?.preset;
	if (!preset) return;
	document.getElementById('weatherRisk').value = preset.weather;
	document.getElementById('trafficSeverity').value = preset.traffic;
	document.getElementById('warehouseLoad').value = preset.warehouse;
	document.getElementById('fleetAvailabilityInput').value = preset.fleet;
	document.getElementById('driverReadiness').value = preset.driver;
	const note = document.getElementById('scenarioNote');
	if (note) note.textContent = scenarioLibrary[scenario].note;
}

function renderRiskBreakdown(breakdown, topContributors = [], interaction = 0) {
	const keys = Object.keys(breakdown);
	if (!keys.length) {
		setHtml('riskBreakdown', '<p>No risk breakdown available.</p>');
		return;
	}

	const contributorText = topContributors.length
		? `<div class="top-contributors"><strong>Top contributors:</strong> ${topContributors.join(', ')}</div>`
		: '';

	setHtml(
		'riskBreakdown',
		`<strong>Risk breakdown</strong><br>${keys
			.map((key) => `${key}: ${breakdown[key]}`)
			.join('<br>')}<br>${contributorText}<br><strong>Interaction penalty:</strong> ${interaction}`
	);
}

function renderDashboard() {
	renderShipmentTable();
	renderWarehouseList();
	renderInventoryChart();
	renderAuditLog();
	updateKpis();
}

function updateKpis() {
	const activeShipments = shipments.filter((shipment) => shipment.status === 'In transit' || shipment.status === 'Departed').length;
	const onTime = shipments.filter((shipment) => shipment.status !== 'Delayed').length;
	const onTimeRate = Math.round((onTime / shipments.length) * 100);
	const warehouseUtilization = Math.round(warehouses.reduce((sum, item) => sum + item.occupancy, 0) / warehouses.length);
	const availableFleet = 18;
	const totalFleet = 22;
	const fleetAvailability = Math.round((availableFleet / totalFleet) * 100);

	document.getElementById('shipmentsCount').textContent = `${activeShipments}`;
	document.getElementById('fleetAvailability').textContent = `${fleetAvailability}%`;
	document.getElementById('warehouseUtilization').textContent = `${warehouseUtilization}%`;
	document.getElementById('onTimeRate').textContent = `${onTimeRate}%`;
}

function renderShipmentTable() {
	const tbody = document.getElementById('shipmentTableBody');
	tbody.innerHTML = shipments
		.map((shipment) => {
			const statusClass =
				shipment.status === 'Delayed' ? 'status-critical' : shipment.status === 'In transit' ? 'status-active' : 'status-warning';
			return `
				<tr>
					<td>${shipment.id}</td>
					<td><span class="status-pill ${statusClass}">${shipment.status}</span></td>
					<td>${shipment.eta}</td>
					<td>${shipment.location}</td>
				</tr>
			`;
		})
		.join('');
}

function renderWarehouseList() {
	const list = document.getElementById('warehouseList');
	list.innerHTML = warehouses
		.map((warehouse) => {
			const status = warehouse.occupancy > 85 ? 'Critical' : warehouse.occupancy > 70 ? 'Constrained' : 'Stable';
			const statusClass = status === 'Critical' ? 'status-critical' : status === 'Constrained' ? 'status-warning' : 'status-active';
			return `
				<li class="warehouse-item">
					<div>
						<strong>${warehouse.name}</strong>
						<div>${warehouse.occupancy}% occupancy · ${warehouse.throughput} throughput</div>
					</div>
					<span class="status-pill ${statusClass}">${status}</span>
				</li>
			`;
		})
		.join('');
}

function renderInventoryChart() {
	const container = document.getElementById('inventoryChart');
	container.innerHTML = inventoryLevels
		.map(
			(item) => `
				<div class="bar-row">
					<span class="bar-label">${item.sku}</span>
					<div class="bar-track"><div class="bar-fill" style="width: ${item.value}%;"></div></div>
					<span>${item.value}%</span>
				</div>
			`
		)
		.join('');
}

function renderAlertList(alerts) {
	const list = document.getElementById('alertList');
	if (alerts.length === 0) {
		list.innerHTML = '<li class="alert-item status-active">No active operational alerts.</li>';
		return;
	}

	list.innerHTML = alerts
		.map((alert) => `<li class="alert-item status-warning">${alert}</li>`)
		.join('');
}

function approveAlceRecommendation() {
	const commandResult = document.getElementById('commandResult');
	if (!commandResult.textContent.includes('Recommendations:')) {
		setText('commandResult', 'No recommendation to approve. Run the risk scan first.');
		return;
	}
	setText('commandResult', 'Recommendation approved. Updates have been logged and distributed to operations teams.');
	logAudit('ALCE recommendation approved by operator');
}

function logAudit(message) {
	auditEntries.unshift({
		message,
		timestamp: new Date().toISOString().slice(0, 19).replace('T', ' ')
	});
	if (auditEntries.length > 14) {
		auditEntries.pop();
	}
	renderAuditLog();
}

function renderAuditLog() {
	const container = document.getElementById('auditLog');
	container.innerHTML = auditEntries
		.map(
			(entry) => `
				<li class="audit-entry">
					<div>${entry.message}</div>
					<time>${entry.timestamp}</time>
				</li>
			`
		)
		.join('');
}
