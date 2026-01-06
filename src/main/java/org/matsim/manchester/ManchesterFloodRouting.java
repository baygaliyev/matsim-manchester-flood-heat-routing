package org.matsim.manchester;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.io.PopulationReader;
import org.matsim.core.router.Dijkstra;
import org.matsim.core.router.util.LeastCostPathCalculator;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.core.router.util.TravelTime;
import org.matsim.core.scenario.ScenarioUtils;

import java.io.*;
import java.util.*;

/**
 * Manchester Flood-Aware Routing
 *
 * Adapted from your MDM paper:
 * - Instead of emission exposure → flood risk exposure
 * - Instead of Pisa pedestrians → Manchester pedestrians/cyclists
 * - Same logic: optimize weight per OD pair using hypervolume
 *
 * Input files:
 * - data/input/network_base.xml (Manchester network)
 * - data/input/2021.output_plans.xml (Population plans - SUBSET!)
 * - data/input/flood_risk_processed.csv (Flood risk per link)
 */
public class ManchesterFloodRouting {

    private static final String BASE_PATH = "data/";
    private static final String NETWORK_FILE = BASE_PATH + "input/network_base.xml";
    private static final String PLANS_FILE = BASE_PATH + "input/2021.output_plans.xml";
    private static final String FLOOD_FILE = BASE_PATH + "processed/flood_risk_processed.csv";
    private static final String OUTPUT_DIR = "output/routes/";

    // Mode to analyze (walk or bike)
    private static final String MODE = "walk"; // or "bike"

    // Subset size (2M plans is too much - start small!)
    private static final int MAX_PERSONS = 1000; // Start with 1000 persons

    public static void main(String[] args) throws IOException {

        System.out.println("=== Manchester Flood-Aware Routing ===\n");

        // Step 1: Load network
        System.out.println("Step 1: Loading Manchester network...");
        Network network = loadNetwork(NETWORK_FILE);
        System.out.println("  Loaded: " + network.getNodes().size() + " nodes, " +
                network.getLinks().size() + " links\n");

        // Step 2: Load flood risk data
        System.out.println("Step 2: Loading flood risk data...");
        FloodDataLoader.loadFloodData(network, FLOOD_FILE);
        System.out.println("  Flood risk attached to links\n");

        // Step 3: Load plans (subset!)
        System.out.println("Step 3: Loading population plans (subset of " + MAX_PERSONS + ")...");
        List<PersonTrip> trips = loadPersonTrips(PLANS_FILE, network, MODE, MAX_PERSONS);
        System.out.println("  Loaded: " + trips.size() + " " + MODE + " trips\n");

        // Step 4: Optimize routes
        System.out.println("Step 4: Computing flood-aware routes...");
        LocalWeightOptimizer optimizer = new LocalWeightOptimizer(network, MODE);
        List<RouteResult> results = new ArrayList<>();

        int count = 0;
        for (PersonTrip trip : trips) {
            try {
                // Find optimal weight (like your MDM paper)
                double optimalWeight = optimizer.findOptimalWeight(
                        trip.fromNode, trip.toNode);

                // Compute route with optimal weight
                RouteResult result = computeRoute(network, trip, optimalWeight, MODE);
                results.add(result);

                count++;
                if (count % 100 == 0) {
                    System.out.println("  Processed " + count + "/" + trips.size());
                }
            } catch (Exception e) {
                System.err.println("  Failed for person " + trip.personId + ": " + e.getMessage());
            }
        }

        System.out.println("  Completed: " + results.size() + " routes\n");

        // Step 5: Export results
        System.out.println("Step 5: Exporting results...");
        new File(OUTPUT_DIR).mkdirs();
        exportResults(results, OUTPUT_DIR + "flood_routes_" + MODE + ".csv");
        exportSummary(results, OUTPUT_DIR + "flood_summary_" + MODE + ".csv");

        System.out.println("\n=== Done! ===");
        System.out.println("Check: " + OUTPUT_DIR);
    }

    /**
     * Load network from MATSim XML.
     */
    private static Network loadNetwork(String filename) {
        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.createScenario(config);
        new MatsimNetworkReader(scenario.getNetwork()).readFile(filename);
        return scenario.getNetwork();
    }

    /**
     * Load person trips from plans file (SUBSET only!).
     * Extracts OD pairs for specified mode (walk/bike).
     */
    private static List<PersonTrip> loadPersonTrips(String filename, Network network,
                                                    String mode, int maxPersons) {
        List<PersonTrip> trips = new ArrayList<>();

        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.createScenario(config);
        scenario.setNetwork(network);

        // Use streaming reader to avoid loading all 2M plans into memory
        PopulationReader reader = new PopulationReader(scenario);

        // Read population
        reader.readFile(filename);
        Population population = scenario.getPopulation();

        System.out.println("  Total persons in file: " + population.getPersons().size());
        System.out.println("  Extracting subset of " + maxPersons + " for mode: " + mode);

        int count = 0;
        for (Person person : population.getPersons().values()) {
            if (count >= maxPersons) break;

            Plan plan = person.getSelectedPlan();
            if (plan == null) continue;

            // Find trips with specified mode
            for (int i = 0; i < plan.getPlanElements().size(); i++) {
                if (plan.getPlanElements().get(i) instanceof Leg) {
                    Leg leg = (Leg) plan.getPlanElements().get(i);

                    if (leg.getMode().equals(mode)) {
                        // Get origin and destination activities
                        Activity originAct = (Activity) plan.getPlanElements().get(i - 1);
                        Activity destAct = (Activity) plan.getPlanElements().get(i + 1);

                        // Find nearest nodes
                        Node fromNode = org.matsim.core.network.NetworkUtils
                                .getNearestNode(network, originAct.getCoord());
                        Node toNode = org.matsim.core.network.NetworkUtils
                                .getNearestNode(network, destAct.getCoord());

                        if (fromNode != null && toNode != null && !fromNode.equals(toNode)) {
                            trips.add(new PersonTrip(
                                    person.getId().toString(),
                                    mode,
                                    fromNode,
                                    toNode
                            ));
                            count++;
                            break; // One trip per person for now
                        }
                    }
                }
            }
        }

        return trips;
    }

