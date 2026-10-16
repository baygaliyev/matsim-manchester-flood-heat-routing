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
import org.matsim.core.router.util.TravelTime;
import org.matsim.core.scenario.ScenarioUtils;

import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;

public class ManchesterHeatRouting {

    private static final String BASE_PATH =
            "/mnt/usb-TOSHIBA_EXTERNAL_USB_20241114001799F-0:0-part1/gurban/input_data/";
    private static final String NETWORK_FILE = BASE_PATH + "network_base.xml";
    private static final String PLANS_FILE   = BASE_PATH + "2021.output_plans.xml.gz";
    private static final String WBGT_META    = BASE_PATH + "wbgt_grid.meta";
    private static final String OUTPUT_DIR   =
            "/home/admin/IdeaProjects/matsim-project-gurban/output/";

    private static final List<String> MODES = Arrays.asList("walk", "bike");
    private static final int MAX_PERSONS_PER_MODE = 5000;

    private static final double[] WEIGHTS = {
            1.000, 0.640, 0.410, 0.262, 0.168,
            0.107, 0.069, 0.044, 0.028, 0.018
    };

    private static final Map<String, Double> MODE_SPEED = Map.of("walk", 1.27, "bike", 4.2);
    private static final Map<String, Double> MODE_HEAT_FACTOR = Map.of("walk", 1.0, "bike", 1.53);

    public static void main(String[] args) throws IOException {
        // Parse scenario argument
        String scenario = (args.length > 0) ? args[0] : "commute";
        String wbgtFile = switch (scenario) {
            case "peak"    -> BASE_PATH + "wbgt_scenario_peak.bin";
            case "weekend" -> BASE_PATH + "wbgt_scenario_weekend.bin";
            default        -> BASE_PATH + "wbgt_scenario_commute.bin";
        };
        System.out.printf("%n=== Manchester Heat-Aware Routing [%s] ===%n%n", scenario);

        // Load WBGT slice
        HeatDataLoader wbgt = new HeatDataLoader(wbgtFile, WBGT_META);
        if (wbgt.getNSlices() != 1) {
            System.err.println("ERROR: expected single-slice scenario file");
            return;
        }

        // Load scenario
        Config config = ConfigUtils.createConfig();
        config.network().setInputFile(NETWORK_FILE);
        config.plans().setInputFile(PLANS_FILE);
        Scenario matsimScenario = ScenarioUtils.loadScenario(config);
        Network network = matsimScenario.getNetwork();
        Population population = matsimScenario.getPopulation();
        System.out.printf("Network: %d nodes, %d links%n",
                network.getNodes().size(), network.getLinks().size());
        System.out.printf("Population: %d persons%n", population.getPersons().size());

        // Assign WBGT cells to links
        wbgt.assignToLinks(network);

        // Extract trips
        List<HeatTrip> allTrips = new ArrayList<>();
        for (String mode : MODES) {
            List<HeatTrip> modeTrips = extractTrips(population, network, mode, MAX_PERSONS_PER_MODE);
            allTrips.addAll(modeTrips);
            System.out.printf("Loaded %d %s trips%n", modeTrips.size(), mode);
        }

        // Route
        String timeStamp = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new Date());
        String dynamicOutputDir = OUTPUT_DIR + "results_heat_" + scenario + "_" + timeStamp + "/";
        new File(dynamicOutputDir).mkdirs();

