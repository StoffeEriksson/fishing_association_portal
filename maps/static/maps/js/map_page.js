(function () {
  const mapElement = document.getElementById("map-page-map");
  const geojsonScript = document.getElementById("map-geojson-data");
  const metaScript = document.getElementById("map-meta");
  const areaToggle = document.getElementById("toggle-areas");
  const waterToggle = document.getElementById("toggle-waters");
  const actionToggle = document.getElementById("toggle-actions");
  const actionStatusToggles = document.querySelectorAll(".js-action-status-toggle");

  if (
    !mapElement ||
    !geojsonScript ||
    !metaScript ||
    !areaToggle ||
    !waterToggle ||
    !actionToggle ||
    actionStatusToggles.length === 0
  ) {
    return;
  }

  const geojsonData = JSON.parse(geojsonScript.textContent);
  const meta = JSON.parse(metaScript.textContent);
  const selectedActionId =
    meta.selected_action_id === null || meta.selected_action_id === undefined
      ? null
      : Number(meta.selected_action_id);
  const selectedWaterId =
    meta.selected_water_id === null || meta.selected_water_id === undefined
      ? null
      : Number(meta.selected_water_id);

  const map = L.map(mapElement).setView([59.33, 18.03], 11);

  L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution: "Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap",
  }).addTo(map);

  function getFeatureStyle(feature) {
    const type = feature.properties?.type;
    if (type === "water") {
      return {
        color: "#0e7490",
        weight: 2,
        fillColor: "#14b8a6",
        fillOpacity: 0.4,
      };
    }
    if (type === "action") {
      const status = feature.properties?.status;
      if (status === "urgent") {
        return {
          color: "#dc2626",
          fillColor: "#ef4444",
          weight: 2,
          fillOpacity: 0.4,
        };
      } else if (status === "planned") {
        return {
          color: "#ca8a04",
          fillColor: "#eab308",
          weight: 2,
          fillOpacity: 0.4,
        };
      } else if (status === "in_progress") {
        return {
          color: "#2563eb",
          fillColor: "#3b82f6",
          weight: 2,
          fillOpacity: 0.4,
        };
      } else if (status === "completed") {
        return {
          color: "#16a34a",
          fillColor: "#22c55e",
          weight: 2,
          fillOpacity: 0.4,
        };
      } else if (status === "needs_action") {
        return {
          color: "#c2410c",
          fillColor: "#fb923c",
          weight: 2,
          fillOpacity: 0.35,
        };
      } else {
        return {
          color: "#c2410c",
          fillColor: "#fb923c",
          weight: 2,
          fillOpacity: 0.35,
        };
      }
    }
    return {
      color: "#1d4ed8",
      weight: 2,
      fillColor: "#60a5fa",
      fillOpacity: 0.05,
    };
  }

  function bindFeatureInteractions(feature, featureLayer) {
    const name = feature.properties?.name || "Område";
    const type = feature.properties?.type || "area";
    const fish = Array.isArray(feature.properties?.fish)
      ? feature.properties.fish
      : [];

    let popupHtml = `<strong>${name}</strong>`;
    if (type === "water") {
      const fishText = fish.length > 0 ? fish.join(", ") : "Inga registrerade arter";
      popupHtml += `<br>Fiskarter: ${fishText}`;
    } else if (type === "action") {
      const statusLabel = feature.properties?.status_label || feature.properties?.status || "Ej angiven";
      popupHtml += `<br>Status: ${statusLabel}`;
    }
    featureLayer.bindPopup(popupHtml);

    if (type === "water") {
      featureLayer.on("mouseover", function () {
        featureLayer.setStyle({
          color: "#0f4c5c",
          fillColor: "#0f766e",
          fillOpacity: 0.6,
        });
      });

      featureLayer.on("mouseout", function () {
        featureLayer.setStyle({
          color: "#0e7490",
          fillColor: "#14b8a6",
          fillOpacity: 0.4,
        });
      });
    } else if (type === "action") {
      featureLayer.on("mouseover", function () {
        const baseStyle = getFeatureStyle(feature);
        featureLayer.setStyle({
          color: baseStyle.color,
          fillColor: baseStyle.fillColor,
          weight: 3,
          fillOpacity: Math.min((baseStyle.fillOpacity || 0.35) + 0.15, 0.75),
        });
      });

      featureLayer.on("mouseout", function () {
        featureLayer.setStyle(getFeatureStyle(feature));
      });

      featureLayer.on("click", function () {
        if (typeof featureLayer.bringToFront === "function") {
          featureLayer.bringToFront();
        }
        if (typeof featureLayer.getBounds === "function") {
          const bounds = featureLayer.getBounds();
          if (bounds && bounds.isValid && bounds.isValid()) {
            map.fitBounds(bounds, { padding: [30, 30] });
          }
        }
      });
    }
  }

  const areaFeatures = (geojsonData.features || []).filter(
    function (feature) {
      return feature.properties?.type === "area";
    }
  );
  const waterFeatures = (geojsonData.features || []).filter(
    function (feature) {
      return feature.properties?.type === "water";
    }
  );
  const actionFeatures = (geojsonData.features || []).filter(
    function (feature) {
      return feature.properties?.type === "action";
    }
  );

  const areaLayer = L.geoJSON(
    { type: "FeatureCollection", features: areaFeatures },
    {
      style: getFeatureStyle,
      onEachFeature: bindFeatureInteractions,
    }
  );

  const waterLayer = L.geoJSON(
    { type: "FeatureCollection", features: waterFeatures },
    {
      style: getFeatureStyle,
      onEachFeature: bindFeatureInteractions,
    }
  );
  function getSelectedActionStatuses() {
    return Array.from(actionStatusToggles)
      .filter(function (toggle) {
        return toggle.checked;
      })
      .map(function (toggle) {
        return toggle.value;
      });
  }

  let actionLayer = L.geoJSON(
    { type: "FeatureCollection", features: [] },
    {
      style: getFeatureStyle,
      onEachFeature: bindFeatureInteractions,
    }
  );

  function rebuildActionLayer() {
    const selectedStatuses = getSelectedActionStatuses();
    const filteredActionFeatures = actionFeatures.filter(function (feature) {
      const status = feature.properties?.status;
      return selectedStatuses.includes(status);
    });

    const shouldBeVisible = actionToggle.checked;
    if (map.hasLayer(actionLayer)) {
      map.removeLayer(actionLayer);
    }

    actionLayer = L.geoJSON(
      { type: "FeatureCollection", features: filteredActionFeatures },
      {
        style: getFeatureStyle,
        onEachFeature: bindFeatureInteractions,
      }
    );

    if (shouldBeVisible) {
      actionLayer.addTo(map);
    }
  }

  function focusSelectedAction() {
    if (selectedActionId === null || !map.hasLayer(actionLayer)) {
      return;
    }
    actionLayer.eachLayer(function (layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedActionId) {
        return;
      }
      if (typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
      if (typeof layer.getBounds === "function") {
        const bounds = layer.getBounds();
        if (bounds && bounds.isValid && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [30, 30] });
        }
      }
      if (typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    });
  }

  function focusSelectedWater() {
    if (selectedActionId !== null || selectedWaterId === null || !map.hasLayer(waterLayer)) {
      return;
    }
    waterLayer.eachLayer(function (layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedWaterId) {
        return;
      }
      if (typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
      if (typeof layer.getBounds === "function") {
        const bounds = layer.getBounds();
        if (bounds && bounds.isValid && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [30, 30] });
        }
      }
      if (typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    });
  }

  if (areaFeatures.length > 0) {
    areaLayer.addTo(map);
  }
  if (waterFeatures.length > 0) {
    waterLayer.addTo(map);
  }
  rebuildActionLayer();
  focusSelectedAction();
  focusSelectedWater();

  function updateLayerVisibility() {
    if (areaToggle.checked) {
      if (!map.hasLayer(areaLayer)) {
        areaLayer.addTo(map);
      }
    } else if (map.hasLayer(areaLayer)) {
      map.removeLayer(areaLayer);
    }

    if (waterToggle.checked) {
      if (!map.hasLayer(waterLayer)) {
        waterLayer.addTo(map);
      }
    } else if (map.hasLayer(waterLayer)) {
      map.removeLayer(waterLayer);
    }

    if (actionToggle.checked) {
      if (!map.hasLayer(actionLayer)) {
        actionLayer.addTo(map);
      }
    } else if (map.hasLayer(actionLayer)) {
      map.removeLayer(actionLayer);
    }
  }

  areaToggle.addEventListener("change", updateLayerVisibility);
  waterToggle.addEventListener("change", updateLayerVisibility);
  actionToggle.addEventListener("change", updateLayerVisibility);
  actionStatusToggles.forEach(function (toggle) {
    toggle.addEventListener("change", function () {
      rebuildActionLayer();
      updateLayerVisibility();
      focusSelectedAction();
      focusSelectedWater();
    });
  });

  const layer = L.featureGroup();
  if (areaFeatures.length > 0) {
    layer.addLayer(areaLayer);
  }
  if (waterFeatures.length > 0) {
    layer.addLayer(waterLayer);
  }
  if (actionFeatures.length > 0) {
    layer.addLayer(actionLayer);
  }

  if (layer.getLayers().length > 0) {
    map.fitBounds(layer.getBounds(), { padding: [20, 20] });
  } else if (!meta.has_org) {
    L.popup()
      .setLatLng(map.getCenter())
      .setContent("Ingen organisation vald. Kartan visas utan områden.")
      .openOn(map);
  }
})();

