package org.matsim.manchester;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.NetworkUtils;

import org.matsim.core.router.DijkstraFactory;
import org.matsim.core.router.util.LeastCostPathCalculator;
//import org.matsim.core.router.util.TravelDisutility;
import org.matsim.core.router.util.TravelTime;
import org.matsim.core.scenario.ScenarioUtils;

//import org.matsim.vehicles.Vehicle;


//import java.io.*;
import java.util.*;
import java.util.stream.Collectors;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.List;
import java.util.Map;
import java.text.SimpleDateFormat; // Required import
import java.util.Date;             // Required import

/**
 * Manchester Flood-Aware Routing
 *
 * Static MDM-style routing:
 * - Fixed OD
 * - Multi-objective cost (time vs flood exposure)
 * - Local weight optimization
 *
 */
public class ManchesterFloodRouting {

    /* ===================== FILE PATHS ===================== */

    private static final String BASE_PATH =
            "/mnt/usb-TOSHIBA_EXTERNAL_USB_20241114001799F-0:0-part1/gurban/input_data/";

    private static final String NETWORK_FILE = BASE_PATH + "network_base.xml";
    private static final String ENRICHED_NETWORK_FILE = BASE_PATH + "network_with_flood_data.xml";
    private static final String PLANS_FILE   = BASE_PATH + "2021.output_plans.xml.gz";
    // directory containing multiple .shp files
//    private static final String FLOOD_DIR    = BASE_PATH + "flooding_risk_manchester/";

    private static final String OUTPUT_DIR =
            "/home/admin/IdeaProjects/matsim-project-gurban/output/";


    /* ===================== SETTINGS ===================== */

    private static final List<String> MODES = Arrays.asList("walk", "bike");
    private static final int MAX_PERSONS_PER_MODE = 5000;
    // Depth-dependent speed tables (midpoint-based)
    // Pedestrian: Bernardini (2020) + Li (2025); ≥0.6 m impassable
    private static final NavigableMap<Double, Double> PED_SPEED_MAP = new TreeMap<>();
    static {
        PED_SPEED_MAP.put(0.0, 1.27);   // dry (Bernardini dry free-flow limit)
        PED_SPEED_MAP.put(0.1, 1.03);   // extent-only, midpoint 0.1 m (Li 2025)
        PED_SPEED_MAP.put(0.2, 0.85);   // midpoint 0.25 m (interpolated Bernardini 0.2–0.3)
        PED_SPEED_MAP.put(0.3, 0.78);   // midpoint 0.45 m (Bernardini ~0.5 m)
    }

    // Cyclist: Toda et al. (2016) — no-flow empirical data; ≥0.6 m impassable
    private static final NavigableMap<Double, Double> BIKE_SPEED_MAP = new TreeMap<>();
    static {
        BIKE_SPEED_MAP.put(0.0, 4.2);    // dry (~15 km/h utility cycling)
        BIKE_SPEED_MAP.put(0.1, 2.04);   // [0.1,0.2) midpoint 15 cm, interp Toda 10→20 cm
        BIKE_SPEED_MAP.put(0.2, 1.76);   // [0.2,0.3) midpoint 25 cm, interp Toda 20→30 cm
        BIKE_SPEED_MAP.put(0.3, 1.31);   // [0.3,0.6) midpoint 45 cm, interp Toda 40→50 cm
    }

    private static final Map<String, NavigableMap<Double, Double>> MODE_SPEED_MAPS = Map.of(
            "walk", PED_SPEED_MAP,
            "bike", BIKE_SPEED_MAP
    );

    private static final Map<String, Double> MODE_IMPASSABLE_DEPTH = Map.of(
            "walk", 0.6,
            "bike", 0.6
    );

    private static final double IMPASSABLE_SPEED = 0.001; // m/s — makes link cost near-infinite

    /**
     * Returns depth-dependent speed for a given mode and flood depth.
     */
    private static double getFloodSpeed(String mode, double depth) {
        double impassableDepth = MODE_IMPASSABLE_DEPTH.get(mode);
        if (depth >= impassableDepth - 1e-9) return IMPASSABLE_SPEED;

        NavigableMap<Double, Double> speedMap = MODE_SPEED_MAPS.get(mode);
        Map.Entry<Double, Double> entry = speedMap.floorEntry(depth);
        if (entry == null) entry = speedMap.firstEntry();
        return entry.getValue();
    }



