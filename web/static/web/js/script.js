const ROUTES_URL = "/api/routes/";
const GEOCODE_URL = "/api/geocode/";
const HEATMAP_URL = "/api/safety-heatmap/";
const ROUTE_COLORS = ["#087f5b", "#2563eb", "#7c3aed", "#ea580c"];
const CARTO_API_KEY = JSON.parse(
    document.getElementById("carto-api-key")?.textContent || '""',
);
const OSM_TILE_CONFIG = {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};
const TILE_CONFIG = {
    light: OSM_TILE_CONFIG,
    dark: CARTO_API_KEY
        ? {
              url: `https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=${encodeURIComponent(CARTO_API_KEY)}`,
              attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attribution/">CARTO</a>',
          }
        : OSM_TILE_CONFIG,
};
const DEFAULT_START = { lat: 28.474780644693578, lon: 77.47638190820159 };

const state = {
    destination: null,
    heatData: null,
    heatLayer: null,
    heatmapEnabled: false,
    heatmapLoading: false,
    map: null,
    origin: null,
    routeColors: new Map(),
    routeLayerGroup: null,
    routeLayers: new Map(),
    routes: [],
    selectedRouteId: null,
    selectionMode: "destination",
    theme: document.documentElement.dataset.theme || "light",
    tileLayer: null,
};

const elements = {
    clearButton: document.getElementById("clear"),
    comparisonBody: document.getElementById("comparison-body"),
    comparisonPanel: document.getElementById("comparison-panel"),
    directionsButton: document.getElementById("directions-btn"),
    emptyState: document.getElementById("route-empty-state"),
    fromInput: document.getElementById("from-input"),
    heatmapStatus: document.getElementById("heatmap-status"),
    heatmapToggle: document.getElementById("heatmap-toggle"),
    loadingState: document.getElementById("route-loading-state"),
    mapStatus: document.getElementById("map-status"),
    routeCount: document.getElementById("route-count"),
    routeForm: document.getElementById("route-form"),
    routeLegend: document.getElementById("route-legend"),
    routeLegendList: document.getElementById("route-legend-list"),
    routeList: document.getElementById("route-list"),
    routeStatus: document.getElementById("route-status"),
    setDestination: document.getElementById("set-destination"),
    setStart: document.getElementById("set-start"),
    swapButton: document.getElementById("swap-locations"),
    themeLabel: document.querySelector("[data-theme-label]"),
    themeToggle: document.getElementById("theme-toggle"),
    toInput: document.getElementById("to-input"),
};

state.map = L.map("map").setView([28.5639, 77.219], 11);
state.map.createPane("routePane").style.zIndex = 450;
state.routeLayerGroup = L.layerGroup().addTo(state.map);
state.tileLayer = createTileLayer(state.theme).addTo(state.map);

function createTileLayer(theme) {
    const config = TILE_CONFIG[theme] || TILE_CONFIG.light;
    return L.tileLayer(config.url, {
        attribution: config.attribution,
        maxZoom: 19,
        subdomains: config.subdomains || "abc",
    });
}

function updateTileLayer(theme) {
    if (state.tileLayer) {
        state.map.removeLayer(state.tileLayer);
    }
    state.tileLayer = createTileLayer(theme).addTo(state.map);
}

function applyTheme(theme, persist = true) {
    const nextTheme = theme === "dark" ? "dark" : "light";
    state.theme = nextTheme;
    document.documentElement.dataset.theme = nextTheme;
    elements.themeToggle.setAttribute("aria-pressed", String(nextTheme === "dark"));
    elements.themeToggle.setAttribute(
        "aria-label",
        `Switch to ${nextTheme === "dark" ? "light" : "dark"} theme`,
    );
    elements.themeLabel.textContent = nextTheme === "dark" ? "Light" : "Dark";

    if (state.tileLayer) {
        updateTileLayer(nextTheme);
    }

    if (persist) {
        try {
            localStorage.setItem("safepath-theme", nextTheme);
        } catch {
            return;
        }
    }
}