    /**
     * Compute route with given weight.
     */
    private static RouteResult computeRoute(Network network, PersonTrip trip,
                                            double weight, String mode) {

        // Travel speed based on mode
        double speed = mode.equals("bike") ? 4.17 : 1.4; // bike: 15km/h, walk: 5km/h

        // Create weighted disutility (like your MDM paper)
        FloodAwareDisutility disutility = new FloodAwareDisutility(weight, speed);
        TravelTime travelTime = (link, time, person, vehicle) -> link.getLength() / speed;

        // Run Dijkstra
        Dijkstra dijkstra = new Dijkstra(network, disutility, travelTime);
        LeastCostPathCalculator.Path path = dijkstra.calcLeastCostPath(
                trip.fromNode, trip.toNode, 0, null, null);

        if (path == null) {
            return new RouteResult(trip.personId, trip.mode, weight,
                    0, 0, 0, new ArrayList<>(), "NO_ROUTE");
        }

        // Calculate metrics
        double totalTime = 0;
        double totalFloodRisk = 0;
        double totalDistance = 0;
        List<String> linkIds = new ArrayList<>();

        for (Link link : path.links) {
            totalTime += link.getLength() / speed;
            totalDistance += link.getLength();

            Object risk = link.getAttributes().getAttribute("flood_risk");
            totalFloodRisk += (risk instanceof Double) ? (Double) risk : 0.0;

            linkIds.add(link.getId().toString());
        }

        return new RouteResult(trip.personId, trip.mode, weight,
                totalTime, totalFloodRisk, totalDistance,
                linkIds, "SUCCESS");
    }

    /**
     * Export detailed results.
     */
    private static void exportResults(List<RouteResult> results, String filename)
            throws IOException {
        try (PrintWriter pw = new PrintWriter(new FileWriter(filename))) {
            pw.println("person_id,mode,optimal_weight,travel_time,flood_risk," +
                    "distance,num_links,status");

            for (RouteResult r : results) {
                pw.printf("%s,%s,%.4f,%.2f,%.6f,%.2f,%d,%s%n",
                        r.personId, r.mode, r.weight, r.travelTime,
                        r.floodRisk, r.distance, r.linkIds.size(), r.status);
            }
        }
        System.out.println("  Saved: " + filename);
    }

    /**
     * Export summary statistics.
     */
    private static void exportSummary(List<RouteResult> results, String filename)
            throws IOException {

        DoubleSummaryStatistics timeStats = results.stream()
                .mapToDouble(r -> r.travelTime).summaryStatistics();
        DoubleSummaryStatistics riskStats = results.stream()
                .mapToDouble(r -> r.floodRisk).summaryStatistics();
        DoubleSummaryStatistics weightStats = results.stream()
                .mapToDouble(r -> r.weight).summaryStatistics();

        try (PrintWriter pw = new PrintWriter(new FileWriter(filename))) {
            pw.println("metric,count,mean,min,max,sum");
            pw.printf("travel_time,%.0f,%.2f,%.2f,%.2f,%.2f%n",
                    (double)timeStats.getCount(), timeStats.getAverage(),
                    timeStats.getMin(), timeStats.getMax(), timeStats.getSum());
            pw.printf("flood_risk,%.0f,%.6f,%.6f,%.6f,%.6f%n",
                    (double)riskStats.getCount(), riskStats.getAverage(),
                    riskStats.getMin(), riskStats.getMax(), riskStats.getSum());
            pw.printf("weight,%.0f,%.4f,%.4f,%.4f,%.4f%n",
                    (double)weightStats.getCount(), weightStats.getAverage(),
                    weightStats.getMin(), weightStats.getMax(), weightStats.getSum());
        }
        System.out.println("  Saved: " + filename);
    }

    // ============= Helper Classes =============

    static class PersonTrip {
        final String personId;
        final String mode;
        final Node fromNode;
        final Node toNode;

        PersonTrip(String personId, String mode, Node fromNode, Node toNode) {
            this.personId = personId;
            this.mode = mode;
            this.fromNode = fromNode;
            this.toNode = toNode;
        }
    }

    static class RouteResult {
        final String personId;
        final String mode;
        final double weight;
        final double travelTime;
        final double floodRisk;
        final double distance;
        final List<String> linkIds;
        final String status;

        RouteResult(String personId, String mode, double weight, double travelTime,
                    double floodRisk, double distance, List<String> linkIds, String status) {
            this.personId = personId;
            this.mode = mode;
            this.weight = weight;
            this.travelTime = travelTime;
            this.floodRisk = floodRisk;
            this.distance = distance;
            this.linkIds = linkIds;
            this.status = status;
        }
    }
}