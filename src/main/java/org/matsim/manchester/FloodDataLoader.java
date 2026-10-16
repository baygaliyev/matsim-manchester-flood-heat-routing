package org.matsim.manchester;

import org.geotools.api.data.DataStore;
import org.geotools.api.data.DataStoreFinder;
import org.geotools.api.data.FeatureSource;
import org.geotools.api.feature.simple.SimpleFeature;
import org.geotools.api.feature.simple.SimpleFeatureType;
import org.geotools.api.feature.type.AttributeDescriptor;
import org.geotools.feature.FeatureIterator;
import org.geotools.geometry.jts.JTS;

import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.LineString;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.Coord;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;

import java.io.File;
import java.io.IOException;
import java.util.*;

/**
 * Modern 2026 Flood Data Loader for MATSim.
 *
 * Loads RoFSW (Risk of Flooding from Surface Water) shapefiles.
 * Each layer corresponds to a depth threshold (0.0m, 0.2m, ..., 1.2m).
 * Polygons within each layer have a likelihood attribute
 * (High / Medium / Low) indicating annual probability.
 *
 * For each road link, this loader builds a probability profile:
 *   {0.0m: High, 0.2m: Medium, 0.6m: Low, ...}
 * and assigns flood_depth = highest depth that still has "High" likelihood.
 */
public class FloodDataLoader {

    private static final String FLOOD_DIR =
            "/mnt/usb-TOSHIBA_EXTERNAL_USB_20241114001799F-0:0-part1/gurban/input_data/flooding_risk_manchester/";

    // Depth layers in order: shallowest first (for profile building)
    // 0.0m = flood extent (just "might get wet")
    private static final String[][] DEPTH_LAYERS = {
            {"rofswPolygon.shp",               "0.0"},
            {"rofsw_0_2m_depthPolygon.shp",   "0.2"},
            {"rofsw_0_3m_depthPolygon.shp",   "0.3"},
            {"rofsw_0_6m_depthPolygon.shp",   "0.6"},
            {"rofsw_0_9m_depthPolygon.shp",   "0.9"},
            {"rofsw_1_2m_depthPolygon.shp",   "1.2"}
    };

    private static final double EXTENT_ONLY_DEPTH = 0.1; // interpolated depth for extent-only links

    // Risk band ordering
    private static final Map<String, Integer> LIKELIHOOD_ORDER = new LinkedHashMap<>();
    static {
        LIKELIHOOD_ORDER.put("High",      3);
        LIKELIHOOD_ORDER.put("Medium",    2);
        LIKELIHOOD_ORDER.put("Low",       1);
        LIKELIHOOD_ORDER.put("Very low",  0);
    }

    // Known attribute names for risk band (checked in order)
    private static final String[] LIKELIHOOD_CANDIDATES = {"risk_band", "Risk_band", "RISK_BAND", "likelihood", "Likelihood"};


    /* ============================================================
     *  INSPECT SHAPEFILE (diagnostic)
     * ============================================================ */

    public static void inspectShapefile(File shpFile) throws IOException {
        System.out.println("\n" + "=".repeat(60));
        System.out.println("INSPECTING: " + shpFile.getName());
        System.out.println("=".repeat(60));

        Map<String, Object> map = new HashMap<>();
        map.put("url", shpFile.toURI().toURL());

        DataStore dataStore = DataStoreFinder.getDataStore(map);
        String typeName = dataStore.getTypeNames()[0];
        FeatureSource<SimpleFeatureType, SimpleFeature> source =
                dataStore.getFeatureSource(typeName);

        SimpleFeatureType schema = source.getSchema();

        System.out.println("\nATTRIBUTES:");
        for (int i = 0; i < schema.getAttributeCount(); i++) {
            String name = schema.getDescriptor(i).getLocalName();
            String type = schema.getDescriptor(i).getType().getBinding().getSimpleName();
            System.out.printf("  [%d] %-25s (%s)%n", i, name, type);
        }

        System.out.println("\nSAMPLE (first 5 features):");
        try (FeatureIterator<SimpleFeature> it = source.getFeatures().features()) {
            int n = 0;
            while (it.hasNext() && n < 5) {
                SimpleFeature f = it.next();
                System.out.println("  Feature " + (n + 1) + ":");
                for (int i = 0; i < schema.getAttributeCount(); i++) {
                    String name = schema.getDescriptor(i).getLocalName();
                    Object val = f.getAttribute(name);
                    if (val instanceof Geometry) {
                        System.out.printf("    %-25s = %s (area=%.1f)%n",
                                name, ((Geometry) val).getGeometryType(), ((Geometry) val).getArea());
                    } else {
                        System.out.printf("    %-25s = %s%n", name, val);
                    }
                }
                n++;
            }
        }

        System.out.println("Total features: " + source.getFeatures().size());
        System.out.println("=".repeat(60) + "\n");
        dataStore.dispose();
    }


