const nextConfig = {
  async rewrites() {
    // The Python engine serves every data route; the browser talks to Next
    // on one origin so there is no CORS preflight in normal use.
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
};
export default nextConfig;
