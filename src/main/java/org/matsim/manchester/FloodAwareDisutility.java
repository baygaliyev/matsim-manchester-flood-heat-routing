package org.matsim.manchester;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.vehicles.Vehicle;

/**
 * Flood-aware travel disutility for Manchester.
 *
 * Same logic as MDM paper,
 * but adapted for flood risk instead of emissions.
 *
 * Cost = weight * time + (1-weight) * flood_exposure
 *
 * where:
 * - weight ∈ [0,1]: trade-off parameter
 * - time: normalized travel time
 * - flood_risk: normalized flood exposure (0-1)
 */
public class FloodAwareDisutility implements TravelDisutility {

    private final double weight;
//    private final double speed; // m/s (walk: 1.4, bike: 4.17)

    public FloodAwareDisutility(double weight) {
        this.weight = weight;
//        this.speed = speed;
    }

    @Override
    public double getLinkTravelDisutility(Link link, double time,
                                          Person person, Vehicle vehicle) {

        // Get normalized travel time (0-1) from attributes
        double travelTimeNorm = (Double) link.getAttributes().getAttribute("travel_time_norm");

        // Get normalized personal exposure (0-1)
        Object exposureObj = link.getAttributes().getAttribute("personal_exposure_norm");
        double exposureNorm = (exposureObj instanceof Double) ? (Double) exposureObj : 0.0;

        // Weighted cost: w * time + (1-w) * flood_risk
        // (Same formula as your MDM paper!)
        return weight * travelTimeNorm + (1.0 - weight) * exposureNorm;
    }

    @Override
    public double getLinkMinimumTravelDisutility(Link link) {
        // Minimum assumes zero flood risk (best case scenario)
        // Must be admissible heuristic for A*: never overestimate actual cost
        double travelTimeNorm = (Double) link.getAttributes().getAttribute("travel_time_norm");
        return weight * travelTimeNorm;
    } // not just length/speed

    /**
     * Get normalized personal exposure for link.
     */
}