    /* ============================================================
     *  INSPECT ALL LAYERS (convenience)
     * ============================================================ */

    public static void inspectAllLayers() throws IOException {
        for (String[] layer : DEPTH_LAYERS) {
            File f = new File(FLOOD_DIR + layer[0]);
            if (f.exists()) {
                inspectShapefile(f);
            } else {
                System.out.println("[SKIP] " + layer[0] + " not found");
            }
        }
    }


    /* ============================================================
     *  STANDALONE RUNNER (just update the network file)
     * ============================================================ */

    public static void main(String[] args) throws IOException {
        String basePath = "/mnt/usb-TOSHIBA_EXTERNAL_USB_20241114001799F-0:0-part1/gurban/input_data/";
        String networkFile = basePath + "network_base.xml";
        String enrichedFile = basePath + "network_with_flood_data.xml";

        System.out.println("Loading network from: " + networkFile);
        org.matsim.core.config.Config config = org.matsim.core.config.ConfigUtils.createConfig();
        config.network().setInputFile(networkFile);
        org.matsim.api.core.v01.Scenario scenario =
                org.matsim.core.scenario.ScenarioUtils.loadScenario(config);
        org.matsim.api.core.v01.network.Network network = scenario.getNetwork();
        System.out.println("Network loaded: " + network.getNodes().size()
                + " nodes, " + network.getLinks().size() + " links");

        loadFloodData(network);

        System.out.println("Saving enriched network to: " + enrichedFile);
        new org.matsim.api.core.v01.network.NetworkWriter(network).write(enrichedFile);
        System.out.println("Done!");
    }


    /* ============================================================
     *  MAIN LOADER
     * ============================================================ */

