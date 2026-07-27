/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 共享契约包以 TS 源码直接被 Next 编译，需 transpile
  transpilePackages: ['@fr/shared'],
};

export default nextConfig;
