/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#0f1115",
        surface: "#161b22",
        "surface-elevated": "#1c2330",
        border: "#30363d",
        "border-strong": "#484f58",
        main: "#f0f6fc",
        muted: "#8b949e",
        success: "#75c69a",
        warning: "#d9a85c",
        proposal: "#b9a46d",
        danger: "#e06c75",
        info: "#7d9bb8",
        decision: "#9b8fbd",
      },
      boxShadow: {
        panel: "0 12px 32px rgba(0,0,0,.14)",
      },
    },
  },
  plugins: [],
};
