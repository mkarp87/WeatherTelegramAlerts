from weather_alerts.web import radar_config_from_config


def test_radar_config_defaults_to_wms_and_normalizes_regions():
    cfg = {
        "Webapp": {
            "Radar": {
                "Enabled": True,
                "DefaultRegion": "pitt_craven",
                "Regions": {
                    "pitt_craven": {
                        "Label": "Pitt / Craven",
                        "CenterLat": "35.35",
                        "CenterLon": "-77.35",
                        "Zoom": "9",
                    }
                },
            }
        }
    }

    radar = radar_config_from_config(cfg)

    assert radar["enabled"] is True
    assert radar["mode"] == "wms"
    assert radar["default_region"] == "pitt_craven"
    assert radar["regions"]["pitt_craven"]["center_lat"] == 35.35
    assert radar["regions"]["pitt_craven"]["center_lon"] == -77.35
    assert radar["wms_url"].startswith("https://opengeo.ncep.noaa.gov/")
    assert radar["wms_layers"] == "conus_bref_qcd"
    assert radar["wms_version"] == "1.1.1"
    assert radar["wms_uppercase"] is True
    assert radar["disable_cache"] is True
    assert radar["startup_delay_ms"] == 350
    assert radar["leaflet_js_url"].startswith("https://")


def test_arcgis_mode_keeps_noaa_default_visible_layers():
    cfg = {
        "Webapp": {
            "Radar": {
                "Enabled": True,
                "Mode": "arcgis",
                "LayerIds": [3],
                "Regions": {
                    "pitt": {
                        "Label": "Pitt",
                        "CenterLat": 35.59249,
                        "CenterLon": -77.372739,
                        "Zoom": 10,
                    }
                },
            }
        }
    }

    radar = radar_config_from_config(cfg)

    assert radar["mode"] == "arcgis"
    assert radar["use_default_layers"] is True
    assert radar["layer_ids"] == []
    assert radar["esri_leaflet_js_url"].startswith("https://")


def test_wms_config_can_be_overridden():
    cfg = {
        "Webapp": {
            "Radar": {
                "Enabled": True,
                "Mode": "wms",
                "WmsURL": "https://example.test/wms",
                "WmsLayers": "custom_layer",
                "WmsVersion": "1.3.0",
                "WmsUppercase": False,
                "Regions": {
                    "test": {
                        "CenterLat": 1,
                        "CenterLon": 2,
                    }
                },
            }
        }
    }

    radar = radar_config_from_config(cfg)

    assert radar["wms_url"] == "https://example.test/wms"
    assert radar["wms_layers"] == "custom_layer"
    assert radar["wms_version"] == "1.3.0"
    assert radar["wms_uppercase"] is False
