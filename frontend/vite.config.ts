import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export const backendPathPattern =
  "^/(agent|ui|customers|orders|tickets|memories|escalations)(?:/|$)|^/(health|ready)$";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, "..", "");
  const backendTarget = environment.VITE_BACKEND_TARGET || "http://localhost:8000";
  const runtimeEnvironment = (
    globalThis as typeof globalThis & {
      process?: { env: Record<string, string | undefined> };
    }
  ).process?.env;
  const demoToken =
    runtimeEnvironment?.LOCAL_DEMO_AUTH_TOKEN || environment.LOCAL_DEMO_AUTH_TOKEN || "";

  return {
    envDir: "..",
    define: {
      "import.meta.env.VITE_DEMO_AUTH_TOKEN": JSON.stringify(demoToken),
    },
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        [backendPathPattern]: {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
