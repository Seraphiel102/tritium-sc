# Engine Layers

Map layer management system for the tactical map.

## Key Files

- `layer.py` — Layer base class and layer type definitions
- `manager.py` — LayerManager: registration, toggle, z-ordering
- `exporters/` — Export layers to various formats (KML, GeoJSON, etc.)
- `parsers/` — Parse external layer formats for import

## Related

- Frontend map rendering: `src/frontend/js/command/map.js`
- GIS layers plugin: `plugins/gis_layers/`
