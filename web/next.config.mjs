/** @type {import('next').NextConfig} */
const nextConfig = {
  // Traced server bundle for the Docker runtime stage: ships the imports the
  // server actually uses instead of the whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
