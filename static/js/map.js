let map, previewLayerGroup, contourLayerGroup;

function initMap() {
  map = L.map('map').setView([-19.0, 29.15], 7); // default: Zimbabwe
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 20,
  }).addTo(map);
  previewLayerGroup = L.layerGroup().addTo(map);
  contourLayerGroup = L.layerGroup().addTo(map);
}

const KIND_STYLE = {
  bathymetry: { radius: 3, color: '#1f77b4', fillColor: '#1f77b4', fillOpacity: 0.8 },
  fsl_boundary: { radius: 3, color: '#2ca02c', fillColor: '#2ca02c', fillOpacity: 0.8 },
  dead_water_point: { radius: 5, color: '#d62728', fillColor: '#d62728', fillOpacity: 0.9 },
};

function loadPreview(surveyId) {
  fetch(`/api/survey/${surveyId}/preview`)
    .then(r => r.json())
    .then(data => {
      previewLayerGroup.clearLayers();
      let bounds = [];
      Object.entries(data).forEach(([kind, geojson]) => {
        const style = KIND_STYLE[kind] || KIND_STYLE.bathymetry;
        const layer = L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => L.circleMarker(latlng, style),
          onEachFeature: (feature, layer) => {
            const z = feature.properties && feature.properties.z;
            if (z !== undefined) layer.bindTooltip(`${kind}: ${Number(z).toFixed(2)} m`);
          },
        });
        layer.addTo(previewLayerGroup);
        const b = layer.getBounds();
        if (b.isValid()) bounds.push(b);
      });
      if (bounds.length) {
        let combined = bounds[0];
        bounds.slice(1).forEach(b => combined.extend(b));
        map.fitBounds(combined, { padding: [20, 20] });
      }
    });
}

// depth-band color ramp: shallow (near current level) = light, deep (near bottom) = dark blue
function depthColor(bandIndex, nBands) {
  const t = nBands > 1 ? bandIndex / (nBands - 1) : 0;
  // interpolate light cyan -> dark navy
  const c1 = [198, 235, 255];
  const c2 = [8, 48, 107];
  const rgb = c1.map((v, i) => Math.round(v + (c2[i] - v) * t));
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

function renderContours(geojson) {
  contourLayerGroup.clearLayers();
  if (!geojson || !geojson.features || !geojson.features.length) return;
  const bands = geojson.features.map(f => f.properties.band);
  const nBands = Math.max(...bands) + 1;
  const layer = L.geoJSON(geojson, {
    style: feature => ({
      fillColor: depthColor(feature.properties.band, nBands),
      color: '#08306b',
      weight: 0.4,
      fillOpacity: 0.75,
    }),
    onEachFeature: (feature, lyr) => {
      const p = feature.properties;
      lyr.bindTooltip(`${p.depth_min}\u2013${p.depth_max} m`);
    },
  });
  layer.addTo(contourLayerGroup);
  const b = layer.getBounds();
  if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });

  const legend = document.getElementById('legend');
  if (legend) {
    let html = '<strong>Depth band (m)</strong><br/>';
    const uniqueBands = [...new Set(bands)].sort((a, b) => a - b);
    uniqueBands.forEach(b => {
      const f = geojson.features.find(ft => ft.properties.band === b);
      html += `<span class="swatch" style="background:${depthColor(b, nBands)}"></span>` +
              `${f.properties.depth_min}\u2013${f.properties.depth_max}<br/>`;
    });
    legend.innerHTML = html;
  }
}
