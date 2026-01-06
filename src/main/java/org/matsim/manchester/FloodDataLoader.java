package org.matsim.manchester;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.util.*;

/**
 * Load flood risk data and attach to network links.
 *
 * Similar to ExposureDataLoader from your MDM paper,
 * but for flood data instead of emissions.
 *
 * Expected input: CSV with flood risk per location
 * Format: lon, lat, flood_risk (or link_id, flood_risk if already mapped)
 */
public class FloodDataLoader {

    /**
     * Load flood data from CSV and attach to network links.
     */
    public static void loadFloodData(Network network, String floodFilePath) throws IOException {

        System.out.println("  Loading flood data from: " + floodFilePath);

        // Try two approaches:
        // 1. If CSV has link_id, flood_risk → direct mapping
        // 2. If CSV has lon, lat, flood_risk → spatial join

        Map<String, Double> floodByLinkId = new HashMap<>();
        Map<GridCell, Double> floodByLocation = new HashMap<>();

        boolean hasLinkId = detectFormat(floodFilePath);

        if (hasLinkId) {
            floodByLinkId = loadFloodByLinkId(floodFilePath);
            attachFloodByLinkId(network, floodByLinkId);
        } else {
            floodByLocation = loadFloodByLocation(floodFilePath);
            attachFloodBySpatialJoin(network, floodByLocation);
        }

        // Normalize flood risk values
        normalizeFloodRisk(network);

        System.out.println("  Flood data attached successfully");
    }

    /**
     * Detect CSV format.
     */
    private static boolean detectFormat(String filePath) throws IOException {
        try (BufferedReader br = new BufferedReader(new FileReader(filePath))) {
            String header = br.readLine();
            return header != null && header.toLowerCase().contains("link_id");
        }
    }

    /**
     * Load flood data with link IDs (direct mapping).
     * Format: link_id, flood_risk
     */
    private static Map<String, Double> loadFloodByLinkId(String filePath) throws IOException {
        Map<String, Double> floodData = new HashMap<>();

        try (BufferedReader br = new BufferedReader(new FileReader(filePath))) {
            String line = br.readLine(); // skip header

            while ((line = br.readLine()) != null) {
                String[] parts = line.split(",");
                if (parts.length >= 2) {
                    try {
                        String linkId = parts[0].trim();
                        double risk = Double.parseDouble(parts[1].trim());
                        floodData.put(linkId, risk);
                    } catch (NumberFormatException e) {
                        // Skip malformed lines
                    }
                }
            }
        }

        System.out.println("    Loaded flood risk for " + floodData.size() + " links");
        return floodData;
    }

    /**
     * Load flood data with coordinates (spatial join needed).
     * Format: lon, lat, flood_risk
     */
    private static Map<GridCell, Double> loadFloodByLocation(String filePath) throws IOException {
        Map<GridCell, Double> floodData = new HashMap<>();

        try (BufferedReader br = new BufferedReader(new FileReader(filePath))) {
            String line = br.readLine(); // skip header

            while ((line = br.readLine()) != null) {
                String[] parts = line.split(",");
                if (parts.length >= 3) {
                    try {
                        double lon = Double.parseDouble(parts[0].trim());
                        double lat = Double.parseDouble(parts[1].trim());
                        double risk = Double.parseDouble(parts[2].trim());

                        floodData.put(new GridCell(lon, lat), risk);
                    } catch (NumberFormatException e) {
                        // Skip malformed lines
                    }
                }
            }
        }

        System.out.println("    Loaded flood risk for " + floodData.size() + " locations");
        return floodData;
    }

    /**
     * Attach flood data using direct link ID mapping.
     */
    private static void attachFloodByLinkId(Network network, Map<String, Double> floodData) {
        int matched = 0;

        for (Link link : network.getLinks().values()) {
            String linkId = link.getId().toString();
            Double risk = floodData.get(linkId);

            if (risk != null) {
                link.getAttributes().putAttribute("flood_risk", risk);
                matched++;
            } else {
                link.getAttributes().putAttribute("flood_risk", 0.0);
            }
        }

        System.out.println("    Matched " + matched + " of " + network.getLinks().size() + " links");
    }

