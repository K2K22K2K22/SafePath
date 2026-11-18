# External Data Provider Policy

SAFE PATH uses external providers for road geometry, geocoding, and map tiles. Provider configuration does not transfer responsibility for licensing, availability, or acceptable use to the application operator.

## Road data

The route loader uses an Overpass-compatible read-only endpoint. It sends a fixed query for highway ways in one bounded bounding box and requests the referenced nodes. It does not call the OpenStreetMap editing or Map API.

The development fallback is `https://overpass-api.de/api/interpreter`. Public Overpass instances are shared services with no availability guarantee. They are suitable only for low-volume development and testing. Official guidance suggests no more than about 10,000 requests and about 1 GB of downloads per day, and states that applications relying on a public instance as their backend should run their own service. A deployed environment must use a paid or self-hosted Overpass-compatible provider. See the [Overpass API commons guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

Configure the provider with an HTTPS URL, an exact host allowlist, and an explicit production approval list:

```bash
SAFEPATH_OSM_API_URL='https://road-provider.example/api/interpreter'
SAFEPATH_OSM_API_ALLOWED_HOSTS='road-provider.example'
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS='road-provider.example'
```

Production mode requires the configured provider host to appear in `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS`. Known public Overpass hosts remain rejected even when an operator lists one. Host comparisons are canonicalized so case, IDNA form, and a trailing DNS dot cannot bypass either list. The production check script applies the same rule even when `DJANGO_DEBUG` is enabled for the surrounding command:

```bash
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY="$(cat /run/secrets/safepath_secret_key)" \
DJANGO_ALLOWED_HOSTS="safepath.example.com" \
SAFEPATH_OSM_API_URL="https://road-provider.example/api/interpreter" \
SAFEPATH_OSM_API_ALLOWED_HOSTS="road-provider.example" \
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS="road-provider.example" \
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
- Maximum XML depth of 8 and 500,000 XML elements
- Maximum 250,000 graph edges

Provider requests are serialized within one application process. Each Gunicorn worker has an independent lock, so provider capacity must cover the configured worker count. The process-local graph cache retains up to 8 graphs for 24 hours by default. Multiple application instances require provider-side capacity or shared coordination so their combined requests remain within the provider agreement. The application does not enforce a daily quota because that total cannot be coordinated reliably within one process.

Provider failures, oversized responses, invalid documents, and exhausted limits produce a road-data-unavailable response. A rejected request is split only when the provider explicitly reports an oversized area or element count. Documents must be UTF-8, and DTD or entity declarations are rejected. The application does not silently substitute a different provider or fabricate road geometry.

### Licensing and attribution

OpenStreetMap data is available under the Open Database License. The map interface displays the required OpenStreetMap attribution. See the [OpenStreetMap copyright page](https://www.openstreetmap.org/copyright) and [ODbL summary](https://opendatacommons.org/licenses/odbl/1-0/) for the applicable terms.

## Geocoding

Geocoding policy, request pacing, caching, and attribution are recorded with the geocoder implementation.

## Map tiles

The browser loads OpenStreetMap standard tiles and CARTO dark tiles directly. A deployed environment must use tile services covered by the operator's plan and keep the visible attribution intact.
