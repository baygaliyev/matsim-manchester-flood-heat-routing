package org.matsim.manchester;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.vehicles.Vehicle;

/**
 * Flood-aware travel disutility for Manchester.
 *
 * Same logic as your MDM paper ExposureAwarePedestrianDisutility,
 * but adapted for flood risk instead of emissions.
 *
 * Cost = weight * time + (1-weight) * flood_risk
 *
 * where:
 * - weight ∈ [0,1]: trade-off parameter
 * - time: normalized travel time
 * - flood_risk: normalized flood exposure
 */
public class FloodAwareDisutility implements TravelDisutility {

    private final double weight;
    private final double speed; // m/s (walk: 1.4, bike: 4.17)

    public FloodAwareDisutility(double weight, double speed) {
        this.weight = weight;
        this.speed = speed;
    }

    @Override
    public double getLinkTravelDisutility(Link link, double time,
                                          Person person, Vehicle vehicle) {

        // Get normalized travel time
        double travelTime = link.getLength() / speed;

        // Get normalized flood risk
        double floodRisk = getFloodRisk(link);

        // Weighted cost: w * time + (1-w) * flood_risk
        // (Same formula as your MDM paper!)
        return weight * travelTime + (1.0 - weight) * floodRisk;
    }

    @Override
    public double getLinkMinimumTravelDisutility(Link link) {
        // Minimum = just travel time (weight = 1.0)
        return link.getLength() / speed;
    }

    /**
     * Get normalized flood risk for link.
     */
    private double getFloodRisk(Link link) {
        Object risk = link.getAttributes().getAttribute("flood_risk_norm");

        if (risk instanceof Double) {
            return (Double) risk;
        }

        // Fallback to non-normalized
        Object riskRaw = link.getAttributes().getAttribute("flood_risk");
        if (riskRaw instanceof Double) {
            return (Double) riskRaw;
        }

        return 0.0; // No flood risk
    }
}