    /**
     * Attach flood data using spatial join (like your emission loader).
     */
    private static void attachFloodBySpatialJoin(Network network, Map<GridCell, Double> floodData) {

        double gridResolution = estimateGridResolution(floodData);
        System.out.println("    Estimated grid resolution: " + gridResolution + "m");

        int matched = 0;
        for (Link link : network.getLinks().values()) {

            // Sample flood risk along the link
            double avgRisk = sampleRiskAlongLink(link, floodData, gridResolution);
            link.getAttributes().putAttribute("flood_risk", avgRisk);

            if (avgRisk > 0) matched++;
        }

        System.out.println("    Assigned flood risk to " + matched + " links");
    }

    /**
     * Sample flood risk along a link (like your emission sampling).
     */
    private static double sampleRiskAlongLink(Link link, Map<GridCell, Double> floodData,
                                              double resolution) {
        Coord from = link.getFromNode().getCoord();
        Coord to = link.getToNode().getCoord();

        // Sample at multiple points
        int numSamples = Math.max(3, (int) (link.getLength() / resolution));
        double totalRisk = 0.0;
        int validSamples = 0;

        for (int i = 0; i <= numSamples; i++) {
            double fraction = (double) i / numSamples;
            double x = from.getX() + fraction * (to.getX() - from.getX());
            double y = from.getY() + fraction * (to.getY() - from.getY());

            GridCell cell = new GridCell(x, y, resolution);
            Double risk = floodData.get(cell);

            if (risk != null) {
                totalRisk += risk;
                validSamples++;
            }
        }

        return validSamples > 0 ? totalRisk / validSamples : 0.0;
    }

    /**
     * Normalize flood risk across all links (min-max normalization).
     */
    private static void normalizeFloodRisk(Network network) {
        double minRisk = Double.MAX_VALUE;
        double maxRisk = -Double.MAX_VALUE;

        // Find min/max
        for (Link link : network.getLinks().values()) {
            double risk = (Double) link.getAttributes().getAttribute("flood_risk");
            minRisk = Math.min(minRisk, risk);
            maxRisk = Math.max(maxRisk, risk);
        }

        // Normalize
        for (Link link : network.getLinks().values()) {
            double risk = (Double) link.getAttributes().getAttribute("flood_risk");
            double normRisk = (maxRisk > minRisk) ?
                    (risk - minRisk) / (maxRisk - minRisk) : 0.0;
            link.getAttributes().putAttribute("flood_risk_norm", normRisk);
        }

        System.out.println("    Flood risk range: [" + minRisk + ", " + maxRisk + "]");
    }

    /**
     * Estimate grid resolution from data.
     */
    private static double estimateGridResolution(Map<GridCell, Double> floodData) {
        if (floodData.isEmpty()) return 100.0;

        List<GridCell> cells = new ArrayList<>(floodData.keySet());
        if (cells.size() < 2) return 100.0;

        GridCell first = cells.get(0);
        GridCell second = cells.get(1);

        double dx = Math.abs(first.x - second.x);
        double dy = Math.abs(first.y - second.y);

        return Math.max(dx, dy);
    }

    /**
     * Helper class for grid cells.
     */
    static class GridCell {
        final double x;
        final double y;

        GridCell(double x, double y) {
            this.x = x;
            this.y = y;
        }

        GridCell(double x, double y, double resolution) {
            this.x = Math.floor(x / resolution) * resolution;
            this.y = Math.floor(y / resolution) * resolution;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof GridCell)) return false;
            GridCell cell = (GridCell) o;
            return Double.compare(cell.x, x) == 0 && Double.compare(cell.y, y) == 0;
        }

        @Override
        public int hashCode() {
            return Objects.hash(x, y);
        }
    }
}