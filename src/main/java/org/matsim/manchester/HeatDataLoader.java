package org.matsim.manchester;

import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.util.HashMap;
import java.util.Map;

/**
 * Loads pre-processed WBGT binary data and provides per-link WBGT lookup.
 *
 * Supports both multi-slice (e.g. 24-hour averages) and single-slice
 * (specific scenario) files produced by preprocess_wbgt.py.
 *
 * Binary file header: nx, ny, nSlices (3 ints), x0, y0, dx, dy (4 doubles)
 * Data: float32[nSlices][ny][nx] in C-order
 *
 * Usage:
 *   HeatDataLoader loader = new HeatDataLoader(binPath, metaPath);
 *   loader.assignToLinks(network);
 *   double wbgt = loader.getWBGT(linkId);       // single-slice file
 *   double wbgt = loader.getWBGT(linkId, hour);  // multi-slice file
 */
public class HeatDataLoader {

    private int nx, ny, nSlices;
    private double x0, y0, dx, dy;
    private float[] sliceData;       // [nSlices * ny * nx], C-order
    private Map<String, Integer> linkCellIndex;

    public HeatDataLoader(String binPath, String metaPath) throws IOException {
        readMeta(metaPath);
        readBinary(binPath);
        linkCellIndex = new HashMap<>();
    }

    private void readMeta(String metaPath) throws IOException {
        try (BufferedReader br = new BufferedReader(new FileReader(metaPath))) {
            String line;
            while ((line = br.readLine()) != null) {
                String[] parts = line.split("=", 2);
                if (parts.length < 2) continue;
                switch (parts[0]) {
                    case "nx" -> nx = Integer.parseInt(parts[1]);
                    case "ny" -> ny = Integer.parseInt(parts[1]);
                    case "x0" -> x0 = Double.parseDouble(parts[1]);
                    case "y0" -> y0 = Double.parseDouble(parts[1]);
                    case "dx" -> dx = Double.parseDouble(parts[1]);
                    case "dy" -> dy = Double.parseDouble(parts[1]);
                }
            }
        }
        System.out.printf("  WBGT grid: %dx%d, (%.0f,%.0f) cell=%.0f×%.0f%n",
                nx, ny, x0, y0, dx, dy);
    }

    private void readBinary(String binPath) throws IOException {
        try (RandomAccessFile raf = new RandomAccessFile(binPath, "r");
             FileChannel ch = raf.getChannel()) {

            ByteBuffer hdr = ByteBuffer.allocate(44);
            hdr.order(ByteOrder.LITTLE_ENDIAN);
            ch.read(hdr);
            hdr.flip();

            int hNx = hdr.getInt();
            int hNy = hdr.getInt();
            nSlices = hdr.getInt();
            hdr.getDouble(); hdr.getDouble(); hdr.getDouble(); hdr.getDouble();

            if (hNx != nx || hNy != ny) {
                throw new IOException(String.format(
                        "Header dims mismatch: expected %dx%d, got %dx%d",
                        nx, ny, hNx, hNy));
            }

            int total = nx * ny * nSlices;
            ByteBuffer data = ByteBuffer.allocate(total * 4);
            data.order(ByteOrder.LITTLE_ENDIAN);
            ch.read(data);
            data.flip();

            sliceData = new float[total];
            data.asFloatBuffer().get(sliceData);
        }
        System.out.printf("  Loaded %d slices × %d cells (%d values)%n",
                nSlices, nx * ny, sliceData.length);
    }

    public void assignToLinks(Network network) {
        for (Link link : network.getLinks().values()) {
            double cx = (link.getFromNode().getCoord().getX()
                       + link.getToNode().getCoord().getX()) / 2.0;
            double cy = (link.getFromNode().getCoord().getY()
                       + link.getToNode().getCoord().getY()) / 2.0;
            int xi = clamp((int) Math.round((cx - x0) / dx), 0, nx - 1);
            int yi = clamp((int) Math.round((y0 - cy) / Math.abs(dy)), 0, ny - 1);
            linkCellIndex.put(link.getId().toString(), yi * nx + xi);
        }
        System.out.printf("  Assigned %d links to nearest WBGT cell%n",
                linkCellIndex.size());
    }

    /** Get WBGT for a single-slice file (scenario). */
    public double getWBGT(String linkId) {
        Integer idx = linkCellIndex.get(linkId);
        if (idx == null) return 0.0;
        return sliceData[idx];
    }

    /** Get WBGT for a specific slice in a multi-slice file. */
    public double getWBGT(String linkId, int slice) {
        Integer idx = linkCellIndex.get(linkId);
        if (idx == null || slice < 0 || slice >= nSlices) return 0.0;
        return sliceData[slice * nx * ny + idx];
    }

    /** Max WBGT across all cells in a given slice (0 = first slice). */
    public double getMaxWBGT(int slice) {
        int offset = Math.max(0, Math.min(slice, nSlices - 1)) * nx * ny;
        double maxVal = Double.NEGATIVE_INFINITY;
        for (int i = 0; i < nx * ny; i++) {
            double v = sliceData[offset + i];
            if (v > maxVal) maxVal = v;
        }
        return maxVal;
    }

    public int getNSlices() { return nSlices; }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
