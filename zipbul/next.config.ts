import type { NextConfig } from 'next';
const config: NextConfig = {
  distDir: process.env.ZIPBUL_DIST_DIR || '.next',
  devIndicators: false,
  async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.ZIPBUL_API_ORIGIN||'http://127.0.0.1:3001'}/api/:path*` }]; },
};
export default config;