    /**
     * Load flood data from all depth layers and assign:
     *   - flood_depth_profile : JSON-like string of {depth: likelihood, ...}
     *   - flood_depth         : highest depth with High likelihood
     */
    public static void loadFloodData(Network network) throws IOException {
        System.out.println("\n=== Loading RoFSW flood data ===");

        // Step 1: For each link, collect depth -> likelihood mapping
        // We'll build this incrementally layer by layer
        Map<String, Map<String, String>> linkProfiles = new HashMap<>(); // linkId -> {depthStr: likelihood}

        // Initialise all links with empty profiles
        for (Link link : network.getLinks().values()) {
            linkProfiles.put(link.getId().toString(), new LinkedHashMap<>());
        }

        // Step 2: Process each depth layer (shallowest first)
        for (String[] layer : DEPTH_LAYERS) {
            String filename = layer[0];
            String depthStr = layer[1];

            File shpFile = new File(FLOOD_DIR + filename);
            if (!shpFile.exists()) {
                System.out.println("  [SKIP] " + filename + " not found");
                continue;
            }

            System.out.println("\n  Processing: " + filename + " (depth >= " + depthStr + "m)");
            String likelihoodAttr = processDepthLayer(network, shpFile, depthStr, linkProfiles);
            System.out.println("    Likelihood attribute used: " + likelihoodAttr);
        }

        // Step 3: Compute flood_depth from each link's profile
        int highCount = 0;
        int extentOnlyCount = 0;
        int noFloodCount = 0;

        for (Link link : network.getLinks().values()) {
            Map<String, String> profile = linkProfiles.get(link.getId().toString());

            // Store profile as JSON-like attribute
            StringBuilder sb = new StringBuilder("{");
            boolean first = true;
            for (Map.Entry<String, String> e : profile.entrySet()) {
                if (!first) sb.append(", ");
                sb.append("\"").append(e.getKey()).append("m\":\"").append(e.getValue()).append("\"");
                first = false;
            }
            sb.append("}");
            link.getAttributes().putAttribute("flood_depth_profile", sb.toString());

            // Find highest depth with High likelihood
            double assignedDepth = 0.0;
            boolean hasHigh = false;
            for (String[] layer : DEPTH_LAYERS) {
                String d = layer[1];
                String lik = profile.getOrDefault(d, "");
                if ("High".equals(lik)) {
                    assignedDepth = Double.parseDouble(d);
                    hasHigh = true;
                }
            }

            if (hasHigh) {
                if (assignedDepth == 0.0) {
                    // In 0.0m extent but no measurable depth layer has High likelihood
                    assignedDepth = EXTENT_ONLY_DEPTH;
                    extentOnlyCount++;
                }
                highCount++;
            } else {
                // Not in any High-likelihood zone
                assignedDepth = 0.0;
                noFloodCount++;
            }

            link.getAttributes().putAttribute("flood_depth", assignedDepth);
        }

        System.out.println("\n=== Flood assignment complete ===");
        System.out.println("  Links with High-likelihood flooding: " + highCount);
        System.out.println("    of which extent-only (depth ~" + EXTENT_ONLY_DEPTH + "m): " + extentOnlyCount);
        System.out.println("  Links with no High-likelihood flood: " + noFloodCount);
        printDepthDistribution(network);
    }


    /* ============================================================
     *  PROCESS ONE DEPTH LAYER
     * ============================================================ */

    /**
     * Process one depth layer shapefile. For each link, checks intersection
     * with flood polygons and records the HIGHEST likelihood found.
     *
     * @return the attribute name used for likelihood
     */
    private static String processDepthLayer(
            Network network, File shpFile, String depthStr,
            Map<String, Map<String, String>> linkProfiles) throws IOException {

        // Open shapefile
        Map<String, Object> map = new HashMap<>();
        map.put("url", shpFile.toURI().toURL());

        DataStore dataStore = DataStoreFinder.getDataStore(map);
        String typeName = dataStore.getTypeNames()[0];
        FeatureSource<SimpleFeatureType, SimpleFeature> source =
                dataStore.getFeatureSource(typeName);

        // Detect the likelihood attribute name from schema
        SimpleFeatureType schema = source.getSchema();
        String likelihoodAttr = null;
        for (AttributeDescriptor desc : schema.getAttributeDescriptors()) {
            String name = desc.getLocalName();
            for (String candidate : LIKELIHOOD_CANDIDATES) {
                if (name.equalsIgnoreCase(candidate)) {
                    likelihoodAttr = name;
                    break;
                }
            }
            if (likelihoodAttr != null) break;
        }

        // If no likelihood attribute found, treat all features as "High"
        boolean hasLikelihood = (likelihoodAttr != null);

        // Coordinate transformation: shapefile CRS -> network CRS
        // Assuming shapefiles are EPSG:4326 (WGS84) and network is EPSG:27700 (British National Grid)
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                "EPSG:4326", "EPSG:27700");

        // Collect all flood zones with their likelihood
        System.out.println("    Loading flood zones...");
        List<FloodZone> zones = new ArrayList<>();

