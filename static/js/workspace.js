document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadPreview(SURVEY_ID);

  document.getElementById('method').addEventListener('change', (e) => {
    const isKrig = e.target.value === 'kriging';
    document.getElementById('idw-params').style.display = isKrig ? 'none' : 'block';
    document.getElementById('krig-params').style.display = isKrig ? 'block' : 'none';
  });
});

function runInterpolation() {
  const method = document.getElementById('method').value;
  const cellSize = parseFloat(document.getElementById('cell-size').value);
  const params = method === 'idw'
    ? { power: parseFloat(document.getElementById('idw-power').value), k: parseInt(document.getElementById('idw-k').value) }
    : { variogram_model: document.getElementById('krig-model').value };

  const btn = document.getElementById('run-btn');
  const status = document.getElementById('run-status');
  btn.disabled = true;
  status.textContent = 'Interpolating, building DEM, classifying depth bands, computing volumes... this can take a little while for kriging on dense point sets.';

  fetch(`/api/survey/${SURVEY_ID}/interpolate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, cell_size: cellSize, params }),
  })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      if (data.error) {
        status.textContent = 'Error: ' + data.error;
        return;
      }
      status.textContent = `Done — ${data.grid_shape[0]}x${data.grid_shape[1]} grid, bottom elevation ${data.bottom_elevation_m} m, ${data.n_contour_bands} depth bands.`;
      renderContours(data.contours_geojson);
      renderVolumeTable(data.volume_table);
      renderSiltation(data.siltation);
      document.getElementById('siltation-card').style.display = 'block';
      document.getElementById('volume-card').style.display = 'block';
      location.reload(); // refresh so download links (DEM/CSV) appear
    })
    .catch(err => {
      btn.disabled = false;
      status.textContent = 'Request failed: ' + err;
    });
}

function loadResultsFromServer() {
  fetch(`/api/survey/${SURVEY_ID}/results`)
    .then(r => r.json())
    .then(data => {
      if (data.error) return;
      renderContours(data.contours_geojson);
      renderVolumeTable(data.volume_table);
      renderSiltation(data.siltation);
    });
}

function renderVolumeTable(rows) {
  const tbody = document.querySelector('#volume-table tbody');
  tbody.innerHTML = '';
  rows.forEach(r => {
    const tr = document.createElement('tr');
    let marker = '';
    if (r.is_bottom) marker = 'Bottom';
    if (r.is_dead_water_level) marker = 'Dead Water Level';
    if (r.is_current_level) marker = 'Current Level';
    if (r.is_full_supply_level) marker = 'Full Supply Level';
    if (marker) tr.classList.add('marked-row');
    tr.innerHTML = `<td>${r.elevation_m}</td><td>${r.surface_area_m2.toLocaleString()}</td>` +
      `<td>${r.surface_area_ha}</td><td>${r.cumulative_volume_m3.toLocaleString()}</td>` +
      `<td>${r.cumulative_volume_Mm3}</td><td>${marker}</td>`;
    tbody.appendChild(tr);
  });
}

function renderSiltation(s) {
  const el = document.getElementById('siltation-summary');
  let html = `<div class="stat"><span class="stat-label">Current capacity at FSL</span>
    <span class="stat-value">${s.current_capacity_at_fsl_Mm3} Mm&sup3;</span></div>`;
  if (s.original_design_capacity_m3) {
    html += `<div class="stat"><span class="stat-label">Original design capacity</span>
      <span class="stat-value">${(s.original_design_capacity_m3/1e6).toFixed(5)} Mm&sup3;</span></div>`;
    html += `<div class="stat"><span class="stat-label">Siltation volume</span>
      <span class="stat-value">${s.siltation_volume_Mm3} Mm&sup3;</span></div>`;
    html += `<div class="stat"><span class="stat-label">Siltation</span>
      <span class="stat-value">${s.siltation_percent}%</span></div>`;
    html += `<div class="stat"><span class="stat-label">Capacity remaining</span>
      <span class="stat-value">${s.capacity_remaining_percent}%</span></div>`;
  } else {
    html += `<div class="stat note">${s.note}</div>`;
  }
  el.innerHTML = html;
}
