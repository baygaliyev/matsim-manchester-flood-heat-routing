package org.matsim.manchester;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.vehicles.Vehicle;

/**
 * Heat-aware travel disutility for Manchester.
 *
 * Cost = w * time_norm + (1-w) * heat_norm
 *
 * where time_norm and heat_norm are pre-computed per-hour-of-day
 * and stored on each link as attributes.
 */
public class HeatAwareDisutility implements TravelDisutility {

    private final double weight;

    public HeatAwareDisutility(double weight) {
        this.weight = weight;
    }

    @Override
    public double getLinkTravelDisutility(Link link, double time,
                                          Person person, Vehicle vehicle) {
        double timeNorm = (Double) link.getAttributes().getAttribute("heat_time_norm");
        double heatNorm = (Double) link.getAttributes().getAttribute("heat_exposure_norm");
        return weight * timeNorm + (1.0 - weight) * heatNorm;
    }

    @Override
    public double getLinkMinimumTravelDisutility(Link link) {
        double timeNorm = (Double) link.getAttributes().getAttribute("heat_time_norm");
        return weight * timeNorm;
    }
}