function setStatus(message, tone = "neutral") {
    const pill = document.createElement("span");
    pill.className = "status-pill";
    pill.dataset.tone = tone;
    pill.textContent = message;
    elements.routeStatus.replaceChildren(pill);
}

function setMapStatus(message) {
    elements.mapStatus.textContent = message;
}

async function fetchJson(url, options = {}, timeoutMilliseconds = 15000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMilliseconds);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.detail || `Request failed with status ${response.status}.`);
        }
        return data;
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("The request took too long. Please try again.", {
                cause: error,
            });
        }
        throw error;
    } finally {
        window.clearTimeout(timeout);
    }
}

function createMarkerIcon(type) {
    return L.divIcon({
        className: "",
        html: `<span class="map-marker map-marker-${type}"></span>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });
}

function setMarker(type, location) {
    const key = `${type}Marker`;
    const icon = createMarkerIcon(type);
    const marker = L.marker([location.lat, location.lon], {
        icon,
        title: type === "origin" ? "Starting location" : "Destination",
        keyboard: true,
    }).addTo(state.map);

    if (state[key]) {
        state.map.removeLayer(state[key]);
    }
    state[key] = marker;
}

function clearMarker(type) {
    const key = `${type}Marker`;
    if (state[key]) {
        state.map.removeLayer(state[key]);
        state[key] = null;
    }
}

function setSelectionMode(mode) {
    state.selectionMode = mode;
    elements.setStart.setAttribute("aria-pressed", String(mode === "start"));
    elements.setDestination.setAttribute("aria-pressed", String(mode === "destination"));
    setMapStatus(
        mode === "start"
            ? "Click the map to set your starting location."
            : "Click the map to set your destination.",
    );
}

function formatDistance(distanceMeters) {
    if (!Number.isFinite(distanceMeters)) {
        return "Not available";
    }
    if (distanceMeters < 1000) {
        return `${Math.round(distanceMeters)} m`;
    }
    return `${(distanceMeters / 1000).toFixed(distanceMeters < 10000 ? 1 : 0)} km`;
}

function formatDuration(durationSeconds) {
    if (!Number.isFinite(durationSeconds)) {
        return "Not available";
    }
    const minutes = Math.max(1, Math.round(durationSeconds / 60));
    if (minutes < 60) {
        return `${minutes} min`;
    }
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return remainingMinutes ? `${hours} hr ${remainingMinutes} min` : `${hours} hr`;
}

function formatLabel(label) {
    if (label === "safest") {
        return "Lowest modeled risk";
    }
    return label.charAt(0).toUpperCase() + label.slice(1);
}

function routeTitle(route) {
    if (!route.labels.length) {
        return `Route ${route.id.replace("route-", "")}`;
    }
    return `${route.labels.map(formatLabel).join(" + ")} route`;
}

function routeColor(routeId) {
    return state.routeColors.get(routeId) || ROUTE_COLORS[0];
}

function assignRouteColors(routes) {
    state.routeColors = new Map(
        routes.map((route, index) => [route.id, ROUTE_COLORS[index % ROUTE_COLORS.length]]),
    );
}

function riskLabel(route) {
    if (!route.risk_data_available || !route.risk_level) {
        return "Not rated";
    }
    return formatLabel(route.risk_level);
}

function recordScoreLabel(route) {
    if (!route.risk_data_available || route.safety_score === null) {
        return "Not rated";
    }
    return `${route.safety_score}/100`;
}

function coverageLabel(route) {
    if (!Number.isFinite(route.incident_coverage_ratio)) {
        return "Record-proximity coverage unavailable.";
    }
    if (route.risk_data_available) {
        const percentage = Math.round(route.incident_coverage_ratio * 100);
        return `Record-proximity coverage: ${percentage}% (all route edges covered).`;
    }
    const percentage = Math.min(
        99,
        Math.floor(route.incident_coverage_ratio * 100),
    );
    return `Record-proximity coverage: ${percentage}%. Safety estimate unavailable because route coverage is incomplete.`;
}

function createBadge(label) {
    const badge = document.createElement("span");
    const toneClasses = {
        safest: "bg-accent-soft text-accent-strong",
        shortest: "bg-surface-strong text-ink",
        balanced: "bg-warning-soft text-warning",
        alternative: "bg-surface-strong text-ink-muted",
    };
    badge.className = `rounded-full px-2 py-0.5 text-[0.65rem] font-extrabold ${toneClasses[label] || toneClasses.alternative}`;
    badge.textContent = formatLabel(label);
    return badge;
}

function renderRouteCards(routes) {
    const template = document.getElementById("route-card-template");
    const fragment = document.createDocumentFragment();

    routes.forEach((route) => {
        const card = template.content.firstElementChild.cloneNode(true);
        const button = card.querySelector("[data-route-select]");
        const badges = card.querySelector("[data-route-badges]");

        card.dataset.routeId = route.id;
        button.dataset.routeId = route.id;
        card.querySelector(".route-swatch").style.backgroundColor = routeColor(route.id);
        route.labels.forEach((label) => badges.appendChild(createBadge(label)));
        card.querySelector("[data-route-title]").textContent = routeTitle(route);
        card.querySelector("[data-route-distance]").textContent = formatDistance(route.distance_meters);
        card.querySelector("[data-route-duration]").textContent = formatDuration(route.duration_seconds);
        card.querySelector("[data-route-safety]").textContent = recordScoreLabel(route);
        card.querySelector("[data-route-risk]").textContent = riskLabel(route);
        card.querySelector("[data-route-explanation]").textContent = route.explanation;
        card.querySelector("[data-route-coverage]").textContent = coverageLabel(route);
        card.querySelector("[data-route-algorithm]").textContent =
            route.algorithm === "modified_astar" ? "Modified A* objective" : "Dijkstra objective";
        button.addEventListener("click", () => selectRoute(route.id));
        fragment.appendChild(card);
    });

    elements.routeList.replaceChildren(fragment);
    elements.emptyState.classList.add("hidden");
    updateRouteSelection();
}

function renderComparison(routes) {
    const template = document.getElementById("comparison-row-template");
    const fragment = document.createDocumentFragment();

    routes.forEach((route) => {
        const row = template.content.firstElementChild.cloneNode(true);
        row.querySelector("[data-comparison-route]").textContent = routeTitle(route);
        row.querySelector("[data-comparison-distance]").textContent = formatDistance(route.distance_meters);
        row.querySelector("[data-comparison-duration]").textContent = formatDuration(route.duration_seconds);
        row.querySelector("[data-comparison-safety]").textContent = recordScoreLabel(route);
        row.querySelector("[data-comparison-risk]").textContent = riskLabel(route);
        fragment.appendChild(row);
    });

    elements.comparisonBody.replaceChildren(fragment);
    elements.comparisonPanel.classList.toggle("hidden", routes.length === 0);
}

function renderRouteLegend(routes) {
    const fragment = document.createDocumentFragment();

    routes.forEach((route) => {
        const item = document.createElement("span");
        const swatch = document.createElement("span");
        const label = document.createElement("span");

        item.className = "flex items-center gap-2";
        swatch.className = "size-2.5 shrink-0 rounded-full";
        swatch.style.backgroundColor = routeColor(route.id);
        label.textContent = routeTitle(route);
        item.append(swatch, label);
        fragment.appendChild(item);
    });

    elements.routeLegendList.replaceChildren(fragment);
    elements.routeLegend.hidden = routes.length === 0;
}

function updateRouteSelection() {
    elements.routeList.querySelectorAll("[data-route-card]").forEach((card) => {
        const selected = card.dataset.routeId === state.selectedRouteId;
        card.dataset.selected = String(selected);
        const button = card.querySelector("[data-route-select]");
        const action = card.querySelector("[data-route-action]");
        button.setAttribute("aria-pressed", String(selected));
        action.textContent = selected ? "Selected" : "View route";
    });
}

function selectRoute(routeId, fitBounds = true) {
    const route = state.routes.find((candidate) => candidate.id === routeId);
    if (!route) {
        return;
    }

    state.selectedRouteId = routeId;
    updateRouteSelection();
    updateRouteLayerStyles();

    const layer = state.routeLayers.get(routeId);
    if (fitBounds && layer) {
        state.map.fitBounds(layer.getBounds(), {
            padding: [48, 48],
            maxZoom: 17,
        });
    }
}

function drawRouteLayers(routes) {
    state.routeLayerGroup.clearLayers();
    state.routeLayers.clear();

    routes.forEach((route) => {
        const points = route.geometry.map(([lat, lon]) => [lat, lon]);
        if (!points.length) {
            return;
        }

        const layer = L.polyline(points, {
            color: routeColor(route.id),
            weight: 5,
            opacity: 0.52,
            lineCap: "round",
            lineJoin: "round",
            pane: "routePane",
        });
        layer.bindTooltip(routeTitle(route), { sticky: true });
        state.routeLayers.set(route.id, layer);
        state.routeLayerGroup.addLayer(layer);
    });

    updateRouteLayerStyles();
}

function updateRouteLayerStyles() {
    state.routeLayers.forEach((layer, routeId) => {
        const selected = routeId === state.selectedRouteId;
        layer.setStyle({
            color: routeColor(routeId),
            opacity: selected ? 1 : 0.52,
            weight: selected ? 8 : 5,
        });
        if (selected) {
            layer.bringToFront();
        }
    });
}

function heatRadiusPixels() {
    if (!state.heatData) {
        return 25;
    }
    const center = state.map.getCenter();
    const metersPerPixel =
        (156543.03392 * Math.cos((center.lat * Math.PI) / 180)) /
        2 ** state.map.getZoom();
    return Math.max(
        4,
        Math.min(60, state.heatData.radius_meters / metersPerPixel),
    );
}

function updateHeatRadius() {
    if (state.heatLayer) {
        state.heatLayer.setOptions({ radius: heatRadiusPixels() });
    }
}

async function toggleHeatmap() {
    if (state.heatmapEnabled) {
        state.map.removeLayer(state.heatLayer);
        state.heatLayer = null;
        state.heatmapEnabled = false;
        elements.heatmapToggle.setAttribute("aria-pressed", "false");
        elements.heatmapStatus.textContent = "Heatmap off";
        return;
    }
    if (state.heatmapLoading) {
        return;
    }
    if (typeof L.heatLayer !== "function") {
        elements.heatmapStatus.textContent = "Heatmap could not be loaded.";
        return;
    }

    state.heatmapLoading = true;
    elements.heatmapToggle.disabled = true;
    elements.heatmapStatus.textContent = "Loading unverified demonstration incident records...";

    try {
        const data = state.heatData || (await fetchJson(HEATMAP_URL, {}, 10000));
        state.heatData = data;
        if (!data.points.length) {
            elements.heatmapStatus.textContent = "No unverified demonstration incident records are available.";
            return;
        }

        const points = data.points.map((point) => [
            point.lat,
            point.lon,
            point.intensity,
        ]);
        state.heatLayer = L.heatLayer(points, {
            blur: 0.35,
            gradient: {
                0.2: "#fef3c7",
                0.45: "#fbbf24",
                0.7: "#fb7185",
                1: "#b42318",
            },
            max: 1,
            minOpacity: 0.3,
            radius: heatRadiusPixels(),
        }).addTo(state.map);
        state.heatmapEnabled = true;
        elements.heatmapToggle.setAttribute("aria-pressed", "true");
        elements.heatmapStatus.textContent = `${data.record_count} unverified demonstration records, ${data.radius_meters} m influence radius`;
    } catch (error) {
        elements.heatmapStatus.textContent = error.message;
    } finally {
        state.heatmapLoading = false;
        elements.heatmapToggle.disabled = false;
    }
}

function setLoading(isLoading) {
    elements.loadingState.classList.toggle("hidden", !isLoading);
    elements.loadingState.classList.toggle("grid", isLoading);
    elements.directionsButton.disabled = isLoading;
    elements.directionsButton.querySelector("[data-button-label]").textContent = isLoading
        ? "Finding routes"
        : "Find routes";
}

async function requestRoutes() {
    if (!state.origin || !state.destination) {
        setStatus("Choose both a starting location and a destination.", "warning");
        return;
    }

    setLoading(true);
    elements.emptyState.classList.add("hidden");
    setStatus("Loading road data and comparing routes...");
    setMapStatus("Calculating route options...");

    const query = new URLSearchParams({
        start_lat: String(state.origin.lat),
        start_lon: String(state.origin.lon),
        end_lat: String(state.destination.lat),
        end_lon: String(state.destination.lon),
    });

    try {
        const data = await fetchJson(`${ROUTES_URL}?${query}`, {}, 45000);
        state.routes = data.routes;
        state.selectedRouteId = null;
        assignRouteColors(state.routes);

        drawRouteLayers(state.routes);
        renderRouteCards(state.routes);
        renderComparison(state.routes);
        renderRouteLegend(state.routes);
        elements.routeCount.textContent = `${data.route_count} ${data.route_count === 1 ? "route" : "routes"}`;

        const initialRoute =
            state.routes.find((route) => route.labels.includes("safest")) || state.routes[0];
        if (initialRoute) {
            selectRoute(initialRoute.id);
        }

        setStatus(`${data.route_count} route ${data.route_count === 1 ? "option" : "options"} ready to compare.`, "success");
        setMapStatus("Route options calculated. Select a card to change the highlighted route.");
    } catch (error) {
        state.routes = [];
        state.selectedRouteId = null;
        drawRouteLayers([]);
        renderRouteLegend([]);
        elements.routeList.replaceChildren();
        elements.comparisonBody.replaceChildren();
        elements.comparisonPanel.classList.add("hidden");
        elements.routeCount.textContent = "0 routes";
        elements.emptyState.classList.remove("hidden");
        setStatus(error.message, "error");
        setMapStatus("Routes could not be loaded.");
    } finally {
        setLoading(false);
    }
}

async function geocode(query) {
    const data = await fetchJson(`${GEOCODE_URL}?q=${encodeURIComponent(query)}`, {}, 10000);
    return data.results[0] || null;
}

async function resolveLocation(input, existingLocation) {
    const text = input.value.trim();
    const mapLabels = new Set(["Current location", "Sample starting point", "Map point"]);
    if (existingLocation && mapLabels.has(text)) {
        return existingLocation;
    }
    return geocode(text);
}

async function searchRoutes(event) {
    event.preventDefault();
    const fromText = elements.fromInput.value.trim();
    const toText = elements.toInput.value.trim();

    if (!fromText || !toText) {
        setStatus("Enter both a starting location and a destination.", "warning");
        return;
    }

    elements.directionsButton.disabled = true;
    elements.directionsButton.querySelector("[data-button-label]").textContent = "Finding locations";
    setStatus("Resolving both locations...");

    try {
        const [origin, destination] = await Promise.all([
            resolveLocation(elements.fromInput, state.origin),
            resolveLocation(elements.toInput, state.destination),
        ]);

        if (!origin || !destination) {
            const missing = !origin && !destination ? "both locations" : !origin ? "the starting location" : "the destination";
            throw new Error(`Could not find ${missing}. Try a more specific place name.`);
        }

        state.origin = origin;
        state.destination = destination;
        elements.fromInput.value = origin.label || fromText;
        elements.toInput.value = destination.label || toText;
        setMarker("origin", origin);
        setMarker("destination", destination);
        state.map.fitBounds(
            L.latLngBounds(
                [origin.lat, origin.lon],
                [destination.lat, destination.lon],
            ),
            { padding: [48, 48], maxZoom: 16 },
        );
        await requestRoutes();
    } catch (error) {
        setStatus(error.message, "error");
        setMapStatus("Locations could not be resolved.");
    } finally {
        elements.directionsButton.disabled = false;
        elements.directionsButton.querySelector("[data-button-label]").textContent = "Find routes";
    }
}

function useCurrentLocation(position) {
    state.origin = {
        lat: position.coords.latitude,
        lon: position.coords.longitude,
    };
    state.destination = null;
    elements.fromInput.value = "Current location";
    setMarker("origin", state.origin);
    state.map.setView([state.origin.lat, state.origin.lon], 14);
    setSelectionMode("destination");
    setStatus("Starting location acquired. Choose a destination.");
    setMapStatus("Starting location acquired. Choose a destination.");
}

function useDefaultLocation() {
    state.origin = { ...DEFAULT_START };
    state.destination = null;
    elements.fromInput.value = "Sample starting point";
    setMarker("origin", state.origin);
    state.map.setView([state.origin.lat, state.origin.lon], 14);
    setSelectionMode("destination");
    setStatus("Location unavailable. Using the sample start. Change it any time.", "warning");
    setMapStatus("Sample start selected. Choose a destination.");
}

function clearAll() {
    state.destination = null;
    state.origin = null;
    state.routes = [];
    state.selectedRouteId = null;
    clearMarker("origin");
    clearMarker("destination");
    drawRouteLayers([]);
    renderRouteLegend([]);
    elements.fromInput.value = "";
    elements.toInput.value = "";
    elements.routeList.replaceChildren();
    elements.comparisonBody.replaceChildren();
    elements.comparisonPanel.classList.add("hidden");
    elements.routeCount.textContent = "0 routes";
    setStatus("Locations and routes cleared.", "success");
    setSelectionMode("destination");
    state.map.setView([28.5639, 77.219], 11);
}

function swapLocations() {
    const fromValue = elements.fromInput.value;
    elements.fromInput.value = elements.toInput.value;
    elements.toInput.value = fromValue;

    if (state.origin && state.destination) {
        const origin = state.origin;
        state.origin = state.destination;
        state.destination = origin;
        setMarker("origin", state.origin);
        setMarker("destination", state.destination);
        requestRoutes();
    }
}

state.map.on("zoomend", updateHeatRadius);
state.map.on("click", (event) => {
    const location = { lat: event.latlng.lat, lon: event.latlng.lng };

    if (state.selectionMode === "start") {
        state.origin = location;
        elements.fromInput.value = "Map point";
        setMarker("origin", location);
        setSelectionMode("destination");
        setStatus("Starting location selected. Choose a destination.");
    } else {
        state.destination = location;
        elements.toInput.value = "Map point";
        setMarker("destination", location);
        setStatus("Destination selected. Finding routes...");
    }

    if (state.origin && state.destination) {
        requestRoutes();
    }
});

elements.routeForm.addEventListener("submit", searchRoutes);
elements.clearButton.addEventListener("click", clearAll);
elements.heatmapToggle.addEventListener("click", toggleHeatmap);
elements.setStart.addEventListener("click", () => setSelectionMode("start"));
elements.setDestination.addEventListener("click", () => setSelectionMode("destination"));
elements.swapButton.addEventListener("click", swapLocations);
elements.themeToggle.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
});

applyTheme(state.theme, false);

if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        useCurrentLocation,
        useDefaultLocation,
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 300000 },
    );
} else {
    useDefaultLocation();
}
