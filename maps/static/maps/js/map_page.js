(function () {
  const mapElement = document.getElementById("map-page-map");
  const geojsonScript = document.getElementById("map-geojson-data");
  const metaScript = document.getElementById("map-meta");
  const areaToggle = document.getElementById("toggle-areas");
  const waterToggle = document.getElementById("toggle-waters");
  const actionToggle = document.getElementById("toggle-actions");
  const observationToggle = document.getElementById("toggle-observations");
  const actionStatusToggles = document.querySelectorAll(".js-action-status-toggle");

  const ACTION_STATUS_LABELS = {
    urgent: "Akut",
    needs_action: "Behöver beslut",
    planned: "Planerad",
    in_progress: "Pågår",
    completed: "Klar",
  };

  function getActionStatusLabel(status) {
    if (!status) {
      return "Ej angiven";
    }
    return ACTION_STATUS_LABELS[status] || status;
  }

  const OBSERVATION_MARKER_STYLE = {
    radius: 7,
    color: "#ffffff",
    weight: 2,
    fillColor: "#9333ea",
    fillOpacity: 0.9,
  };

  const ACTION_POINT_MARKER_BASE = {
    radius: 8,
    color: "#ffffff",
    weight: 2,
    fillOpacity: 0.95,
  };

  const ACTION_POINT_MARKER_BY_STATUS = {
    urgent: { fillColor: "#ef4444" },
    needs_action: { fillColor: "#fb923c" },
    planned: { fillColor: "#eab308" },
    in_progress: { fillColor: "#3b82f6" },
    completed: { fillColor: "#22c55e" },
  };

  function getActionPointMarkerStyle(status) {
    const statusStyle = ACTION_POINT_MARKER_BY_STATUS[status] || ACTION_POINT_MARKER_BY_STATUS.needs_action;
    return { ...ACTION_POINT_MARKER_BASE, ...statusStyle };
  }

  function isExactActionPointFeature(feature) {
    return (
      feature.properties?.type === "action" &&
      feature.properties?.exact_position === true &&
      feature.geometry?.type === "Point"
    );
  }

  function buildActionPointPopupHtml(properties) {
    const name = properties?.name || "Insats";
    const statusLabel = getActionStatusLabel(properties?.status);
    return (
      `<div class="map-popup-action-point">` +
      `<strong>${name}</strong>` +
      `<div class="map-popup-water-meta">Status: ${statusLabel}</div>` +
      `</div>`
    );
  }

  const OBSERVATION_CREATE_BASE = "/fisheries/observations/create/";
  const ACTION_CREATE_BASE = "/fisheries/actions/create/";

  function formatMapCoord(value) {
    return Number(value).toFixed(6);
  }

  function pointInRing(lng, lat, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = Number(ring[i][0]);
      const yi = Number(ring[i][1]);
      const xj = Number(ring[j][0]);
      const yj = Number(ring[j][1]);
      if (!Number.isFinite(xi) || !Number.isFinite(yi) || !Number.isFinite(xj) || !Number.isFinite(yj)) {
        continue;
      }
      const intersects =
        yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
      if (intersects) {
        inside = !inside;
      }
    }
    return inside;
  }

  function geometryContainsLatLng(geometry, latlng) {
    if (!geometry || !geometry.type || !geometry.coordinates) {
      return false;
    }
    const lat = latlng.lat;
    const lng = latlng.lng;
    const geomType = geometry.type;
    const coordinates = geometry.coordinates;

    if (geomType === "Polygon") {
      if (!Array.isArray(coordinates[0])) {
        return false;
      }
      return pointInRing(lng, lat, coordinates[0]);
    }
    if (geomType === "MultiPolygon") {
      return coordinates.some(function (polygon) {
        return Array.isArray(polygon[0]) && pointInRing(lng, lat, polygon[0]);
      });
    }
    return false;
  }

  function buildCreateUrl(baseUrl, lat, lng, waterId) {
    const params = new URLSearchParams();
    params.set("lat", String(lat));
    params.set("lng", String(lng));
    if (waterId !== null && waterId !== undefined && waterId !== "") {
      params.set("water_id", String(waterId));
    }
    return baseUrl + "?" + params.toString();
  }

  function buildCreateLinksHtml(lat, lng, waterId) {
    const observationUrl = buildCreateUrl(
      OBSERVATION_CREATE_BASE,
      lat,
      lng,
      waterId
    );
    const actionUrl = buildCreateUrl(ACTION_CREATE_BASE, lat, lng, waterId);
    return (
      '<div class="map-create-popup-links">' +
      `<a class="map-create-popup-link" href="${observationUrl}">Skapa observation här</a>` +
      `<a class="map-create-popup-link" href="${actionUrl}">Planera insats här</a>` +
      "</div>"
    );
  }

  function getModeCreateConfig() {
    const isObservation = mapCreateMode === "create_observation";
    return {
      baseUrl: isObservation ? OBSERVATION_CREATE_BASE : ACTION_CREATE_BASE,
      title: isObservation ? "Ny observation" : "Ny insats",
      linkLabel: isObservation ? "Skapa observation här" : "Planera insats här",
      helpText: isObservation
        ? "Platsen blir observationens exakta position på kartan."
        : "Platsen blir insatsens exakta position på kartan.",
    };
  }

  function buildModeCreateLinkHtml(lat, lng, waterId) {
    const config = getModeCreateConfig();
    const url = buildCreateUrl(config.baseUrl, lat, lng, waterId);
    return (
      `<a class="map-create-popup-link map-create-popup-link--primary" href="${url}">` +
      `${config.linkLabel}</a>`
    );
  }

  function buildModeCreatePopupHtml(lat, lng, waterId) {
    const config = getModeCreateConfig();
    return (
      '<div class="map-create-popup">' +
      `<p class="map-create-popup-title">${config.title}</p>` +
      `<p class="map-create-popup-help">${config.helpText}</p>` +
      '<div class="map-create-popup-links">' +
      buildModeCreateLinkHtml(lat, lng, waterId) +
      "</div></div>"
    );
  }

  function buildMapClickPopupHtml(lat, lng, waterId) {
    if (mapCreateMode) {
      return buildModeCreatePopupHtml(lat, lng, waterId);
    }
    return (
      '<div class="map-create-popup">' +
      '<p class="map-create-popup-title">Skapa här</p>' +
      buildCreateLinksHtml(lat, lng, waterId) +
      "</div>"
    );
  }

  function navigateToPickReturn(lat, lng, waterId) {
    if (!mapPickReturnUrl) {
      return;
    }
    window.location.href = buildCreateUrl(mapPickReturnUrl, lat, lng, waterId);
  }

  function openMapCreatePopup(latlng, lat, lng, waterId) {
    const resolvedWaterId =
      waterId !== null && waterId !== undefined && waterId !== ""
        ? waterId
        : findWaterIdAtLatLng(latlng);
    L.popup({ className: "map-create-popup-leaflet" })
      .setLatLng(latlng)
      .setContent(buildMapClickPopupHtml(lat, lng, resolvedWaterId))
      .openOn(map);
  }

  function buildWaterPopupHtml(properties, lat, lng) {
    const name = properties?.name || "Vatten";
    const fish = Array.isArray(properties?.fish) ? properties.fish : [];
    const fishText = fish.length > 0 ? fish.join(", ") : "Inga registrerade arter";
    const detailUrl = properties?.detail_url || "";
    const waterId =
      properties?.type === "water" && properties?.id != null
        ? properties.id
        : null;

    let popupHtml =
      `<div class="map-popup-water">` +
      `<strong>${name}</strong>` +
      `<div class="map-popup-water-meta">Fiskarter: ${fishText}</div>`;
    if (detailUrl) {
      popupHtml +=
        `<a class="map-popup-water-link" href="${detailUrl}">Öppna vatten →</a>`;
    }
    popupHtml += '<div class="map-create-popup map-create-popup--inline">';
    if (mapCreateMode) {
      const config = getModeCreateConfig();
      popupHtml +=
        `<p class="map-create-popup-help">${config.helpText}</p>` +
        '<div class="map-create-popup-links">' +
        buildModeCreateLinkHtml(lat, lng, waterId) +
        "</div>";
    } else {
      popupHtml += buildCreateLinksHtml(lat, lng, waterId);
    }
    popupHtml += "</div></div>";
    return popupHtml;
  }

  function buildObservationPopupHtml(properties) {
    const title = properties?.title || "Observation";
    const categoryLabel = properties?.category_label || "Ej angiven";
    const statusLabel = properties?.status_label || "Ej angiven";
    const waterName = properties?.water_body_name || "Ej kopplat";
    const createdAt = properties?.created_at || "—";
    const excerpt = (properties?.description_excerpt || "").trim();
    const detailUrl = properties?.detail_url || "#";

    let popupHtml =
      `<div class="map-popup-observation">` +
      `<strong>${title}</strong>` +
      `<div class="map-popup-observation-meta">` +
      `Kategori: ${categoryLabel}<br>` +
      `Status: ${statusLabel}<br>` +
      `Vatten: ${waterName}<br>` +
      `Skapad: ${createdAt}` +
      `</div>`;

    if (excerpt) {
      popupHtml += `<p class="map-popup-observation-excerpt">${excerpt}</p>`;
    }

    popupHtml +=
      `<a class="map-popup-observation-link" href="${detailUrl}">Öppna observation →</a>` +
      `</div>`;

    return popupHtml;
  }

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
  const mapCreateMode =
    meta.map_create_mode === "create_observation" ||
    meta.map_create_mode === "create_action" ||
    meta.map_create_mode === "pick_observation" ||
    meta.map_create_mode === "pick_action"
      ? meta.map_create_mode
      : null;
  const isPickMode =
    mapCreateMode === "pick_observation" || mapCreateMode === "pick_action";
  const mapPickReturnUrl = meta.map_pick_return_url || null;
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
  const selectedObservationId =
    meta.selected_observation_id === null || meta.selected_observation_id === undefined
      ? null
      : Number(meta.selected_observation_id);

  const map = L.map(mapElement).setView([59.33, 18.03], 11);

  map.createPane("paneWater");
  map.getPane("paneWater").style.zIndex = "420";
  map.createPane("paneActions");
  map.getPane("paneActions").style.zIndex = "460";
  map.createPane("paneActionPoints");
  map.getPane("paneActionPoints").style.zIndex = "520";
  map.createPane("paneObservations");
  map.getPane("paneObservations").style.zIndex = "560";

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
          syncInteractiveLayerOrder();
        } else if (map.hasLayer(fvofLayer)) {
          map.removeLayer(fvofLayer);
          setFvofAttribution(false);
        }
      });
    }
  }

  initFvofOverlay();

  const AREA_LAYER_STYLE = {
    color: "#4f46e5",
    weight: 2.5,
    fillColor: "#a5b4fc",
    fillOpacity: 0.1,
    dashArray: "6 4",
  };

  function getAreaLayerStyle() {
    return { ...AREA_LAYER_STYLE };
  }

  function getFeatureStyle(feature) {
    const type = feature.properties?.type;
    if (type === "area") {
      return getAreaLayerStyle();
    }
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
    return getAreaLayerStyle();
  }

  function bindFeatureInteractions(feature, featureLayer) {
    const name = feature.properties?.name || "Område";
    const type = feature.properties?.type || "area";

    let popupHtml = `<strong>${name}</strong>`;
    if (type === "water") {
      featureLayer.on("click", function (event) {
        L.DomEvent.stopPropagation(event);
        const lat = formatMapCoord(event.latlng.lat);
        const lng = formatMapCoord(event.latlng.lng);
        const waterId =
          feature.properties?.type === "water" && feature.properties?.id != null
            ? feature.properties.id
            : null;
        if (isPickMode) {
          navigateToPickReturn(lat, lng, waterId);
          return;
        }
        featureLayer
          .bindPopup(buildWaterPopupHtml(feature.properties, lat, lng))
          .openPopup(event.latlng);
      });

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
      return;
    }

    if (type === "action") {
      const statusLabel = getActionStatusLabel(feature.properties?.status);
      popupHtml += `<br>Status: ${statusLabel}`;
    }
    featureLayer.bindPopup(popupHtml);

    if (type === "action") {
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

      featureLayer.on("click", function (event) {
        L.DomEvent.stopPropagation(event);
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
  const observationFeatures = (geojsonData.features || []).filter(
    function (feature) {
      return feature.properties?.type === "observation";
    }
  );

  const areaLayer = L.geoJSON(
    { type: "FeatureCollection", features: areaFeatures },
    {
      style: getAreaLayerStyle,
      interactive: false,
    }
  );

  const waterLayer = L.geoJSON(
    { type: "FeatureCollection", features: waterFeatures },
    {
      pane: "paneWater",
      style: getFeatureStyle,
      onEachFeature: bindFeatureInteractions,
    }
  );

  function findWaterIdAtLatLng(latlng) {
    let waterId = null;
    waterFeatures.forEach(function (feature) {
      if (waterId !== null) {
        return;
      }
      if (!feature || feature.properties?.type !== "water") {
        return;
      }
      if (geometryContainsLatLng(feature.geometry, latlng)) {
        waterId = feature.properties.id;
      }
    });
    return waterId;
  }
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
  const actionPointLayer = L.layerGroup();

  function buildActionPointLayer(features) {
    actionPointLayer.clearLayers();

    features.forEach(function (feature) {
      const coordinates = feature.geometry?.coordinates;
      if (!Array.isArray(coordinates) || coordinates.length < 2) {
        return;
      }

      const lng = Number(coordinates[0]);
      const lat = Number(coordinates[1]);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        return;
      }

      const status = feature.properties?.status;
      const marker = L.circleMarker([lat, lng], {
        ...getActionPointMarkerStyle(status),
        pane: "paneActionPoints",
      });
      marker.feature = feature;
      marker.bindPopup(buildActionPointPopupHtml(feature.properties || {}));

      marker.on("click", function (event) {
        L.DomEvent.stopPropagation(event);
      });

      marker.on("mouseover", function () {
        marker.setStyle({ radius: 10, weight: 2 });
        if (typeof marker.bringToFront === "function") {
          marker.bringToFront();
        }
      });

      marker.on("mouseout", function () {
        marker.setStyle(getActionPointMarkerStyle(status));
      });

      actionPointLayer.addLayer(marker);
    });
  }

  function rebuildActionLayer() {
    const selectedStatuses = getSelectedActionStatuses();
    const filteredActionFeatures = actionFeatures.filter(function (feature) {
      const status = feature.properties?.status;
      return selectedStatuses.includes(status);
    });

    const filteredPointFeatures = filteredActionFeatures.filter(isExactActionPointFeature);
    const filteredAreaFeatures = filteredActionFeatures.filter(function (feature) {
      return !isExactActionPointFeature(feature);
    });

    const shouldBeVisible = actionToggle.checked;
    if (map.hasLayer(actionLayer)) {
      map.removeLayer(actionLayer);
    }
    if (map.hasLayer(actionPointLayer)) {
      map.removeLayer(actionPointLayer);
    }

    actionLayer = L.geoJSON(
      { type: "FeatureCollection", features: filteredAreaFeatures },
      {
        pane: "paneActions",
        style: getFeatureStyle,
        onEachFeature: bindFeatureInteractions,
      }
    );
    buildActionPointLayer(filteredPointFeatures);

    if (shouldBeVisible) {
      actionLayer.addTo(map);
      actionPointLayer.addTo(map);
    }
    syncInteractiveLayerOrder();
  }

  const observationLayer = L.layerGroup();

  function buildObservationLayer() {
    observationLayer.clearLayers();

    observationFeatures.forEach(function (feature) {
      const coordinates = feature.geometry?.coordinates;
      if (!Array.isArray(coordinates) || coordinates.length < 2) {
        return;
      }

      const lng = Number(coordinates[0]);
      const lat = Number(coordinates[1]);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        return;
      }

      const marker = L.circleMarker([lat, lng], {
        ...OBSERVATION_MARKER_STYLE,
        pane: "paneObservations",
        radius: 9,
        zIndexOffset: 2000,
      });
      marker.bindPopup(buildObservationPopupHtml(feature.properties || {}));

      marker.on("click", function (event) {
        L.DomEvent.stopPropagation(event);
      });

      marker.on("mouseover", function () {
        marker.setStyle({
          radius: 9,
          weight: 2,
        });
        if (typeof marker.bringToFront === "function") {
          marker.bringToFront();
        }
      });

      marker.on("mouseout", function () {
        marker.setStyle({
          radius: 9,
          weight: OBSERVATION_MARKER_STYLE.weight,
        });
      });

      observationLayer.addLayer(marker);
    });
  }

  buildObservationLayer();

  function syncInteractiveLayerOrder() {
    if (fvofLayer && map.hasLayer(fvofLayer) && typeof fvofLayer.bringToBack === "function") {
      fvofLayer.bringToBack();
    }
    if (map.hasLayer(areaLayer) && typeof areaLayer.bringToBack === "function") {
      areaLayer.bringToBack();
    }
    if (map.hasLayer(waterLayer) && typeof waterLayer.bringToFront === "function") {
      waterLayer.bringToFront();
    }
    if (map.hasLayer(actionLayer) && typeof actionLayer.bringToFront === "function") {
      actionLayer.bringToFront();
    }
    if (map.hasLayer(actionPointLayer) && typeof actionPointLayer.bringToFront === "function") {
      actionPointLayer.bringToFront();
    }
    if (map.hasLayer(observationLayer) && typeof observationLayer.bringToFront === "function") {
      observationLayer.bringToFront();
    }
  }

  function updateObservationLayerVisibility() {
    if (!observationToggle) {
      return;
    }
    if (observationToggle.checked) {
      if (!map.hasLayer(observationLayer)) {
        observationLayer.addTo(map);
      }
    } else if (map.hasLayer(observationLayer)) {
      map.removeLayer(observationLayer);
    }
    syncInteractiveLayerOrder();
  }

  function focusSelectedAction() {
    if (selectedActionId === null) {
      return false;
    }
    if (!map.hasLayer(actionLayer) && !map.hasLayer(actionPointLayer)) {
      return false;
    }
    let focused = false;

    function focusActionLayer(layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedActionId) {
        return;
      }
      focused = true;
      if (typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
      if (typeof layer.getLatLng === "function") {
        map.setView(layer.getLatLng(), Math.max(map.getZoom(), 14));
      } else if (typeof layer.getBounds === "function") {
        const bounds = layer.getBounds();
        if (bounds && bounds.isValid && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [30, 30] });
        }
      }
      if (typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    }

    if (map.hasLayer(actionPointLayer)) {
      actionPointLayer.eachLayer(focusActionLayer);
    }
    if (!focused && map.hasLayer(actionLayer)) {
      actionLayer.eachLayer(focusActionLayer);
    }
    return focused;
  }

  function focusSelectedObservation() {
    if (selectedObservationId === null || !map.hasLayer(observationLayer)) {
      return false;
    }
    let focused = false;
    observationLayer.eachLayer(function (layer) {
      const featureId = Number(layer.feature?.properties?.id);
      if (featureId !== selectedObservationId) {
        return;
      }
      focused = true;
      if (typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
      if (typeof layer.getLatLng === "function") {
        map.setView(layer.getLatLng(), Math.max(map.getZoom(), 14));
      }
      if (typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    });
    return focused;
  }

  function focusSelectedWater() {
    if (
      selectedActionId !== null ||
      selectedObservationId !== null ||
      selectedWaterId === null ||
      !map.hasLayer(waterLayer)
    ) {
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
    if (focusSelectedObservation()) {
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
  if (waterFeatures.length > 0 && waterToggle.checked) {
    waterLayer.addTo(map);
  }
  rebuildActionLayer();
  updateObservationLayerVisibility();
  syncInteractiveLayerOrder();
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
      if (!map.hasLayer(actionPointLayer)) {
        actionPointLayer.addTo(map);
      }
    } else {
      if (map.hasLayer(actionLayer)) {
        map.removeLayer(actionLayer);
      }
      if (map.hasLayer(actionPointLayer)) {
        map.removeLayer(actionPointLayer);
      }
    }

    updateObservationLayerVisibility();
    syncInteractiveLayerOrder();
  }

  areaToggle.addEventListener("change", updateLayerVisibility);
  waterToggle.addEventListener("change", updateLayerVisibility);
  actionToggle.addEventListener("change", updateLayerVisibility);
  if (observationToggle) {
    observationToggle.addEventListener("change", updateLayerVisibility);
  }
  actionStatusToggles.forEach(function (toggle) {
    toggle.addEventListener("change", function () {
      rebuildActionLayer();
      updateLayerVisibility();
      if (!focusSelectedAction()) {
        focusSelectedWater();
      }
    });
  });

  map.on("click", function (event) {
    const lat = formatMapCoord(event.latlng.lat);
    const lng = formatMapCoord(event.latlng.lng);
    const waterId = findWaterIdAtLatLng(event.latlng);
    if (isPickMode) {
      navigateToPickReturn(lat, lng, waterId);
      return;
    }
    openMapCreatePopup(event.latlng, lat, lng, waterId);
  });
})();

