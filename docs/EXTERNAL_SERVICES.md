# External Services

This guide records the services SAFE PATH depends on, operator responsibilities, credential handling, attribution, and failure behavior. Exact request limits and technical safeguards are in [DATA_PROVIDERS.md](DATA_PROVIDERS.md). No service credential belongs in this repository.

## Service inventory

| Service | Used by | Configuration | Production requirement |
| --- | --- | --- | --- |
| Overpass-compatible road provider (selected: Overpass.ch) | Server | `SAFEPATH_OSM_API_URL`, `SAFEPATH_OSM_API_KEY`, `SAFEPATH_OSM_API_ALLOWED_HOSTS`, `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS` | Paid or self-hosted HTTPS service with explicit host approval and API key |
| Nominatim-compatible geocoder | Server | `SAFEPATH_GEOCODER_URL`, `SAFEPATH_GEOCODER_ALLOWED_HOSTS` | Service whose policy permits the expected traffic; public Nominatim has no availability guarantee |
| OpenStreetMap raster tiles | Browser | Fixed canonical endpoint | Use only when the tile policy permits the expected traffic |
| CARTO raster tiles | Browser | `SAFEPATH_CARTO_API_KEY` | Customer-owned publishable key restricted to the deployed domain |
| PostgreSQL | Server | `DATABASE_URL` | External durable database with TLS and a tested backup policy |
| Render | Hosting platform | `render.yaml` | Academic demonstration only on the Free plan |

SAFE PATH does not send bundled incident records to external services. A route request sends a bounded road-search area to the road provider. A geocoding request sends the user's normalized search text to the geocoder. Map tiles are requested directly by the browser and do not pass through Django.

## Credential handling

- Store `DJANGO_SECRET_KEY` and `DATABASE_URL` only in a secret manager or ignored local environment file.
- `SAFEPATH_CARTO_API_KEY` is a publishable browser value, not a server secret. Restrict it to the deployed domain and keep it visible only in the intended tile requests.
- Road and geocoder URLs cannot contain embedded credentials. Overpass.ch authenticates with `SAFEPATH_OSM_API_KEY` in an `X-API-Key` request header. Store the key only in a secret manager or the platform's secret setting. It is never placed in the endpoint URL, request body, logs, exception text, or HTTP responses.
- Never place credentials in `render.yaml`, `.env.example`, committed documentation, shell history, CI logs, or provider URLs.
- Application and Gunicorn logs omit query strings and redact credential-like values. Provider response bodies and exception text are not returned to users.

## Road data policy

The route loader uses an Overpass-compatible read-only endpoint. It does not use the OpenStreetMap editing or Map API. Public Overpass instances are shared development resources with no availability guarantee. Official guidance advises applications that depend on a public instance as their backend to operate their own service and describes a suggested shared limit of about 10,000 requests and 1 GB per day.

A production deployment must use a paid or self-hosted provider and record its exact host in both allowlists. The application rejects known public Overpass hosts in production even if they are listed. Listing a non-public host is an operator assertion that the service contract, licensing, and capacity are suitable; the application cannot verify them.

The selected provider is Overpass.ch at `https://api.overpass.ch/v1/interpreter`, with host `api.overpass.ch` in both allowlists. Requests use a form-encoded `data` POST carrying fixed bounded Overpass QL, request XML output through the `out:xml` settings block, and authenticate with the `X-API-Key` header. HTTPS, no redirects, finite timeouts, byte and element limits, per-process serialization, and an application-wide cap of 60 interpreter requests per rolling minute are enforced. Provider requests stay at one concurrency in the supported one-worker Render configuration, within the Overpass.ch Small plan limit of two concurrent queries. Graph caching prevents repeated downloads. Multiple instances need provider-side capacity or shared coordination. Review the [Overpass API commons guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) before changing traffic patterns.

## Geocoding policy

