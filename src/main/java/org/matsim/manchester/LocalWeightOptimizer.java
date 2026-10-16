package org.matsim.manchester;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.router.DijkstraFactory;
import org.matsim.core.router.util.LeastCostPathCalculator;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.core.router.util.TravelTime;

import java.util.*;

/**
 * Local weight optimization for Manchester flood routing.
 *
 * Same logic as your MDM paper, adapted for:
 * - Flood risk instead of emissions
 * - Walk/bike modes
 *
 * For each OD pair:
 * 1. Compute routes for different weights
 * 2. Build Pareto front
 * 3. Select weight with max hypervolume
 */
public class LocalWeightOptimizer {

    private final Network network;
    private final String mode;

    // Candidate weights: 0.8^(2k) for k=0..9 (from MDM paper)
    private static final double[] WEIGHTS = {
            1.000, 0.640, 0.410, 0.262, 0.168, 0.107, 0.069, 0.044, 0.028, 0.018
    };

    public LocalWeightOptimizer(Network network, String mode) {
        this.network = network;
        this.mode = mode;
    }

    /**
     * Find optimal weight for a single OD pair.
     * Returns weight that maximizes hypervolume on Pareto front.
     */
    public double findOptimalWeight(Node origin, Node destination) {

        // Step 1: Compute fastest path (baseline, w=1.0)
        PathMetrics fastest = computePathMetrics(origin, destination, 1.0);

        if (fastest == null) {
            System.err.println("Cannot route from " + origin.getId() + " to " + destination.getId());
            return 0.5; // fallback
        }

        // Step 2: Compute paths for all candidate weights
        List<WeightedMetrics> paretoFront = new ArrayList<>();

        for (double w : WEIGHTS) {
            PathMetrics metrics = computePathMetrics(origin, destination, w);

            if (metrics != null) {
                // Compute % difference from fastest
                double timeDiff = ((metrics.time - fastest.time) / fastest.time) * 100.0;
                double depthDiff = ((metrics.depth - fastest.depth) / fastest.depth) * 100.0;

                paretoFront.add(new WeightedMetrics(w, timeDiff, depthDiff));
            }
        }

        // Step 3: Select weight with max hypervolume
        return selectBestWeight(paretoFront);
    }

    /**
     * Compute path metrics (time and flood depth) for given weight.
     */
    private PathMetrics computePathMetrics(Node from, Node to, double weight) {

        // Speed based on mode
        double speed = mode.equals("bike") ? 4.17 : 1.4;

        // Create weighted disutility
        FloodAwareDisutility disutility = new FloodAwareDisutility(weight);

        // Dummy travel time (we use disutility only)
        TravelTime travelTime = (link, time, person, vehicle) -> link.getLength() / speed;

        // Run Dijkstra
//        Dijkstra dijkstra = new Dijkstra(network, disutility, travelTime);
//        LeastCostPathCalculator.Path path = dijkstra.calcLeastCostPath(from, to, 0, null, null);

        // If DijkstraFactory is a factory that returns a LeastCostPathCalculator
        LeastCostPathCalculator dijkstra = new DijkstraFactory().createPathCalculator(network, disutility, travelTime);
        LeastCostPathCalculator.Path path = dijkstra.calcLeastCostPath(from, to, 0, null, null);

        if (path == null) {
            return null;
        }

        // Compute actual time and flood depth
        double totalTime = 0;
        double totalDepth = 0;

// 2. The Loop (The Calculation)
        for (Link link : path.links) {
            // Use the 'travelTime' logic defined above instead of re-calculating
            double linkTime = travelTime.getLinkTravelTime(link, 0, null, null);
            double depth = getDepth(link);

            totalTime += linkTime;
            totalDepth += depth;
        }

        return new PathMetrics(totalTime, totalDepth);
    }

    /**
     * Get flood depth for a link.
     */
    private double getDepth(Link link) {
        Object depth = link.getAttributes().getAttribute("flood_depth");
        return (depth instanceof Double) ? (Double) depth : 0.0;
    }

    /**
     * Select weight that maximizes hypervolume (MDM paper Eq. 1).
     */
    private double selectBestWeight(List<WeightedMetrics> paretoFront) {

        if (paretoFront.isEmpty()) {
            return 1.0; // fastest path
        }

        // Find ranges
        double minTime = paretoFront.stream().mapToDouble(m -> m.timeDiff).min().orElse(0);
        double maxTime = paretoFront.stream().mapToDouble(m -> m.timeDiff).max().orElse(0);
        double minDepth = paretoFront.stream().mapToDouble(m -> m.depthDiff).min().orElse(0);
        double maxDepth = paretoFront.stream().mapToDouble(m -> m.depthDiff).max().orElse(0);

        // Ideal point with 10% buffer (MDM paper)
        double idealTime = maxTime + 0.1 * (maxTime - minTime);
        double idealDepth = maxDepth + 0.1 * (maxDepth - minDepth);

        // Find max hypervolume
        double bestWeight = 1.0;
        double maxHV = -Double.MAX_VALUE;

        for (WeightedMetrics m : paretoFront) {
            double hv = (idealTime - m.timeDiff) * (idealDepth - m.depthDiff);

            if (hv > maxHV) {
                maxHV = hv;
                bestWeight = m.weight;
            }
        }

        return bestWeight;
    }

    // Helper classes
    private static class PathMetrics {
        final double time;
        final double depth;

        PathMetrics(double time, double depth) {
            this.time = time;
            this.depth = depth;
        }
    }

    private static class WeightedMetrics {
        final double weight;
        final double timeDiff;
        final double depthDiff;

        WeightedMetrics(double weight, double timeDiff, double depthDiff) {
            this.weight = weight;
            this.timeDiff = timeDiff;
            this.depthDiff = depthDiff;
        }
    }
}