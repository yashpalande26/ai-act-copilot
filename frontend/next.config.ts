import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The floating dev badge overlaps the bottom-left of the UI and is not part
  // of the product. Hidden so design review sees what users see.
  devIndicators: false,
};

export default nextConfig;