    /* ===================== MAIN ===================== */

    public static void main(String[] args) throws IOException {

        System.out.println("\n=== Manchester Flood-Aware Routing ===\n");

        /* ---- 1. Check which network to use BEFORE creating config ---- */
        File enrichedNetworkFile = new File(ENRICHED_NETWORK_FILE);
        String networkToLoad;
        boolean needsFloodProcessing;

        if (enrichedNetworkFile.exists()) {
            System.out.println("Found enriched network - will load directly...");
            networkToLoad = ENRICHED_NETWORK_FILE;
            needsFloodProcessing = false;
        } else {
            System.out.println("No enriched network found - will load base network...");
            networkToLoad = NETWORK_FILE;
            needsFloodProcessing = true;
        }

        /* ---- 2. Load MATSim scenario (network + population) ---- */

        Config config = ConfigUtils.createConfig();
        config.network().setInputFile(networkToLoad);
        config.plans().setInputFile(PLANS_FILE);
        Scenario scenario = ScenarioUtils.loadScenario(config);

        Network network = scenario.getNetwork();
        Population population = scenario.getPopulation();

        System.out.println("Network: " + network.getNodes().size()
                + " nodes, " + network.getLinks().size() + " links");
        System.out.println("Population: " + population.getPersons().size() + " persons\n");

        /* ---- . Attach flood risk to links ---- */
//        FloodDataLoader.loadFloodData(network);


        /* ---- 3. Extract OD trips (subset) ---- */

        List<PersonTrip> trips = new ArrayList<>();

        for (String mode : MODES) {
            List<PersonTrip> modeTrips = extractTrips(
                    population, network, mode, MAX_PERSONS_PER_MODE
            );
            trips.addAll(modeTrips);
            System.out.println("Loaded " + modeTrips.size() + " " + mode + " trips");
        }

        System.out.println("\nTotal trips: " + trips.size() + "\n");

        /* ---- 4. Route dry + flood, export raw route CSVs ---- */

        Map<String, List<PersonTrip>> tripsByMode =
                trips.stream().collect(Collectors.groupingBy(t -> t.mode));

        String timeStamp = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new Date());
        String dynamicOutputDir = OUTPUT_DIR + "results_" + timeStamp + "/";
        new File(dynamicOutputDir).mkdirs();

        for (String mode : MODES) {
            List<PersonTrip> modeTrips = tripsByMode.get(mode);
            if (modeTrips == null || modeTrips.isEmpty()) continue;
            System.out.println("\n=== " + mode + ": " + modeTrips.size() + " trips ===");

            /* Dry routing (no rain — evaluate at dry speed, zero exposure) */
            System.out.println("  Routing dry...");
            normalizeDry(network, mode);
            double drySpeed = getFloodSpeed(mode, 0.0);
            List<RouteData> dryRoutes = new ArrayList<>();
            for (PersonTrip trip : modeTrips) {
                try {
                    LeastCostPathCalculator.Path p = doRoute(network, trip, mode);
                    if (p == null) continue;
                    List<String> nodes = extractNodePath(p);
                    List<String> linkIds = extractLinkIds(p);
                    double dryTime = 0;
                    for (Link l : p.links) dryTime += l.getLength() / drySpeed;
                    dryRoutes.add(new RouteData(trip, nodes, linkIds, dryTime, 0.0));
                } catch (Exception e) {
                    System.err.println("  dry failed: " + trip.personId + ": " + e.getMessage());
                }
            }

            /* Flood-aware routing */
            System.out.println("  Routing flood-aware...");
            normalizeExposureAndTimes(network, mode);
            List<RouteData> floodRoutes = new ArrayList<>();
            for (PersonTrip trip : modeTrips) {
                try {
                    LeastCostPathCalculator.Path p = doRoute(network, trip, mode);
                    if (p == null) continue;
                    double[] te = evaluateFloodOnPath(p, mode);
                    floodRoutes.add(new RouteData(trip,
                            extractNodePath(p), extractLinkIds(p), te[0], te[1]));
                } catch (Exception e) {
                    System.err.println("  flood failed: " + trip.personId + ": " + e.getMessage());
                }
            }

            exportRoutes(dryRoutes, dynamicOutputDir + "routes_dry_" + mode + ".csv");
            exportRoutes(floodRoutes, dynamicOutputDir + "routes_flood_" + mode + ".csv");
        }

