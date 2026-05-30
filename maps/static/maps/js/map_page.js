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
  const fvofFocusScript = document.getElementById("fvof-focus-data");
  let fvofFocus = { found: false, name: "", geojson: null };
  if (fvofFocusScript) {
    try {
      fvofFocus = JSON.parse(fvofFocusScript.textContent);
    } catch (error) {
      console.warn("Kunde inte läsa FVOF-fokusdata.", error);
    }
  }
  const selectedActionId =
    meta.selected_action_id === null || meta.selected_action_id === undefined
      ? null
      : Number(meta.selected_action_id);
  const selectedWaterId =
    meta.selected_water_id === null || meta.selected_water_id === undefined
      ? null
      : Number(meta.selected_water_id);

  const map = L.map(mapElement).setView([59.33, 18.03], 11);

  const basemapTopographicRadio = document.getElementById("basemap-topographic");
  const basemapSatelliteRadio = document.getElementById("basemap-satellite");

  const BASEMAP_ATTRIBUTION = {
    topographic:
      "Map data: &copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors, SRTM | Map style: &copy; <a href=\"https://opentopomap.org\">OpenTopoMap</a>",
    satellite:
      "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  };

  const topographicBasemap = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution: BASEMAP_ATTRIBUTION.topographic,
  });

  const satelliteBasemap = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: BASEMAP_ATTRIBUTION.satellite,
    }
  );

  let activeBasemap = topographicBasemap;
  let satelliteBasemapFailed = false;

  function setBasemap(basemapLayer) {
    if (activeBasemap === basemapLayer) {
      return;
    }
    if (map.hasLayer(activeBasemap)) {
      map.removeLayer(activeBasemap);
    }
    activeBasemap = basemapLayer;
    activeBasemap.addTo(map);
    if (typeof activeBasemap.bringToBack === "function") {
      activeBasemap.bringToBack();
    }
  }

  function switchToTopographic(fromFallback) {
    if (basemapTopographicRadio) {
      basemapTopographicRadio.checked = true;
    }
    setBasemap(topographicBasemap);
    if (fromFallback && basemapSatelliteRadio) {
      basemapSatelliteRadio.disabled = true;
    }
  }

  topographicBasemap.addTo(map);

  satelliteBasemap.on("tileerror", function () {
    if (satelliteBasemapFailed) {
      return;
    }
    satelliteBasemapFailed = true;
    console.warn(
      "Satellitbaskarta (Esri World Imagery) kunde inte laddas. Återgår till topografisk karta."
    );
    if (activeBasemap === satelliteBasemap) {
      switchToTopographic(true);
    }
  });

  if (basemapTopographicRadio && basemapSatelliteRadio) {
    basemapTopographicRadio.addEventListener("change", function () {
      if (basemapTopographicRadio.checked) {
        setBasemap(topographicBasemap);
      }
    });
    basemapSatelliteRadio.addEventListener("change", function () {
      if (basemapSatelliteRadio.checked && !basemapSatelliteRadio.disabled) {
        setBasemap(satelliteBasemap);
      }
    });
  }

  const fvofConfigScript = document.getElementById("fiskekartan-map-config");
  const fvofToggle = document.getElementById("toggle-fvof");
  let fvofConfig = null;
  let fvofLayer = null;
  let fvofAttributionActive = false;

  if (fvofConfigScript) {
    try {
      fvofConfig = JSON.parse(fvofConfigScript.textContent);
    } catch (error) {
      console.warn("Kunde inte läsa Fiskekartan-konfiguration.", error);
    }
  }

  function setFvofAttribution(active) {
    if (!fvofConfig || !fvofConfig.attribution) {
      return;
    }
    if (active && !fvofAttributionActive) {
      map.attributionControl.addAttribution(fvofConfig.attribution);
      fvofAttributionActive = true;
    } else if (!active && fvofAttributionActive) {
      map.attributionControl.removeAttribution(fvofConfig.attribution);
      fvofAttributionActive = false;
    }
  }

  function disableFvofToggle() {
    if (!fvofToggle) {
      return;
    }
    fvofToggle.checked = false;
    fvofToggle.disabled = true;
  }

  function initFvofOverlay() {
    if (!fvofConfig || !fvofConfig.enabled) {
      return;
    }
    if (!fvofConfig.mapserver_url || fvofConfig.layer_id === undefined || fvofConfig.layer_id === null) {
      console.warn("Fiskekartan FVOF-konfiguration saknar URL eller layer-id.");
      disableFvofToggle();
      return;
    }
    if (typeof L === "undefined" || !L.esri || typeof L.esri.dynamicMapLayer !== "function") {
      console.warn("Esri Leaflet saknas. FVOF-overlay inaktiveras.");
      disableFvofToggle();
      return;
    }

    fvofLayer = L.esri.dynamicMapLayer({
      url: fvofConfig.mapserver_url,
      layers: [Number(fvofConfig.layer_id)],
      opacity: 0.35,
    });

    if (fvofToggle && fvofToggle.checked) {
      fvofLayer.addTo(map);
      setFvofAttribution(true);
    }

    if (fvofToggle) {
      fvofToggle.addEventListener("change", function () {
        if (!fvofLayer) {
          return;
        }
        if (fvofToggle.checked) {
          fvofLayer.addTo(map);
          setFvofAttribution(true);
        } else if (map.hasLayer(fvofLayer)) {
          map.removeLayer(fvofLayer);
          setFvofAttribution(false);
        }
      });
    }
  }

  initFvofOverlay();

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
      return false;
    }
    let focused = false;
    actionLayer.eachLayer(function (layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedActionId) {
        return;
      }
      focused = true;
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
    return focused;
  }

  function focusSelectedWater() {
    if (selectedActionId !== null || selectedWaterId === null || !map.hasLayer(waterLayer)) {
      return false;
    }
    let focused = false;
    waterLayer.eachLayer(function (layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedWaterId) {
        return;
      }
      focused = true;
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
    return focused;
  }

  function focusFvofBoundary() {
    if (!fvofFocus.found || !fvofFocus.geojson) {
      return false;
    }
    const tempLayer = L.geoJSON(fvofFocus.geojson);
    const bounds = tempLayer.getBounds();
    if (bounds && bounds.isValid && bounds.isValid()) {
      map.fitBounds(bounds, { padding: [30, 30] });
      return true;
    }
    return false;
  }

  function applyInitialMapView() {
    if (focusSelectedAction()) {
      return;
    }
    if (focusSelectedWater()) {
      return;
    }
    if (focusFvofBoundary()) {
      return;
    }

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
  }

  if (areaFeatures.length > 0) {
    areaLayer.addTo(map);
  }
  if (waterFeatures.length > 0) {
    waterLayer.addTo(map);
  }
  rebuildActionLayer();
  applyInitialMapView();

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
      if (!focusSelectedAction()) {
        focusSelectedWater();
      }
    });
  });
})();

