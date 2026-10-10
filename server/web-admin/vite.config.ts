import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  server: {
    proxy: {
      "/admin/api": "http://127.0.0.1:8000",
      "/admin/login": "http://127.0.0.1:8000",
      "/admin/logout": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
    },
  },
});