        /* Also export link flood depths for Python analysis */
        exportLinkDepths(network, dynamicOutputDir + "link_flood_depths.csv");

        System.out.println("\n=== DONE ===");
        System.out.println("Output: " + dynamicOutputDir);
    }

    /* ===================== CORE METHODS ===================== */

    /** Dry normalization: treat all flood_depth as 0. */
    private static void normalizeDry(Network network, String mode) {
        double maxTime = 0.0;
        double drySpeed = getFloodSpeed(mode, 0.0);
        for (Link link : network.getLinks().values()) {
            double time = link.getLength() / drySpeed;
            maxTime = Math.max(maxTime, time);
        }
        if (maxTime == 0.0) maxTime = 1.0;
        for (Link link : network.getLinks().values()) {
            link.getAttributes().putAttribute("travel_time_norm",
                    link.getLength() / drySpeed / maxTime);
            link.getAttributes().putAttribute("personal_exposure_norm", 0.0);
        }
    }

    /**
     * Normalizes network attributes using depth-dependent speed for the given mode.
     * Links at or above impassable depth get max cost (1.0).
     */
    private static void normalizeExposureAndTimes(Network network, String mode) {
        double impassableDepth = MODE_IMPASSABLE_DEPTH.get(mode);
        double maxTime = 0.0;
        double maxExposure = 0.0;

        for (Link link : network.getLinks().values()) {
            double depth = (Double) link.getAttributes().getAttribute("flood_depth");
            if (depth >= impassableDepth - 1e-9) continue;
            double speed = getFloodSpeed(mode, depth);
            double time = link.getLength() / speed;
            maxTime = Math.max(maxTime, time);
            maxExposure = Math.max(maxExposure, depth * time);
        }

        if (maxTime == 0.0) {
            System.err.println("WARNING: Max time is zero.");
            maxTime = 1.0;
        }

        for (Link link : network.getLinks().values()) {
            double depth = (Double) link.getAttributes().getAttribute("flood_depth");
            if (depth >= impassableDepth - 1e-9) {
                link.getAttributes().putAttribute("travel_time_norm", 1.0);
                link.getAttributes().putAttribute("personal_exposure_norm", 1.0);
            } else {
                double speed = getFloodSpeed(mode, depth);
                double time = link.getLength() / speed;
                link.getAttributes().putAttribute("travel_time_norm", time / maxTime);
                link.getAttributes().putAttribute("personal_exposure_norm",
                        maxExposure == 0.0 ? 0.0 : (depth * time) / maxExposure);
            }
        }
        System.out.printf("  flood-normalized (impassable ≥ %.1f m, maxTime=%.2fs, maxExp=%.2f)\n",
                impassableDepth, maxTime, maxExposure);
    }

    /** Evaluate flood cost on a MATSim Path object. */
    private static double[] evaluateFloodOnPath(LeastCostPathCalculator.Path path, String mode) {
        double totalTime = 0.0;
        double totalExp = 0.0;
        for (Link link : path.links) {
            Object depthObj = link.getAttributes().getAttribute("flood_depth");
            double depth = (depthObj instanceof Double) ? (Double) depthObj : 0.0;
            double speed = getFloodSpeed(mode, depth);
            totalTime += link.getLength() / speed;
            totalExp += depth * link.getLength() / speed;
        }
        return new double[]{totalTime, totalExp};
    }

    private static List<PersonTrip> extractTrips(
            Population population,
            Network network,
            String mode,
            int maxPersons) {

        List<PersonTrip> trips = new ArrayList<>();
        int count = 0;

        for (Person person : population.getPersons().values()) {
            if (count >= maxPersons) break;

            Plan plan = person.getSelectedPlan();
            if (plan == null) continue;

            for (int i = 0; i < plan.getPlanElements().size(); i++) {
                if (!(plan.getPlanElements().get(i) instanceof Leg)) continue;

                Leg leg = (Leg) plan.getPlanElements().get(i);
                if (!leg.getMode().equals(mode)) continue;

                Activity o = (Activity) plan.getPlanElements().get(i - 1);
                Activity d = (Activity) plan.getPlanElements().get(i + 1);

                Node from = NetworkUtils.getNearestNode(network, o.getCoord());
                Node to   = NetworkUtils.getNearestNode(network, d.getCoord());

                if (from != null && to != null && !from.equals(to)) {
                    trips.add(new PersonTrip(
                            person.getId().toString(), mode, from, to));
                    count++;
                    break;
                }
            }
        }
        return trips;
    }

    /** Route and return the raw MATSim Path */
    private static LeastCostPathCalculator.Path doRoute(Network network, PersonTrip trip, String mode) {
        FloodAwareDisutility disutility = new FloodAwareDisutility(1.0);
        double drySpeed = getFloodSpeed(mode, 0.0);
        TravelTime travelTime = (l, t, p, v) -> l.getLength() / drySpeed;
        LeastCostPathCalculator router =
                new DijkstraFactory().createPathCalculator(network, disutility, travelTime);
        return router.calcLeastCostPath(trip.fromNode, trip.toNode, 0, null, null);
    }

    private static List<String> extractNodePath(LeastCostPathCalculator.Path path) {
        List<String> nodes = new ArrayList<>();
        nodes.add(path.nodes.get(0).getId().toString());
        for (Link l : path.links) {
            nodes.add(l.getToNode().getId().toString());
        }
        return nodes;
    }

    private static List<String> extractLinkIds(LeastCostPathCalculator.Path path) {
        List<String> ids = new ArrayList<>();
        for (Link l : path.links) {
            ids.add(l.getId().toString());
        }
        return ids;
    }


    /* ===================== OUTPUT ===================== */

    private static void exportRoutes(List<RouteData> routes, String file) throws IOException {
        try (PrintWriter pw = new PrintWriter(new FileWriter(file))) {
            pw.println("person,mode,origin,destination,path,links,travel_time,flood_exposure");
            for (RouteData r : routes) {
                String pathStr = "[" + String.join(", ", r.nodes) + "]";
                String linksStr = "[" + String.join(", ", r.linkIds) + "]";
                pw.printf("%s,%s,%s,%s,\"%s\",\"%s\",%.2f,%.6f%n",
                        r.personId, r.mode, r.origin, r.dest,
                        pathStr, linksStr,
                        r.travelTime, r.exposure);
            }
        }
        System.out.println("  Wrote: " + file);
    }

    private static void exportLinkDepths(Network network, String file) throws IOException {
        try (PrintWriter pw = new PrintWriter(new FileWriter(file))) {
            pw.println("link_id,from_node,to_node,length,flood_depth");
            for (Link link : network.getLinks().values()) {
                Object depthObj = link.getAttributes().getAttribute("flood_depth");
                double depth = (depthObj instanceof Double) ? (Double) depthObj : 0.0;
                pw.printf("%s,%s,%s,%.2f,%.4f%n",
                        link.getId().toString(),
                        link.getFromNode().getId().toString(),
                        link.getToNode().getId().toString(),
                        link.getLength(), depth);
            }
        }
        System.out.println("  Wrote: " + file);
    }


    /* ===================== DATA CLASSES ===================== */

    static class RouteData {
        final String personId;
        final String mode;
        final String origin;
        final String dest;
        final List<String> nodes;
        final List<String> linkIds;
        final double travelTime;
        final double exposure;

        RouteData(PersonTrip trip, List<String> nodes, List<String> linkIds,
                  double travelTime, double exposure) {
            this.personId = trip.personId;
            this.mode = trip.mode;
            this.origin = trip.fromNode.getId().toString();
            this.dest = trip.toNode.getId().toString();
            this.nodes = nodes;
            this.linkIds = linkIds;
            this.travelTime = travelTime;
            this.exposure = exposure;
        }
    }

    static class PersonTrip {
        final String personId;
        final String mode;
        final Node fromNode;
        final Node toNode;

        PersonTrip(String id, String mode, Node from, Node to) {
            this.personId = id;
            this.mode = mode;
            this.fromNode = from;
            this.toNode = to;
        }
    }
}
