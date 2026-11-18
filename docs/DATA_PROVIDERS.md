# External Data Provider Policy

SAFE PATH uses external providers for road geometry, geocoding, and map tiles. Provider configuration does not transfer responsibility for licensing, availability, or acceptable use to the application operator. See [EXTERNAL_SERVICES.md](EXTERNAL_SERVICES.md) for the operator service inventory, credential classes, attribution checklist, and failure-response guide.

## Road data

The route loader uses an Overpass-compatible read-only endpoint. It sends a fixed query for highway ways in one bounded bounding box and requests the referenced nodes. It does not call the OpenStreetMap editing or Map API.

The development fallback is `https://overpass-api.de/api/interpreter`. Public Overpass instances are shared services with no availability guarantee. They are suitable only for low-volume development and testing. Official guidance suggests no more than about 10,000 requests and about 1 GB of downloads per day, and states that applications relying on a public instance as their backend should run their own service. A deployed environment must use a paid or self-hosted Overpass-compatible provider. See the [Overpass API commons guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

Configure the provider with an HTTPS URL, an exact host allowlist, and an explicit production approval list:

```bash
SAFEPATH_OSM_API_URL='https://road-provider.example/api/interpreter'
SAFEPATH_OSM_API_ALLOWED_HOSTS='road-provider.example'
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS='road-provider.example'
```

These are reserved example values. Replace them with the operator's approved provider URL and exact host.

Production mode requires the configured provider host to appear in `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS`. Known public Overpass hosts remain rejected even when an operator lists one. The denylist was reviewed against the OSM Wiki public-instance list on 18 November 2026 and must be reviewed when that list changes. Host comparisons are canonicalized so case, IDNA form, and a trailing DNS dot cannot bypass either list.

The production check script applies the same rule even when `DJANGO_DEBUG` is enabled for the surrounding command. It also requires the operator-provided Django secret, customer-owned CARTO key, deployed host, and approved provider values, so export them before running it:

```bash
: "${DJANGO_SECRET_KEY:?Export the operator-provided Django secret}"
: "${SAFEPATH_CARTO_API_KEY:?Export the customer-owned CARTO key}"
: "${DJANGO_ALLOWED_HOSTS:?Export the exact deployed host list}"
: "${SAFEPATH_OSM_API_URL:?Export the approved provider URL}"
: "${SAFEPATH_OSM_API_ALLOWED_HOSTS:?Export the approved provider host}"
: "${SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS:?Export the approved provider host}"

export DJANGO_SECRET_KEY
export SAFEPATH_CARTO_API_KEY
export DJANGO_ALLOWED_HOSTS
export SAFEPATH_OSM_API_URL
export SAFEPATH_OSM_API_ALLOWED_HOSTS
export SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS
export DJANGO_DEBUG=False
python scripts/check_production.py
```

The application cannot verify that an approved non-public host is paid, self-hosted, correctly licensed, or available. Listing a host is an explicit operator assertion. The operator remains responsible for the provider contract and capacity plan.

### Road request safeguards

The loader preserves these limits for every graph load:

- HTTPS only, exact host allowlist, no URL credentials, and no non-standard port
- No redirects
- One fixed Overpass QL query for drivable highway classes with a 25 second server timeout and a 256 MiB server memory declaration
- Maximum bounding-box area of `0.20` square degrees
- Maximum 16 provider requests per graph load
- Maximum split depth of 3
- Maximum 25,000,000 downloaded bytes per graph load
- Maximum 30 second acquisition deadline checked between response reads
- Maximum XML depth of 8 per document and 500,000 XML elements in aggregate across split documents
- Maximum 250,000 graph edges

Provider requests are serialized within one application process. Each Gunicorn worker has an independent lock, so provider capacity must cover the configured worker count. The process-local graph cache retains up to 8 graphs for 24 hours by default. Multiple application instances require provider-side capacity or shared coordination so their combined requests remain within the provider agreement. The application does not enforce a daily quota because that total cannot be coordinated reliably within one process.

Provider failures, oversized responses, invalid documents, and exhausted limits produce a road-data-unavailable response. A rejected request is split only when the provider explicitly reports an oversized area or element count. Documents must be UTF-8, and DTD or entity declarations are rejected. The application does not silently substitute a different provider or fabricate road geometry.

### Licensing and attribution

OpenStreetMap data is available under the Open Database License. The map interface displays the required OpenStreetMap attribution. See the [OpenStreetMap copyright page](https://www.openstreetmap.org/copyright) and [ODbL summary](https://opendatacommons.org/licenses/odbl/1-0/) for the applicable terms.

## Geocoding

The server proxies place search to the configured Nominatim-compatible HTTPS endpoint. The default is the public `https://nominatim.openstreetmap.org/search` endpoint. Public Nominatim has donated infrastructure and no availability guarantee, so a deployed environment must confirm that its expected traffic is allowed or use a self-hosted service covered by the operator's plan. See the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

The public service requires no more than one request per second, an identifying User-Agent, visible attribution, caching, and no autocomplete. SAFE PATH enforces the request interval with a shared file lock across Gunicorn workers in one application instance. A cache hit does not consume provider capacity. The lock coordinates workers only when they share the same `SAFEPATH_CACHE_DIR`; multiple application instances require external shared coordination or a provider-side limit.

Geocoder queries are normalized with Unicode NFKC, collapsed whitespace, and case folding before use. Cache keys are SHA-256 digests of the normalized query and provider URL. Successful empty results are cached. Provider failures and malformed payloads are not cached. The file-based cache holds at most 1,000 entries for 24 hours by default, configurable with `SAFEPATH_GEOCODER_CACHE_MAX_ENTRIES` and `SAFEPATH_GEOCODER_CACHE_TTL_SECONDS`. The cache directory must be owned by the application user with mode `0700`; startup rejects a public or symlinked directory because Django's file cache deserializes local files. Cache read and write failures do not block a valid provider response. A request-lock failure returns HTTP 503 because provider pacing cannot be guaranteed.

Every provider request uses the identifying `SAFEPATH_HTTP_USER_AGENT`, rejects redirects, applies finite connect and read timeouts, limits the response to 64 KiB, requires a JSON list, validates returned coordinates, and returns a generic service-unavailable response without exposing upstream details. A non-empty list with no valid coordinate is treated as malformed and is not cached. The browser input disables autocomplete. The page visibly credits Nominatim and OpenStreetMap contributors.

## Map tiles

The browser loads map tiles directly. The light theme uses the canonical OpenStreetMap standard raster endpoint:

```text
https://tile.openstreetmap.org/{z}/{x}/{y}.png
```

The dark theme uses CARTO's current raster basemap endpoint when a publishable key is configured:

```text
https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=...
```

OpenStreetMap standard tiles are best-effort and have no service-level guarantee. Their policy prohibits heavy or inappropriate use and requires valid attribution. The application keeps the OpenStreetMap attribution visible and uses a referrer policy that preserves the page origin on cross-origin tile requests. A deployment that cannot meet the tile policy must use an approved alternative provider.

CARTO basemap access requires a customer-owned publishable key. Production startup requires `SAFEPATH_CARTO_API_KEY` and rejects obvious placeholder values. The key is domain-restricted, visible in browser requests, and is not a confidential server secret. It must not be proxied through the application or restricted as a server-side secret. The page keeps the CARTO and OpenStreetMap attribution visible. See the [CARTO basemap FAQ](https://docs.carto.com/faqs/carto-basemaps/) and [CARTO attribution guidance](https://carto.com/attribution/).

Without a key, local development uses the OpenStreetMap raster tiles with a dark-theme filter. It does not request CARTO without a usable key. Production still requires CARTO for the configured dark basemap.

The operator remains responsible for provider plans, quotas, key restrictions, licensing, and availability.
