(function () {
  'use strict';

  function setStatus(message) {
    const status = document.getElementById('radar-status');
    if (status) {
      status.textContent = message;
    }
  }

  function showError(message) {
    const errorBox = document.getElementById('radar-error');
    if (!errorBox) {
      return;
    }
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function hideError() {
    const errorBox = document.getElementById('radar-error');
    if (errorBox) {
      errorBox.hidden = true;
      errorBox.textContent = '';
    }
  }

  function readConfig() {
    const node = document.getElementById('radar-config');
    if (!node) {
      return null;
    }
    try {
      return JSON.parse(node.textContent || '{}');
    } catch (error) {
      showError('Radar configuration could not be parsed.');
      return null;
    }
  }

  function selectedRegion(config, key) {
    if (config.regions && config.regions[key]) {
      return config.regions[key];
    }
    const keys = Object.keys(config.regions || {});
    if (keys.length === 0) {
      return null;
    }
    return config.regions[keys[0]];
  }

  function setRegion(map, config, key) {
    const region = selectedRegion(config, key);
    if (!region) {
      showError('No usable radar regions are configured.');
      return false;
    }
    map.setView([region.center_lat, region.center_lon], region.zoom, { animate: false });
    return true;
  }

  function refreshLayer(layer) {
    if (!layer) {
      return;
    }

    if (layer.__weatherAlertsLayerType === 'wms' && typeof layer.setParams === 'function') {
      if (layer.__weatherAlertsDisableCache) {
        layer.setParams({ cache_buster: String(Date.now()) }, false);
      } else if (typeof layer.redraw === 'function') {
        layer.redraw();
      }
      return;
    }

    if (typeof layer.redraw === 'function') {
      layer.redraw();
      return;
    }
    if (typeof layer.refresh === 'function') {
      layer.refresh();
    }
  }

  function addWmsRadarLayer(map, config) {
    if (!(window.L.tileLayer && typeof window.L.tileLayer.wms === 'function')) {
      showError('Leaflet WMS support is not available.');
      return null;
    }
    if (!config.wms_url || !config.wms_layers) {
      showError('Radar WMS URL or layer name is missing.');
      return null;
    }

    const wmsOptions = {
      layers: config.wms_layers,
      styles: config.wms_styles || '',
      format: config.wms_format || 'image/png',
      transparent: config.wms_transparent !== false,
      version: config.wms_version || '1.1.1',
      attribution: config.radar_attribution || 'NOAA/NWS',
      opacity: Number(config.opacity || 0.85),
      uppercase: config.wms_uppercase !== false,
      tiled: config.wms_tiled !== false
    };

    if (config.disable_cache) {
      wmsOptions.cache_buster = String(Date.now());
    }
    if (config.wms_time) {
      wmsOptions.time = String(config.wms_time);
    }

    setStatus('Loading radar WMS tiles...');
    const radarLayer = window.L.tileLayer.wms(config.wms_url, wmsOptions).addTo(map);
    radarLayer.__weatherAlertsLayerType = 'wms';
    radarLayer.__weatherAlertsDisableCache = Boolean(config.disable_cache);

    if (typeof radarLayer.on === 'function') {
      radarLayer.on('tileloadstart', function () {
        hideError();
        setStatus('Loading radar WMS tiles...');
      });
      radarLayer.on('tileload', function () {
        hideError();
        setStatus('Radar layer loaded. Blank areas mean no radar returns are present.');
      });
      radarLayer.on('tileloaderror', function () {
        setStatus('Radar WMS tile load failed.');
        showError('The radar WMS tiles could not be loaded. Check the configured WMS URL/layer and browser network access.');
      });
    }
    return radarLayer;
  }

  function addArcgisRadarLayer(map, config) {
    if (!(window.L.esri && typeof window.L.esri.dynamicMapLayer === 'function')) {
      showError('Esri Leaflet did not load from the configured CDN.');
      return null;
    }

    const layerOptions = {
      url: config.service_url,
      opacity: Number(config.opacity || 0.72),
      attribution: config.radar_attribution || 'NOAA/NWS',
      format: config.image_format || 'png32',
      transparent: true,
      disableCache: Boolean(config.disable_cache)
    };

    if (Array.isArray(config.layer_ids) && config.layer_ids.length > 0 && !config.use_default_layers) {
      layerOptions.layers = config.layer_ids;
    }

    setStatus('Loading ArcGIS radar layer...');
    const radarLayer = window.L.esri.dynamicMapLayer(layerOptions).addTo(map);
    radarLayer.__weatherAlertsLayerType = 'arcgis';
    if (typeof radarLayer.on === 'function') {
      radarLayer.on('requesterror', function (error) {
        const detail = error && error.message ? ' ' + error.message : '';
        setStatus('ArcGIS radar layer load failed.');
        showError('The NOAA/NWS radar layer could not be loaded.' + detail);
      });
      radarLayer.on('load', function () {
        hideError();
        setStatus('Radar layer loaded. Blank areas mean no radar returns are present.');
      });
      radarLayer.on('loading', function () {
        hideError();
        setStatus('Loading ArcGIS radar layer...');
      });
    }
    return radarLayer;
  }

  function addRadarLayer(map, config) {
    const mode = String(config.mode || 'wms').toLowerCase();
    if (mode === 'arcgis') {
      return addArcgisRadarLayer(map, config);
    }
    return addWmsRadarLayer(map, config);
  }

  function initRadar() {
    const config = readConfig();
    const mapElement = document.getElementById('weather-radar-map');
    if (!config || !config.enabled || !mapElement) {
      return;
    }

    if (mapElement.dataset.radarInitialized === '1') {
      return;
    }
    mapElement.dataset.radarInitialized = '1';

    if (typeof window.L === 'undefined') {
      showError('Leaflet did not load from the configured CDN.');
      return;
    }

    const initialRegion = selectedRegion(config, config.default_region);
    if (!initialRegion) {
      showError('No usable radar regions are configured.');
      return;
    }

    const map = window.L.map(mapElement, {
      center: [initialRegion.center_lat, initialRegion.center_lon],
      zoom: initialRegion.zoom,
      scrollWheelZoom: Boolean(config.scroll_wheel_zoom),
      zoomControl: true,
      attributionControl: true
    });

    window.L.tileLayer(config.base_tile_url, {
      attribution: config.base_tile_attribution,
      maxZoom: config.max_zoom || 18,
      updateWhenIdle: true
    }).addTo(map);

    let radarLayer = null;

    const startupDelayMs = Math.max(0, Number(config.startup_delay_ms || 350));
    window.setTimeout(function () {
      map.invalidateSize(false);
      setRegion(map, config, config.default_region);
      radarLayer = addRadarLayer(map, config);
      window.setTimeout(function () {
        map.invalidateSize(false);
        refreshLayer(radarLayer);
      }, 500);
    }, startupDelayMs);

    const selector = document.getElementById('radar-region');
    if (selector) {
      selector.addEventListener('change', function () {
        if (setRegion(map, config, selector.value)) {
          window.setTimeout(function () {
            map.invalidateSize(false);
            refreshLayer(radarLayer);
          }, 250);
        }
      });
    }

    const refreshSeconds = Math.max(60, Number(config.refresh_seconds || 300));
    window.setInterval(function () {
      refreshLayer(radarLayer);
    }, refreshSeconds * 1000);
  }

  if (document.readyState === 'complete') {
    initRadar();
  } else {
    window.addEventListener('load', initRadar, { once: true });
  }
}());