        try (FeatureIterator<SimpleFeature> it = source.getFeatures().features()) {
            while (it.hasNext()) {
                SimpleFeature feature = it.next();
                Geometry geom = (Geometry) feature.getDefaultGeometry();
                if (geom == null || !geom.isValid()) continue;

                // Get likelihood
                String likelihood = "High"; // default
                if (hasLikelihood) {
                    Object raw = feature.getAttribute(likelihoodAttr);
                    if (raw != null) {
                        String rawStr = raw.toString().trim();
                        // Map common variations
                        if (rawStr.equalsIgnoreCase("High") || rawStr.equals("3") || rawStr.equals("H")) {
                            likelihood = "High";
                        } else if (rawStr.equalsIgnoreCase("Medium") || rawStr.equals("2") || rawStr.equals("M")) {
                            likelihood = "Medium";
                        } else if (rawStr.equalsIgnoreCase("Low") || rawStr.equals("1") || rawStr.equals("L")) {
                            likelihood = "Low";
                        } else if (rawStr.equalsIgnoreCase("Very low") || rawStr.equals("0") || rawStr.equals("VL")) {
                            likelihood = "Very low";
                        }
                    }
                }

                zones.add(new FloodZone(geom, likelihood));
            }
        }

        System.out.println("    Loaded " + zones.size() + " flood zones (likelihood attr: "
                + (hasLikelihood ? likelihoodAttr : "NONE — assuming High") + ")");

        // Check each link against flood zones
        int intersectedCount = 0;
        int checked = 0;

        for (Link link : network.getLinks().values()) {
            String linkId = link.getId().toString();

            // Create line geometry for this link
            Coord fc = link.getFromNode().getCoord();
            Coord tc = link.getToNode().getCoord();
            org.locationtech.jts.geom.GeometryFactory gf =
                    new org.locationtech.jts.geom.GeometryFactory();
            LineString linkLine = gf.createLineString(new org.locationtech.jts.geom.Coordinate[]{
                    new org.locationtech.jts.geom.Coordinate(fc.getX(), fc.getY()),
                    new org.locationtech.jts.geom.Coordinate(tc.getX(), tc.getY())
            });

            // Check intersection with any flood zone
            String bestLikelihood = linkProfiles.get(linkId).getOrDefault(depthStr, "");

            for (FloodZone zone : zones) {
                if (zone.geometry.intersects(linkLine)) {
                    // Take the HIGHEST likelihood
                    int currentRank = LIKELIHOOD_ORDER.getOrDefault(bestLikelihood, 0);
                    int newRank = LIKELIHOOD_ORDER.getOrDefault(zone.likelihood, 0);
                    if (newRank > currentRank) {
                        bestLikelihood = zone.likelihood;
                        currentRank = newRank;
                    }
                }
            }

            if (!bestLikelihood.isEmpty()) {
                linkProfiles.get(linkId).put(depthStr, bestLikelihood);
                intersectedCount++;
            }

            checked++;
            if (checked % 5000 == 0) {
                System.out.println("      Checked " + checked + "/" + network.getLinks().size() + " links...");
            }
        }

        dataStore.dispose();
        return hasLikelihood ? likelihoodAttr : "NONE";
    }


    /* ============================================================
     *  HELPERS
     * ============================================================ */

    private static void printDepthDistribution(Network network) {
        Map<Double, Integer> dist = new TreeMap<>();
        for (Link link : network.getLinks().values()) {
            double d = (Double) link.getAttributes().getAttribute("flood_depth");
            dist.put(d, dist.getOrDefault(d, 0) + 1);
        }
        System.out.println("\n  Flood depth distribution (High-likelihood):");
        for (Map.Entry<Double, Integer> e : dist.entrySet()) {
            double pct = 100.0 * e.getValue() / network.getLinks().size();
            System.out.printf("    %.1fm: %,6d links (%.1f%%)%n", e.getKey(), e.getValue(), pct);
        }
    }

    private static class FloodZone {
        final Geometry geometry;
        final String likelihood;

        FloodZone(Geometry geometry, String likelihood) {
            this.geometry = geometry;
            this.likelihood = likelihood;
        }
    }
}
