import type { NextConfig } from "next";

/**
 * Static export (D-057).
 *
 * Eight of the ten pages read nothing but JSON committed beside the code, so the
 * whole site can be a static bundle on a CDN: no server, no cold start, free
 * hosting, instant load. The two live pages talk to the API from the browser at
 * runtime, which a static bundle is perfectly able to do.
 */
const nextConfig: NextConfig = {
  output: "export",
  // A static host serves /network/ as a directory, not /network.html.
  trailingSlash: true,
  images: {
    // No Node server exists to run the optimiser at request time.
    unoptimized: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