        for (String mode : MODES) {
            System.out.printf("%n=== %s ===%n", mode);
            double speed = MODE_SPEED.get(mode);
            double heatFactor = MODE_HEAT_FACTOR.get(mode);
            setLinkAttributes(network, wbgt, speed, heatFactor);

            List<RouteData> fastestRoutes = new ArrayList<>();
            List<RouteData> optimalRoutes = new ArrayList<>();

            for (HeatTrip trip : allTrips) {
                if (!trip.mode.equals(mode)) continue;
                try {
                    var fastestPath = doRoute(network, trip, 1.0, speed);
                    if (fastestPath == null) continue;
                    double[] ft = evaluatePath(fastestPath, wbgt, speed, heatFactor);
                    fastestRoutes.add(new RouteData(trip, fastestPath, ft[0], ft[1], 1.0));

                    List<WeightedMetrics> candidates = new ArrayList<>();
                    for (double w : WEIGHTS) {
                        var p = doRoute(network, trip, w, speed);
                        if (p == null) continue;
                        double[] te = evaluatePath(p, wbgt, speed, heatFactor);
                        double tDiff = (te[0] - ft[0]) / ft[0] * 100.0;
                        double hDiff = ft[1] < 1e-9 ? 0.0 : (te[1] - ft[1]) / ft[1] * 100.0;
                        candidates.add(new WeightedMetrics(w, tDiff, hDiff, te[0], te[1], p));
                    }

                    double bestWeight = selectOptimalWeight(candidates);
                    WeightedMetrics best = candidates.stream()
                            .filter(c -> Math.abs(c.weight - bestWeight) < 1e-9)
                            .findFirst().orElse(candidates.get(0));
                    optimalRoutes.add(new RouteData(trip, best.path,
                            best.travelTime, best.heatExposure, best.weight));
                } catch (Exception e) {
                    System.err.printf("  Failed: %s %s: %s%n", trip.personId, trip.mode, e.getMessage());
                }
            }

            exportRoutes(fastestRoutes, dynamicOutputDir + "routes_fastest_" + mode + ".csv");
            exportRoutes(optimalRoutes, dynamicOutputDir + "routes_heat_" + mode + ".csv");
            printStats(fastestRoutes, optimalRoutes, mode);
        }
        System.out.printf("%n=== DONE [%s] ===%nOutput: %s%n", scenario, dynamicOutputDir);
    }

    private static void setLinkAttributes(Network network, HeatDataLoader wbgt, double speed, double heatFactor) {
        double maxTime = 0.0, maxRawHeat = 0.0;
        for (Link link : network.getLinks().values()) {
            double w = wbgt.getWBGT(link.getId().toString());
            double t = link.getLength() / speed;
            double h = w * t;
            if (t > maxTime) maxTime = t;
            if (h > maxRawHeat) maxRawHeat = h;
        }
        if (maxTime <= 0) maxTime = 1.0;
        if (maxRawHeat <= 0) maxRawHeat = 1.0;
        for (Link link : network.getLinks().values()) {
            double w = wbgt.getWBGT(link.getId().toString());
            double t = link.getLength() / speed;
            double h = w * t;
            link.getAttributes().putAttribute("heat_time_norm", t / maxTime);
            link.getAttributes().putAttribute("heat_exposure_norm", h / maxRawHeat * heatFactor);
        }
    }

    private static LeastCostPathCalculator.Path doRoute(Network network, HeatTrip trip, double w, double s) {
        HeatAwareDisutility d = new HeatAwareDisutility(w);
        TravelTime tt = (l, t, p, v) -> l.getLength() / s;
        return new DijkstraFactory().createPathCalculator(network, d, tt)
                .calcLeastCostPath(trip.fromNode, trip.toNode, 0, null, null);
    }

    private static double[] evaluatePath(LeastCostPathCalculator.Path path, HeatDataLoader wbgt, double speed, double heatFactor) {
        double totalTime = 0.0, totalHeat = 0.0;
        for (Link link : path.links) {
            double t = link.getLength() / speed;
            totalTime += t;
            totalHeat += wbgt.getWBGT(link.getId().toString()) * t * heatFactor;
        }
        return new double[]{totalTime, totalHeat};
    }

    private static double selectOptimalWeight(List<WeightedMetrics> candidates) {
        if (candidates.isEmpty()) return 1.0;
        if (candidates.size() == 1) return candidates.get(0).weight;
        double minT = candidates.stream().mapToDouble(c -> c.timeDiff).min().orElse(0);
        double maxT = candidates.stream().mapToDouble(c -> c.timeDiff).max().orElse(0);
        double minH = candidates.stream().mapToDouble(c -> c.heatDiff).min().orElse(0);
        double maxH = candidates.stream().mapToDouble(c -> c.heatDiff).max().orElse(0);
        double tRange = Math.max(maxT - minT, 1.0);
        double hRange = Math.max(maxH - minH, 1.0);
        double idealTime = maxT + 0.1 * tRange;
        double idealHeat = maxH + 0.1 * hRange;
        double bestW = 1.0, bestHV = -Double.MAX_VALUE;
        for (WeightedMetrics c : candidates) {
            double hv = (idealTime - c.timeDiff) * (idealHeat - c.heatDiff);
            if (hv > bestHV) { bestHV = hv; bestW = c.weight; }
        }
        return bestW;
    }

    private static List<HeatTrip> extractTrips(Population population, Network network, String mode, int max) {
        List<HeatTrip> trips = new ArrayList<>();
        int count = 0;
        for (Person person : population.getPersons().values()) {
            if (count >= max) break;
            Plan plan = person.getSelectedPlan();
            if (plan == null) continue;
            for (int i = 0; i < plan.getPlanElements().size(); i++) {
                if (!(plan.getPlanElements().get(i) instanceof Leg leg)) continue;
                if (!leg.getMode().equals(mode)) continue;
                Activity o = (Activity) plan.getPlanElements().get(i - 1);
                Activity d = (Activity) plan.getPlanElements().get(i + 1);
                Node from = NetworkUtils.getNearestNode(network, o.getCoord());
                Node to   = NetworkUtils.getNearestNode(network, d.getCoord());
                if (from != null && to != null && !from.equals(to)) {
                    trips.add(new HeatTrip(person.getId().toString(), mode, from, to));
                    count++; break;
                }
            }
        }
        return trips;
    }

    private static void exportRoutes(List<RouteData> routes, String file) throws IOException {
        try (PrintWriter pw = new PrintWriter(new FileWriter(file))) {
            pw.println("person,mode,origin,destination,path,links,travel_time,heat_exposure,weight");
            for (RouteData r : routes) {
                String pathStr = "[" + String.join(", ", r.nodes) + "]";
                String linksStr = "[" + String.join(", ", r.linkIds) + "]";
                pw.printf("%s,%s,%s,%s,\"%s\",\"%s\",%.2f,%.6f,%.6f%n",
                        r.personId, r.mode, r.origin, r.dest,
                        pathStr, linksStr, r.travelTime, r.heatExposure, r.weight);
            }
        }
        System.out.println("  Wrote: " + file);
    }

    private static void printStats(List<RouteData> fast, List<RouteData> opt, String mode) {
        if (fast.isEmpty()) return;
        double[] ft = fast.stream().mapToDouble(r -> r.travelTime / 60.0).toArray();
        double[] fh = fast.stream().mapToDouble(r -> r.heatExposure).toArray();
        double[] ot = opt.stream().mapToDouble(r -> r.travelTime / 60.0).toArray();
        double[] oh = opt.stream().mapToDouble(r -> r.heatExposure).toArray();
        Arrays.sort(ft); Arrays.sort(fh); Arrays.sort(ot); Arrays.sort(oh);
        int n = ft.length;
        double mft = n % 2 == 0 ? (ft[n/2-1]+ft[n/2])/2 : ft[n/2];
        double mfh = n % 2 == 0 ? (fh[n/2-1]+fh[n/2])/2 : fh[n/2];
        double mot = n % 2 == 0 ? (ot[n/2-1]+ot[n/2])/2 : ot[n/2];
        double moh = n % 2 == 0 ? (oh[n/2-1]+oh[n/2])/2 : oh[n/2];
        System.out.printf("  Fastest:  median time=%.1f min, median heat=%.1f%n", mft, mfh);
        System.out.printf("  Optimal:  median time=%.1f min, median heat=%.1f%n", mot, moh);
    }

    static class HeatTrip {
        final String personId; final String mode; final Node fromNode; final Node toNode;
        HeatTrip(String id, String m, Node f, Node t) { this.personId = id; this.mode = m; this.fromNode = f; this.toNode = t; }
    }

    static class RouteData {
        final String personId, mode, origin, dest;
        final List<String> nodes, linkIds;
        final double travelTime, heatExposure, weight;
        RouteData(HeatTrip trip, LeastCostPathCalculator.Path path, double tt, double he, double w) {
            this.personId = trip.personId; this.mode = trip.mode;
            this.origin = trip.fromNode.getId().toString(); this.dest = trip.toNode.getId().toString();
            this.travelTime = tt; this.heatExposure = he; this.weight = w;
            this.nodes = new ArrayList<>(); this.linkIds = new ArrayList<>();
            this.nodes.add(path.nodes.get(0).getId().toString());
            for (Link l : path.links) { this.nodes.add(l.getToNode().getId().toString()); this.linkIds.add(l.getId().toString()); }
        }
    }

    private static class WeightedMetrics {
        final double weight, timeDiff, heatDiff, travelTime, heatExposure;
        final LeastCostPathCalculator.Path path;
        WeightedMetrics(double w, double t, double h, double tt, double he, LeastCostPathCalculator.Path p) {
            this.weight = w; this.timeDiff = t; this.heatDiff = h; this.travelTime = tt; this.heatExposure = he; this.path = p;
        }
    }
}
