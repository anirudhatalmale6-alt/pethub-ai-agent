import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#e8f1fb",
          100: "#c5dcf5",
          500: "#046bd2",
          600: "#034ea2",
          700: "#023572",
        },
        surface: {
          0: "#ffffff",
          50: "#f8f9fc",
          100: "#f1f3f9",
          200: "#e2e7f0",
          300: "#c8cfd8",
          800: "#1e293b",
          900: "#0f172a",
          950: "#080a0f",
        },
      },
    },
  },
  plugins: [],
};
export default config;