The public Nominatim service requires an identifying User-Agent, no more than one request per second, caching, no autocomplete, valid attribution, and appropriate use. SAFE PATH sends `SAFEPATH_HTTP_USER_AGENT`, disables browser autocomplete, caches normalized results, and coordinates uncached requests across workers that share one instance filesystem.

The file lock does not coordinate separate application instances. Keep a public-provider deployment at one instance or move to a self-hosted or approved geocoder with external coordination. Cache hits do not consume provider capacity. Review the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) before deployment.

## Map tile policy

The light theme loads OpenStreetMap standard raster tiles directly in the browser. Standard tiles are a best-effort service with no service-level guarantee, and their policy prohibits heavy or inappropriate use. Keep the visible attribution and preserve the page referrer. A deployment that cannot meet the tile policy must use an approved alternative provider.

The dark theme loads CARTO raster tiles directly. Use a customer-owned publishable key, restrict it to the deployed domain, follow the provider's plan and usage terms, and keep the CARTO and OpenStreetMap attribution visible. Review the [CARTO basemap FAQ](https://docs.carto.com/faqs/carto-basemaps/) and [CARTO attribution guidance](https://carto.com/attribution/).

## Attribution

The map keeps tile attribution visible through Leaflet. The page footer credits Nominatim and OpenStreetMap contributors. Do not remove, hide, or replace these notices without a documented legal and provider review.

OpenStreetMap data is available under the Open Database License. The relevant references are the [OpenStreetMap copyright page](https://www.openstreetmap.org/copyright) and the [ODbL summary](https://opendatacommons.org/licenses/odbl/1-0/). Basemap attribution does not replace road-data attribution obligations. Keep the required attribution when changing providers.

## Failure behavior

| Failure | User-visible result | Operator check |
| --- | --- | --- |
| Road provider unavailable, rejected, oversized, or invalid | HTTP 503 with `road_provider_unavailable` | Provider status, quota, exact HTTPS host, production approval, and recent error logs |
| Geocoder unavailable or malformed | HTTP 503 with `geocoder_unavailable` or `invalid_provider_response` | Provider status, identifying User-Agent, cache-directory permissions, and request pacing |
| Geocoder lock unavailable | HTTP 503 with `geocoder_unavailable` | Cache directory ownership, mode `0700`, disk state, and instance count |
| CARTO tiles fail in the browser | Missing dark basemap | Key validity, domain restriction, plan, quota, and browser network errors |
| PostgreSQL unavailable | Readiness returns HTTP 503 with `database_unavailable` | DNS, TLS, credentials, database status, and migration state |
| Application process fails | Liveness probe fails | Gunicorn and startup logs, configuration, and worker limits |

Provider errors are controlled and do not expose upstream response text. Repeated failures should be correlated with provider status before changing allowlists or limits.

## Incident data is not a verified service

`data/delhi_crime_data.csv` is unverified demonstration data. Its original source, collection methodology, collection date, geographical coverage, license, and redistribution permission are unknown. Repository history describes it as fictitious testing data but does not establish separate licensing or redistribution permission. The application and interface label it accordingly.

The score is a deterministic proximity measure around bundled demonstration records. It is not crime probability, live incident data, a complete incident dataset, or a personal-safety assessment. Do not market it as verified crime data or real-time safety guidance. Confirm the dataset license and redistribution permission before any use beyond this academic demonstration.

## Provider change checklist

Before changing a provider:

1. Confirm a written agreement, license, quota, attribution requirement, and retention policy.
2. Use HTTPS and exact host allowlists. Add an explicit production road-provider approval only after the agreement is in place.
3. Keep request limits compatible with the provider agreement and SAFE PATH's resource bounds.
4. Update visible attribution and this guide when provider terms change.
5. Run the deterministic mocked provider tests, then perform the manual live smoke test in [DEPLOYMENT.md](DEPLOYMENT.md#optional-live-smoke-test):

```bash
DJANGO_DEBUG=True python manage.py test \
  web.test_osm_graph web.test_geocode_api --verbosity 2
```
6. Verify that logs and responses contain no credentials, query strings, or upstream response text.
